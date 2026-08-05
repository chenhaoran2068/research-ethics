#!/usr/bin/env python3
"""Mechanically normalize the atomic registration map without guessing branches.

The active DAG is deliberately conservative: a structural node whose condition
cannot be expressed and resolved with the canonical condition grammar is moved
intact to the owning page's ``unverified_candidate_nodes`` section.  ``--check``
writes and validates a temporary file only; the canonical file is never replaced.
"""

from __future__ import annotations

import argparse
import copy
import os
import re
import sys
import tempfile
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable

import yaml

from validate_atomic_schema import validate_document as validate_atomic_document


SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_TARGET = SCRIPT_DIR.parent / "references" / "registration-tree.yaml"
CONDITION_OPERATORS = {"equals", "in", "not_equals", "not_in", "is_set"}
STRUCTURAL_KINDS = {"group", "control", "action"}
ALWAYS_TEXT = {"always", "parent visible", "parent_visible"}
NEVER_TEXT = {"never_user_visible", "never user visible"}
ROUTE_CONTROL = "research-category.route-leaf"
CHICTR_CONTROL = "tab1.sync-platform"
CHICTR_PUBLIC = "中国临床试验注册中心公开"
PRODUCT_ROUTES = [
    "product-drug",
    "product-medical-device",
    "product-ivd",
    "product-special-food",
]

# These are the only UI structures that the current root-route exploration has
# not made reachable or whose trigger still depends on a saved draft.
UNKNOWN_NODE_IDS = {
    "sponsor-contact-cache",
    "sponsor-contact-cache-group",
    "category-sponsor",
    "cro-name",
    "cro-nature",
    "supplementary-material-description-file",
    "funding-other-info",
    "indicator-other",
    "indicator-other-type",
    "biological-samples-other",
    "human-health-data",
    "human-health-data-items",
    "invasive-bci",
}
UNKNOWN_TECHNICAL_NAMES = {
    "sponsor-contact-cache",
    "category-sponsor",
    "materialDescribed",
    "funds.otherInfo",
    "indicator.otherType",
}


def equals(control: str, value: str) -> dict[str, Any]:
    return {"control": control, "equals": value}


def one_of(control: str, values: list[str]) -> dict[str, Any]:
    return {"control": control, "in": values}


def all_of(*conditions: Any) -> dict[str, Any]:
    return {"all": list(conditions)}


def not_equals(control: str, value: str) -> dict[str, Any]:
    return {"control": control, "not_equals": value}


class NoAliasSafeDumper(yaml.SafeDumper):
    def ignore_aliases(self, data: Any) -> bool:  # noqa: D401
        return True


def yaml_load(path: Path) -> dict[str, Any]:
    loader = getattr(yaml, "CSafeLoader", yaml.SafeLoader)
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.load(handle, Loader=loader)
    if not isinstance(data, dict):
        raise ValueError("canonical YAML root must be a mapping")
    return data


def node_container(owner: dict[str, Any], *, page: bool) -> tuple[str, list[Any]]:
    keys = ("nodes", "fields") if page else ("children", "nodes")
    present = [key for key in keys if key in owner]
    if not present:
        key = keys[0]
        owner[key] = []
        return key, owner[key]
    key = present[0]
    value = owner.get(key)
    return key, value if isinstance(value, list) else []


def option_ids(node: dict[str, Any]) -> set[str]:
    result: set[str] = set()
    raw_options = node.get("options")
    if not isinstance(raw_options, list):
        return result
    for raw in raw_options:
        if isinstance(raw, str):
            result.add(raw)
        elif isinstance(raw, dict) and isinstance(raw.get("id"), str):
            result.add(raw["id"])
    return result


def iter_structural(
    nodes: Iterable[Any], parent_path: str
) -> Iterable[tuple[dict[str, Any], str]]:
    for raw in nodes:
        if not isinstance(raw, dict):
            continue
        node_id = raw.get("id")
        path = raw.get("path") if isinstance(raw.get("path"), str) else None
        derived = f"{parent_path}.{node_id}" if isinstance(node_id, str) else parent_path
        yield raw, path or derived
        if raw.get("kind") == "group":
            _, children = node_container(raw, page=False)
            yield from iter_structural(children, derived)


