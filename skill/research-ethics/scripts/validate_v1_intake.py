#!/usr/bin/env python3
"""Validate a de-identified V1 intake before rendering a filling draft."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

import yaml

from validate_atomic_schema import AtomicSchemaValidator


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CANONICAL = PROJECT_ROOT / "references" / "registration-tree.yaml"
SUPPORTED_ROUTE = "investigator-observational"
DISABLED_PLATFORM = "traditional-disabled"


def load_mapping(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        value = yaml.safe_load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a mapping")
    return value


def selected_values(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value]
    return [str(value)]


def validate(canonical: dict[str, Any], intake: dict[str, Any]) -> list[str]:
    validator = AtomicSchemaValidator(canonical)
    errors = validator.validate()
    if errors:
        return ["canonical YAML 无法通过校验：" + "; ".join(errors[:3])]

    selections = intake.get("selections")
    values = intake.get("values", {})
    repeat_groups = intake.get("repeat_groups", {})
    issues: list[str] = []
    if not isinstance(selections, dict):
        return ["intake.selections 必须是映射"]
    if not isinstance(values, dict):
        issues.append("intake.values 必须是映射")
    if not isinstance(repeat_groups, dict):
        issues.append("intake.repeat_groups 必须是映射")

    if selections.get("research-category.route-leaf") != SUPPORTED_ROUTE:
        issues.append("V1 仅支持 investigator-observational；其他路线为 deferred_to_v2")
    if selections.get("research-category.diagnostic-trial") not in {"yes", "no"}:
        issues.append("必须选择 research-category.diagnostic-trial = yes 或 no")
    if selections.get("basic-information.sync-platform") not in {"private", "public-on-chictr"}:
        issues.append("必须选择公开策略 private 或 public-on-chictr")
    if selections.get("basic-information.sync-platform") == DISABLED_PLATFORM:
        issues.append("传统医学注册平台暂未开通，不能生成 V1 填写稿")

    for path, selected in selections.items():
        control = validator.controls.get(path)
        if control is None:
            issues.append(f"未知选择字段：{path}")
            continue
        option_ids = {option.option_id for option in control.options}
        if not option_ids:
            continue  # Runtime dictionary controls are checked manually on the platform.
        for option in selected_values(selected):
            if option not in option_ids:
                issues.append(f"{path} 的选项 ID 不存在：{option}")

    for path, entries in repeat_groups.items():
        if not isinstance(entries, list):
            issues.append(f"可重复组 {path} 必须是列表")
    return issues


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--intake", required=True, type=Path)
    parser.add_argument("--canonical", type=Path, default=DEFAULT_CANONICAL)
    args = parser.parse_args()
    try:
        issues = validate(load_mapping(args.canonical), load_mapping(args.intake))
    except ValueError as error:
        print(f"Intake 无法读取：{error}")
        return 2
    if issues:
        print("Intake 未通过：")
        for issue in issues:
            print(f"- {issue}")
        return 2
    print("Intake 校验通过：可生成观察性研究 V1 填写稿。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
