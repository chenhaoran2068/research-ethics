#!/usr/bin/env python3
"""Render the mandatory structural-confirmation sheet for a V1 intake.

This tool deliberately accepts an incomplete proposed intake.  It never marks
anything confirmed: the calling agent must show the result to the user, wait
for an explicit reply, then record the exact confirmed option IDs in the
intake before it may render a filling draft.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

import yaml

from validate_atomic_schema import AtomicSchemaValidator
from confirmation_workflow import active_structural_paths


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CANONICAL = PROJECT_ROOT / "references" / "registration-tree.yaml"
CONDITION_KEYS = {"visible_if", "required", "required_if", "enabled_if"}


def read_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"{path} 必须是 YAML 映射")
    return data


def condition_paths(value: Any) -> set[str]:
    paths: set[str] = set()
    if isinstance(value, dict):
        control = value.get("control")
        if isinstance(control, str):
            paths.add(control)
        for child in value.values():
            paths.update(condition_paths(child))
    elif isinstance(value, list):
        for child in value:
            paths.update(condition_paths(child))
    return paths


def impact_labels(canonical: dict[str, Any]) -> dict[str, list[str]]:
    """Map a driver to labels whose visibility/requiredness it can change."""
    impacts: dict[str, list[str]] = {}

    def add(condition: Any, target: str) -> None:
        for path in condition_paths(condition):
            impacts.setdefault(path, []).append(target)

    def visit_nodes(nodes: Any) -> None:
        if not isinstance(nodes, list):
            return
        for node in nodes:
            if not isinstance(node, dict):
                continue
            label = str(node.get("label") or node.get("path") or "未命名字段")
            for key in CONDITION_KEYS:
                if key in node:
                    add(node[key], label)
            options = node.get("options")
            if isinstance(options, list):
                for option in options:
                    if isinstance(option, dict):
                        for key in CONDITION_KEYS:
                            if key in option:
                                add(option[key], f"{label} 的可选项")
            visit_nodes(node.get("children"))

    workflow = canonical.get("workflow", {})
    pages = workflow.get("pages", []) if isinstance(workflow, dict) else []
    for page in pages if isinstance(pages, list) else []:
        if not isinstance(page, dict):
            continue
        page_label = str(page.get("label") or page.get("id") or "未命名页面")
        for key in CONDITION_KEYS:
            if key in page:
                add(page[key], f"页面：{page_label}")
        visit_nodes(page.get("nodes"))
    return impacts


def option_labels(canonical: dict[str, Any]) -> dict[str, dict[str, str]]:
    labels: dict[str, dict[str, str]] = {}

    def visit_nodes(nodes: Any) -> None:
        if not isinstance(nodes, list):
            return
        for node in nodes:
            if not isinstance(node, dict):
                continue
            path = node.get("path")
            options = node.get("options")
            if isinstance(path, str) and isinstance(options, list):
                mapping: dict[str, str] = {}
                for option in options:
                    if isinstance(option, dict):
                        option_id = str(option.get("id", option.get("label", "")))
                        mapping[option_id] = str(option.get("label", option_id))
                    else:
                        mapping[str(option)] = str(option)
                labels[path] = mapping
            visit_nodes(node.get("children"))

    workflow = canonical.get("workflow", {})
    if isinstance(workflow, dict):
        for page in workflow.get("pages", []):
            if isinstance(page, dict):
                visit_nodes(page.get("nodes"))
    return labels


def option_text(control: Any, labels: dict[str, str]) -> str:
    values: list[str] = []
    for option in control.options:
        option_id = str(option.option_id)
        label = labels.get(option_id, option_id)
        values.append(label if label == option_id else f"{label}（{option_id}）")
    return "、".join(values) if values else "平台实时字典／当前页面选择"


def display_value(control: Any, proposed: Any, labels: dict[str, str]) -> str:
    if proposed is None:
        return "**待用户确认**"
    selected = {str(item) for item in proposed} if isinstance(proposed, list) else {str(proposed)}
    selected_labels = [labels.get(str(option.option_id), str(option.option_id)) for option in control.options if str(option.option_id) in selected]
    return "、".join(selected_labels) if selected_labels else "、".join(sorted(selected))


def render(canonical: dict[str, Any], intake: dict[str, Any]) -> str:
    validator = AtomicSchemaValidator(canonical)
    errors = validator.validate()
    if errors:
        raise ValueError("canonical YAML 无法通过校验：" + "; ".join(errors[:3]))

    selections = intake.get("selections", {})
    metadata = intake.get("metadata", {})
    if not isinstance(selections, dict):
        selections = {}
    if not isinstance(metadata, dict):
        metadata = {}
    confirmation = metadata.get("structural_confirmation", {})
    confirmed = confirmation.get("confirmed_selections", {}) if isinstance(confirmation, dict) else {}
    if not isinstance(confirmed, dict):
        confirmed = {}

    impacts = impact_labels(canonical)
    labels_by_path = option_labels(canonical)
    lines = [
        "# 结构性确认单（必须先确认）",
        "",
        "本单列出当前路线中会改变页面、字段、必填性、可选项、重复组或附件的选择。",
        "研究计划书中的内容仅是建议；请由用户逐项确认或修改。未完成本单时，不得生成 Markdown 或 Word 逐项填写稿。",
        "",
    ]
    for number, path in enumerate(active_structural_paths(validator, canonical, selections), start=1):
        control = validator.controls[path]
        proposed = selections.get(path)
        is_confirmed = path in selections and confirmed.get(path) == proposed
        targets = list(dict.fromkeys(impacts.get(path, [])))
        impact = "、".join(targets[:4]) if targets else "当前路线或派生字段"
        if len(targets) > 4:
            impact += "等"
        lines.extend(
            [
                f"## {number}. {control.label}",
                f"- 字段路径：`{path}`",
                f"- 计划书候选：{display_value(control, proposed, labels_by_path.get(path, {}))}",
                f"- 可选项：{option_text(control, labels_by_path.get(path, {}))}",
                f"- 结构影响：{impact}",
                f"- 用户确认：{'已记录；仍须核对本轮回复' if is_confirmed else '**待用户明确确认**'}",
                "",
            ]
        )
    lines.extend(
        [
            "## 确认方式",
            "",
            "请回复每个待确认字段的选择；可采用“字段路径＝选项 ID”的形式。",
            "收到明确回复后，将确认过的精确选项 ID 同时写入 `selections` 与 `metadata.structural_confirmation.confirmed_selections`，并设定：",
            "`status: explicitly_confirmed`、`method: user_explicit`。",
            "如确认结果显示新的结构性控件，必须重新生成本单并继续确认；本工具不会自行写入确认状态。",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--intake", type=Path, required=True, help="proposed intake; confirmation may be incomplete")
    parser.add_argument("--canonical", type=Path, default=DEFAULT_CANONICAL)
    parser.add_argument("--output", type=Path, help="optional Markdown output; stdout when omitted")
    args = parser.parse_args()
    try:
        result = render(read_yaml(args.canonical), read_yaml(args.intake))
    except ValueError as error:
        print(f"无法生成结构性确认单：{error}", file=sys.stderr)
        return 2
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(result, encoding="utf-8")
        print(f"Rendered {args.output}")
    else:
        print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
