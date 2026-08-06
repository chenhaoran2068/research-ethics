#!/usr/bin/env python3
"""Render a platform-ordered V1 copy/paste checklist after explicit confirmation.

The input contains only route selections and already-reviewed values.  This
tool does not extract a protocol, decide a branch, or infer any study fact.
It is intentionally a renderer: validation blocks output until the user has
explicitly confirmed every currently visible structural decision.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

import yaml

from check_v1_skill_readiness import readiness
from validate_atomic_schema import AtomicSchemaValidator
from validate_dfs_ledger import DEFAULT_CANONICAL, DEFAULT_LEDGER, validate_ledger
from validate_v1_intake import validate as validate_intake


PROJECT_ROOT = Path(__file__).resolve().parents[1]
V1_ROUTES = {"investigator-observational"}
BLOCKED_OTHER = {
    "research-category.route-leaf": "investigator-interventional",
    "research-category.iit-product-attribute": "unproduct",
    "research-category.unmarketed-product-type": "其他",
}
ROUTE_DERIVED_VALUES = {
    "research-category.research-classification-level-1": "研究者发起的临床研究",
}


def read_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        value = yaml.safe_load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a mapping")
    return value


def value_details(raw: Any) -> tuple[str, str, str]:
    if isinstance(raw, dict):
        value = str(raw.get("value", "待用户确认"))
        source = str(raw.get("source", "用户确认"))
        note = str(raw.get("note", ""))
        return value, source, note
    if raw is None:
        return "待用户确认", "用户确认", ""
    return str(raw), "用户确认", ""


def options_text(item: dict[str, Any], raw_control: dict[str, Any] | None = None) -> str:
    options = item.get("options")
    if not isinstance(options, list) or not options:
        return ""
    return "；可选：" + "、".join(human_option(raw_control, option) for option in options)


def raw_control_index(canonical: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Index authored controls so option IDs can be shown with human labels."""
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
    """Return repeatable groups and the nearest repeatable parent for controls.

    Canonical paths identify templates, not an unlimited series of UI instances.
    Intake supplies the actual instance count and values for each template.
    """
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
                children = collect_controls(node.get("nodes", node.get("children")))
                groups[path] = {"label": str(node.get("label", path)), "children": children}
            if node.get("kind") == "control" and isinstance(path, str) and repeat_parent:
                parent_by_control[path] = repeat_parent
            visit(node.get("nodes") or node.get("children"), current_parent)

    workflow = canonical.get("workflow", {})
    if isinstance(workflow, dict):
        for page in workflow.get("pages", []):
            if isinstance(page, dict):
                visit(page.get("nodes", page.get("fields")))
    return groups, parent_by_control


def human_option(raw_control: dict[str, Any] | None, option_id: Any) -> str:
    if not raw_control:
        return str(option_id)
    candidates: list[Any] = []
    candidates.extend(raw_control.get("options", []) if isinstance(raw_control.get("options"), list) else [])
    groups = raw_control.get("options_by_parent", {})
    if isinstance(groups, dict):
        for values in groups.values():
            if isinstance(values, list):
                candidates.extend(values)
    for option in candidates:
        if isinstance(option, dict):
            candidate_id = option.get("id", option.get("value", option.get("label")))
            if str(candidate_id) == str(option_id):
                return str(option.get("label", candidate_id))
        elif str(option) == str(option_id):
            return str(option)
    return str(option_id)


def default_value(path: str, selections: dict[str, Any]) -> Any:
    if path in selections:
        return selections[path]
    route = selections.get("research-category.route-leaf")
    if path == "research-category.research-classification-level-2":
        return {"investigator-observational": "观察性研究"}.get(route)
    return ROUTE_DERIVED_VALUES.get(path)


