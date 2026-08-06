#!/usr/bin/env python3
"""Render the two user-facing confirmation stages before a V1 filling draft."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

import yaml

from confirmation_workflow import pending_completion_items, plan_value_candidates
from render_structural_confirmation import render as render_structural
from validate_v1_intake import framework_issues


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CANONICAL = PROJECT_ROOT / "references" / "registration-tree.yaml"


def read_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        value = yaml.safe_load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"{path} 必须是 YAML 映射")
    return value


def _option_text(options: list[Any]) -> str:
    return "、".join(str(option) for option in options) if options else "文本／平台实时字典"


def render_framework(canonical: dict[str, Any], intake: dict[str, Any]) -> str:
    metadata = intake.get("metadata", {})
    confirmation = metadata.get("proposal_confirmation", {}) if isinstance(metadata, dict) else {}
    confirmed = confirmation.get("confirmed_values", {}) if isinstance(confirmation, dict) else {}
    if not isinstance(confirmed, dict):
        confirmed = {}
    lines = [
        "# 第一阶段：总体框架与计划书已提取内容确认",
        "",
        "先确认路线与全部会改变后续表单结构的选择；再确认研究计划书中已提取出的拟填写内容。",
        "此阶段未完成时，不得进入缺口补全，也不得生成 Markdown 或 Word 填写稿。",
        "",
        "## A. 路线与结构性选择",
        "",
        render_structural(canonical, intake).strip(),
        "",
        "## B. 计划书已提取的拟填写内容",
        "",
    ]
    candidates = plan_value_candidates(canonical, intake)
    if not candidates:
        lines.append("- 当前 intake 中没有带“研究计划书／研究方案”来源的可确认值；完成结构性选择后即可进入第二阶段。")
    else:
        for number, item in enumerate(candidates, start=1):
            state = "已记录；仍须核对本轮回复" if confirmed.get(item["key"]) == item["value"] else "**待用户明确确认或修正**"
            required = "必填" if item["required"] else "非必填"
            lines.extend(
                [
                    f"### {number}. {item['page_label']}｜{item['label']}",
                    f"- 确认键：`{item['key']}`",
                    f"- 计划书拟填写值：{item['value']}",
                    f"- 来源：{item['source']}",
                    f"- 平台属性：{required}",
                    f"- 用户确认：{state}",
                    "",
                ]
            )
    lines.extend(
        [
            "## 回复与记录规则",
            "",
            "请先逐项确认或修正本阶段内容。确认结构性选择时使用 `字段路径＝选项 ID`；确认计划书值时使用 `确认键＝最终值`。",
            "收到用户明确回复后，结构性选择写入 `metadata.structural_confirmation`；计划书已提取值写入 `metadata.proposal_confirmation.confirmed_values`，并将其状态设为 `explicitly_confirmed`、方法设为 `user_explicit`。",
            "如确认某一选择后出现新的结构性问题，重新生成第一阶段确认单；所有结构性项稳定且本阶段值确认完毕后，才生成第二阶段。",
            "",
        ]
    )
    return "\n".join(lines)


def render_gaps(canonical: dict[str, Any], intake: dict[str, Any], page_number: int | None = None) -> str:
    issues = framework_issues(canonical, intake)
    if issues:
        raise ValueError("第一阶段尚未完成：" + "; ".join(issues))
    items = pending_completion_items(canonical, intake)
    if page_number is not None:
        items = [item for item in items if item["page_number"] == page_number]
    title = f"第 {page_number} 批" if page_number is not None else "全部批次"
    lines = [
        f"# 第二阶段：按平台顺序补全缺失内容（{title}）",
        "",
        "以下是已确认路线下尚未提供的字段或可重复组。请逐项给出内容、选择“不适用／不新增”、或明确标为平台实时选择／暂缓。",
        "完成每一批后更新 intake；所有批次完成并被用户明确确认后，才可生成填写稿。",
        "",
    ]
    if not items:
        lines.append("- 当前路线下没有尚未解决的缺口。可记录第二阶段完成确认并生成填写稿。")
    current_page: tuple[int, str] | None = None
    for number, item in enumerate(items, start=1):
        page_key = (item["page_number"], item["page_label"])
        if page_key != current_page:
            current_page = page_key
            lines.extend([f"## 页面 {page_key[0]}：{page_key[1]}", ""])
        required = "必填" if item["required"] else "可选"
        lines.extend(
            [
                f"### {number}. {item['label']}",
                f"- 确认键：`{item['key']}`",
                f"- 控件：{item['widget']}；{required}",
                f"- 当前可选项：{_option_text(item['options'])}",
                "- 请回复：实际内容／选项，或 `not_applicable`、`account_prefill`、`platform_realtime`、`attachment_prepared`、`user_deferred`。",
                "",
            ]
        )
    lines.extend(
        [
            "## 完成记录",
            "",
            "每项均须记录到 `metadata.completion_confirmation.resolutions`：有实际值时用 `provided`；可选项不适用用 `not_applicable`；账户自动带入用 `account_prefill`；平台实时字典用 `platform_realtime`；附件已准备用 `attachment_prepared`；仅在用户明确暂缓时用 `user_deferred`。",
            "本阶段全部处理后，将 `metadata.completion_confirmation.status` 设为 `explicitly_confirmed`、方法设为 `user_explicit`。`user_deferred` 会在最终 Word 中保留红色“待用户确认”；其余已处理状态不会被误写成普通缺失。",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--intake", type=Path, required=True)
    parser.add_argument("--canonical", type=Path, default=DEFAULT_CANONICAL)
    parser.add_argument("--stage", choices=("framework", "gaps"), required=True)
    parser.add_argument("--page", type=int, help="only render one platform page during the gap stage")
    parser.add_argument("--output", type=Path, help="optional Markdown file; stdout when omitted")
    args = parser.parse_args()
    try:
        canonical = read_yaml(args.canonical)
        intake = read_yaml(args.intake)
        result = render_framework(canonical, intake) if args.stage == "framework" else render_gaps(canonical, intake, args.page)
    except ValueError as error:
        print(f"无法生成确认单：{error}", file=sys.stderr)
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
