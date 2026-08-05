#!/usr/bin/env python3
"""Generate a de-identified V1 field-by-field evidence gap matrix."""

from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

import yaml

from generate_v1_candidate_queue import ROOT_PATH, V1_ROOTS, conditions, possible_in_v1
from validate_dfs_ledger import DEFAULT_CANONICAL, DEFAULT_LEDGER, validate_ledger


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = PROJECT_ROOT / "references" / "v1-field-coverage-matrix.md"


def children(node: dict[str, Any]) -> Iterable[dict[str, Any]]:
    for key in ("nodes", "children"):
        value = node.get(key)
        if isinstance(value, list):
            yield from (item for item in value if isinstance(item, dict))


def path_of(node: dict[str, Any], parent: str, position: int) -> str:
    return str(node.get("path") or f"{parent}.{node.get('id', f'node-{position}')}")


def v1_paths(canonical: dict[str, Any]) -> set[str]:
    result: set[str] = set()
    pages = canonical.get("workflow", {}).get("pages", [])
    for page in pages if isinstance(pages, list) else []:
        if not isinstance(page, dict) or not isinstance(page.get("id"), str):
            continue

        def walk(node: dict[str, Any], parent: str, position: int, inherited: tuple[dict[str, Any], ...] = ()) -> None:
            path = path_of(node, parent, position)
            effective = inherited + tuple(conditions(node.get("visible_if")))
            if not possible_in_v1(effective):
                return
            result.add(path)
            for child_position, child in enumerate(children(node), start=1):
                walk(child, path, child_position, effective)

        for position, node in enumerate(page.get("nodes", []), start=1):
            if isinstance(node, dict):
                walk(node, page["id"], position)
    return result


def evidence_sets(ledger: dict[str, Any]) -> tuple[set[str], set[str]]:
    snapshot_paths: set[str] = set()
    manual_paths: set[str] = set()
    for route in ledger.get("routes", []):
        if not isinstance(route, dict):
            continue
        for page in route.get("display", {}).get("pages", []):
            if isinstance(page, dict):
                snapshot_paths.update(str(path) for path in page.get("field_paths", []))
    for collection in ("manual_live_observations", "live_current_page_observations"):
        for observation in ledger.get(collection, []):
            if not isinstance(observation, dict):
                continue
            if isinstance(observation.get("control_path"), str):
                manual_paths.add(observation["control_path"])
            for key in ("visible_field_paths", "hidden_field_paths"):
                manual_paths.update(str(path) for path in observation.get(key, []))
            options = observation.get("compared_options", {})
            if isinstance(options, dict):
                for details in options.values():
                    if isinstance(details, dict):
                        for key in ("visible_field_paths", "hidden_field_paths"):
                            manual_paths.update(str(path) for path in details.get(key, []))
    return snapshot_paths, manual_paths


def render(validated: dict[str, Any]) -> str:
    canonical, ledger, index = validated["canonical"], validated["ledger"], validated["index"]
    relevant = v1_paths(canonical)
    snapshots, manual = evidence_sets(ledger)
    rows: list[tuple[str, str, str, str]] = []
    for path in sorted(relevant, key=lambda item: (index.page_of_path.get(item, ""), item)):
        node = index.node_by_path.get(path, {})
        if node.get("kind") != "control" or node.get("widget") == "hidden":
            continue
        if path in manual:
            grade = "current_page_verified"
        elif path in snapshots:
            grade = "partial_route_snapshot"
        else:
            grade = "canonical_only_pending"
        rows.append((index.page_of_path.get(path, "unknown"), path, str(node.get("widget", "control")), grade))
    counts = Counter(row[3] for row in rows)
    lines = [
        "# V1 逐字段证据缺口矩阵（自动生成）",
        "",
        "> 唯一规则源为 `registration-tree.yaml`。本表仅反映脱敏 DFS 账本中已经观察到的字段路径，不能把 `partial_route_snapshot` 当作完整路线验证。",
        "",
        f"- V1 相关 canonical 路径：{len(rows)}",
        f"- `current_page_verified`：{counts['current_page_verified']}",
        f"- `partial_route_snapshot`：{counts['partial_route_snapshot']}",
        f"- `canonical_only_pending`：{counts['canonical_only_pending']}",
        "",
        "| 页面 | canonical 路径 | 控件 | 证据等级 |",
        "| --- | --- | --- | --- |",
    ]
    lines.extend(f"| `{page}` | `{path}` | `{widget}` | `{grade}` |" for page, path, widget, grade in rows)
    lines.extend(
        [
            "",
            "说明：`canonical_only_pending` 不代表字段不存在，只代表本轮尚未取得符合 V1 标准的现场证据。产品注册目的路线已由根范围排除，不纳入本表。",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--canonical", type=Path, default=DEFAULT_CANONICAL)
    parser.add_argument("--ledger", type=Path, default=DEFAULT_LEDGER)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    validated = validate_ledger(args.canonical, args.ledger)
    text = render(validated)
    if args.check:
        pending = sum(
            1
            for line in text.splitlines()
            if line.rstrip().endswith("`canonical_only_pending` |")
        )
        print(f"V1 field coverage matrix check passed: {pending} pending entries")
        return 0
    args.output.write_text(text, encoding="utf-8", newline="\n")
    print("Wrote V1 field coverage matrix")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