class ControlIndex:
    def __init__(self, pages: list[Any]) -> None:
        self.controls: dict[str, dict[str, Any]] = {}
        self.technical_paths: dict[str, list[str]] = defaultdict(list)
        for page in pages:
            if not isinstance(page, dict) or not isinstance(page.get("id"), str):
                continue
            _, nodes = node_container(page, page=True)
            for node, path in iter_structural(nodes, page["id"]):
                if node.get("kind") != "control":
                    continue
                self.controls[path] = node
                technical = node.get("technical_name")
                if isinstance(technical, str) and technical.strip():
                    self.technical_paths[technical.strip()].append(path)

    def unique_path(self, technical_name: str) -> str | None:
        paths = self.technical_paths.get(technical_name.strip(), [])
        return paths[0] if len(paths) == 1 else None

    def declared(self, control_path: str) -> set[str]:
        node = self.controls.get(control_path)
        return option_ids(node) if isinstance(node, dict) else set()


def normalize_literal(text: str) -> str:
    return text.strip().strip("`'\"").strip()


def parse_simple_condition(text: str, index: ControlIndex) -> Any | None:
    """Convert only exact, declared ``technicalName=value`` conditions."""

    source = text.strip()
    lowered = source.lower()
    if lowered in ALWAYS_TEXT:
        return True
    if lowered in NEVER_TEXT:
        return False

    # Parent visibility is inherited by the validator's visibility chain.
    source = re.sub(
        r"^\s*parent[ _]visible\s*(?:且|and|&)\s*",
        "",
        source,
        flags=re.IGNORECASE,
    )
    source = re.sub(r"^\s*父(?:级|节点)?可见\s*(?:且|and|&)\s*", "", source)

    # A known display-only note does not alter the trigger itself.
    source = source.split("；不公开路线的现场标签无星", 1)[0].strip()
    match = re.fullmatch(r"([A-Za-z_][A-Za-z0-9_.]*)\s*=\s*(.+?)\s*", source)
    if not match:
        return None
    technical_name, raw_values = match.groups()
    control_path = index.unique_path(technical_name)
    if control_path is None:
        return None

    values = [normalize_literal(value) for value in re.split(r"\s*(?:或|\||/|,|，)\s*", raw_values)]
    if not values or any(not value for value in values):
        return None
    declared = index.declared(control_path)
    if not declared or any(value not in declared for value in values):
        return None
    if len(values) == 1:
        return {"control": control_path, "equals": values[0]}
    return {"control": control_path, "in": values}


def condition_valid(condition: Any, index: ControlIndex, *, resolve: bool = True) -> bool:
    if isinstance(condition, bool):
        return True
    if not isinstance(condition, dict) or not condition:
        return False
    logical = [key for key in ("all", "any", "not") if key in condition]
    if logical:
        if len(logical) != 1 or len(condition) != 1:
            return False
        key = logical[0]
        child = condition[key]
        if key in {"all", "any"}:
            return (
                isinstance(child, list)
                and bool(child)
                and all(condition_valid(item, index, resolve=resolve) for item in child)
            )
        return condition_valid(child, index, resolve=resolve)

    control = condition.get("control")
    operators = [key for key in CONDITION_OPERATORS if key in condition]
    if not isinstance(control, str) or len(operators) != 1:
        return False
    if set(condition) != {"control", operators[0]}:
        return False
    if resolve and control not in index.controls:
        return False
    operator = operators[0]
    value = condition[operator]
    if operator == "is_set":
        return isinstance(value, bool)
    values = value if operator in {"in", "not_in"} else [value]
    if not isinstance(values, list) or not values or any(not isinstance(v, str) for v in values):
        return False
    if not resolve:
        return True
    declared = index.declared(control)
    return bool(declared) and all(v in declared for v in values)


def normalize_condition(value: Any, index: ControlIndex) -> Any | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return parse_simple_condition(value, index)
    # Cross-page aliases (route-leaf and the historical ChiCTR names) are
    # repaired in a later phase.  At this phase a structurally valid condition
    # remains active even when its target path is not yet present.
    if condition_valid(value, index, resolve=False):
        return copy.deepcopy(value)
    return None


