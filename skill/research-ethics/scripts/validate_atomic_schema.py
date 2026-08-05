#!/usr/bin/env python3
"""Validate the schema-0.3 atomic registration map.

This validator is intentionally independent from the Markdown generator.  It
checks the authoring model itself, evaluates every verification scenario, and
compares the expected visible-control signature with the signature observed in
the browser.

Canonical condition grammar::

    true | false
    {control: "page.group.control", equals: "option-id"}
    {control: "page.group.control", in: ["option-a", "option-b"]}
    {control: "page.group.control", not_equals: "option-id"}
    {control: "page.group.control", not_in: ["option-a"]}
    {control: "page.group.control", is_set: true}
    {all: [<condition>, ...]}
    {any: [<condition>, ...]}
    {not: <condition>}

Control paths are derived as ``page-id.group-id.control-id`` unless a control
declares an explicit ``path``.  Scenario ``selections`` and condition
references must use those paths.  Pages may store their nodes under ``nodes``
or ``fields``; groups may store children under ``nodes`` or ``children``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

import yaml


SUPPORTED_SCHEMA_VERSIONS = {"0.3", "0.3-draft"}
NODE_KINDS = {"group", "control", "action"}
CONDITION_OPERATORS = {"equals", "in", "not_equals", "not_in", "is_set"}
SIGNATURE_KEYS = ("observed_key", "label", "widget", "required", "enabled")


@dataclass
class IssueCollector:
    issues: list[str] = field(default_factory=list)

    def add(self, location: str, message: str) -> None:
        self.issues.append(f"{location}: {message}")


@dataclass
class OptionSpec:
    option_id: str
    visible_if: Any = True


@dataclass
class ControlSpec:
    path: str
    node_id: str
    page_id: str
    location: str
    label: str
    widget: str
    order: int
    required: Any
    enabled_if: Any
    visibility_chain: list[Any]
    observed_key: str
    options: list[OptionSpec]
    observable: bool


@dataclass
class PageSpec:
    page_id: str
    label: str
    location: str
    source_index: int
    order: int
    visible_if: Any
    controls: list[ControlSpec] = field(default_factory=list)


@dataclass
class ConditionUse:
    location: str
    condition: Any
    purpose: str


class AtomicSchemaValidator:
    """Collect all structural, reference, scenario, and coverage failures."""

    def __init__(self, data: Any) -> None:
        self.data = data
        self.errors = IssueCollector()
        self.pages: list[PageSpec] = []
        self.controls: dict[str, ControlSpec] = {}
        self.condition_uses: list[ConditionUse] = []
        self.referenced_option_values: set[tuple[str, str]] = set()

    def validate(self) -> list[str]:
        if not isinstance(self.data, dict):
            self.errors.add("$", "document must be a mapping")
            return self.errors.issues

        version = str(self.data.get("schema_version", ""))
        if version not in SUPPORTED_SCHEMA_VERSIONS:
            self.errors.add(
                "$.schema_version",
                f"expected one of {sorted(SUPPORTED_SCHEMA_VERSIONS)!r}, found {version!r}",
            )

        self._reject_string_field_shorthands(self.data, "$")
        self._collect_pages()
        self._validate_all_conditions()
        self._validate_scenarios()
        return self.errors.issues

    def _reject_string_field_shorthands(self, value: Any, location: str) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                child_location = f"{location}.{key}"
                key_text = str(key).lower()
                if key_text == "fields" or key_text.endswith("_fields") or key_text.endswith("_subfields"):
                    string_locations = list(self._shorthand_string_locations(child, child_location))
                    if string_locations:
                        sample = ", ".join(string_locations[:3])
                        suffix = " ..." if len(string_locations) > 3 else ""
                        self.errors.add(
                            child_location,
                            "field shorthand contains string leaves; represent each UI control "
                            f"as a kind=control node ({sample}{suffix})",
                        )
                self._reject_string_field_shorthands(child, child_location)
        elif isinstance(value, list):
            for index, child in enumerate(value):
                self._reject_string_field_shorthands(child, f"{location}[{index}]")

    def _shorthand_string_locations(self, value: Any, location: str) -> Iterable[str]:
        """Find strings used *as field entries*, not strings inside node objects.

        A list such as ``fields: [{kind: control, id: x, ...}]`` necessarily
        contains strings, but those strings are attributes of an atomic node and
        must not be reported as shorthand.  Legacy node-shaped mappings with an
        id and label are also left for the clearer missing-``kind`` diagnostic.
        """

        if isinstance(value, str):
            yield location
        elif isinstance(value, list):
            for index, child in enumerate(value):
                yield from self._shorthand_string_locations(child, f"{location}[{index}]")
        elif isinstance(value, dict):
            if "kind" in value or ("id" in value and "label" in value):
                return
            for key, child in value.items():
                yield from self._shorthand_string_locations(child, f"{location}.{key}")

    def _collect_pages(self) -> None:
        workflow = self.data.get("workflow")
        if not isinstance(workflow, dict):
            self.errors.add("$.workflow", "must be a mapping")
            return
        raw_pages = workflow.get("pages")
        if not isinstance(raw_pages, list):
            self.errors.add("$.workflow.pages", "must be a list")
            return

        page_ids: set[str] = set()
        page_orders: set[int] = set()
        for index, raw_page in enumerate(raw_pages):
            location = f"$.workflow.pages[{index}]"
            if not isinstance(raw_page, dict):
                self.errors.add(location, "page must be a mapping")
                continue
            page_id = self._required_string(raw_page, "id", location)
            label = self._required_string(raw_page, "label", location)
            if not page_id:
                page_id = f"__invalid_page_{index}"
            if page_id in page_ids:
                self.errors.add(f"{location}.id", f"duplicate page id {page_id!r}")
            page_ids.add(page_id)

            page_order_raw = raw_page.get("order", index)
            page_order = self._nonnegative_int(page_order_raw, f"{location}.order", fallback=index)
            if "order" in raw_page and page_order in page_orders:
                self.errors.add(f"{location}.order", f"duplicate page order {page_order}")
            page_orders.add(page_order)
            visible_if = raw_page.get("visible_if", True)
            if "visible_if" in raw_page:
                self.condition_uses.append(
                    ConditionUse(f"{location}.visible_if", visible_if, "page visibility")
                )

            page = PageSpec(
                page_id=page_id,
                label=label,
                location=location,
                source_index=index,
                order=page_order,
                visible_if=visible_if,
            )
            self.pages.append(page)

            nodes, nodes_key = self._node_list(raw_page, location, is_page=True)
            self._collect_nodes(
                nodes,
                page=page,
                parent_path=page_id,
                parent_visibility=[visible_if],
                location=f"{location}.{nodes_key}",
            )

        self.pages.sort(key=lambda page: (page.order, page.source_index))

    def _node_list(self, owner: dict[str, Any], location: str, *, is_page: bool) -> tuple[list[Any], str]:
        allowed = ("nodes", "fields") if is_page else ("nodes", "children")
        present = [key for key in allowed if key in owner]
        if len(present) > 1:
            self.errors.add(location, f"use exactly one node container, not {present}")
        key = present[0] if present else allowed[0]
        nodes = owner.get(key)
        if not isinstance(nodes, list):
            self.errors.add(f"{location}.{key}", "must be a list of atomic nodes")
            return [], key
        return nodes, key

    def _collect_nodes(
        self,
        raw_nodes: list[Any],
        *,
        page: PageSpec,
        parent_path: str,
        parent_visibility: list[Any],
        location: str,
    ) -> None:
        sibling_orders: set[int] = set()
        sibling_ids: set[str] = set()
        sortable: list[tuple[int, int, Any, str]] = []

        for index, raw_node in enumerate(raw_nodes):
            node_location = f"{location}[{index}]"
            if not isinstance(raw_node, dict):
                self.errors.add(node_location, "node must be a mapping")
                continue
            kind = raw_node.get("kind")
            if kind not in NODE_KINDS:
                self.errors.add(
                    f"{node_location}.kind",
                    f"must be one of {sorted(NODE_KINDS)}, found {kind!r}",
                )
                continue
            node_id = self._required_string(raw_node, "id", node_location)
            self._required_string(raw_node, "label", node_location)
            if not node_id:
                node_id = f"__invalid_node_{index}"
            if node_id in sibling_ids:
                self.errors.add(f"{node_location}.id", f"duplicate sibling id {node_id!r}")
            sibling_ids.add(node_id)
            order = self._nonnegative_int(raw_node.get("order"), f"{node_location}.order", fallback=index)
            if order in sibling_orders:
                self.errors.add(f"{node_location}.order", f"duplicate sibling order {order}")
            sibling_orders.add(order)
            sortable.append((order, index, raw_node, node_location))

        for order, _, raw_node, node_location in sorted(sortable):
            kind = raw_node["kind"]
            node_id = str(raw_node.get("id") or "__invalid_node")
            node_path = f"{parent_path}.{node_id}"
            if "visible_if" not in raw_node:
                self.errors.add(f"{node_location}.visible_if", f"required for kind={kind}")
            visible_if = raw_node.get("visible_if", True)
            self.condition_uses.append(
                ConditionUse(f"{node_location}.visible_if", visible_if, f"{kind} visibility")
            )
            visibility_chain = [*parent_visibility, visible_if]

            if kind == "group":
                children, child_key = self._node_list(raw_node, node_location, is_page=False)
                self._collect_nodes(
                    children,
                    page=page,
                    parent_path=node_path,
                    parent_visibility=visibility_chain,
                    location=f"{node_location}.{child_key}",
                )
                continue

            if kind == "action":
                continue

            # kind=control: all six atomic attributes are mandatory.
            for required_key in ("id", "label", "widget", "order", "required", "visible_if"):
                if required_key not in raw_node:
                    self.errors.add(f"{node_location}.{required_key}", "required for kind=control")
            label = self._required_string(raw_node, "label", node_location)
            widget = self._required_string(raw_node, "widget", node_location)
            control_path = raw_node.get("path", node_path)
            if not isinstance(control_path, str) or not control_path.strip():
                self.errors.add(f"{node_location}.path", "must be a non-empty string when present")
                control_path = node_path
            control_path = str(control_path)
            if control_path in self.controls:
                self.errors.add(f"{node_location}.path", f"duplicate control path {control_path!r}")

            required = raw_node.get("required", False)
            if not isinstance(required, bool):
                self.condition_uses.append(
                    ConditionUse(f"{node_location}.required", required, "conditional requiredness")
                )
            enabled_if = raw_node.get("enabled_if", True)
            if "enabled_if" in raw_node:
                self.condition_uses.append(
                    ConditionUse(f"{node_location}.enabled_if", enabled_if, "control enabledness")
                )
            observed_key = raw_node.get("observed_key", control_path)
            if not isinstance(observed_key, str) or not observed_key:
                self.errors.add(f"{node_location}.observed_key", "must be a non-empty string when present")
                observed_key = control_path

            options = self._collect_options(raw_node.get("options"), node_location, control_path)
            control = ControlSpec(
                path=control_path,
                node_id=node_id,
                page_id=page.page_id,
                location=node_location,
                label=label,
                widget=widget,
                order=order,
                required=required,
                enabled_if=enabled_if,
                visibility_chain=visibility_chain,
                observed_key=observed_key,
                options=options,
                # Hidden inputs are legitimate atomic system fields (for
                # example internal row IDs and selected-record caches), but
                # they cannot occur in a browser *visible-control* signature.
                # They remain in the control registry so references and
                # metadata are still validated.
                observable=widget != "hidden",
            )
            self.controls[control_path] = control
            page.controls.append(control)

    def _collect_options(self, raw_options: Any, location: str, control_path: str) -> list[OptionSpec]:
        if raw_options is None:
            return []
        if not isinstance(raw_options, list):
            self.errors.add(f"{location}.options", "must be a list")
            return []
        options: list[OptionSpec] = []
        seen: set[str] = set()
        for index, raw_option in enumerate(raw_options):
            option_location = f"{location}.options[{index}]"
            if isinstance(raw_option, str):
                option_id = raw_option
                option_visible_if = True
            elif isinstance(raw_option, dict):
                option_id = self._required_string(raw_option, "id", option_location)
                self._required_string(raw_option, "label", option_location)
                option_visible_if = raw_option.get("visible_if", True)
                if "visible_if" in raw_option:
                    self.condition_uses.append(
                        ConditionUse(
                            f"{option_location}.visible_if",
                            option_visible_if,
                            "option visibility",
                        )
                    )
            else:
                self.errors.add(option_location, "option must be a string or mapping")
                continue
            if not option_id:
                continue
            if option_id in seen:
                self.errors.add(option_location, f"duplicate option id {option_id!r}")
            seen.add(option_id)
            options.append(OptionSpec(option_id=option_id, visible_if=option_visible_if))
        return options

    def _validate_all_conditions(self) -> None:
        for use in self.condition_uses:
            self._validate_condition(use.condition, use.location)

    def _validate_condition(self, condition: Any, location: str) -> None:
        if isinstance(condition, bool):
            return
        if not isinstance(condition, dict) or not condition:
            self.errors.add(location, "condition must be boolean or a non-empty condition mapping")
            return

        logical_keys = [key for key in ("all", "any", "not") if key in condition]
        if logical_keys:
            if len(logical_keys) != 1 or len(condition) != 1:
                self.errors.add(location, "logical condition must contain exactly one of all/any/not")
                return
            operator = logical_keys[0]
            child = condition[operator]
            if operator in {"all", "any"}:
                if not isinstance(child, list) or not child:
                    self.errors.add(f"{location}.{operator}", "must be a non-empty list")
                    return
                for index, nested in enumerate(child):
                    self._validate_condition(nested, f"{location}.{operator}[{index}]")
            else:
                self._validate_condition(child, f"{location}.not")
            return

        control_ref = condition.get("control")
        operators = [key for key in CONDITION_OPERATORS if key in condition]
        if not isinstance(control_ref, str) or not control_ref:
            self.errors.add(f"{location}.control", "must reference a non-empty control path")
            return
        if len(operators) != 1 or set(condition) != {"control", *operators}:
            self.errors.add(
                location,
                "atomic condition must contain control and exactly one of "
                f"{sorted(CONDITION_OPERATORS)}",
            )
            return
        if control_ref not in self.controls:
            self.errors.add(f"{location}.control", f"unknown control path {control_ref!r}")
            return

        operator = operators[0]
        value = condition[operator]
        if operator == "is_set":
            if not isinstance(value, bool):
                self.errors.add(f"{location}.is_set", "must be boolean")
            return
        values = value if operator in {"in", "not_in"} else [value]
        if not isinstance(values, list) or not values:
            self.errors.add(f"{location}.{operator}", "must provide at least one option id")
            return
        declared_options = {option.option_id for option in self.controls[control_ref].options}
        if not declared_options:
            self.errors.add(
                f"{location}.{operator}",
                f"control {control_ref!r} has no declared options to reference",
            )
            return
        for index, option_id in enumerate(values):
            if not isinstance(option_id, str):
                self.errors.add(f"{location}.{operator}[{index}]", "option reference must be a string")
                continue
            if option_id not in declared_options:
                self.errors.add(
                    f"{location}.{operator}",
                    f"unknown option {option_id!r} for control {control_ref!r}",
                )
            self.referenced_option_values.add((control_ref, option_id))

    def _validate_scenarios(self) -> None:
        verification = self.data.get("verification")
        if not isinstance(verification, dict):
            self.errors.add("$.verification", "must be a mapping with scenarios")
            return
        scenarios = verification.get("scenarios")
        if not isinstance(scenarios, list) or not scenarios:
            self.errors.add("$.verification.scenarios", "must be a non-empty list")
            return

        scenario_ids: set[str] = set()
        control_visible_count = {
            path: 0 for path, control in self.controls.items() if control.observable
        }
        page_visible_count = {page.page_id: 0 for page in self.pages}
        condition_outcomes: dict[str, set[bool]] = {
            use.location: set()
            for use in self.condition_uses
            if not isinstance(use.condition, bool)
        }
        selected_values: set[tuple[str, str]] = set()

        for index, scenario in enumerate(scenarios):
            location = f"$.verification.scenarios[{index}]"
            if not isinstance(scenario, dict):
                self.errors.add(location, "scenario must be a mapping")
                continue
            scenario_id = self._required_string(scenario, "id", location)
            if scenario_id in scenario_ids:
                self.errors.add(f"{location}.id", f"duplicate scenario id {scenario_id!r}")
            scenario_ids.add(scenario_id)

            selections = scenario.get("selections")
            if not isinstance(selections, dict):
                self.errors.add(f"{location}.selections", "must be a control-path to option-id mapping")
                selections = {}
            self._validate_selections(selections, f"{location}.selections", selected_values)

            for use in self.condition_uses:
                if isinstance(use.condition, bool):
                    continue
                refs = self._condition_refs(use.condition)
                if refs and refs.issubset(selections):
                    condition_outcomes[use.location].add(self._evaluate(use.condition, selections))

            expected_pages = self._expected_pages(selections)
            expected_page_ids = [page.page_id for page, _ in expected_pages]
            for page, signature in expected_pages:
                page_visible_count[page.page_id] += 1
                by_key = {item["observed_key"]: path for path, item in signature}
                for observed_key in by_key:
                    control_visible_count[by_key[observed_key]] += 1

            page_sequence = scenario.get("page_sequence")
            if page_sequence != expected_page_ids:
                self._add_diff(
                    f"{location}.page_sequence",
                    expected_page_ids,
                    page_sequence,
                )

            observed_pages = scenario.get("observed_pages")
            if not isinstance(observed_pages, list):
                self.errors.add(f"{location}.observed_pages", "must be a list")
                continue
            observed_page_ids = [
                page.get("page_id") if isinstance(page, dict) else None
                for page in observed_pages
            ]
            if observed_page_ids != expected_page_ids:
                self._add_diff(
                    f"{location}.observed_pages page order",
                    expected_page_ids,
                    observed_page_ids,
                )

            observed_by_id = {
                page.get("page_id"): (position, page)
                for position, page in enumerate(observed_pages)
                if isinstance(page, dict) and isinstance(page.get("page_id"), str)
            }
            for page, signature_pairs in expected_pages:
                expected_signature = [item for _, item in signature_pairs]
                if page.page_id not in observed_by_id:
                    self.errors.add(
                        f"{location}.observed_pages",
                        f"missing expected page {page.page_id!r}",
                    )
                    continue
                position, observed_page = observed_by_id[page.page_id]
                page_location = f"{location}.observed_pages[{position}]"
                observed_signature = observed_page.get("observed_signature")
                self._validate_observed_signature(observed_signature, f"{page_location}.observed_signature")
                if observed_signature != expected_signature:
                    self._add_signature_diff(
                        f"{page_location}.observed_signature",
                        expected_signature,
                        observed_signature,
                    )
                if "signature_hash" in observed_page:
                    observed_hash = str(observed_page["signature_hash"])
                    expected_hash = self._signature_hash(observed_signature)
                    if observed_hash.removeprefix("sha256:") != expected_hash:
                        self.errors.add(
                            f"{page_location}.signature_hash",
                            f"hash mismatch: expected sha256:{expected_hash}, found {observed_hash!r}",
                        )

        for page_id, count in page_visible_count.items():
            if count == 0:
                self.errors.add(
                    "$.verification.scenarios",
                    f"coverage gap: page {page_id!r} is never expected visible",
                )
        for control_path, count in control_visible_count.items():
            if count == 0:
                self.errors.add(
                    "$.verification.scenarios",
                    f"coverage gap: control {control_path!r} is never expected visible",
                )
        for use in self.condition_uses:
            if isinstance(use.condition, bool):
                continue
            outcomes = condition_outcomes.get(use.location, set())
            if outcomes != {False, True}:
                self.errors.add(
                    "$.verification.scenarios",
                    f"coverage gap: {use.purpose} condition at {use.location} has "
                    f"covered outcomes {sorted(outcomes)}, expected [False, True] with all references selected",
                )
        for control_path, option_id in sorted(self.referenced_option_values):
            if (control_path, option_id) not in selected_values:
                self.errors.add(
                    "$.verification.scenarios",
                    f"coverage gap: condition-referenced option {control_path}={option_id!r} is never selected",
                )

    def _validate_selections(
        self,
        selections: dict[Any, Any],
        location: str,
        selected_values: set[tuple[str, str]],
    ) -> None:
        for control_path, selected in selections.items():
            item_location = f"{location}.{control_path}"
            if not isinstance(control_path, str) or control_path not in self.controls:
                self.errors.add(item_location, f"unknown control path {control_path!r}")
                continue
            control = self.controls[control_path]
            values = selected if isinstance(selected, list) else [selected]
            option_ids = {option.option_id for option in control.options}
            if not option_ids:
                self.errors.add(item_location, "scenario selections may only target controls with options")
                continue
            for value in values:
                if not isinstance(value, str):
                    self.errors.add(item_location, "selected option id must be a string")
                    continue
                if value not in option_ids:
                    self.errors.add(item_location, f"unknown option {value!r}")
                selected_values.add((control_path, value))

    def _expected_pages(self, selections: dict[Any, Any]) -> list[tuple[PageSpec, list[tuple[str, dict[str, Any]]]]]:
        expected: list[tuple[PageSpec, list[tuple[str, dict[str, Any]]]]] = []
        for page in self.pages:
            if not self._evaluate(page.visible_if, selections):
                continue
            signature: list[tuple[str, dict[str, Any]]] = []
            for control in page.controls:
                if not control.observable:
                    continue
                if not all(self._evaluate(condition, selections) for condition in control.visibility_chain):
                    continue
                item: dict[str, Any] = {
                    "observed_key": control.observed_key,
                    "label": control.label,
                    "widget": control.widget,
                    "required": self._evaluate(control.required, selections),
                    "enabled": self._evaluate(control.enabled_if, selections),
                }
                if control.options:
                    item["options"] = [
                        option.option_id
                        for option in control.options
                        if self._evaluate(option.visible_if, selections)
                    ]
                signature.append((control.path, item))
            expected.append((page, signature))
        return expected

    def _evaluate(self, condition: Any, selections: dict[Any, Any]) -> bool:
        if isinstance(condition, bool):
            return condition
        if not isinstance(condition, dict):
            return False
        if "all" in condition:
            children = condition.get("all")
            return isinstance(children, list) and all(self._evaluate(child, selections) for child in children)
        if "any" in condition:
            children = condition.get("any")
            return isinstance(children, list) and any(self._evaluate(child, selections) for child in children)
        if "not" in condition:
            return not self._evaluate(condition.get("not"), selections)
        control_ref = condition.get("control")
        selected = selections.get(control_ref)
        selected_values = selected if isinstance(selected, list) else [selected]
        if "equals" in condition:
            return condition["equals"] in selected_values
        if "not_equals" in condition:
            return selected is not None and condition["not_equals"] not in selected_values
        if "in" in condition:
            choices = condition.get("in")
            return isinstance(choices, list) and any(value in choices for value in selected_values)
        if "not_in" in condition:
            choices = condition.get("not_in")
            return selected is not None and isinstance(choices, list) and all(value not in choices for value in selected_values)
        if "is_set" in condition:
            return (selected is not None) is bool(condition["is_set"])
        return False

    def _condition_refs(self, condition: Any) -> set[str]:
        if not isinstance(condition, dict):
            return set()
        control = condition.get("control")
        if isinstance(control, str):
            return {control}
        refs: set[str] = set()
        for key in ("all", "any"):
            children = condition.get(key)
            if isinstance(children, list):
                for child in children:
                    refs.update(self._condition_refs(child))
        if "not" in condition:
            refs.update(self._condition_refs(condition["not"]))
        return refs

    def _validate_observed_signature(self, signature: Any, location: str) -> None:
        if not isinstance(signature, list):
            self.errors.add(location, "must be a list")
            return
        seen: set[str] = set()
        for index, item in enumerate(signature):
            item_location = f"{location}[{index}]"
            if not isinstance(item, dict):
                self.errors.add(item_location, "signature item must be a mapping")
                continue
            required_keys = set(SIGNATURE_KEYS)
            allowed_keys = required_keys | {"options"}
            missing = sorted(required_keys - set(item))
            extra = sorted(set(item) - allowed_keys)
            if missing:
                self.errors.add(item_location, f"missing signature keys {missing}")
            if extra:
                self.errors.add(item_location, f"unexpected signature keys {extra}")
            observed_key = item.get("observed_key")
            if not isinstance(observed_key, str) or not observed_key:
                self.errors.add(f"{item_location}.observed_key", "must be a non-empty string")
            elif observed_key in seen:
                self.errors.add(f"{item_location}.observed_key", f"duplicate {observed_key!r}")
            seen.add(observed_key)
            for key in ("label", "widget"):
                if not isinstance(item.get(key), str):
                    self.errors.add(f"{item_location}.{key}", "must be a string")
            for key in ("required", "enabled"):
                if not isinstance(item.get(key), bool):
                    self.errors.add(f"{item_location}.{key}", "must be boolean")
            if "options" in item and (
                not isinstance(item["options"], list)
                or any(not isinstance(option, str) for option in item["options"])
            ):
                self.errors.add(f"{item_location}.options", "must be a list of option ids")

    def _add_signature_diff(self, location: str, expected: list[Any], observed: Any) -> None:
        if not isinstance(observed, list):
            self.errors.add(location, f"signature mismatch: expected {len(expected)} controls, observed non-list")
            return
        expected_keys = [item.get("observed_key") for item in expected]
        observed_keys = [item.get("observed_key") if isinstance(item, dict) else None for item in observed]
        missing = [key for key in expected_keys if key not in observed_keys]
        extra = [key for key in observed_keys if key not in expected_keys]
        order_mismatch = not missing and not extra and expected_keys != observed_keys
        detail: list[str] = []
        if missing:
            detail.append(f"missing={missing}")
        if extra:
            detail.append(f"extra={extra}")
        if order_mismatch:
            detail.append(f"order expected={expected_keys}, observed={observed_keys}")
        for index, (expected_item, observed_item) in enumerate(zip(expected, observed)):
            if expected_item != observed_item:
                detail.append(f"first item difference at index {index}: expected={expected_item!r}, observed={observed_item!r}")
                break
        self.errors.add(location, "strict signature mismatch; " + "; ".join(detail))

    def _add_diff(self, location: str, expected: Any, observed: Any) -> None:
        self.errors.add(location, f"strict mismatch: expected={expected!r}, observed={observed!r}")

    def _signature_hash(self, signature: Any) -> str:
        canonical = json.dumps(signature, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def _required_string(self, owner: dict[str, Any], key: str, location: str) -> str:
        value = owner.get(key)
        if not isinstance(value, str) or not value.strip():
            self.errors.add(f"{location}.{key}", "must be a non-empty string")
            return ""
        return value

    def _nonnegative_int(self, value: Any, location: str, *, fallback: int) -> int:
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            self.errors.add(location, "must be a non-negative integer")
            return fallback
        return value


def validate_document(data: Any) -> list[str]:
    """Return every schema-0.3 validation failure without raising."""

    return AtomicSchemaValidator(data).validate()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "target",
        type=Path,
        help="project root or registration-tree.yaml path",
    )
    parser.add_argument("--max-errors", type=int, default=80)
    args = parser.parse_args()

    target = args.target.resolve()
    yaml_path = target if target.is_file() else target / "references" / "registration-tree.yaml"
    try:
        data = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        print(f"Atomic schema validation failed: cannot read {yaml_path}: {exc}", file=sys.stderr)
        return 2

    issues = validate_document(data)
    if issues:
        print(f"Atomic schema validation failed: {len(issues)} issue(s)", file=sys.stderr)
        limit = max(args.max_errors, 0)
        for issue in issues[:limit]:
            print(f"- {issue}", file=sys.stderr)
        if len(issues) > limit:
            print(f"- ... {len(issues) - limit} additional issue(s) omitted", file=sys.stderr)
        return 1

    scenarios = data["verification"]["scenarios"]
    pages = data["workflow"]["pages"]
    print(
        "Atomic schema validation passed: "
        f"schema={data['schema_version']}, pages={len(pages)}, scenarios={len(scenarios)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
