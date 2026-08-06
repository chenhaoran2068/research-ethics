#!/usr/bin/env python3
"""Validate a V1 intake before rendering a filling draft."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

import yaml

from confirmation_workflow import (
    CORE_STRUCTURAL_PATHS,
    active_structural_paths,
    pending_completion_items,
    plan_value_candidates,
    selected_values,
    structural_driver_paths,
)
from validate_atomic_schema import AtomicSchemaValidator


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CANONICAL = PROJECT_ROOT / "references" / "registration-tree.yaml"
SUPPORTED_ROUTE = "investigator-observational"
DISABLED_PLATFORM = "traditional-disabled"
OPERATING_MODES = {"actual_submission", "test_public"}
CONFIRMATION_STATUS = "explicitly_confirmed"
CONFIRMATION_METHOD = "user_explicit"
RESOLUTION_STATES = {
    "provided",
    "not_applicable",
    "account_prefill",
    "platform_realtime",
    "attachment_prepared",
    "user_deferred",
}


def load_mapping(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        value = yaml.safe_load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a mapping")
    return value


def _confirmation_issues(
    validator: AtomicSchemaValidator, canonical: dict[str, Any], metadata: dict[str, Any], selections: dict[str, Any]
) -> list[str]:
    confirmation = metadata.get("structural_confirmation")
    if not isinstance(confirmation, dict):
        return ["必须先完成 metadata.structural_confirmation；请先生成并获得用户明确确认的结构性确认单"]

    issues: list[str] = []
    if confirmation.get("status") != CONFIRMATION_STATUS:
        issues.append(f"metadata.structural_confirmation.status 必须是 {CONFIRMATION_STATUS}")
    if confirmation.get("method") != CONFIRMATION_METHOD:
        issues.append(f"metadata.structural_confirmation.method 必须是 {CONFIRMATION_METHOD}")
    confirmed = confirmation.get("confirmed_selections")
    if not isinstance(confirmed, dict):
        return issues + ["metadata.structural_confirmation.confirmed_selections 必须是映射"]

    for path in active_structural_paths(validator, canonical, selections):
        if path not in selections:
            issues.append(f"结构性选择尚未给出：{path}；必须先向用户询问并确认")
            continue
        if confirmed.get(path) != selections[path]:
            issues.append(f"结构性选择尚未获得用户明确确认或确认值不一致：{path}")
    return issues


def _proposal_confirmation_issues(canonical: dict[str, Any], metadata: dict[str, Any], intake: dict[str, Any]) -> list[str]:
    confirmation = metadata.get("proposal_confirmation")
    if not isinstance(confirmation, dict):
        return ["必须先完成 metadata.proposal_confirmation；请先确认研究计划书已提取的拟填写内容"]
    issues: list[str] = []
    if confirmation.get("status") != CONFIRMATION_STATUS:
        issues.append(f"metadata.proposal_confirmation.status 必须是 {CONFIRMATION_STATUS}")
    if confirmation.get("method") != CONFIRMATION_METHOD:
        issues.append(f"metadata.proposal_confirmation.method 必须是 {CONFIRMATION_METHOD}")
    confirmed = confirmation.get("confirmed_values")
    if not isinstance(confirmed, dict):
        return issues + ["metadata.proposal_confirmation.confirmed_values 必须是映射"]
    for candidate in plan_value_candidates(canonical, intake):
        if confirmed.get(candidate["key"]) != candidate["value"]:
            issues.append(f"计划书已提取值尚未获得用户明确确认或确认值不一致：{candidate['key']}")
    return issues


def _resolution_state(value: Any) -> str | None:
    if isinstance(value, dict):
        value = value.get("state")
    return str(value) if value is not None else None


def _completion_confirmation_issues(canonical: dict[str, Any], metadata: dict[str, Any], intake: dict[str, Any]) -> list[str]:
    confirmation = metadata.get("completion_confirmation")
    if not isinstance(confirmation, dict):
        return ["必须先完成 metadata.completion_confirmation；请先按页面顺序补全所有缺失必填和可选内容"]
    issues: list[str] = []
    if confirmation.get("status") != CONFIRMATION_STATUS:
        issues.append(f"metadata.completion_confirmation.status 必须是 {CONFIRMATION_STATUS}")
    if confirmation.get("method") != CONFIRMATION_METHOD:
        issues.append(f"metadata.completion_confirmation.method 必须是 {CONFIRMATION_METHOD}")
    resolutions = confirmation.get("resolutions")
    if not isinstance(resolutions, dict):
        return issues + ["metadata.completion_confirmation.resolutions 必须是映射"]
    for item in pending_completion_items(canonical, intake):
        state = _resolution_state(resolutions.get(item["key"]))
        if state not in RESOLUTION_STATES:
            issues.append(f"缺失项尚未由用户明确处理：{item['key']}")
            continue
        if state == "provided":
            issues.append(f"已标记 provided 但 intake 仍没有实际值或选项：{item['key']}")
        if item["required"] and state == "not_applicable":
            issues.append(f"必填项不能标记为 not_applicable：{item['key']}")
    return issues


def framework_issues(canonical: dict[str, Any], intake: dict[str, Any]) -> list[str]:
    """Return only first-stage issues, for the ordered gap-sheet renderer."""
    validator = AtomicSchemaValidator(canonical)
    errors = validator.validate()
    if errors:
        return ["canonical YAML 无法通过校验：" + "; ".join(errors[:3])]
    selections = intake.get("selections")
    metadata = intake.get("metadata", {})
    if not isinstance(selections, dict) or not isinstance(metadata, dict):
        return ["intake.selections 和 intake.metadata 必须是映射"]
    issues: list[str] = []
    if selections.get("research-category.route-leaf") != SUPPORTED_ROUTE:
        issues.append("V1 仅支持 investigator-observational；其他路线为 deferred_to_v2")
    if selections.get("research-category.diagnostic-trial") not in {"yes", "no"}:
        issues.append("必须选择 research-category.diagnostic-trial = yes 或 no")
    if selections.get("basic-information.sync-platform") not in {"private", "public-on-chictr"}:
        issues.append("必须选择公开策略 private 或 public-on-chictr")
    if not issues:
        issues.extend(_confirmation_issues(validator, canonical, metadata, selections))
        issues.extend(_proposal_confirmation_issues(canonical, metadata, intake))
    return issues


def validate(canonical: dict[str, Any], intake: dict[str, Any]) -> list[str]:
    validator = AtomicSchemaValidator(canonical)
    errors = validator.validate()
    if errors:
        return ["canonical YAML 无法通过校验：" + "; ".join(errors[:3])]

    selections = intake.get("selections")
    metadata = intake.get("metadata", {})
    values = intake.get("values", {})
    repeat_groups = intake.get("repeat_groups", {})
    issues: list[str] = []
    if not isinstance(selections, dict):
        return ["intake.selections 必须是映射"]
    if not isinstance(metadata, dict):
        issues.append("intake.metadata 必须是映射")
    else:
        if metadata.get("operating_mode") not in OPERATING_MODES:
            issues.append("metadata.operating_mode 必须明确为 actual_submission 或 test_public")
    if not isinstance(values, dict):
        issues.append("intake.values 必须是映射")
    if not isinstance(repeat_groups, dict):
        issues.append("intake.repeat_groups 必须是映射")

    framework: list[str] = []
    if isinstance(metadata, dict):
        framework = framework_issues(canonical, intake)
        issues.extend(framework)
        if not framework:
            issues.extend(_completion_confirmation_issues(canonical, metadata, intake))

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