def evidence_index(ledger: dict[str, Any]) -> dict[str, str]:
    """Return the strongest retained, de-identified evidence for each path."""
    grades: dict[str, str] = {}

    def record(path: Any, grade: str) -> None:
        if isinstance(path, str) and path and path not in grades:
            grades[path] = grade

    for collection in ("manual_live_observations", "live_current_page_observations"):
        for observation in ledger.get(collection, []):
            if not isinstance(observation, dict):
                continue
            level = observation.get("verification_level")
            if level not in {"sample_verified", "fully_live_verified"}:
                continue
            record(observation.get("control_path"), "sample_verified（当前页）")
            compared = observation.get("compared_options", {})
            if isinstance(compared, dict):
                for details in compared.values():
                    if isinstance(details, dict):
                        for key in ("visible_field_paths", "hidden_field_paths", "added_field_paths"):
                            for path in details.get(key, []):
                                record(path, "sample_verified（当前页）")
    for route in ledger.get("routes", []):
        if not isinstance(route, dict):
            continue
        if route.get("verification_level") not in {"sample_verified", "fully_live_verified"}:
            continue
        if route.get("evidence_grade") not in {"downstream_spot_checked", "full_leaf_replay"}:
            continue
        grade = "fully_live_verified（完整路径）" if route.get("evidence_grade") == "full_leaf_replay" else "sample_verified（代表路线后续抽查）"
        for page in route.get("display", {}).get("pages", []):
            if isinstance(page, dict) and page.get("disposition") == "visited":
                for path in page.get("field_paths", []):
                    record(path, grade)
    return grades


def control_item(validator: AtomicSchemaValidator, path: str, selections: dict[str, Any]) -> dict[str, Any] | None:
    """Evaluate a single canonical control under one global or repeat-item state."""
    control = validator.controls.get(path)
    if control is None or not control.observable:
        return None
    if not all(validator._evaluate(condition, selections) for condition in control.visibility_chain):
        return None
    item: dict[str, Any] = {
        "label": control.label,
        "widget": control.widget,
        "required": validator._evaluate(control.required, selections),
        "enabled": validator._evaluate(control.enabled_if, selections),
    }
    if control.options:
        item["options"] = [
            option.option_id for option in control.options if validator._evaluate(option.visible_if, selections)
        ]
    return item


def mapping_value(mapping: dict[str, Any], path: str, raw_control: dict[str, Any] | None) -> Any:
    """Accept canonical paths or a repeat-template child ID in an intake item."""
    if path in mapping:
        return mapping[path]
    if raw_control and isinstance(raw_control.get("id"), str):
        return mapping.get(raw_control["id"])
    return None


def effective_verification(
    raw_control: dict[str, Any] | None, selections: dict[str, Any]
) -> tuple[str | None, str]:
    """Resolve route-scoped evidence without weakening deferred routes.

    A control may retain a global ``mismatch_found`` because a V2 route is
    unresolved while a V1 route has separate evidence.  Rendering must use
    the status applicable to the intake route, rather than globally blocking
    an otherwise supported V1 field.
    """
    if not raw_control:
        return None, ""
    status = raw_control.get("verification_status")
    note = ""
    by_route = raw_control.get("verification_by_route")
    route = selections.get("research-category.route-leaf")
    if isinstance(by_route, dict) and route in by_route:
        scoped = by_route[route]
        if isinstance(scoped, dict):
            status = scoped.get("verification_status", status)
            note = str(scoped.get("verification_note", ""))
    return str(status) if status is not None else None, note


def as_text_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value]
    if value is None:
        return []
    return [str(value)]


def is_realtime_dictionary(raw_control: dict[str, Any] | None, item: dict[str, Any]) -> bool:
    """Identify selectors whose live option values must not be frozen in a draft."""
    widget = str(item.get("widget", ""))
    if "dictionary" in widget:
        return True
    if not raw_control:
        return False
    source_classes = as_text_list(raw_control.get("source_classification"))
    options_status = str(raw_control.get("options_status", ""))
    return "platform_dictionary" in source_classes or "platform_dynamic" in options_status


def pending_details(
    raw_control: dict[str, Any] | None,
    item: dict[str, Any],
    verification_status: str | None,
) -> tuple[str, str]:
    """Explain why a red pending value remains pending.

    The distinction is actionable: a user can confirm a real-world fact,
    select a live dictionary value, or supply text that the extractor has not
    mapped yet.  It avoids treating all missing content as the same problem.
    """
    if verification_status in {"mismatch_found", "out_of_scope_or_blocked"}:
        return "平台规则待核验", "当前规则不足以安全生成；请先以平台当前页面为准。"
    if is_realtime_dictionary(raw_control, item):
        return "平台实时字典待选择", "请以平台当日下拉库检索结果为准；本稿不固化长字典具体值。"
    value_source = str(raw_control.get("value_source", "")) if raw_control else ""
    if "研究计划书" in value_source:
        return "计划书可提取但映射待补全", "方案可能已有对应信息；请核对后补充，或完善 intake 映射。"
    return "真实事实待确认", "该信息取决于账户、伦理决定、经费、机构或附件准备情况，不能由方案安全推断。"


