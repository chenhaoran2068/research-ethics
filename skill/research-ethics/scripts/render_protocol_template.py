#!/usr/bin/env python3
"""Render deterministic Chinese, English, or bilingual protocol skeletons.

The coverage matrix remains the only source of chapter order, conditions, and
registration mappings.  The language-pair catalog supplies controlled English
counterparts for the same module and chapter IDs; it never supplies study facts.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

import yaml

from validate_protocol_template_assets import (
    DEFAULT_CANONICAL,
    DEFAULT_LANGUAGE_PAIRS,
    DEFAULT_MATRIX,
    DEFAULT_SOURCES,
    load_yaml,
    validate,
)


SUPPORTED_ROUTE = "investigator-observational"
SUPPORTED_PROFILE = "china-mainland"
SUPPORTED_LANGUAGES = {"zh", "en", "bilingual"}
CONDITION_FLAGS = {
    "multicenter": "multi_center",
    "biospecimen": "biospecimen",
    "public-on-chictr": "public_chictr",
    "international-collaboration": "international_collaboration",
    "consent-waiver": "consent_waiver",
    "vulnerable-participants": "vulnerable_participants",
}
CONDITION_LABELS = {
    "zh": {
        "multicenter": "多中心",
        "biospecimen": "生物样本",
        "public-on-chictr": "ChiCTR 公开",
        "international-collaboration": "国际合作",
        "consent-waiver": "知情同意豁免",
        "vulnerable-participants": "弱势群体",
    },
    "en": {
        "multicenter": "multicentre study",
        "biospecimen": "biospecimen collection",
        "public-on-chictr": "ChiCTR public registration",
        "international-collaboration": "international collaboration",
        "consent-waiver": "consent waiver",
        "vulnerable-participants": "vulnerable participants",
    },
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


def _condition_text(conditions: set[str], language: str) -> str:
    if not conditions:
        return "无额外条件模块" if language == "zh" else "no additional condition modules"
    labels = CONDITION_LABELS[language]
    return "、".join(labels[condition] for condition in sorted(conditions)) if language == "zh" else ", ".join(
        labels[condition] for condition in sorted(conditions)
    )


def _header(language: str, matrix: dict[str, Any], route: str, diagnostic_trial: str, conditions: set[str]) -> list[str]:
    chinese_conditions = _condition_text(conditions, "zh")
    english_conditions = _condition_text(conditions, "en")
    if language == "zh":
        return [
            "# 中国通用研究计划书骨架（代码生成草案）",
            "",
            "> 本文由 `protocol-coverage-matrix.yaml` 机械生成，不能替代伦理审查、法律意见、使用机构的最终格式要求或平台最终校验。",
            "> 仅适用于：中国大陆 → 研究者发起的临床研究 → 观察性研究。",
            "",
            "## 生成参数",
            "",
            f"- 国家／地区规则包：`{SUPPORTED_PROFILE}`",
            f"- 平台路线：`{route}`",
            f"- 诊断试验：`{diagnostic_trial}`",
            f"- 条件模块：{chinese_conditions}",
            f"- 覆盖矩阵状态：`{matrix['status']}`",
            "",
            "## 使用规则",
            "",
            "1. 把每个“待填事实”用项目真实、已确认的信息替换；不得从模板自动推断。",
            "2. 本文是中国通用骨架；正式提交前由使用者自行按本院章节顺序、附件与流程要求调整。",
            "3. 需要英文时，英文应与同一事实组的中文内容配对，并由用户确认研究事实和专业术语。",
            "4. 研究计划书完成后，仍须运行 `research-ethics` 的两阶段确认流程，才可生成平台逐项填写稿。",
            "",
        ]
    if language == "en":
        return [
            "# China-General Research Protocol Skeleton (Code-Generated Draft)",
            "",
            "> This document is deterministically generated from `protocol-coverage-matrix.yaml`. It does not replace ethics review, legal advice, an institution's final formatting requirements, or final platform validation.",
            "> Applicable only to: China mainland → investigator-initiated clinical research → observational studies.",
            "",
            "## Generation Parameters",
            "",
            f"- Country/region rule pack: `{SUPPORTED_PROFILE}`",
            f"- Platform route: `{route}`",
            f"- Diagnostic study: `{diagnostic_trial}`",
            f"- Condition modules: {english_conditions}",
            f"- Coverage-matrix status: `{matrix['status']}`",
            "",
            "## Use Rules",
            "",
            "1. Replace each fact placeholder with real, confirmed project information; do not infer project facts from this template.",
            "2. This is a China-general skeleton. Before formal submission, the user must adapt it to the submitting institution's sequence, attachments, and process requirements.",
            "3. English content must be paired with the Chinese content from the same fact group and reviewed by the user for research facts and specialist terminology.",
            "4. After the protocol is complete, run the two-stage `research-ethics` confirmation workflow before generating a copyable platform-filling draft.",
            "",
        ]
    return [
        "# 中国通用研究计划书骨架 | China-General Research Protocol Skeleton",
        "",
        "> 本文由 `protocol-coverage-matrix.yaml` 与受控中英文配对目录机械生成；不替代伦理审查、法律意见、使用机构的最终格式要求或平台最终校验。",
        "> This document is deterministically generated from the coverage matrix and controlled language-pair catalog; it does not replace ethics review, legal advice, an institution's final formatting requirements, or final platform validation.",
        "",
        "## 生成参数 | Generation Parameters",
        "",
        f"- 国家／地区规则包 | Country/region rule pack: `{SUPPORTED_PROFILE}`",
        f"- 平台路线 | Platform route: `{route}`",
        f"- 诊断试验 | Diagnostic study: `{diagnostic_trial}`",
        f"- 条件模块 | Condition modules: {chinese_conditions} | {english_conditions}",
        f"- 覆盖矩阵状态 | Coverage-matrix status: `{matrix['status']}`",
        "",
        "## 使用规则 | Use Rules",
        "",
        "1. 每个待填事实必须以真实、已确认的信息替换；不得从模板自动推断。| Replace each fact placeholder with real, confirmed project information; do not infer project facts from this template.",
        "2. 本文是中国通用骨架；正式提交前由使用者自行按本院章节顺序、附件与流程要求调整。| This is a China-general skeleton; before formal submission, adapt it to the submitting institution's sequence, attachments, and process requirements.",
        "3. 中英文必须来自同一事实组；英文研究事实和专业术语须经用户核对。| Chinese and English content must come from the same fact group; the user must verify English research facts and specialist terminology.",
        "4. 计划书完成后，仍须完成 `research-ethics` 两阶段确认，才可生成平台逐项填写稿。| Complete the two-stage `research-ethics` confirmation workflow before generating a copyable platform-filling draft.",
        "",
    ]


def _module_heading(module: dict[str, Any], language_pairs: dict[str, Any], language: str) -> str:
    title_en = language_pairs["module_pairs"][module["id"]]["title_en"]
    if language == "zh":
        return module["title"]
    if language == "en":
        return title_en
    return f"{module['title']} | {title_en}"


def _chapter_lines(chapter: dict[str, Any], language_pairs: dict[str, Any], number: int, language: str) -> list[str]:
    pair = language_pairs["chapter_pairs"][chapter["id"]]
    registration_paths = "、".join(f"`{path}`" for path in chapter["registration_paths"]) or "（暂无已核验平台字段映射）"
    if language == "zh":
        return [
            f"### {number}. {chapter['title']} (`{chapter['id']}`)",
            "",
            f"- 覆盖等级：`{chapter['evidence']}`",
            f"- 对应备案字段：{registration_paths}",
            f"- 写作要求：{chapter['prompt']}",
            f"- 同源事实组：`{chapter['id']}`",
            "- 中文待填事实：`[由研究者／用户确认后填写]`",
            "",
        ]
    if language == "en":
        return [
            f"### {number}. {pair['title_en']} (`{chapter['id']}`)",
            "",
            f"- Coverage level: `{chapter['evidence']}`",
            f"- Mapped registration fields: {registration_paths}",
            f"- Writing prompt: {pair['prompt_en']}",
            f"- Shared fact group: `{chapter['id']}`",
            "- English paired fact: `[To be completed after researcher/user confirmation]`",
            "",
        ]
    return [
        f"### {number}. {chapter['title']} | {pair['title_en']} (`{chapter['id']}`)",
        "",
        f"- 覆盖等级 | Coverage level: `{chapter['evidence']}`",
        f"- 对应备案字段 | Mapped registration fields: {registration_paths}",
        f"- 中文写作要求: {chapter['prompt']}",
        f"- English writing prompt: {pair['prompt_en']}",
        f"- 同源事实组 | Shared fact group: `{chapter['id']}`",
        "- 中文待填事实: `[由研究者／用户确认后填写]`",
        "- English paired fact: `[To be completed after researcher/user confirmation]`",
        "",
    ]


def _footer(language: str) -> list[str]:
    if language == "zh":
        return [
            "## 医院补充层（可选的私有适配）",
            "",
            "- 如使用者希望适配具体医院，可在私有工作区叠加：伦理申请表、章节顺序、风险与受试者保护要求、知情同意／豁免模板、附件目录与流程时限。",
            "- 中国通用骨架不以该层为前置条件；本模块不从其他医院或国家自动外推。",
            "",
            "## 来源索引",
            "",
        ]
    if language == "en":
        return [
            "## Institution-Specific Overlay (Optional Private Adaptation)",
            "",
            "- If the user wishes to adapt the output for a specific institution, a private workspace can add its ethics-application form, section sequence, participant-protection requirements, consent/waiver templates, attachment list, and timelines.",
            "- The China-general skeleton does not require this overlay and does not infer it from another institution or country.",
            "",
            "## Source Index",
            "",
        ]
    return [
        "## 医院补充层（可选的私有适配） | Institution-Specific Overlay (Optional Private Adaptation)",
        "",
        "- 如使用者希望适配具体医院，可在私有工作区叠加伦理申请表、章节顺序、参与者保护要求、知情同意／豁免模板、附件目录和流程时限。| A private workspace can add institution-specific forms, section sequence, participant-protection requirements, consent/waiver templates, attachments, and timelines if the user wishes to adapt the output.",
        "- 中国通用骨架不以该层为前置条件，也不从其他医院或国家自动外推。| The China-general skeleton does not require this overlay and does not infer it from another institution or country.",
        "",
        "## 来源索引 | Source Index",
        "",
    ]


def render(
    matrix: dict[str, Any],
    sources: dict[str, Any],
    canonical: dict[str, Any],
    *,
    route: str,
    diagnostic_trial: str,
    conditions: set[str],
    language: str = "zh",
    language_pairs: dict[str, Any] | None = None,
) -> str:
    if language not in SUPPORTED_LANGUAGES:
        raise ValueError(f"language 必须为 {'、'.join(sorted(SUPPORTED_LANGUAGES))}")
    language_pairs = language_pairs or load_yaml(DEFAULT_LANGUAGE_PAIRS)
    issues = validate(matrix, sources, canonical, language_pairs)
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

    lines = _header(language, matrix, route, diagnostic_trial, conditions)
    chapter_no = 0
    for module in modules:
        lines.extend([f"## {module['order'] // 10}. {_module_heading(module, language_pairs, language)}", ""])
        for chapter in module["chapters"]:
            chapter_no += 1
            lines.extend(_chapter_lines(chapter, language_pairs, chapter_no, language))
    lines.extend(_footer(language))
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
    parser.add_argument("--language", choices=tuple(sorted(SUPPORTED_LANGUAGES)), default="zh")
    parser.add_argument("--multi-center", action="store_true")
    parser.add_argument("--biospecimen", action="store_true")
    parser.add_argument("--public-chictr", action="store_true")
    parser.add_argument("--international-collaboration", action="store_true")
    parser.add_argument("--consent-waiver", action="store_true")
    parser.add_argument("--vulnerable-participants", action="store_true")
    parser.add_argument("--matrix", type=Path, default=DEFAULT_MATRIX)
    parser.add_argument("--sources", type=Path, default=DEFAULT_SOURCES)
    parser.add_argument("--canonical", type=Path, default=DEFAULT_CANONICAL)
    parser.add_argument("--language-pairs", type=Path, default=DEFAULT_LANGUAGE_PAIRS)
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
            language=args.language,
            language_pairs=load_yaml(args.language_pairs),
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
