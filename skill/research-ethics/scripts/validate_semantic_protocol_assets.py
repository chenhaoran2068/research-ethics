#!/usr/bin/env python3
"""Validate public semantic-composition assets without reading private study facts."""

from __future__ import annotations

import sys

from render_semantic_protocol import DEFAULT_COMPOSITION, validate_composition
from validate_protocol_template_assets import DEFAULT_MATRIX, load_yaml


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    issues = validate_composition(load_yaml(DEFAULT_COMPOSITION), load_yaml(DEFAULT_MATRIX))
    if issues:
        print("semantic protocol asset validation failed:", file=sys.stderr)
        for issue in issues:
            print(f"- {issue}", file=sys.stderr)
        return 2
    print("semantic protocol assets valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
