#!/usr/bin/env python3
"""Render a deterministic China-mainland research-protocol skeleton from the coverage matrix."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

import yaml

from validate_protocol_template_assets import DEFAULT_CANONICAL, DEFAULT_MATRIX, DEFAULT_SOURCES, load_yaml, validate


SUPPORTED_ROUTE = "investigator-observational"
SUPPORTED_PROFILE = "china-mainland"
CONDITION_FLAGS = {
    "multicenter": "multi_center",
    "biospecimen": "biospecimen",
    "public-on-chictr": "public_chictr",
    "international-collaboration": "international_collaboration",
    "consent-waiver": "consent_waiver",
    "vulnerable-participants": "vulnerable_participants",
}


def selected_module_ids(
    matrix: dict[str, Any],
    *,
    route: str,
    diagnostic_trial: str,
    conditions: set[str],
) -> list[str]:
    if route != SUPPORTED_ROUTE:
        raise ValueError("当前生成器只支持 investigator-observational；其他路线请等待对应 V2+ 规则包。")
    if diagnostic_trial not in {"yes", "no"}:
        raise ValueError("diagnostic_trial 必须为 yes 或 no")
    profile = matrix["profiles"][SUPPORTED_PROFILE]
    route_spec = profile["generator_routes"][route]
    module_ids = list(route_spec["required_modules"])
    conditional = route_spec["conditional_modules"]
    if diagnostic_trial == "yes":
        module_ids.append(conditional["diagnostic-trial"])
    for condition in sorted(conditions):
        module_key = condition
        if condition == "vulnerable-participants" and "consent-waiver" in conditions:
            continue
        if condition == "consent-waiver" and "vulnerable-participants" in conditions:
            module_key = "consent-waiver"
        module_id = conditional[module_key]
        if module_id not in module_ids:
            module_ids.append(module_id)
    return module_ids


def render(
    matrix: dict[str, Any],
    sources: dict[str, Any],
    canonical: dict[str, Any],
    *,
    route: str,
    diagnostic_trial: str,
    conditions: set[str],
) -> str:
    issues = validate(matrix, sources, canonical)
    if issues:
        raise ValueError("覆盖矩阵校验失败：" + "; ".join(issues))
    module_ids = set(selected_module_ids(matrix, route=route, diagnostic_trial=diagnostic_trial, conditions=conditions))
    modules = sorted(
        (module for module in matrix["modules"] if module["id"] in module_ids),
        key=lambda module: module["order"],
    )
    source_by_id = {item["id"]: item for item in sources["sources"]}
    selected_source_ids: list[str] = []
    for module in modules:
        for source_id in module["sources"]:
            if source_id not in selected_source_ids:
                selected_source_ids.append(source_id)

    condition_text = "、".join(sorted(conditions)) if conditions else "无额外条件模块"
    lines = [
        "# 研究计划书骨架（代码生成草案）",
        "",
        "> 本文由 `protocol-coverage-matrix.yaml` 机械生成，不能替代伦理审查、法律意见、医院模板或平台最终校验。",
        "> 仅适用于：中国大陆 → 研究者发起的临床研究 → 观察性研究。",
        "",
        "## 生成参数",
        "",
        f"- 国家／地区规则包：`{SUPPORTED_PROFILE}`",
        f"- 平台路线：`{route}`",
        f"- 诊断试验：`{diagnostic_trial}`",
        f"- 条件模块：{condition_text}",
        f"- 覆盖矩阵状态：`{matrix['status']}`",
        "",
        "## 使用规则",
        "",
        "1. 把每个“待填事实”用项目真实、已确认的信息替换；不得从模板自动推断。",
        "2. 进入医院正式伦理程序前，必须叠加本院的章节顺序、附件与流程要求。",
        "3. 研究计划书完成后，仍须运行 `research-ethics` 的两阶段确认流程，才可生成平台逐项填写稿。",
        "",
    ]
    chapter_no = 0
    for module in modules:
        lines.extend([f"## {module['order'] // 10}. {module['title']}", ""])
        for chapter in module["chapters"]:
            chapter_no += 1
            registration_paths = "、".join(f"`{path}`" for path in chapter["registration_paths"]) or "（暂无已核验平台字段映射）"
            lines.extend(
                [
                    f"### {chapter_no}. {chapter['title']} (`{chapter['id']}`)",
                    "",
                    f"- 覆盖等级：`{chapter['evidence']}`",
                    f"- 对应备案字段：{registration_paths}",
                    f"- 写作要求：{chapter['prompt']}",
                    "- 待填事实：`[由研究者／用户确认后填写]`",
                    "",
                ]
            )
    lines.extend(
        [
            "## 医院补充层（正式提交前必须处理）",
            "",
            "- 待接入：本院伦理审查申请表、研究计划书章节顺序、风险与受试者保护要求、知情同意／豁免模板、附件目录与流程时限。",
            "- 本模块不从其他医院或国家自动外推；须由目标医院提供或由用户明确确认。",
            "",
            "## 来源索引",
            "",
        ]
    )
    for source_id in selected_source_ids:
        source = source_by_id[source_id]
        lines.append(f"- `{source_id}`：[{source['title']}]({source.get('url', '#')})（{source['authority']}）")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--route", default=SUPPORTED_ROUTE)
    parser.add_argument("--diagnostic-trial", choices=("yes", "no"), required=True)
    parser.add_argument("--multi-center", action="store_true")
    parser.add_argument("--biospecimen", action="store_true")
    parser.add_argument("--public-chictr", action="store_true")
    parser.add_argument("--international-collaboration", action="store_true")
    parser.add_argument("--consent-waiver", action="store_true")
    parser.add_argument("--vulnerable-participants", action="store_true")
    parser.add_argument("--matrix", type=Path, default=DEFAULT_MATRIX)
    parser.add_argument("--sources", type=Path, default=DEFAULT_SOURCES)
    parser.add_argument("--canonical", type=Path, default=DEFAULT_CANONICAL)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    conditions = {
        condition
        for condition, arg_name in CONDITION_FLAGS.items()
        if getattr(args, arg_name)
    }
    try:
        content = render(
            load_yaml(args.matrix),
            load_yaml(args.sources),
            load_yaml(args.canonical),
            route=args.route,
            diagnostic_trial=args.diagnostic_trial,
            conditions=conditions,
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(content, encoding="utf-8", newline="\n")
    except (OSError, UnicodeError, yaml.YAMLError, ValueError) as exc:
        print(f"研究计划书骨架未生成：{exc}", file=sys.stderr)
        return 2
    print(f"研究计划书骨架已生成：{args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