def attachment_instructions(raw_control: dict[str, Any] | None) -> list[str]:
    if not raw_control:
        return []
    return as_text_list(raw_control.get("instruction"))


def join_instructions(instructions: list[str]) -> str:
    cleaned = [instruction.strip().rstrip("。；") for instruction in instructions if instruction.strip()]
    return ("；".join(cleaned) + "。") if cleaned else "以平台当前说明为准。"


def field_lines(
    title: str,
    path: str,
    item: dict[str, Any],
    raw_control: dict[str, Any] | None,
    raw_values: dict[str, Any],
    selection_values: dict[str, Any],
    evidence: dict[str, str],
    *,
    heading: str = "###",
) -> list[str]:
    if item["widget"] == "hidden" or (raw_control and raw_control.get("user_copyable") is False):
        return []
    verification_status, verification_note = effective_verification(raw_control, selection_values)
    if raw_control and verification_status in {"mismatch_found", "out_of_scope_or_blocked"}:
        return [
            f"{heading} {title}｜暂不自动生成",
            "- 状态：当前平台规则与现场抽样不一致，或该字段超出 V1 可验证范围。",
            "- 操作：请先在平台当前页面人工核对；本填写稿不会猜测或提供可直接复制的内容。",
            f"- 规则证据：{verification_status}。",
            "",
        ]
    raw_value = mapping_value(raw_values, path, raw_control)
    if raw_value is None and path in selection_values:
        value, source, note = human_option(raw_control, selection_values[path]), "已确认的选择", ""
    elif raw_value is None and default_value(path, selection_values) is not None:
        selected = default_value(path, selection_values)
        value, source, note = human_option(raw_control, selected), "已确认的路线选择", ""
    else:
        value, source, note = value_details(raw_value)
        if raw_value is None:
            source, pending_note = pending_details(raw_control, item, verification_status)
            note = (note + "；" if note else "") + pending_note
    if path == "research-category.implementing-organization":
        value, source = "核对账户自动带入", "账户预填"
    choice_widget = any(token in item["widget"] for token in ("select", "radio", "checkbox"))
    operation = "自行上传" if "upload" in item["widget"] else ("选择对应选项" if choice_widget else "复制粘贴")
    required = "必填" if item["required"] else "非必填"
    lines = [
        f"{heading} {title}｜{item['widget']}",
        f"- 建议填写／选择：{value}{options_text(item, raw_control)}",
        f"- 来源：{source}",
        f"- 操作：{operation}（{required}）",
    ]
    if note:
        lines.append(f"- 提示：{note}")
    if verification_note:
        lines.append(f"- 平台规则说明：{verification_note}")
    if is_realtime_dictionary(raw_control, item):
        lines.append("- 实时字典：请在平台当前下拉库检索并选择；本稿只保留研究计划书中的检索依据，不固化具体字典叶值。")
    if "upload" in item["widget"]:
        for instruction in attachment_instructions(raw_control):
            lines.append(f"- 附件说明：{instruction}")
    lines.extend([f"- 规则证据：{evidence.get(path, 'inferred_from_initial_tree（需现场核对）')}", ""])
    return lines


