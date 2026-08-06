#!/usr/bin/env python3
"""Shared, de-identified helpers for the two-stage intake confirmation flow.

The canonical workflow remains the only source of platform fields and
conditions.  This module only determines which existing intake items need a
user reply; it never supplies a study fact or writes confirmation metadata.
"""

from __future__ import annotations

from typing import Any

from validate_atomic_schema import AtomicSchemaValidator


CORE_STRUCTURAL_PATHS = {
    "research-category.route-leaf",
    "research-category.diagnostic-trial",
    "basic-information.sync-platform",
}
PENDING_MARKERS = {"", "待用户确认", "<待用户确认>"}


def selected_values(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value]
    return [str(value)]


def _condition_control_paths(value: Any) -> set[str]:
    paths: set[str] = set()
    if isinstance(value, dict):
        control = value.get("control")
        if isinstance(control, str):
            paths.add(control)
        for child in value.values():
            paths.update(_condition_control_paths(child))
    elif isinstance(value, list):
        for child in value:
            paths.update(_condition_control_paths(child))
    return paths


def structural_driver_paths(canonical: dict[str, Any]) -> set[str]:
    workflow = canonical.get("workflow", {})
    if not isinstance(workflow, dict):
        return set(CORE_STRUCTURAL_PATHS)
    return CORE_STRUCTURAL_PATHS | _condition_control_paths(workflow.get("pages", []))


def active_structural_paths(
    validator: AtomicSchemaValidator, canonical: dict[str, Any], selections: dict[str, Any]
) -> list[str]:
    """Return the currently visible decisions that can alter form structure."""
    active: set[str] = set()
    for path in structural_driver_paths(canonical):
        control = validator.controls.get(path)
        if control is None:
            continue
        if path not in CORE_STRUCTURAL_PATHS and (not control.options or not control.observable):
            continue
        if path in CORE_STRUCTURAL_PATHS or all(
            validator._evaluate(condition, selections) for condition in control.visibility_chain
        ):
            active.add(path)
    return sorted(active)


def raw_control_index(canonical: dict[str, Any]) -> dict[str, dict[str, Any]]:
    controls: dict[str, dict[str, Any]] = {}

    def visit(nodes: Any) -> None:
        if not isinstance(nodes, list):
            return
        for node in nodes:
            if not isinstance(node, dict):
                continue
            if node.get("kind") == "control" and isinstance(node.get("path"), str):
                controls[node["path"]] = node
            visit(node.get("nodes") or node.get("children"))

    workflow = canonical.get("workflow", {})
    if isinstance(workflow, dict):
        for page in workflow.get("pages", []):
            if isinstance(page, dict):
                visit(page.get("nodes", page.get("fields")))
    return controls


def repeatable_group_index(canonical: dict[str, Any]) -> tuple[dict[str, dict[str, Any]], dict[str, str]]:
    groups: dict[str, dict[str, Any]] = {}
    parent_by_control: dict[str, str] = {}

    def collect_controls(nodes: Any) -> list[dict[str, Any]]:
        collected: list[dict[str, Any]] = []
        if not isinstance(nodes, list):
            return collected
        for node in nodes:
            if not isinstance(node, dict):
                continue
            if node.get("kind") == "control" and isinstance(node.get("path"), str):
                collected.append(node)
            collected.extend(collect_controls(node.get("nodes") or node.get("children")))
        return collected

    def visit(nodes: Any, repeat_parent: str | None = None) -> None:
        if not isinstance(nodes, list):
            return
        for node in nodes:
            if not isinstance(node, dict):
                continue
            path = node.get("path")
            is_repeatable = (
                node.get("kind") == "group"
                and (node.get("repeatable") is True or node.get("widget") == "repeatable-group")
                and isinstance(path, str)
            )
            current_parent = path if is_repeatable else repeat_parent
            if is_repeatable:
                groups[path] = {
                    "label": str(node.get("label", path)),
                    "children": collect_controls(node.get("nodes", node.get("children"))),
                    "required": node.get("required", False),
                }
            if node.get("kind") == "control" and isinstance(path, str) and repeat_parent:
                parent_by_control[path] = repeat_parent
            visit(node.get("nodes") or node.get("children"), current_parent)

    workflow = canonical.get("workflow", {})
    if isinstance(workflow, dict):
        for page in workflow.get("pages", []):
            if isinstance(page, dict):
                visit(page.get("nodes", page.get("fields")))
    return groups, parent_by_control