def preferred_option(index: ControlIndex, control: str, choices: list[str]) -> str:
    """Use a declared representation when present, otherwise the verified id."""

    declared = index.declared(control)
    for choice in choices:
        if choice in declared:
            return choice
    return choices[0]


def is_explicit_unknown(page_id: str, node: dict[str, Any]) -> tuple[bool, str | None]:
    node_id = str(node.get("id", ""))
    technical = str(node.get("technical_name", ""))
    if node_id in UNKNOWN_NODE_IDS or technical in UNKNOWN_TECHNICAL_NAMES:
        return True, "trigger is outside the currently reachable root routes or remains unverified"
    if technical.lower().startswith("cro"):
        return True, "CRO fields have no verified visible trigger"
    if page_id == "related-attachments" and (
        node_id.endswith("-candidate")
        or node.get("requires_saved_state") is True
        or node.get("source_classification") == "save_state_candidate"
    ):
        return True, "attachment control is only observable after saving a draft"
    return False, None


def known_rule(
    page_id: str,
    node: dict[str, Any],
    index: ControlIndex,
) -> dict[str, Any]:
    """Return rules established by live exploration for formerly textual nodes."""

    node_id = str(node.get("id", ""))
    rule: dict[str, Any] = {}
    route_observational = equals(ROUTE_CONTROL, "investigator-observational")
    route_interventional = equals(ROUTE_CONTROL, "investigator-interventional")
    route_drug_device = one_of(ROUTE_CONTROL, ["product-drug", "product-medical-device"])
    chictr_public = equals(CHICTR_CONTROL, CHICTR_PUBLIC)

    if node_id == "research-classification-level-2":
        rule.update(visible_if=True, required=True)
    elif node_id == "research-classification-level-3":
        condition = one_of(ROUTE_CONTROL, ["product-medical-device", "product-ivd"])
        rule.update(visible_if=condition, required=condition)
    elif node_id == "diagnostic-test-classification":
        rule["visible_if"] = route_observational
    elif node_id == "nmpa-information":
        rule.update(
            visible_if=one_of(
                ROUTE_CONTROL,
                ["product-drug", "product-medical-device", "product-ivd"],
            ),
            required=False,
            requiredness_note="NMPA requiredness differs by product/class and is retained for later class-level repair",
        )
    elif node_id in {"nmpa-number", "nmpa-date", "nmpa-document"}:
        # The parent group's visibility is already inherited by the active DAG.
        # Requiredness uses the same conservative product-route condition until
        # the class-II/III refinement is applied.
        nmpa_condition = one_of(
            ROUTE_CONTROL,
            ["product-drug", "product-medical-device", "product-ivd"],
        )
        rule.update(visible_if=True, required=nmpa_condition)
    elif node_id == "iit-product-attribute":
        rule["visible_if"] = route_interventional
    elif node_id == "gcp-cell-product-attribute":
        rule["visible_if"] = route_drug_device
    elif node_id == "unmarketed-product-repeat":
        condition = all_of(route_interventional, equals("tab0.iit-product-attribute", "unproduct"))
        rule.update(visible_if=condition, required=condition)
    elif node_id == "unmarketed-organ-type":
        rule["visible_if"] = True
    elif node_id == "cell-preparation-information":
        condition = all_of(
            route_drug_device,
            one_of("tab0.gcp-cell-product-attribute", ["stem", "somatic"]),
        )
        rule.update(visible_if=condition, required=condition)
    elif node_id == "cell-indication-other":
        rule["visible_if"] = equals(
            "tab0.cell-preparation-information.cell-indication", "其他"
        )
    elif node_id == "cell-preparation-type-other":
        rule["visible_if"] = equals(
            "tab0.cell-preparation-information.cell-preparation-type", "其他"
        )
    elif node_id == "cell-preparation-manufacturer-other":
        rule["visible_if"] = equals(
            "tab0.cell-preparation-information.cell-preparation-manufacturer", "其他"
        )
    elif node_id == "innovative-drug-device":
        rule["visible_if"] = route_drug_device
    elif node_id == "tcm-guided":
        rule["visible_if"] = True
    elif node_id == "base-research-sponsor":
        rule["visible_if"] = one_of(ROUTE_CONTROL, PRODUCT_ROUTES)
    elif node_id == "base-research-sponsor-english":
        rule["visible_if"] = all_of(one_of(ROUTE_CONTROL, PRODUCT_ROUTES), chictr_public)
    elif node_id in {"funding-source-level-2", "funding-source-level-3"}:
        rule.update(visible_if=True, required=False)
    elif node_id == "recruitment-period":
        rule["visible_if"] = True
    elif node_id in {"multicenter-type", "organization-role", "has-participating-branches"}:
        yes = preferred_option(index, "tab2.multicenter-flag", ["yes", "是"])
        rule["visible_if"] = equals("tab2.multicenter-flag", yes)
    elif node_id in {"leading-institution", "leading-country"}:
        yes = preferred_option(index, "tab2.multicenter-flag", ["yes", "是"])
        rule["visible_if"] = all_of(
            equals("tab2.multicenter-flag", yes),
            one_of("tab2.organization-role", ["4", "6"]),
        )
    elif node_id == "leading-province":
        rule["visible_if"] = equals("tab2.leading-country", "1")
    elif node_id == "participating-organization-repeat":
        has_branch = preferred_option(index, "tab2.has-participating-branches", ["yes", "有", "是"])
        condition = equals("tab2.has-participating-branches", has_branch)
        rule.update(visible_if=condition, required=condition)
    elif node_id in {"branch-country", "branch-organization-level"}:
        rule["visible_if"] = True
    elif node_id == "branch-province-select":
        rule["visible_if"] = equals("tab2.branch-country", "1")
    elif node_id == "branch-province-name":
        rule["visible_if"] = not_equals("tab2.branch-country", "1")
    elif node_id == "branch-province-name-english":
        rule["visible_if"] = all_of(
            not_equals("tab2.branch-country", "1"),
            chictr_public,
        )
    elif node_id == "observational-status":
        rule["visible_if"] = route_observational
    elif node_id == "research-self-evaluation":
        rule["visible_if"] = route_interventional
    elif node_id == "keyword-1":
        rule["required"] = False
    elif node_id == "research-phase":
        rule["visible_if"] = True
    elif node_id == "research-phase-other":
        other_value = preferred_option(index, "tab3.research-phase", ["other", "其他"])
        condition = equals("tab3.research-phase", other_value)
        rule.update(visible_if=condition, required=condition)
    elif page_id == "recruitment-information" and node_id == "overseas-recruitment":
        recruitment_yes = preferred_option(
            index, "recruitment-information.recruitment-flag", ["yes", "是"]
        )
        rule["visible_if"] = all_of(
            equals("recruitment-information.recruitment-flag", recruitment_yes),
            equals("basic-information.funding-international-cooperation", "是"),
        )
    elif page_id == "recruitment-information" and node_id == "overseas-recruitment-country":
        overseas_yes = preferred_option(
            index,
            "recruitment-information.overseas-recruitment.overseas-recruitment-flag",
            ["yes", "是"],
        )
        condition = equals(
            "recruitment-information.overseas-recruitment.overseas-recruitment-flag",
            overseas_yes,
        )
        rule.update(visible_if=condition, required=condition)

    if node_id == "funding-international-cooperation":
        rule.update(
            path="basic-information.funding-international-cooperation",
            options=["是", "否"],
        )
    if node_id == "keywords" or node.get("technical_name") == "keyword":
        rule["min_nonempty"] = 1
    return rule


