#!/usr/bin/env python3
"""Validate the source registry and deterministic protocol-template matrix."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

import yaml

from validate_atomic_schema import AtomicSchemaValidator


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MATRIX = ROOT / "references" / "protocol-coverage-matrix.yaml"
DEFAULT_SOURCES = ROOT / "references" / "protocol-template-sources.yaml"
DEFAULT_CANONICAL = ROOT / "references" / "registration-tree.yaml"
DEFAULT_LANGUAGE_PAIRS = ROOT / "references" / "protocol-template-language-pairs.yaml"


def load_yaml(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path} must be a mapping")
    return data


def validate(
    matrix: dict[str, Any],
    source_registry: dict[str, Any],
    canonical: dict[str, Any] | None = None,
    language_pairs: dict[str, Any] | None = None,
) -> list[str]:
    issues: list[str] = []
    source_items = source_registry.get("sources")
    if not isinstance(source_items, list):
        return ["source registry sources must be a list"]
    source_ids = {item.get("id") for item in source_items if isinstance(item, dict)}
    if len(source_ids) != len(source_items) or None in source_ids:
        issues.append("source registry must contain unique non-empty source ids")

    controls: set[str] | None = None
    if canonical is not None:
        canonical_validator = AtomicSchemaValidator(canonical)
        canonical_issues = canonical_validator.validate()
        if canonical_issues:
            issues.append("registration-tree.yaml cannot be used for mapping validation")
        else:
            controls = set(canonical_validator.controls)

    modules = matrix.get("modules")
    if not isinstance(modules, list) or not modules:
        return issues + ["coverage matrix modules must be a non-empty list"]
    module_ids: set[str] = set()
    chapter_ids: set[str] = set()
    orders: set[int] = set()
    for index, module in enumerate(modules):
        location = f"modules[{index}]"
        if not isinstance(module, dict):
            issues.append(f"{location} must be a mapping")
            continue
        module_id = module.get("id")
        if not isinstance(module_id, str) or not module_id:
            issues.append(f"{location}.id must be a non-empty string")
        elif module_id in module_ids:
            issues.append(f"{location}.id duplicates {module_id!r}")
        else:
            module_ids.add(module_id)
        order = module.get("order")
        if not isinstance(order, int):
            issues.append(f"{location}.order must be an integer")
        elif order in orders:
            issues.append(f"{location}.order duplicates {order}")
        else:
            orders.add(order)
        for source_id in module.get("sources", []):
            if source_id not in source_ids:
                issues.append(f"{location}.sources references unknown source {source_id!r}")
        chapters = module.get("chapters")
        if not isinstance(chapters, list) or not chapters:
            issues.append(f"{location}.chapters must be a non-empty list")
            continue
        for chapter_index, chapter in enumerate(chapters):
            chapter_location = f"{location}.chapters[{chapter_index}]"
            if not isinstance(chapter, dict):
                issues.append(f"{chapter_location} must be a mapping")
                continue
            chapter_id = chapter.get("id")
            if not isinstance(chapter_id, str) or not chapter_id:
                issues.append(f"{chapter_location}.id must be a non-empty string")
            elif chapter_id in chapter_ids:
                issues.append(f"{chapter_location}.id duplicates {chapter_id!r}")
            else:
                chapter_ids.add(chapter_id)
            for key in ("title", "evidence", "prompt"):
                if not isinstance(chapter.get(key), str) or not chapter[key].strip():
                    issues.append(f"{chapter_location}.{key} must be a non-empty string")
            if not isinstance(chapter.get("registration_paths"), list):
                issues.append(f"{chapter_location}.registration_paths must be a list")
            elif controls is not None:
                for registration_path in chapter["registration_paths"]:
                    if registration_path not in controls:
                        issues.append(
                            f"{chapter_location}.registration_paths references unknown canonical path {registration_path!r}"
                        )

    if language_pairs is not None:
        language_scope = language_pairs.get("scope")
        if not isinstance(language_scope, dict):
            issues.append("language-pair catalog scope must be a mapping")
        else:
            if language_scope.get("canonical_language") != "zh-CN":
                issues.append("language-pair catalog canonical_language must be zh-CN")
            if language_scope.get("paired_language") != "en":
                issues.append("language-pair catalog paired_language must be en")
        paired_modules = language_pairs.get("module_pairs")
        if not isinstance(paired_modules, dict):
            issues.append("language-pair catalog module_pairs must be a mapping")
        else:
            paired_module_ids = set(paired_modules)
            if paired_module_ids != module_ids:
                issues.append("language-pair catalog module IDs must exactly match coverage-matrix module IDs")
            for module_id, pair in paired_modules.items():
                if not isinstance(pair, dict) or not isinstance(pair.get("title_en"), str) or not pair["title_en"].strip():
                    issues.append(f"language-pair catalog module {module_id!r} needs a non-empty title_en")
        paired_chapters = language_pairs.get("chapter_pairs")
        if not isinstance(paired_chapters, dict):
            issues.append("language-pair catalog chapter_pairs must be a mapping")
        else:
            paired_chapter_ids = set(paired_chapters)
            if paired_chapter_ids != chapter_ids:
                issues.append("language-pair catalog chapter IDs must exactly match coverage-matrix chapter IDs")
            for chapter_id, pair in paired_chapters.items():
                if not isinstance(pair, dict):
                    issues.append(f"language-pair catalog chapter {chapter_id!r} must be a mapping")
                    continue
                for key in ("title_en", "prompt_en"):
                    if not isinstance(pair.get(key), str) or not pair[key].strip():
                        issues.append(f"language-pair catalog chapter {chapter_id!r} needs a non-empty {key}")

    profiles = matrix.get("profiles")
    if not isinstance(profiles, dict):
        issues.append("coverage matrix profiles must be a mapping")
    else:
        china = profiles.get("china-mainland")
        if not isinstance(china, dict):
            issues.append("coverage matrix must define the china-mainland profile")
        else:
            scope = matrix.get("scope")
            if not isinstance(scope, dict):
                issues.append("coverage matrix scope must be a mapping")
            else:
                language_policy = scope.get("language_policy")
                if not isinstance(language_policy, dict):
                    issues.append("scope.language_policy must be a mapping")
                else:
                    if language_policy.get("canonical_language") != "zh-CN":
                        issues.append("scope.language_policy.canonical_language must be zh-CN")
                    outputs = language_policy.get("supported_output_languages")
                    if not isinstance(outputs, list) or not {"zh-CN", "en"}.issubset(outputs):
                        issues.append("scope.language_policy.supported_output_languages must include zh-CN and en")
                    if language_policy.get("bilingual_generation") != "same_facts_two_renderings":
                        issues.append("scope.language_policy.bilingual_generation must preserve one fact source")
                    if language_policy.get("chictr_public_requires_platform_english_pairing") is not True:
                        issues.append("scope.language_policy must require ChiCTR public English pairing")
                hospital_policy = scope.get("hospital_policy")
                if not isinstance(hospital_policy, dict):
                    issues.append("scope.hospital_policy must be a mapping")
                elif hospital_policy.get("generic_generation_requires_hospital_template") is not False:
                    issues.append("generic China generation must not require a hospital template")
            route = china.get("generator_routes", {}).get("investigator-observational", {})
            if not isinstance(route, dict):
                issues.append("china-mainland investigator-observational route missing")
            else:
                referenced = list(route.get("required_modules", [])) + list(route.get("conditional_modules", {}).values())
                for module_id in referenced:
                    if module_id not in module_ids:
                        issues.append(f"route references unknown module {module_id!r}")
    return issues


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--matrix", type=Path, default=DEFAULT_MATRIX)
    parser.add_argument("--sources", type=Path, default=DEFAULT_SOURCES)
    parser.add_argument("--canonical", type=Path, default=DEFAULT_CANONICAL)
    parser.add_argument("--language-pairs", type=Path, default=DEFAULT_LANGUAGE_PAIRS)
    args = parser.parse_args()
    try:
        matrix = load_yaml(args.matrix)
        sources = load_yaml(args.sources)
        canonical = load_yaml(args.canonical)
        language_pairs = load_yaml(args.language_pairs)
    except (OSError, UnicodeError, yaml.YAMLError, ValueError) as exc:
        print(f"Protocol-template assets cannot be read: {exc}", file=sys.stderr)
        return 2
    issues = validate(matrix, sources, canonical, language_pairs)
    if issues:
        print(f"Protocol-template asset validation failed: {len(issues)} issue(s)", file=sys.stderr)
        for issue in issues:
            print(f"- {issue}", file=sys.stderr)
        return 1
    print(
        "Protocol-template assets validated: "
        f"modules={len(matrix['modules'])}, chapters={sum(len(module['chapters']) for module in matrix['modules'])}, "
        f"sources={len(sources['sources'])}, language_pairs={len(language_pairs['chapter_pairs'])}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