def repeat_group_lines(
    title: str,
    page_number: int,
    field_number: int,
    group_path: str,
    group: dict[str, Any],
    validator: AtomicSchemaValidator,
    raw_controls: dict[str, dict[str, Any]],
    global_selections: dict[str, Any],
    intake_repeat_groups: dict[str, Any],
    evidence: dict[str, str],
) -> list[str]:
    entries = intake_repeat_groups.get(group_path)
    if not isinstance(entries, list) or not entries:
        entries = [{}]
        count_note = "未提供实例清单；先展示第 1 项模板，填写时请按实际数量点击“增加一项”。"
    else:
        count_note = f"已按 intake 列出 {len(entries)} 项；填写时按同样数量点击“增加一项”。"
    lines = [
        f"### {page_number}.{field_number}｜{title}｜可重复填写组",
        f"- 平台操作：{count_note}",
        "",
    ]
    for position, entry in enumerate(entries, start=1):
        entry = entry if isinstance(entry, dict) else {}
        entry_selections = entry.get("selections", {})
        entry_values = entry.get("values", {})
        if not isinstance(entry_selections, dict):
            entry_selections = {}
        if not isinstance(entry_values, dict):
            entry_values = {}
        local_selections = dict(global_selections)
        for child in group["children"]:
            child_path = child.get("path")
            if not isinstance(child_path, str):
                continue
            chosen = mapping_value(entry_selections, child_path, child)
            if chosen is not None:
                local_selections[child_path] = chosen
        lines.extend([f"#### 第 {position} 项", ""])
        for child in group["children"]:
            child_path = child.get("path")
            if not isinstance(child_path, str):
                continue
            item = control_item(validator, child_path, local_selections)
            if item is None:
                continue
            lines.extend(
                field_lines(
                    child.get("label", child_path),
                    child_path,
                    item,
                    raw_controls.get(child_path),
                    entry_values,
                    local_selections,
                    evidence,
                    heading="#####",
                )
            )
    return lines