def reindex(nodes: list[Any]) -> None:
    for order, node in enumerate(nodes):
        if isinstance(node, dict):
            node["order"] = order


def candidate_record(node: Any, parent_path: str, reasons: list[str]) -> Any:
    if not isinstance(node, dict):
        return {
            "kind": "unparsed-node",
            "raw_value": copy.deepcopy(node),
            "candidate_parent_path": parent_path,
            "candidate_reason": reasons,
        }
    result = copy.deepcopy(node)
    result["candidate_parent_path"] = parent_path
    existing = result.get("candidate_reason")
    merged: list[str] = []
    if isinstance(existing, list):
        merged.extend(str(item) for item in existing)
    elif existing:
        merged.append(str(existing))
    merged.extend(reason for reason in reasons if reason not in merged)
    result["candidate_reason"] = merged
    return result


class Normalizer:
    def __init__(self, document: dict[str, Any]) -> None:
        self.document = copy.deepcopy(document)
        workflow = self.document.get("workflow")
        if not isinstance(workflow, dict) or not isinstance(workflow.get("pages"), list):
            raise ValueError("workflow.pages must be a list")
        self.pages: list[Any] = workflow["pages"]
        self.original_index = ControlIndex(self.pages)
        self.moved: list[dict[str, Any]] = []

    def add_candidate(
        self,
        page: dict[str, Any],
        node: Any,
        parent_path: str,
        reasons: list[str],
    ) -> None:
        section = page.setdefault(
            "unverified_candidate_nodes",
            {
                "status": "needs_live_verification",
                "reason": "Nodes excluded from the active DAG because their structure or trigger is not mechanically verified.",
                "nodes": [],
            },
        )
        if isinstance(section, list):
            section = {
                "status": "needs_live_verification",
                "reason": "Pre-existing candidate nodes plus mechanically excluded nodes.",
                "nodes": section,
            }
            page["unverified_candidate_nodes"] = section
        if not isinstance(section, dict):
            section = {
                "status": "needs_live_verification",
                "reason": "Malformed pre-existing candidate section retained for review.",
                "nodes": [candidate_record(section, page.get("id", "page"), ["malformed candidate section"])],
            }
            page["unverified_candidate_nodes"] = section
        raw_nodes = section.setdefault("nodes", [])
        if not isinstance(raw_nodes, list):
            raw_nodes = [candidate_record(raw_nodes, page.get("id", "page"), ["malformed candidate node list"])]
            section["nodes"] = raw_nodes
        raw_nodes.append(candidate_record(node, parent_path, reasons))
        self.moved.append(
            {
                "page": page.get("id"),
                "node": node.get("id") if isinstance(node, dict) else None,
                "parent": parent_path,
                "reasons": reasons,
            }
        )

    def normalize_node(
        self,
        page: dict[str, Any],
        raw: Any,
        parent_path: str,
    ) -> dict[str, Any] | None:
        if not isinstance(raw, dict):
            self.add_candidate(page, raw, parent_path, ["node is not a mapping"])
            return None
        node = copy.deepcopy(raw)
        kind = node.get("kind")
        node_id = node.get("id")
        reasons: list[str] = []
        if kind not in STRUCTURAL_KINDS:
            reasons.append(f"unsupported or missing kind: {kind!r}")
        if not isinstance(node_id, str) or not node_id.strip():
            reasons.append("missing non-empty id")
        if not isinstance(node.get("label"), str) or not node.get("label"):
            reasons.append("missing non-empty label")
        if reasons:
            self.add_candidate(page, raw, parent_path, reasons)
            return None

        page_id = str(page.get("id", ""))
        unknown, unknown_reason = is_explicit_unknown(page_id, node)
        if unknown:
            self.add_candidate(page, raw, parent_path, [str(unknown_reason)])
            return None

        node_path = f"{parent_path}.{node_id}"
        rule = known_rule(page_id, node, self.original_index)
        for key, value in rule.items():
            node[key] = copy.deepcopy(value)
        if rule:
            node.pop("needs_live_verification", None)

        visible = normalize_condition(node.get("visible_if", True), self.original_index)
        if visible is None:
            raise ValueError(
                f"{node_path}: textual/invalid visible_if has no verified normalization rule: "
                f"{node.get('visible_if')!r}"
            )
        else:
            node["visible_if"] = visible

        if "enabled_if" in node:
            enabled = normalize_condition(node["enabled_if"], self.original_index)
            if enabled is None:
                raise ValueError(
                    f"{node_path}: textual/invalid enabled_if has no verified normalization rule: "
                    f"{node['enabled_if']!r}"
                )
            else:
                node["enabled_if"] = enabled

        required = node.get("required", False)
        if required is None and kind in {"group", "action"}:
            node["required"] = False
        elif isinstance(required, bool):
            node["required"] = required
        else:
            source_required = node.get("required_if") if required == "conditional" else required
            normalized_required = normalize_condition(source_required, self.original_index)
            if normalized_required is None:
                raise ValueError(
                    f"{node_path}: textual/invalid requiredness has no verified normalization rule: "
                    f"{source_required!r}"
                )
            else:
                node["required"] = normalized_required
                node.pop("required_if", None)

        if kind == "control":
            if not isinstance(node.get("widget"), str) or not node.get("widget"):
                reasons.append("missing non-empty widget")
            raw_options = node.get("options")
            if isinstance(raw_options, list):
                for option in raw_options:
                    if not isinstance(option, dict) or "visible_if" not in option:
                        continue
                    normalized = normalize_condition(option["visible_if"], self.original_index)
                    if normalized is None:
                        raise ValueError(
                            f"{node_path}: option {option.get('id')!r} has no verified visibility rule: "
                            f"{option['visible_if']!r}"
                        )
                    else:
                        option["visible_if"] = normalized

        if kind == "group":
            raw_children = node.get("children")
            raw_nodes = node.get("nodes")
            children_nonempty = isinstance(raw_children, list) and bool(raw_children)
            nodes_nonempty = isinstance(raw_nodes, list) and bool(raw_nodes)
            if children_nonempty and nodes_nonempty:
                self.add_candidate(
                    page,
                    raw,
                    parent_path,
                    ["group has conflicting non-empty nodes and children containers"],
                )
                return None
            children_source = raw_children if isinstance(raw_children, list) else raw_nodes
            if not isinstance(children_source, list):
                children_source = []

            if not children_source:
                if (
                    node.get("widget") == "required-selection-modal-and-table"
                    and isinstance(node.get("technical_name"), str)
                    and node["technical_name"].strip()
                ):
                    node["kind"] = "control"
                    node.pop("nodes", None)
                    node.pop("children", None)
                    node.setdefault("normalization_note", "empty runtime-backed group normalized to one composite control")
                    return node
                self.add_candidate(page, raw, parent_path, ["empty group has no verified composite-control rule"])
                return None

            node.pop("nodes", None)
            node["children"] = []
            for child in children_source:
                normalized_child = self.normalize_node(page, child, node_path)
                if normalized_child is not None:
                    node["children"].append(normalized_child)
            reindex(node["children"])
            if not node["children"]:
                self.add_candidate(page, raw, parent_path, ["all group children require live verification"])
                return None
        else:
            node.pop("nodes", None)
            node.pop("children", None)
        return node

    def normalize_page(self, page: Any, page_order: int) -> None:
        if not isinstance(page, dict):
            raise ValueError(f"workflow.pages[{page_order}] is not a mapping")
        page["order"] = page_order
        page_id = page.get("id")
        if not isinstance(page_id, str) or not page_id:
            raise ValueError(f"workflow.pages[{page_order}] lacks a non-empty id")

        if page_id == "recruitment-information":
            original_page_condition = one_of(
                ROUTE_CONTROL,
                [
                    "product-drug",
                    "product-medical-device",
                    "product-special-food",
                    "investigator-interventional",
                ],
            )
            page.pop("unverified_page_visibility", None)
        else:
            original_page_condition = page.get("visible_if", True)
        normalized_page_condition = normalize_condition(original_page_condition, self.original_index)
        key, raw_nodes = node_container(page, page=True)
        if key == "fields":
            page.pop("fields", None)
        page["nodes"] = []

        if normalized_page_condition is None:
            raise ValueError(
                f"page {page_id}: textual/invalid visible_if has no verified normalization rule: "
                f"{original_page_condition!r}"
            )
        page["visible_if"] = normalized_page_condition
        for raw in raw_nodes:
            normalized = self.normalize_node(page, raw, page_id)
            if normalized is not None:
                page["nodes"].append(normalized)
        reindex(page["nodes"])
        self._normalize_existing_candidates(page)

    def _normalize_existing_candidates(self, page: dict[str, Any]) -> None:
        section = page.get("unverified_candidate_nodes")
        if section is None:
            return
        if isinstance(section, list):
            section = {
                "status": "needs_live_verification",
                "reason": "Pre-existing unverified candidate nodes.",
                "nodes": section,
            }
            page["unverified_candidate_nodes"] = section
        if not isinstance(section, dict):
            return
        section.setdefault("status", "needs_live_verification")
        section.setdefault("reason", "Unverified candidates excluded from the active DAG.")
        nodes = section.setdefault("nodes", [])
        if isinstance(nodes, list):
            reindex(nodes)

    def run(self) -> dict[str, Any]:
        for order, page in enumerate(self.pages):
            self.normalize_page(page, order)
        active, candidates = count_nodes(self.document)
        self.document["normalization_audit"] = {
            "mode": "mechanical_no_guessing",
            "schema_version_preserved": self.document.get("schema_version"),
            "status_preserved": self.document.get("status"),
            "active_structural_nodes": active,
            "candidate_structural_nodes": candidates,
            "moved_this_run": len(self.moved),
            "rule": "only explicitly unreachable/unverified UI structures are candidates; cross-page aliases await path repair",
        }
        return self.document


