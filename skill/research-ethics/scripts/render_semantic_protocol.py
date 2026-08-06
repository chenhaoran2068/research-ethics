#!/usr/bin/env python3
"""Render a fact-model-driven Chinese, English, or bilingual protocol draft.

The renderer deliberately separates study facts from composition rules.  A
single private fact model supplies paired Chinese and English statement IDs;
the composition rules decide whether each chapter is narrative, a list,
procedural steps, a checklist, or several independent semantic subsections.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

import yaml

from render_protocol_template import (
    CONDITION_LABELS,
    SUPPORTED_LANGUAGES,
    SUPPORTED_ROUTE,
    _module_heading,
    selected_module_ids,
)
from validate_protocol_template_assets import (
    DEFAULT_CANONICAL,
    DEFAULT_LANGUAGE_PAIRS,
    DEFAULT_MATRIX,
    DEFAULT_SOURCES,
    load_yaml,
    validate,
)


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_COMPOSITION = ROOT / "references" / "protocol-semantic-composition.yaml"
VALID_FORMS = {
    "narrative",
    "definition_list",
    "criteria_list",
    "procedure_steps",
    "checklist",
    "sectioned_narrative",
}


def _chapter_ids(matrix: dict[str, Any]) -> set[str]:
    return {chapter["id"] for module in matrix["modules"] for chapter in module["chapters"]}


def validate_composition(composition: dict[str, Any], matrix: dict[str, Any]) -> list[str]:
    """Return schema-level errors without inspecting any private fact values."""
    issues: list[str] = []
    contract = composition.get("paragraph_contract")
    if not isinstance(contract, dict):
        return ["semantic composition must define paragraph_contract"]
    for form in VALID_FORMS:
        if form not in contract:
            issues.append(f"paragraph_contract missing form: {form}")
    policy = composition.get("table_policy")
    if not isinstance(policy, dict) or not policy.get("use_when") or not policy.get("otherwise"):
        issues.append("semantic composition must define table_policy.use_when and table_policy.otherwise")
    forms = composition.get("chapter_forms")
    if not isinstance(forms, dict) or forms.get("default") not in VALID_FORMS:
        issues.append("chapter_forms.default must be a supported form")
        return issues
    known = _chapter_ids(matrix)
    for chapter_id, override in forms.get("overrides", {}).items():
        if chapter_id not in known:
            issues.append(f"chapter_forms contains unknown chapter ID: {chapter_id}")
        form = override if isinstance(override, str) else override.get("form")
        if form not in VALID_FORMS:
            issues.append(f"chapter_forms.{chapter_id} has unsupported form: {form}")
        if form == "sectioned_narrative":
            units = override.get("required_units", []) if isinstance(override, dict) else []
            if not units:
                issues.append(f"sectioned narrative chapter {chapter_id} has no required units")
            for unit in units:
                if not all(unit.get(key) for key in ("id", "title_zh", "title_en", "prompt_zh", "prompt_en")):
                    issues.append(f"sectioned narrative chapter {chapter_id} has incomplete required unit")
    if composition.get("validation_contract", {}).get("narrative_minimum_confirmed_statements", 0) < 2:
        issues.append("narrative_minimum_confirmed_statements must be at least 2")
    return issues


def validate_fact_model(
    facts: dict[str, Any], composition: dict[str, Any], matrix: dict[str, Any]
) -> list[str]:
    """Validate shape, language pairing and semantic grouping of a private fact model."""
    issues: list[str] = []
    metadata = facts.get("metadata", {})
    if metadata.get("route") != SUPPORTED_ROUTE:
        issues.append(f"unsupported route: {metadata.get('route')!r}")
    if metadata.get("diagnostic_trial") not in {"yes", "no"}:
        issues.append("metadata.diagnostic_trial must be 'yes' or 'no'")
    if not isinstance(metadata.get("conditions", []), list):
        issues.append("metadata.conditions must be a list")
    known_chapters = _chapter_ids(matrix)
    chapter_facts = facts.get("chapters", {})
    if not isinstance(chapter_facts, dict):
        return issues + ["chapters must be a mapping"]
    minimum = composition["validation_contract"]["narrative_minimum_confirmed_statements"]
    forms = composition["chapter_forms"]
    for chapter_id, chapter_data in chapter_facts.items():
        if chapter_id not in known_chapters:
            issues.append(f"fact model contains unknown chapter ID: {chapter_id}")
            continue
        units = chapter_data.get("units", []) if isinstance(chapter_data, dict) else []
        if not isinstance(units, list):
            issues.append(f"{chapter_id}.units must be a list")
            continue
        override = forms.get("overrides", {}).get(chapter_id, forms["default"])
        form = override if isinstance(override, str) else override.get("form")
        if form == "sectioned_narrative":
            required = {unit["id"] for unit in override["required_units"]}
            actual = {unit.get("id") for unit in units if isinstance(unit, dict)}
            missing = required - actual
            if missing:
                issues.append(f"{chapter_id} missing semantic units: {', '.join(sorted(missing))}")
        for unit in units:
            if not isinstance(unit, dict) or not unit.get("id"):
                issues.append(f"{chapter_id} contains a unit without id")
                continue
            statements = unit.get("statements", [])
            if not isinstance(statements, list) or not statements:
                issues.append(f"{chapter_id}.{unit['id']} must contain at least one statement")
                continue
            confirmed = 0
            for statement in statements:
                if not isinstance(statement, dict) or not statement.get("id"):
                    issues.append(f"{chapter_id}.{unit['id']} contains a statement without id")
                    continue
                status = statement.get("status")
                if status not in {"confirmed", "pending"}:
                    issues.append(f"{statement.get('id', '<unknown>')} status must be confirmed or pending")
                if status == "confirmed":
                    confirmed += 1
                    if not statement.get("zh") or not statement.get("en"):
                        issues.append(f"{statement['id']} requires both zh and en when confirmed")
                elif not statement.get("prompt_zh") or not statement.get("prompt_en"):
                    issues.append(f"{statement.get('id', '<unknown>')} requires both prompts when pending")
            if form == "narrative" and confirmed and confirmed < minimum and not unit.get("allow_single_statement"):
                issues.append(
                    f"{chapter_id}.{unit['id']} has {confirmed} confirmed narrative statement; "
                    f"at least {minimum} are required to prevent sentence-by-sentence paragraphs"
                )
    return issues


def _pending(statement: dict[str, Any], language: str) -> str:
    if language == "zh":
        return f"[待用户确认：{statement['prompt_zh']}]"
    return f"[To be completed after researcher/user confirmation: {statement['prompt_en']}]"


def _statement_text(statement: dict[str, Any], language: str) -> str:
    if statement.get("status") == "confirmed":
        return statement[language]
    return _pending(statement, language)


def _form_for(chapter_id: str, composition: dict[str, Any]) -> tuple[str, dict[str, Any] | None]:
    override = composition["chapter_forms"].get("overrides", {}).get(chapter_id)
    if override is None:
        return composition["chapter_forms"]["default"], None
    if isinstance(override, str):
        return override, None
    return override["form"], override


def _render_unit(unit: dict[str, Any], form: str, language: str) -> list[str]:
    values = [_statement_text(statement, language) for statement in unit["statements"]]
    if form == "narrative":
        return [" ".join(values), ""]
    if form == "definition_list":
        return [f"- {value}" for value in values] + [""]
    if form in {"criteria_list", "checklist"}:
        marker = "- [ ]" if form == "checklist" else "-"
        return [f"{marker} {value}" for value in values] + [""]
    if form == "procedure_steps":
        return [f"{index}. {value}" for index, value in enumerate(values, start=1)] + [""]
    raise ValueError(f"unsupported unit form: {form}")


def _missing_chapter(chapter: dict[str, Any], pair: dict[str, Any], language: str) -> list[str]:
    if language == "zh":
        return [f"[待用户确认：{chapter['prompt']}]", ""]
    return [f"[To be completed after researcher/user confirmation: {pair['prompt_en']}]", ""]


def _chapter_lines(
    chapter: dict[str, Any], pair: dict[str, Any], number: int, language: str,
    composition: dict[str, Any], facts: dict[str, Any],
) -> list[str]:
    if language == "zh":
        heading = f"### {number}. {chapter['title']} (`{chapter['id']}`)"
    elif language == "en":
        heading = f"### {number}. {pair['title_en']} (`{chapter['id']}`)"
    else:
        heading = f"### {number}. {chapter['title']} | {pair['title_en']} (`{chapter['id']}`)"
    lines = [heading, "", f"- Coverage level: `{chapter['evidence']}`", ""]
    chapter_data = facts.get("chapters", {}).get(chapter["id"])
    if not chapter_data:
        if language == "bilingual":
            lines.extend(_missing_chapter(chapter, pair, "zh"))
            lines.extend(_missing_chapter(chapter, pair, "en"))
        else:
            lines.extend(_missing_chapter(chapter, pair, language))
        return lines
    form, override = _form_for(chapter["id"], composition)
    units = chapter_data["units"]
    if form != "sectioned_narrative":
        for unit in units:
            if language == "bilingual":
                lines.extend(_render_unit(unit, form, "zh"))
                lines.extend(_render_unit(unit, form, "en"))
            else:
                lines.extend(_render_unit(unit, form, language))
        return lines
    required_by_id = {unit["id"]: unit for unit in override["required_units"]}
    actual_by_id = {unit["id"]: unit for unit in units}
    for unit_id, required in required_by_id.items():
        unit = actual_by_id[unit_id]
        if language in {"zh", "bilingual"}:
            lines.extend([f"#### {required['title_zh']}", ""])
            lines.extend(_render_unit(unit, "narrative", "zh"))
        if language in {"en", "bilingual"}:
            lines.extend([f"#### {required['title_en']}", ""])
            lines.extend(_render_unit(unit, "narrative", "en"))
    return lines


def render(
    matrix: dict[str, Any], sources: dict[str, Any], canonical: dict[str, Any],
    language_pairs: dict[str, Any], composition: dict[str, Any], facts: dict[str, Any], *, language: str,
) -> str:
    if language not in SUPPORTED_LANGUAGES:
        raise ValueError(f"unsupported language: {language}")
    issues = validate(matrix, sources, canonical, language_pairs)
    issues.extend(validate_composition(composition, matrix))
    issues.extend(validate_fact_model(facts, composition, matrix))
    if issues:
        raise ValueError("semantic protocol validation failed: " + "; ".join(issues))
    metadata = facts["metadata"]
    conditions = set(metadata.get("conditions", []))
    module_ids = set(selected_module_ids(
        matrix, route=metadata["route"], diagnostic_trial=metadata["diagnostic_trial"], conditions=conditions,
    ))
    selected_modules = sorted(
        (module for module in matrix["modules"] if module["id"] in module_ids), key=lambda module: module["order"],
    )
    if language == "bilingual":
        condition_text = ", ".join(
            f"{CONDITION_LABELS['zh'][item]} | {CONDITION_LABELS['en'][item]}" for item in sorted(conditions)
        ) or "无 | none"
    else:
        labels = CONDITION_LABELS["zh"] if language == "zh" else CONDITION_LABELS["en"]
        condition_text = ", ".join(labels[item] for item in sorted(conditions)) or ("无" if language == "zh" else "none")
    presentation_status = metadata.get("presentation_status", "content_structure_draft")
    if language == "zh":
        presentation_note = (
            "> **版式状态：内容与结构工作稿。** 本版本优先保证事实、章节、段落逻辑与待确认项的可审查性；"
            "不声称已经完成机构品牌、视觉美编、分页控制或最终提交版式。"
        )
    elif language == "en":
        presentation_note = (
            "> **Presentation status: content-and-structure working draft.** This version prioritizes auditable facts, "
            "chapter order, paragraph logic, and unresolved items; it is not represented as institution-branded, "
            "visually designed, paginated, or submission-final layout."
        )
    else:
        presentation_note = (
            "> **版式状态 | Presentation status：内容与结构工作稿 | content-and-structure working draft。** "
            "本版本优先保证事实、章节、段落逻辑与待确认项；尚未作为机构品牌、视觉美编、分页控制或最终提交版式。"
        )
    lines = [
        "# 中国通用研究计划书（同源事实模型生成）" if language == "zh" else (
            "# China-General Research Protocol (Shared Fact Model)" if language == "en"
            else "# 中国通用研究计划书 | China-General Research Protocol (Shared Fact Model)"
        ),
        "",
        "> 本文由 `protocol-coverage-matrix.yaml`、`protocol-semantic-composition.yaml` 与私有事实模型生成。中英文读取同一 statement_id；待确认内容不会被臆造。" if language != "en" else "> Generated from the coverage matrix, semantic-composition rules, and a private fact model. Chinese and English use the same statement IDs; missing facts are not inferred.",
        presentation_note,
        "",
        f"- Route: `{metadata['route']}`",
        f"- Diagnostic trial: `{metadata['diagnostic_trial']}`",
        f"- Condition modules: {condition_text}",
        f"- Fact confirmation: `{metadata.get('fact_confirmation', 'pending')}`",
        f"- Presentation status: `{presentation_status}`",
        "",
    ]
    chapter_number = 0
    for module in selected_modules:
        lines.extend([f"## {module['order'] // 10}. {_module_heading(module, language_pairs, language)}", ""])
        for chapter in module["chapters"]:
            chapter_number += 1
            pair = language_pairs["chapter_pairs"][chapter["id"]]
            lines.extend(_chapter_lines(chapter, pair, chapter_number, language, composition, facts))
    return "\n".join(lines).rstrip() + "\n"


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--facts", type=Path, required=True, help="Private fact-model YAML")
    parser.add_argument("--language", choices=tuple(sorted(SUPPORTED_LANGUAGES)), default="bilingual")
    parser.add_argument("--composition", type=Path, default=DEFAULT_COMPOSITION)
    parser.add_argument("--matrix", type=Path, default=DEFAULT_MATRIX)
    parser.add_argument("--sources", type=Path, default=DEFAULT_SOURCES)
    parser.add_argument("--canonical", type=Path, default=DEFAULT_CANONICAL)
    parser.add_argument("--language-pairs", type=Path, default=DEFAULT_LANGUAGE_PAIRS)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        content = render(
            load_yaml(args.matrix), load_yaml(args.sources), load_yaml(args.canonical),
            load_yaml(args.language_pairs), load_yaml(args.composition), load_yaml(args.facts), language=args.language,
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(content, encoding="utf-8", newline="\n")
    except (OSError, UnicodeError, yaml.YAMLError, ValueError) as exc:
        print(f"semantic protocol generation failed: {exc}", file=sys.stderr)
        return 2
    print(f"semantic protocol generated: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
