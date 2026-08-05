#!/usr/bin/env python3
"""Generate a de-identified *candidate* DFS queue for V1 live verification.

The canonical YAML remains the only rule source.  This script merely finds
controls referenced by conditional visibility rules on pages that can occur in
the researcher-initiated V1 scope.  It deliberately does not assert that any
candidate is live-verified or that every listed option is structural.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable

import yaml


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CANONICAL = PROJECT_ROOT / "references" / "registration-tree.yaml"
DEFAULT_OUTPUT = PROJECT_ROOT / "references" / "v1-dfs-candidate-queue.md"
V1_ROOTS = {"investigator-observational"}
ROOT_PATH = "research-category.route-leaf"
HIGH_RISK_DRIVERS = {
    "research-category.route-leaf",
    "research-category.diagnostic-trial",
    "basic-information.sync-platform",
    "implementation-information.multicenter-flag",
    "recruitment-information.recruitment-flag",
    "recruitment-information.recruitment-status",
    "data-sharing-and-public-disclosure.data-share-statement",
}


def children(node: dict[str, Any]) -> Iterable[dict[str, Any]]:
    for key in ("nodes", "children"):
        value = node.get(key)
        if isinstance(value, list):
            yield from (item for item in value if isinstance(item, dict))


def conditions(expression: Any) -> Iterable[dict[str, Any]]:
    if not isinstance(expression, dict):
        return
    if isinstance(expression.get("control"), str):
        yield expression
    for key in ("all", "any"):
        items = expression.get(key)
        if isinstance(items, list):
            for item in items:
                yield from conditions(item)


def possible_in_v1(items: Iterable[dict[str, Any]]) -> bool:
    """Reject only branches explicitly limited to non-V1 root routes."""
    root_constraints = [item for item in items if item.get("control") == ROOT_PATH]
    for item in root_constraints:
        if "equals" in item and str(item["equals"]) not in V1_ROOTS:
            return False
        if "in" in item and isinstance(item["in"], list) and not (set(map(str, item["in"])) & V1_ROOTS):
            return False
    return True


def node_path(node: dict[str, Any], parent: str, position: int) -> str:
    return str(node.get("path") or f"{parent}.{node.get('id', f'node-{position}')}")


def collect(canonical: dict[str, Any]) -> list[tuple[str, str, str, str, str]]:
    pages = canonical.get("workflow", {}).get("pages", [])
    pending: dict[tuple[str, str], set[str]] = defaultdict(set)
    # Root controls must be explicitly scheduled even when their effects are
    # page-sequence choices rather than ordinary visible_if dependents.
    pending[("research-category", "research-category.route-leaf")].add("V1 scope entrance and downstream page sequence")
    pending[("research-category", "research-category.diagnostic-trial")].add(
        "research-design.diagnostic-measures and downstream route comparison"
    )
    pending[("research-category", "research-category.tcm-guided")].add("downstream structure spot check")
    pending[("research-category", "research-category.invasive-bci")].add("downstream structure spot check")
    for page in pages if isinstance(pages, list) else []:
        if not isinstance(page, dict) or not isinstance(page.get("id"), str):
            continue
        page_id = page["id"]

        def visit(
            node: dict[str, Any], parent: str, position: int, inherited_conditions: tuple[dict[str, Any], ...] = ()
        ) -> None:
            path = node_path(node, parent, position)
            own_conditions = tuple(conditions(node.get("visible_if")))
            effective_conditions = inherited_conditions + own_conditions
            if possible_in_v1(effective_conditions):
                for item in effective_conditions:
                    control = item.get("control")
                    if isinstance(control, str):
                        # Root choice is recorded separately as the scope entrance.
                        if control != ROOT_PATH:
                            pending[(page_id, control)].add(path)
            for child_position, child in enumerate(children(node), start=1):
                visit(child, path, child_position, effective_conditions)

        for position, node in enumerate(page.get("nodes", []), start=1):
            if isinstance(node, dict):
                visit(node, page_id, position)
    rows = []
    for (page_id, driver), dependents in pending.items():
        priority = "high_risk_deeper_check_required" if driver in HIGH_RISK_DRIVERS else "current_page_compare_first"
        rows.append((page_id, driver, ", ".join(sorted(dependents)), priority, "pending_live_verification"))
    return sorted(rows, key=lambda row: (row[3] != "high_risk_deeper_check_required", row[0], row[1]))


def render(rows: list[tuple[str, str, str, str, str]]) -> str:
    lines = [
        "# V1 DFS 候选队列（自动生成）",
        "",
        "> 此文件从 `registration-tree.yaml` 的条件规则机械生成，只用于安排现场核验顺序。",
        "> 它不证明任何字段已现场验证，也不把候选条件自动认定为结构分支。",
        "",
        "根范围：`investigator-interventional`、`investigator-observational`（含诊断试验是／否）。",
        "产品注册路线不在此队列内，维持 `deferred_to_v2`。",
        "",
        "| 页面 | 候选驱动控件 | 可能受影响的 canonical 路径 | 核验优先级 | 状态 |",
        "| --- | --- | --- | --- | --- |",
    ]
    lines.extend(
        f"| `{page}` | `{driver}` | `{dependents}` | `{priority}` | `{status}` |"
        for page, driver, dependents, priority, status in rows
    )
    lines += [
        "",
        "现场使用规则：每个候选选项均须经正常 UI 切换和后续页面比较；只有确认字段结构发生变化，才写入 DFS 账本的 `structural_branches`。",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--canonical", type=Path, default=DEFAULT_CANONICAL)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    loader = getattr(yaml, "CSafeLoader", yaml.SafeLoader)
    with args.canonical.open("r", encoding="utf-8") as handle:
        canonical = yaml.load(handle, Loader=loader)
    if not isinstance(canonical, dict):
        raise SystemExit("canonical YAML root must be a mapping")
    text = render(collect(canonical))
    if args.check:
        print(f"V1 candidate queue check passed: {text.count('`pending_live_verification`')} candidate rows")
        return 0
    args.output.write_text(text, encoding="utf-8", newline="\n")
    print("Wrote generated V1 candidate queue")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