def walk_active(nodes: Iterable[Any]) -> Iterable[dict[str, Any]]:
    for raw in nodes:
        if not isinstance(raw, dict):
            continue
        yield raw
        if raw.get("kind") == "group":
            yield from walk_active(raw.get("children") or [])


def walk_candidate(nodes: Iterable[Any]) -> Iterable[dict[str, Any]]:
    for raw in nodes:
        if not isinstance(raw, dict):
            continue
        if raw.get("kind") in STRUCTURAL_KINDS:
            yield raw
        children: list[Any] = []
        if isinstance(raw.get("children"), list):
            children.extend(raw["children"])
        if isinstance(raw.get("nodes"), list):
            children.extend(raw["nodes"])
        yield from walk_candidate(children)


def count_nodes(document: dict[str, Any]) -> tuple[int, int]:
    active = 0
    candidates = 0
    pages = document.get("workflow", {}).get("pages", [])
    for page in pages if isinstance(pages, list) else []:
        if not isinstance(page, dict):
            continue
        active += sum(1 for node in walk_active(page.get("nodes") or []) if node.get("kind") in STRUCTURAL_KINDS)
        section = page.get("unverified_candidate_nodes")
        raw = section.get("nodes", []) if isinstance(section, dict) else section
        if isinstance(raw, list):
            candidates += sum(1 for _ in walk_candidate(raw))
    return active, candidates