def render(canonical: dict[str, Any], intake: dict[str, Any], ledger: dict[str, Any]) -> str:
    intake_issues = validate_intake(canonical, intake)
    if intake_issues:
        raise ValueError("填写稿生成被结构性确认门槛拦截：" + "; ".join(intake_issues))
    selections = intake.get("selections", {})
    values = intake.get("values", {})
    repeat_groups = intake.get("repeat_groups", {})
    meta = intake.get("metadata", {})
    if not isinstance(selections, dict) or not isinstance(values, dict) or not isinstance(repeat_groups, dict):
        raise ValueError("intake selections, values and repeat_groups must all be mappings")
    if not isinstance(meta, dict):
        raise ValueError("intake.meta 必须是映射（如提供）")
    route = selections.get("research-category.route-leaf")
    if route not in V1_ROUTES:
        raise ValueError("observational V1 supports only investigator-observational; interventional is deferred_to_v2")
    if all(selections.get(path) == choice for path, choice in BLOCKED_OTHER.items()):
        raise ValueError("blocked V1 subroute: interventional > unproduct > 产品类型：其他")
    if route == "investigator-observational" and selections.get("research-category.diagnostic-trial") not in {"yes", "no"}:
        raise ValueError("observational intake requires research-category.diagnostic-trial = yes or no")
    if selections.get("basic-information.sync-platform") == "traditional-disabled":
        raise ValueError("传统医学注册平台当前暂未开通，不能作为 V1 生成路线")

    validator = AtomicSchemaValidator(canonical)
    errors = validator.validate()
    if errors:
        raise ValueError("canonical schema is invalid: " + "; ".join(errors[:3]))
    pages = validator._expected_pages(selections)
    raw_controls = raw_control_index(canonical)
    group_specs, group_by_control = repeatable_group_index(canonical)
    evidence = evidence_index(ledger)
    title, title_source, _ = value_details(values.get("basic-information.research-title"))
    lines = [
        "# 医学研究登记逐项填写稿（V1）",
        "",
        f"- 路线：`{route}`" + (f"；诊断试验：`{selections.get('research-category.diagnostic-trial')}`" if route == "investigator-observational" else ""),
        "- 证据状态：本稿基于 V1 抽样核验规则；标为“待用户确认”的内容不得直接提交。",
        "- 安全边界：本稿不执行平台操作，不代表伦理、法律或监管结论。",
        f"- 研究题目：{title}（来源：{title_source}）",
        "",
    ]
    if meta.get("assumption_draft") is True:
        rationale = str(meta.get("assumption_rationale", "用户授权下的工作草稿"))
        lines[2:2] = [
            "- **状态：假设版工作草稿，禁止直接保存或提交。**",
            f"- 假设依据：{rationale}。账户资料、伦理决定、资金、实时字典和附件状态均须在平台提交前逐项核对。",
            "",
        ]
    attachment_rows: list[tuple[str, dict[str, Any], dict[str, Any] | None]] = []
    for page_number, (page, items) in enumerate(pages, start=1):
        lines.extend([f"## 页面 {page_number}：{page.label}", ""])
        visible_paths = {path for path, _ in items}
        emitted_groups: set[str] = set()
        displayed_field_number = 0
        for path, item in items:
            group_path = group_by_control.get(path)
            if group_path:
                if group_path in emitted_groups:
                    continue
                group = group_specs[group_path]
                if not any(child.get("path") in visible_paths for child in group["children"]):
                    continue
                emitted_groups.add(group_path)
                displayed_field_number += 1
                lines.extend(
                    repeat_group_lines(
                        group["label"],
                        page_number,
                        displayed_field_number,
                        group_path,
                        group,
                        validator,
                        raw_controls,
                        selections,
                        repeat_groups,
                        evidence,
                    )
                )
                continue
            raw_control = raw_controls.get(path)
            if item["widget"] == "hidden" or (raw_control and raw_control.get("user_copyable") is False):
                continue
            if "upload" in item["widget"]:
                attachment_rows.append((path, item, raw_control))
            displayed_field_number += 1
            lines.extend(
                field_lines(
                    f"{page_number}.{displayed_field_number}｜{item['label']}",
                    path,
                    item,
                    raw_control,
                    values,
                    selections,
                    evidence,
                )
            )
    lines.extend(["## 附件准备清单（不上传）", ""])
    if attachment_rows:
        for path, item, raw_control in attachment_rows:
            required = "必填" if item["required"] else "非必填"
            instructions = join_instructions(attachment_instructions(raw_control))
            lines.append(
                f"- {item['label']}（{required}，`{path}`）：准备状态：待用户确认；{instructions}"
            )
    else:
        lines.append("- 当前路线未显示可上传附件；请仍以平台当前页面为准。")
    lines.extend(
        [
            "- 本清单只说明准备要求；生成器不会上传、保存或提交任何文件。",
            "",
            "## 实时字典使用说明",
            "",
            "- 国家／地区、机构、学科、ICD-11、适应症、资助专项等属于平台实时字典；普通具体值不构成固定规则。",
            "- 先依据计划书中的名称、疾病、机构或项目线索检索，再以平台当日可见选项完成选择。",
            "- 若选择“其他”导致说明文本框出现，按页面提示补充；若当前平台结构与本稿不同，以平台当前结构优先。",
            "",
        ]
    )
    lines.extend(
        [
            "## 提交前人工核对",
            "",
            "- □ 核对账户自动带入的实施单位、研究负责人及联系信息。",
            "- □ 确认公开策略、数据共享、国际合作、材料捐赠、知情同意及伦理文件与研究计划书一致。",
            "- □ 按实际数量新增重复项，并逐项核对必填内容。",
            "- □ 仅由用户在平台自行上传当前要求的附件；本填写稿不表示任何附件已经上传。",
            "- □ 如平台字段与本稿不同，以平台当前可见字段为准，并记录差异后再更新规则。",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--intake", type=Path, required=True, help="de-identified YAML intake")
    parser.add_argument("--output", type=Path, required=True, help="Markdown output path")
    parser.add_argument("--canonical", type=Path, default=DEFAULT_CANONICAL)
    parser.add_argument("--ledger", type=Path, default=DEFAULT_LEDGER)
    args = parser.parse_args()
    validated = validate_ledger(args.canonical, args.ledger)
    issues, _ = readiness(validated)
    if issues:
        raise SystemExit("V1 readiness is not met: " + "; ".join(issues))
    canonical = read_yaml(args.canonical)
    intake = read_yaml(args.intake)
    intake_issues = validate_intake(canonical, intake)
    if intake_issues:
        print("Cannot render V1 checklist: " + "; ".join(intake_issues), file=sys.stderr)
        return 2
    try:
        output = render(canonical, intake, validated["ledger"])
    except ValueError as error:
        print(f"Cannot render V1 checklist: {error}", file=sys.stderr)
        return 2
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(output, encoding="utf-8")
    print(f"Rendered {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
