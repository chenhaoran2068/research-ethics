#!/usr/bin/env python3
"""Compare two de-identified form-structure snapshots.

This utility deliberately accepts only a compact field inventory.  It is for
recording normal-UI observations, not for saving DOM/source, screenshots, or
browser/session data.  A snapshot has this shape::

    {"page_id": "research-design", "controls": [{
      "path": "research-design.random-group", "label": "...", "order": 1,
      "required": true, "widget": "radio", "options": ["yes", "no"],
      "visible": true, "enabled": true, "bilingual": false,
      "repeat_group": null, "attachment": false
    }]}

Only structural properties are compared.  Field values are neither accepted
nor emitted.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


ALLOWED_TOP = {"page_id", "page_order", "controls"}
ALLOWED_CONTROL = {
    "path",
    "label",
    "order",
    "required",
    "widget",
    "options",
    "visible",
    "enabled",
    "bilingual",
    "repeat_group",
    "attachment",
}
PROHIBITED_TOKENS = {
    "value",
    "text",
    "html",
    "source",
    "screenshot",
    "cookie",
    "password",
    "token",
    "localstorage",
    "email",
    "phone",
    "name",
}
COMPARE_PROPERTIES = (
    "label",
    "order",
    "required",
    "widget",
    "options",
    "visible",
    "enabled",
    "bilingual",
    "repeat_group",
    "attachment",
)


def reject_sensitive_keys(mapping: dict[str, Any], allowed: set[str], where: str) -> None:
    unknown = set(mapping) - allowed
    if unknown:
        raise ValueError(f"{where} contains unknown or disallowed keys: {sorted(unknown)}")
    prohibited = [key for key in mapping if key.lower().replace("_", "") in PROHIBITED_TOKENS]
    if prohibited:
        raise ValueError(f"{where} contains prohibited data-bearing keys: {prohibited}")


def load_snapshot(path: Path) -> dict[str, Any]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"{path}: snapshot must be an object")
    reject_sensitive_keys(raw, ALLOWED_TOP, str(path))
    if not isinstance(raw.get("page_id"), str) or not raw["page_id"]:
        raise ValueError(f"{path}: page_id must be a nonempty string")
    controls = raw.get("controls")
    if not isinstance(controls, list):
        raise ValueError(f"{path}: controls must be a list")
    index: dict[str, dict[str, Any]] = {}
    for number, control in enumerate(controls, start=1):
        if not isinstance(control, dict):
            raise ValueError(f"{path}: controls[{number}] must be an object")
        reject_sensitive_keys(control, ALLOWED_CONTROL, f"{path}: controls[{number}]")
        field_path = control.get("path")
        if not isinstance(field_path, str) or not field_path:
            raise ValueError(f"{path}: controls[{number}].path must be a nonempty string")
        if field_path in index:
            raise ValueError(f"{path}: duplicate control path {field_path}")
        if "options" in control and not isinstance(control["options"], list):
            raise ValueError(f"{path}: {field_path}.options must be a list")
        index[field_path] = control
    return {"page_id": raw["page_id"], "page_order": raw.get("page_order"), "index": index}


def compare(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    before_index = before["index"]
    after_index = after["index"]
    before_paths = set(before_index)
    after_paths = set(after_index)
    changed: list[dict[str, Any]] = []
    unchanged: list[str] = []
    for field_path in sorted(before_paths & after_paths):
        property_changes = {
            prop: {"before": before_index[field_path].get(prop), "after": after_index[field_path].get(prop)}
            for prop in COMPARE_PROPERTIES
            if before_index[field_path].get(prop) != after_index[field_path].get(prop)
        }
        if property_changes:
            changed.append({"path": field_path, "properties": property_changes})
        else:
            unchanged.append(field_path)
    return {
        "before_page_id": before["page_id"],
        "after_page_id": after["page_id"],
        "page_changed": before["page_id"] != after["page_id"] or before.get("page_order") != after.get("page_order"),
        "added": sorted(after_paths - before_paths),
        "removed": sorted(before_paths - after_paths),
        "changed": changed,
        "unchanged": unchanged,
    }


def markdown(report: dict[str, Any]) -> str:
    lines = ["# De-identified form-structure difference", ""]
    lines.append(f"- Before page: `{report['before_page_id']}`")
    lines.append(f"- After page: `{report['after_page_id']}`")
    lines.append(f"- Page changed: `{str(report['page_changed']).lower()}`")
    for heading, values in (("Added controls", report["added"]), ("Removed controls", report["removed"]), ("Unchanged controls", report["unchanged"])):
        lines.extend(["", f"## {heading}"])
        lines.extend([f"- `{value}`" for value in values] or ["- None"])
    lines.extend(["", "## Property changes"])
    if not report["changed"]:
        lines.append("- None")
    else:
        for item in report["changed"]:
            lines.append(f"- `{item['path']}`")
            for prop, values in item["properties"].items():
                lines.append(f"  - `{prop}`: `{values['before']}` → `{values['after']}`")
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("before", type=Path, help="de-identified JSON snapshot before a normal UI selection")
    parser.add_argument("after", type=Path, help="de-identified JSON snapshot after a normal UI selection")
    parser.add_argument("--output", type=Path, help="optional Markdown report path")
    args = parser.parse_args()
    report = compare(load_snapshot(args.before), load_snapshot(args.after))
    rendered = markdown(report)
    if args.output:
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
