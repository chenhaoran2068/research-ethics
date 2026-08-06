#!/usr/bin/env python3
"""Validate a V1 intake before rendering a filling draft."""

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
OPERATING_MODES = {"actual_submission", "test_public"}
CONFIRMATION_STATUS = "explicitly_confirmed"
CONFIRMATION_METHOD = "user_explicit"
CORE_STRUCTURAL_PATHS = {
    "research-category.route-leaf",
    "research-category.diagnostic-trial",
    "basic-information.sync-platform",
}


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


def _condition_control_paths(value: Any) -> set[str]:
    """Return canonical control paths referenced by a condition expression."""
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
    """Find selection controls that can change page or field structure.

    The canonical workflow remains the sole rules source: a structural driver is
    any control referenced by a display, requiredness, enablement, or option
    visibility condition in the authored workflow, plus the three V1 route
    selectors that establish the starting route.
    """
    workflow = canonical.get("workflow", {})
    if not isinstance(workflow, dict):
        return set(CORE_STRUCTURAL_PATHS)
    return CORE_STRUCTURAL_PATHS | _condition_control_paths(workflow.get("pages", []))


def active_structural_paths(
    validator: AtomicSchemaValidator, canonical: dict[str, Any], selections: dict[str, Any]
) -> list[str]:
    """List structural decisions visible for the proposed route.

    A selection can reveal further structural decisions.  Callers therefore
    regenerate the confirmation sheet after changing a proposed selection until
    no newly visible decision remains unconfirmed.
    """
    active: set[str] = set()
    for path in structural_driver_paths(canonical):
        control = validator.controls.get(path)
        if control is None:
            continue
        if path not in CORE_STRUCTURAL_PATHS and (not control.options or not control.observable):
            continue
        if path in CORE_STRUCTURAL_PATHS or all(validator._evaluate(condition, selections) for condition in control.visibility_chain):
            active.add(path)
    return sorted(active)


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

    if selections.get("research-category.route-leaf") != SUPPORTED_ROUTE:
        issues.append("V1 仅支持 investigator-observational；其他路线为 deferred_to_v2")
    if selections.get("research-category.diagnostic-trial") not in {"yes", "no"}:
        issues.append("必须选择 research-category.diagnostic-trial = yes 或 no")
    if selections.get("basic-information.sync-platform") not in {"private", "public-on-chictr"}:
        issues.append("必须选择公开策略 private 或 public-on-chictr")
    if selections.get("basic-information.sync-platform") == DISABLED_PLATFORM:
        issues.append("传统医学注册平台暂未开通，不能生成 V1 填写稿")

    if (
        isinstance(metadata, dict)
        and selections.get("research-category.route-leaf") == SUPPORTED_ROUTE
        and selections.get("research-category.diagnostic-trial") in {"yes", "no"}
        and selections.get("basic-information.sync-platform") in {"private", "public-on-chictr"}
    ):
        issues.extend(_confirmation_issues(validator, canonical, metadata, selections))

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