def mapping_value(mapping: dict[str, Any], path: str, raw_control: dict[str, Any] | None) -> Any:
    if path in mapping:
        return mapping[path]
    if raw_control and isinstance(raw_control.get("id"), str):
        return mapping.get(raw_control["id"])
    return None


def value_payload(raw: Any) -> Any:
    return raw.get("value") if isinstance(raw, dict) else raw


def has_value(raw: Any) -> bool:
    payload = value_payload(raw)
    if payload is None:
        return False
    text = str(payload).strip()
    return text not in PENDING_MARKERS and not (text.startswith("<") and text.endswith(">"))


def source_text(raw: Any) -> str:
    return str(raw.get("source", "")) if isinstance(raw, dict) else ""


def is_plan_derived(raw: Any) -> bool:
    source = source_text(raw).lower()
    return any(token in source for token in ("计划书", "研究方案", "protocol")) and has_value(raw)


def _control_item(
    validator: AtomicSchemaValidator, path: str, selections: dict[str, Any]
) -> dict[str, Any] | None:
    control = validator.controls.get(path)
    if control is None or not control.observable:
        return None
    if not all(validator._evaluate(condition, selections) for condition in control.visibility_chain):
        return None
    return {
        "label": control.label,
        "widget": control.widget,
        "required": bool(validator._evaluate(control.required, selections)),
        "enabled": bool(validator._evaluate(control.enabled_if, selections)),
        "options": [
            option.option_id
            for option in control.options
            if validator._evaluate(option.visible_if, selections)
        ],
    }


def _item_key(group_path: str, position: int, child_path: str) -> str:
    return f"{group_path}[{position}].{child_path}"


def _page_order(
    canonical: dict[str, Any], selections: dict[str, Any]
) -> tuple[AtomicSchemaValidator, list[tuple[Any, list[tuple[str, Any]]]]]:
    validator = AtomicSchemaValidator(canonical)
    errors = validator.validate()
    if errors:
        raise ValueError("canonical YAML 无法通过校验：" + "; ".join(errors[:3]))
    return validator, validator._expected_pages(selections)


def plan_value_candidates(canonical: dict[str, Any], intake: dict[str, Any]) -> list[dict[str, Any]]:
    """Return non-structural plan-derived value candidates in platform order."""
    selections = intake.get("selections", {})
    values = intake.get("values", {})
    repeat_groups = intake.get("repeat_groups", {})
    if not isinstance(selections, dict):
        selections = {}
    if not isinstance(values, dict):
        values = {}
    if not isinstance(repeat_groups, dict):
        repeat_groups = {}
    validator, pages = _page_order(canonical, selections)
    raw_controls = raw_control_index(canonical)
    groups, group_by_control = repeatable_group_index(canonical)
    structural = set(active_structural_paths(validator, canonical, selections))
    candidates: list[dict[str, Any]] = []
    emitted_groups: set[str] = set()

    for page_number, (page, items) in enumerate(pages, start=1):
        for path, _ in items:
            group_path = group_by_control.get(path)
            if group_path:
                if group_path in emitted_groups:
                    continue
                emitted_groups.add(group_path)
                entries = repeat_groups.get(group_path, [])
                if not isinstance(entries, list):
                    continue
                for position, entry in enumerate(entries, start=1):
                    entry = entry if isinstance(entry, dict) else {}
                    entry_values = entry.get("values", {})
                    entry_selections = entry.get("selections", {})
                    if not isinstance(entry_values, dict):
                        entry_values = {}
                    if not isinstance(entry_selections, dict):
                        entry_selections = {}
                    local_selections = dict(selections)
                    local_selections.update(entry_selections)
                    for child in groups[group_path]["children"]:
                        child_path = child.get("path")
                        if not isinstance(child_path, str) or child_path in structural:
                            continue
                        item = _control_item(validator, child_path, local_selections)
                        raw = mapping_value(entry_values, child_path, raw_controls.get(child_path))
                        if item and is_plan_derived(raw):
                            candidates.append(
                                {
                                    "key": _item_key(group_path, position, child_path),
                                    "page_number": page_number,
                                    "page_label": page.label,
                                    "label": item["label"],
                                    "value": value_payload(raw),
                                    "source": source_text(raw),
                                    "required": item["required"],
                                }
                            )
                continue
            if path in structural:
                continue
            item = _control_item(validator, path, selections)
            raw_control = raw_controls.get(path)
            raw = mapping_value(values, path, raw_control)
            if item and raw_control and raw_control.get("user_copyable") is not False and is_plan_derived(raw):
                candidates.append(
                    {
                        "key": path,
                        "page_number": page_number,
                        "page_label": page.label,
                        "label": item["label"],
                        "value": value_payload(raw),
                        "source": source_text(raw),
                        "required": item["required"],
                    }
                )
    return candidates