def validate_internal(
    document: dict[str, Any], original_schema: Any, original_status: Any
) -> list[str]:
    issues: list[str] = []
    if document.get("schema_version") != original_schema:
        issues.append("schema_version changed")
    if document.get("status") != original_status:
        issues.append("status changed")
    pages = document.get("workflow", {}).get("pages")
    if not isinstance(pages, list):
        return [*issues, "workflow.pages is not a list"]
    seen_ids: set[str] = set()
    control_index = ControlIndex(pages)

    def check_list(nodes: Any, location: str) -> None:
        if not isinstance(nodes, list):
            issues.append(f"{location} is not a list")
            return
        for order, node in enumerate(nodes):
            here = f"{location}[{order}]"
            if not isinstance(node, dict):
                issues.append(f"{here} is not a mapping")
                continue
            if node.get("order") != order or isinstance(node.get("order"), bool):
                issues.append(f"{here}.order is not zero-based integer {order}")
            node_id = node.get("id")
            if isinstance(node_id, str):
                if node_id in seen_ids:
                    issues.append(f"{here}.id duplicate active id {node_id!r}")
                seen_ids.add(node_id)
            for key in ("visible_if", "enabled_if"):
                if key in node and not condition_valid(node[key], control_index, resolve=False):
                    issues.append(f"{here}.{key} is not a structurally valid canonical condition")
            required = node.get("required", False)
            if not isinstance(required, bool) and not condition_valid(required, control_index, resolve=False):
                issues.append(f"{here}.required is not a structurally valid canonical condition")
            if node.get("kind") == "group":
                if "nodes" in node:
                    issues.append(f"{here} group still uses nodes instead of children")
                children = node.get("children")
                if not isinstance(children, list) or not children:
                    issues.append(f"{here} active group has no children")
                else:
                    check_list(children, f"{here}.children")

    for order, page in enumerate(pages):
        location = f"workflow.pages[{order}]"
        if not isinstance(page, dict):
            issues.append(f"{location} is not a mapping")
            continue
        if page.get("order") != order or isinstance(page.get("order"), bool):
            issues.append(f"{location}.order is not zero-based integer {order}")
        if not condition_valid(page.get("visible_if", True), control_index, resolve=False):
            issues.append(f"{location}.visible_if is not a structurally valid canonical condition")
        check_list(page.get("nodes"), f"{location}.nodes")
    return issues


