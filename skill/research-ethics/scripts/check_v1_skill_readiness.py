#!/usr/bin/env python3
"""Gate construction of a user-facing research-ethics V1 skill.

This gate deliberately relies on the canonical rules and the de-identified
ledger only.  It is conservative: a passing result means the V1 package has
enough declared evidence for the proposed skill scope; a failing result never
invalidates already-recorded current-page observations.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

from validate_dfs_ledger import DEFAULT_CANONICAL, DEFAULT_LEDGER, validate_ledger


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_READINESS = PROJECT_ROOT / "references" / "v1-skill-readiness.md"
DEFAULT_BLOCKED_PROTOCOL = PROJECT_ROOT / "references" / "unproduct-other-local-dfs-protocol.md"
MANUAL_ONLY_MISMATCH_PROTOCOLS = {
    "research-design.intervention-type": PROJECT_ROOT
    / "references"
    / "intervention-type-other-local-replay-protocol.md",
}

# These controls either change the registration route itself or commonly add
# bilingual, organization, consent, or disclosure requirements.  A generated
# user document must not make a silent decision for any of them.
REQUIRED_CURRENT_PAGE_CONTROLS = {
    "research-category.diagnostic-trial",
    "basic-information.sync-platform",
    "implementation-information.multicenter-flag",
    "research-design.study-design",
    "research-design.biological-sample-collection",
    "data-sharing-and-public-disclosure.data-share-statement",
}
REQUIRED_DOWNSTREAM_ROOTS = {
    ("investigator-observational", "yes"),
    ("investigator-observational", "no"),
}


def observations(ledger: dict[str, Any]) -> list[dict[str, Any]]:
    values: list[dict[str, Any]] = []
    for collection in ("manual_live_observations", "live_current_page_observations"):
        raw = ledger.get(collection, [])
        if isinstance(raw, list):
            values.extend(item for item in raw if isinstance(item, dict))
    return values


def route_supports_downstream(route: dict[str, Any], root: str, diagnostic: str | None) -> bool:
    selections = route.get("selections", {})
    if not isinstance(selections, dict) or selections.get("research-category.route-leaf") != root:
        return False
    if diagnostic is not None and selections.get("research-category.diagnostic-trial") != diagnostic:
        return False
    if route.get("verification_level") not in {"sample_verified", "fully_live_verified"}:
        return False
    return route.get("evidence_grade") in {"downstream_spot_checked", "full_leaf_replay"}


def readiness(validated: dict[str, Any]) -> tuple[list[str], list[str]]:
    ledger = validated["ledger"]
    issues: list[str] = []
    excluded: list[str] = []
    routes = ledger.get("routes", [])
    routes = routes if isinstance(routes, list) else []
    current = {
        str(item.get("control_path"))
        for item in observations(ledger)
        if item.get("verification_level") in {"sample_verified", "fully_live_verified"}
        and item.get("evidence_grade") in {"current_page_verified", "downstream_spot_checked", "full_leaf_replay"}
    }
    # Some samples are recorded as partial routes because the root and a
    # representative page were both visited.  Their explicitly selected
    # controls are current-page evidence too; never infer controls that are
    # absent from their recorded selection set.
    for route in routes:
        if not isinstance(route, dict):
            continue
        selections = route.get("selections", {})
        if not isinstance(selections, dict) or selections.get("research-category.route-leaf") != "investigator-observational":
            continue
        if route.get("verification_level") not in {"sample_verified", "fully_live_verified"}:
            continue
        if route.get("evidence_grade") not in {"current_page_verified", "downstream_spot_checked", "full_leaf_replay"}:
            continue
        current.update(path for path in selections if path in REQUIRED_CURRENT_PAGE_CONTROLS)
    missing_current = sorted(REQUIRED_CURRENT_PAGE_CONTROLS - current)
    if missing_current:
        issues.append("missing current-page sample for: " + ", ".join(missing_current))

    for item in observations(ledger):
        selections = item.get("selections", {})
        if isinstance(selections, dict) and selections.get("research-category.route-leaf") == "investigator-interventional":
            continue
        if item.get("verification_level") == "mismatch_found":
            path = str(item.get("control_path", "unknown"))
            if item.get("v1_disposition") == "manual_only_until_local_replay" and path in MANUAL_ONLY_MISMATCH_PROTOCOLS:
                excluded.append(path)
                if not MANUAL_ONLY_MISMATCH_PROTOCOLS[path].exists():
                    issues.append("manual-only mismatch has no local replay protocol: " + path)
            else:
                issues.append("unresolved mismatch below: " + path)
        if item.get("verification_level") == "out_of_scope_or_blocked":
            excluded.append(str(item.get("control_path", "unknown")))

    for root, diagnostic in sorted(REQUIRED_DOWNSTREAM_ROOTS):
        if not any(
            isinstance(route, dict) and route_supports_downstream(route, root, diagnostic)
            for route in routes
        ):
            suffix = "" if diagnostic is None else f", diagnostic={diagnostic}"
            issues.append(f"missing downstream representative route: {root}{suffix}")

    if not DEFAULT_READINESS.exists():
        issues.append("missing documented readiness boundary")
    if excluded and not DEFAULT_BLOCKED_PROTOCOL.exists():
        issues.append("blocked branch has no documented exclusion protocol")
    return issues, sorted(set(excluded))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--canonical", type=Path, default=DEFAULT_CANONICAL)
    parser.add_argument("--ledger", type=Path, default=DEFAULT_LEDGER)
    args = parser.parse_args()
    validated = validate_ledger(args.canonical, args.ledger)
    issues, excluded = readiness(validated)
    if issues:
        print("V1 skill readiness: NOT READY")
        for issue in issues:
            print("- " + issue)
        return 2
    if excluded:
        print("V1 skill readiness: READY_WITH_EXCLUSIONS")
        for path in excluded:
            print("- excluded from supported V1 generation: " + path)
    else:
        print("V1 skill readiness: READY")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