def pending_completion_items(canonical: dict[str, Any], intake: dict[str, Any]) -> list[dict[str, Any]]:
    """Return every visible non-structural field/group without a resolved value.

    A repeat group with no entries is represented by the group itself.  Once an
    entry exists, its visible child fields are assessed separately.
    """
    selections = intake.get("selections", {})
    values = intake.get("values", {})
    repeat_groups = intake.get("repeat_groups", {})
    if not isinstance(selections, dict):
        selections = {}
    if not isinstance(values, dict):
        values = {}
    if not isinstance(repeat_groups, dict):
        repeat_groups = {}
    validator, pages = _page_order(canonical, selections)
    raw_controls = raw_control_index(canonical)
    groups, group_by_control = repeatable_group_index(canonical)
    structural = set(active_structural_paths(validator, canonical, selections))
    pending: list[dict[str, Any]] = []
    emitted_groups: set[str] = set()

    def emit(
        *, key: str, page_number: int, page_label: str, label: str, item: dict[str, Any], kind: str,
        raw_control: dict[str, Any] | None = None,
    ) -> None:
        pending.append(
            {
                "key": key,
                "page_number": page_number,
                "page_label": page_label,
                "label": label,
                "required": bool(item.get("required", False)),
                "widget": str(item.get("widget", "")),
                "options": list(item.get("options", [])),
                "kind": kind,
                "source_classification": raw_control.get("source_classification", []) if raw_control else [],
            }
        )

    for page_number, (page, items) in enumerate(pages, start=1):
        for path, _ in items:
            group_path = group_by_control.get(path)
            if group_path:
                if group_path in emitted_groups:
                    continue
                emitted_groups.add(group_path)
                entries = repeat_groups.get(group_path)
                if not isinstance(entries, list) or not entries:
                    emit(
                        key=group_path,
                        page_number=page_number,
                        page_label=page.label,
                        label=groups[group_path]["label"],
                        item={"required": bool(groups[group_path].get("required", False)), "widget": "repeatable-group", "options": []},
                        kind="repeat_group",
                    )
                    continue
                for position, entry in enumerate(entries, start=1):
                    entry = entry if isinstance(entry, dict) else {}
                    entry_values = entry.get("values", {})
                    entry_selections = entry.get("selections", {})
                    if not isinstance(entry_values, dict):
                        entry_values = {}
                    if not isinstance(entry_selections, dict):
                        entry_selections = {}
                    local_selections = dict(selections)
                    local_selections.update(entry_selections)
                    for child in groups[group_path]["children"]:
                        child_path = child.get("path")
                        if not isinstance(child_path, str) or child_path in structural:
                            continue
                        item = _control_item(validator, child_path, local_selections)
                        raw_control = raw_controls.get(child_path)
                        if not item or (raw_control and raw_control.get("user_copyable") is False):
                            continue
                        selected = mapping_value(entry_selections, child_path, raw_control)
                        raw = mapping_value(entry_values, child_path, raw_control)
                        if selected is None and not has_value(raw):
                            emit(
                                key=_item_key(group_path, position, child_path),
                                page_number=page_number,
                                page_label=page.label,
                                label=f"{groups[group_path]['label']}·第 {position} 项·{item['label']}",
                                item=item,
                                kind="repeat_field",
                                raw_control=raw_control,
                            )
                continue
            if path in structural:
                continue
            item = _control_item(validator, path, selections)
            raw_control = raw_controls.get(path)
            if not item or (raw_control and raw_control.get("user_copyable") is False):
                continue
            if path not in selections and not has_value(mapping_value(values, path, raw_control)):
                emit(
                    key=path,
                    page_number=page_number,
                    page_label=page.label,
                    label=item["label"],
                    item=item,
                    kind="field",
                    raw_control=raw_control,
                )
    return pending
