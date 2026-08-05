#!/usr/bin/env python3
"""Validate the canonical registration map and its generated review view."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import yaml

from generate_expanded_tree import build_artifacts, validate_artifacts


RAW_EVIDENCE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".html", ".txt"}
# These are generated, de-identified review artifacts, not captured page source.
# Keep this allow-list narrow so arbitrary HTML cannot bypass the raw-evidence gate.
GENERATED_NON_EVIDENCE_NAMES = {"registration-tree-v1-unmerged.html"}


def require_unique(values: list[str], context: str) -> None:
    duplicates = sorted({value for value in values if values.count(value) > 1})
    if duplicates:
        raise ValueError(f"Duplicate IDs in {context}: {duplicates}")


def validate_nested_fields(value: Any, context: str) -> None:
    if isinstance(value, dict):
        nested = value.get("fields")
        if isinstance(nested, list) and nested and all(isinstance(item, dict) for item in nested):
            ids = [str(item.get("id", "")) for item in nested]
            if any(not node_id for node_id in ids):
                raise ValueError(f"Missing nested field ID in {context}")
            require_unique(ids, context)
            for item in nested:
                if not item.get("label"):
                    raise ValueError(f"Missing nested field label in {context}/{item.get('id')}")
        for key, child in value.items():
            validate_nested_fields(child, f"{context}/{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value, start=1):
            validate_nested_fields(child, f"{context}[{index}]")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("project_root", type=Path)
    args = parser.parse_args()

    root = args.project_root.resolve()
    yaml_path = root / "references" / "registration-tree.yaml"
    expanded_path = root / "references" / "registration-tree-expanded.md"
    matrix_path = root / "references" / "branch-completion-matrix.md"
    compact_path = root / "references" / "registration-tree.md"

    data = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    pages = data["workflow"]["pages"]
    page_ids = [str(page.get("id", "")) for page in pages]
    if any(not page_id for page_id in page_ids):
        raise ValueError("A page is missing its ID")
    require_unique(page_ids, "workflow.pages")

    for page in pages:
        if not page.get("label"):
            raise ValueError(f"Missing page label: {page.get('id')}")
        nodes = page.get("nodes", [])
        node_ids = [str(node.get("id", "")) for node in nodes if isinstance(node, dict)]
        if len(node_ids) != len(nodes) or any(not node_id for node_id in node_ids):
            raise ValueError(f"Missing top-level node ID in page {page['id']}")
        require_unique(node_ids, f"page {page['id']}")

    artifacts = build_artifacts(data)
    validate_artifacts(artifacts)
    if expanded_path.read_text(encoding="utf-8") != artifacts.expanded.rstrip() + "\n":
        raise ValueError("registration-tree-expanded.md is stale; regenerate it from the YAML")
    if matrix_path.read_text(encoding="utf-8") != artifacts.matrix.rstrip() + "\n":
        raise ValueError("branch-completion-matrix.md is stale; regenerate it from the YAML")

    compact = compact_path.read_text(encoding="utf-8")
    if compact.count("```mermaid") != sum(
        1 for line in compact.splitlines() if line.strip() == "```"
    ):
        raise ValueError("Mermaid code fences are unbalanced in registration-tree.md")

    evidence_like_files = [
        path
        for path in root.rglob("*")
        if path.is_file()
        and path.name not in GENERATED_NON_EVIDENCE_NAMES
        and (
            path.suffix.lower() in RAW_EVIDENCE_SUFFIXES
            or "evidence" in path.name.lower()
            or "源码" in path.name
        )
    ]
    if evidence_like_files:
        raise ValueError(f"Raw evidence-like files found: {evidence_like_files}")

    counts = artifacts.expected_counts
    print(
        "Validation passed: "
        f"pages={counts.pages}, active nodes/options={counts.active_nodes}/{counts.active_options}, "
        f"candidate nodes/options={counts.candidate_nodes}/{counts.candidate_options}"
    )


if __name__ == "__main__":
    main()
