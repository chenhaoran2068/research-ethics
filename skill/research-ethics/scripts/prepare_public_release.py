#!/usr/bin/env python3
"""Build a public-source repository from an explicit, privacy-safe allowlist.

This never copies the working directory wholesale.  In particular, user
protocols, DOCX derivatives, deliverables, browser evidence and caches are
not candidates for the public repository.
"""

from __future__ import annotations

import argparse
import re
import shutil
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILL_FILES = ("SKILL.md", "BUILD_RULES.md")
PUBLIC_ROOT_FILES = ("README.md", "BUILD_RULES.md")
SKILL_DIRS = ("agents", "scripts", "tests")
REFERENCE_FILES = (
    "registration-tree.yaml",
    "dfs-exploration-ledger.yaml",
    "dfs-coverage-matrix.md",
    "v1-scope.md",
    "v1-skill-readiness.md",
    "v1-acceptance.md",
    "chictr-public-route-acceptance.md",
    "intake-schema.md",
    "intake-template.yaml",
    "registration-tree-v1-unmerged.md",
    "registration-tree-v1-unmerged.html",
    "v1-dfs-candidate-queue.md",
    "v1-field-coverage-matrix.md",
    "unproduct-other-local-dfs-protocol.md",
    "intervention-type-other-local-replay-protocol.md",
    # Code-generated protocol skeleton and semantic-composition rules.
    "protocol-coverage-matrix.yaml",
    "protocol-template-sources.yaml",
    "protocol-template-language-pairs.yaml",
    "protocol-template-architecture.md",
    "protocol-semantic-composition.yaml",
    "protocol-semantic-fact-template.yaml",
    "version-roadmap.md",
)
FORBIDDEN_SUFFIXES = {".docx", ".png", ".jpg", ".jpeg", ".webp", ".mhtml", ".pdf"}
FORBIDDEN_NAMES = {"code.txt", "source.txt"}
# These files supported a one-off, private document-restructuring review.
# Public V1 teaches code-generated skeletons and never needs to reproduce a
# user plan by manual restructuring.
PRIVATE_ONLY_BASENAMES = {
    "restructure_observational_protocol.py",
    "validate_restructured_protocol_docx.py",
    "test_restructure_observational_protocol.py",
}
SENSITIVE_PATTERNS = (
    ("email", re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b")),
    ("mobile", re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")),
    ("chinese_id", re.compile(r"(?<!\d)\d{17}[\dXx](?![\dXx])")),
    ("local_path", re.compile(r"(?i)[A-Z]:\\(?:Users|OneDrive|AppData)\\")),
)


def copy_file(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)


def copy_tree(source: Path, destination: Path) -> None:
    for path in source.rglob("*"):
        if not path.is_file() or "__pycache__" in path.parts:
            continue
        if path.suffix.lower() in FORBIDDEN_SUFFIXES or path.name.lower() in FORBIDDEN_NAMES:
            continue
        if path.name in PRIVATE_ONLY_BASENAMES:
            continue
        if path.name.endswith(".generated.md") or path.name.endswith(".generated.docx"):
            continue
        copy_file(path, destination / path.relative_to(source))


def scan_public_tree(root: Path) -> list[str]:
    problems: list[str] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(root)
        if path.suffix.lower() in FORBIDDEN_SUFFIXES or path.name.lower() in FORBIDDEN_NAMES:
            problems.append(f"forbidden file: {relative}")
            continue
        if path.suffix.lower() not in {".md", ".yaml", ".yml", ".py", ".html", ".txt"}:
            continue
        text = path.read_text(encoding="utf-8")
        for label, pattern in SENSITIVE_PATTERNS:
            matches = list(pattern.finditer(text))
            if label == "email":
                matches = [
                    match
                    for match in matches
                    if not match.group(0).lower().endswith(("@example.com", "@example.org", "@invalid"))
                ]
            if matches:
                problems.append(f"{relative}: {label}-like content")
    return problems


def build(destination: Path) -> None:
    if destination.exists():
        raise ValueError(f"destination already exists: {destination}")
    skill_destination = destination / "skill" / "research-ethics"
    destination.mkdir(parents=True)
    for name in PUBLIC_ROOT_FILES:
        copy_file(ROOT / name, destination / name)
    for name in SKILL_FILES:
        copy_file(ROOT / name, skill_destination / name)
    for name in SKILL_DIRS:
        copy_tree(ROOT / name, skill_destination / name)
    for name in REFERENCE_FILES:
        copy_file(ROOT / "references" / name, skill_destination / "references" / name)
    problems = scan_public_tree(destination)
    if problems:
        raise ValueError("public release scan failed: " + "; ".join(problems))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination", type=Path)
    parser.add_argument("--check", type=Path, help="scan an existing public-source tree")
    args = parser.parse_args()
    if args.check:
        problems = scan_public_tree(args.check)
        if problems:
            raise SystemExit("public release scan failed: " + "; ".join(problems))
        print(f"Public release scan passed: {args.check}")
        return 0
    if args.destination is None:
        parser.error("--destination is required unless --check is used")
    build(args.destination)
    print(f"Prepared public release: {args.destination}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
