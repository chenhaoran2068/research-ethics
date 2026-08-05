#!/usr/bin/env python3
"""Validate the auditable V1 artifact set without inspecting browser secrets."""

from __future__ import annotations

import hashlib
import re
import sys
from pathlib import Path

import yaml

from generate_v1_candidate_queue import collect
from generate_v1_field_coverage_matrix import render as render_field_matrix
from generate_observational_v1_coverage import render as render_observational_coverage
from generate_observational_v1_unmerged import build_model, html_document, markdown as unmerged_markdown
from validate_dfs_ledger import LedgerValidationError, validate_ledger


PROJECT_ROOT = Path(__file__).resolve().parents[1]
REFERENCES = PROJECT_ROOT / "references"
CANONICAL = REFERENCES / "registration-tree.yaml"
LEDGER = REFERENCES / "dfs-exploration-ledger.yaml"
PREVIEW_MD = REFERENCES / "registration-tree-v1-unmerged.md"
PREVIEW_HTML = REFERENCES / "registration-tree-v1-unmerged.html"
CANDIDATE_QUEUE = REFERENCES / "v1-dfs-candidate-queue.md"
FIELD_MATRIX = REFERENCES / "v1-field-coverage-matrix.md"
DFS_COVERAGE = REFERENCES / "dfs-coverage-matrix.md"
EXPECTED_V2 = {
    "product-drug",
    "product-medical-device-class-i",
    "product-medical-device-class-ii",
    "product-medical-device-class-iii",
    "product-ivd-class-i",
    "product-ivd-class-ii",
    "product-ivd-class-iii",
    "product-special-food",
}
DISALLOWED_RAW_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".mhtml"}
EMAIL = re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b")
PHONE = re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")
UUID = re.compile(r"(?i)\b[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}\b")


def sha256(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def check_scope(canonical: dict) -> None:
    scope = canonical.get("version_scope")
    if not isinstance(scope, dict) or scope.get("version") != "v1":
        raise ValueError("canonical must declare version_scope.version: v1")
    roots = set(map(str, scope.get("supported_root_routes", [])))
    if roots != {"investigator-observational"}:
        raise ValueError("V1 supported roots must be exactly investigator-observational")
    deferred_roots = scope.get("deferred_root_routes")
    if not isinstance(deferred_roots, list):
        raise ValueError("canonical must explicitly list deferred V2 root routes")
    deferred_root_ids = {
        str(item.get("route_id"))
        for item in deferred_roots
        if isinstance(item, dict) and item.get("status") == "deferred_to_v2"
    }
    expected_deferred_roots = {
        "investigator-interventional",
        "product-drug",
        "product-medical-device",
        "product-ivd",
        "product-special-food",
    }
    if deferred_root_ids != expected_deferred_roots:
        raise ValueError("V1 deferred root-route list is incomplete or has unexpected entries")
    deferred = scope.get("deferred_to_v2_expansions")
    if not isinstance(deferred, list):
        raise ValueError("canonical must explicitly list V2 deferred expansions")
    actual = {str(item.get("route_id")) for item in deferred if isinstance(item, dict) and item.get("status") == "deferred_to_v2"}
    if actual != EXPECTED_V2:
        raise ValueError("V2 deferred expansion list is incomplete or has unexpected entries")


def check_generated_freshness(validated: dict) -> None:
    canonical = validated["canonical"]
    required = [PREVIEW_MD, PREVIEW_HTML, CANDIDATE_QUEUE, FIELD_MATRIX, DFS_COVERAGE]
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        raise ValueError("missing generated V1 artifacts: " + ", ".join(missing))
    expected_hash = validated["canonical_sha256"]
    if expected_hash not in PREVIEW_MD.read_text(encoding="utf-8"):
        raise ValueError("unmerged preview markdown is stale against the canonical hash")
    expected_candidates = len(collect(validated["canonical"]))
    if str(expected_candidates) not in PREVIEW_MD.read_text(encoding="utf-8"):
        raise ValueError("unmerged preview markdown has stale candidate count")
    expected_matrix = render_field_matrix(validated)
    if FIELD_MATRIX.read_text(encoding="utf-8") != expected_matrix:
        raise ValueError("field coverage matrix is stale")
    expected_dfs_coverage = render_observational_coverage(validated)
    if DFS_COVERAGE.read_text(encoding="utf-8") != expected_dfs_coverage:
        raise ValueError("observational DFS coverage matrix is stale")
    model = build_model(canonical, validated)
    expected_preview = unmerged_markdown(model)
    if PREVIEW_MD.read_text(encoding="utf-8") != expected_preview:
        raise ValueError("unmerged preview markdown is stale")
    if PREVIEW_HTML.read_text(encoding="utf-8") != html_document(model):
        raise ValueError("unmerged preview HTML is stale")


def check_privacy() -> None:
    forbidden_files = [
        path for path in PROJECT_ROOT.rglob("*")
        if path.is_file() and (path.suffix.lower() in DISALLOWED_RAW_SUFFIXES or path.name.lower() in {"code.txt", "source.txt"})
    ]
    if forbidden_files:
        raise ValueError("raw evidence-like files are present: " + ", ".join(str(path.relative_to(PROJECT_ROOT)) for path in forbidden_files))
    evidence_texts = [CANONICAL, LEDGER, DFS_COVERAGE, FIELD_MATRIX, CANDIDATE_QUEUE, PREVIEW_MD, PREVIEW_HTML]
    for path in evidence_texts:
        text = path.read_text(encoding="utf-8")
        for pattern, label in ((EMAIL, "email"), (PHONE, "phone"), (UUID, "UUID")):
            if pattern.search(text):
                raise ValueError(f"{path.name} contains {label}-like retained evidence")


def main() -> int:
    try:
        validated = validate_ledger(CANONICAL, LEDGER)
        loader = getattr(yaml, "CSafeLoader", yaml.SafeLoader)
        canonical = yaml.load(CANONICAL.read_text(encoding="utf-8"), Loader=loader)
        if not isinstance(canonical, dict):
            raise ValueError("canonical root is not a mapping")
        check_scope(canonical)
        check_generated_freshness(validated)
        check_privacy()
    except (LedgerValidationError, ValueError) as error:
        print(f"V1 artifact validation failed: {error}", file=sys.stderr)
        return 2
    print(
        "V1 artifact validation passed: "
        f"canonical={sha256(CANONICAL)}, candidates={len(collect(validated['canonical']))}, "
        f"partial_routes={validated['partial_route_count']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
