#!/usr/bin/env python3
"""Run read-only structural checks for the generated unmerged display tree.

This checks the in-memory tree rebuilt from the canonical YAML and the DFS
ledger.  It does not treat an existing HTML file as evidence and it does not
need browser, account or source-page access.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from generate_unmerged_vertical_tree import build_tree
from validate_dfs_ledger import DEFAULT_CANONICAL, DEFAULT_LEDGER, LedgerValidationError, validate_ledger


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--canonical", type=Path, default=DEFAULT_CANONICAL)
    parser.add_argument("--ledger", type=Path, default=DEFAULT_LEDGER)
    args = parser.parse_args()
    try:
        validated = validate_ledger(args.canonical, args.ledger)
        _, metrics = build_tree(validated)
    except LedgerValidationError as error:
        print(f"Unmerged tree validation failed: {error}", file=sys.stderr)
        return 2
    # A structurally well-formed root with no display routes is an empty
    # scaffold, not a completed unmerged tree.  Keep this distinct from a
    # schema failure so callers cannot mistake the preview state for final
    # root-to-leaf coverage.
    if metrics["leaves"] == 0:
        print(
            "Unmerged tree incomplete: single_root=1, single_parent=1, acyclic=1, "
            f"leaves=0, instances={metrics['instances']}, "
            f"structural_branch_instances={metrics['structural_instances']}; "
            "no completed display routes are available yet.",
            file=sys.stderr,
        )
        return 3
    print(
        "Unmerged tree validation passed: single_root=1, single_parent=1, acyclic=1, "
        f"leaves={metrics['leaves']}, instances={metrics['instances']}, "
        f"structural_branch_instances={metrics['structural_instances']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