def atomic_category(issue: str) -> str:
    lower = issue.lower()
    if "field shorthand" in lower:
        return "field_shorthand"
    if "condition must" in lower or "condition mapping" in lower or "atomic condition" in lower:
        return "condition_grammar"
    if "unknown control path" in lower or "unknown option" in lower or "no declared options" in lower:
        return "condition_or_scenario_reference"
    if "coverage gap" in lower:
        return "scenario_coverage"
    if "observed_signature" in lower or "signature mismatch" in lower or "signature keys" in lower:
        return "observed_signature"
    if "page_sequence" in lower or "observed_pages page order" in lower or "strict mismatch" in lower:
        return "scenario_page_sequence"
    if "verification" in lower or "scenario" in lower or ".selections" in lower:
        return "scenario_structure"
    if "duplicate" in lower or ".order" in lower:
        return "duplicate_or_order"
    if "required for kind" in lower or "must be a non-empty string" in lower or "must be a list" in lower:
        return "node_metadata_or_shape"
    return "other"


def write_yaml_atomic_candidate(document: dict[str, Any], target: Path) -> Path:
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=target.parent)
    temp_path = Path(name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            yaml.dump(
                document,
                handle,
                Dumper=NoAliasSafeDumper,
                allow_unicode=True,
                sort_keys=False,
                width=120,
            )
            handle.flush()
            os.fsync(handle.fileno())
        return temp_path
    except Exception:
        temp_path.unlink(missing_ok=True)
        raise


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
    parser = argparse.ArgumentParser()
    parser.add_argument("target", nargs="?", type=Path, default=DEFAULT_TARGET)
    parser.add_argument("--check", action="store_true", help="validate a temporary normalized copy only")
    args = parser.parse_args()
    target = args.target.resolve()
    original_stat = target.stat()
    original = yaml_load(target)
    schema = original.get("schema_version")
    status = original.get("status")

    normalized = Normalizer(original).run()
    temp_path = write_yaml_atomic_candidate(normalized, target)
    try:
        reparsed = yaml_load(temp_path)
        internal = validate_internal(reparsed, schema, status)
        active, candidates = count_nodes(reparsed)
        atomic = validate_atomic_document(reparsed)
        categories = Counter(atomic_category(issue) for issue in atomic)

        print(f"MODE {'CHECK_ONLY' if args.check else 'REPLACE'}")
        print(f"TARGET {target}")
        print(f"ACTIVE_STRUCTURAL_NODES {active}")
        print(f"CANDIDATE_STRUCTURAL_NODES {candidates}")
        print(f"INTERNAL_ISSUES {len(internal)}")
        for issue in internal:
            print(f"INTERNAL_ISSUE {issue}")
        print(f"ATOMIC_ISSUES {len(atomic)}")
        for category, count in sorted(categories.items()):
            print(f"ATOMIC_CATEGORY {category}={count}")

        if internal:
            print("RESULT REFUSED_INTERNAL_VALIDATION")
            return 2
        if args.check:
            current_stat = target.stat()
            unchanged = (
                current_stat.st_size == original_stat.st_size
                and current_stat.st_mtime_ns == original_stat.st_mtime_ns
            )
            print(f"CANONICAL_UNCHANGED {str(unchanged).lower()}")
            print("RESULT CHECK_PASSED")
            return 0 if unchanged else 3

        os.replace(temp_path, target)
        print("RESULT REPLACED_ATOMICALLY")
        return 0
    finally:
        temp_path.unlink(missing_ok=True)


if __name__ == "__main__":
    raise SystemExit(main())
