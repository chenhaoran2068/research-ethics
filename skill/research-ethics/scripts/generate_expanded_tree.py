#!/usr/bin/env python3
"""Generate deterministic review artifacts from the canonical atomic YAML.

The only accepted input is ``references/registration-tree.yaml`` next to this
project's ``scripts`` directory.  The default mode writes two generated views:

* ``references/registration-tree-expanded.md``
* ``references/branch-completion-matrix.md``

``--check`` builds both documents in memory, verifies structural coverage and
counts, and performs no filesystem writes.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Iterator, Sequence

import yaml


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CANONICAL_YAML = PROJECT_ROOT / "references" / "registration-tree.yaml"
EXPANDED_OUTPUT = PROJECT_ROOT / "references" / "registration-tree-expanded.md"
MATRIX_OUTPUT = PROJECT_ROOT / "references" / "branch-completion-matrix.md"

NODE_KINDS = {"group", "control", "action"}
NODE_CONTAINER_KEYS = ("nodes", "children")
PRIMARY_NODE_KEYS = (
    "order",
    "path",
    "technical_name",
    "widget",
    "required",
    "required_if",
    "visible_if",
    "enabled_if",
    "value_source",
    "source_classification",
    "repeatable",
    "repeatable_with_parent",
    "minimum_instances",
    "maximum_instances",
    "repeat_behavior",
    "action",
    "target_group",
    "instance_condition",
    "confirmation",
    "verification_status",
    "status",
    "branch_status",
)
ROOT_ROUTE_ID_HINTS = {
    "research-classification",
    "research-type",
    "route-leaf",
    "research-route",
}
DISCLOSURE_ID_HINTS = {
    "other-registry-public-disclosure",
    "sync-platform",
    "public-disclosure",
}


@dataclass
class InventoryCounts:
    pages: int = 0
    active_nodes: int = 0
    candidate_nodes: int = 0
    active_options: int = 0
    candidate_options: int = 0


@dataclass(frozen=True)
class NodeRecord:
    page_id: str
    page_label: str
    path: str
    kind: str
    node: dict[str, Any]
    candidate: bool
    source_index: int


@dataclass
class RenderState:
    counts: InventoryCounts = field(default_factory=InventoryCounts)
    page_ids: list[str] = field(default_factory=list)


@dataclass
class Artifacts:
    expanded: str
    matrix: str
    expected_counts: InventoryCounts
    expanded_counts: InventoryCounts
    expanded_page_ids: list[str]
    matrix_page_ids: list[str]


def scalar_text(value: Any) -> str:
    """Return deterministic, Markdown-safe inline text for a scalar value."""
    if value is True:
        return "是"
    if value is False:
        return "否"
    if value is None:
        return "空"
    return str(value).replace("\r", "").replace("\n", "<br>")


def key_text(key: Any) -> str:
    if key is True:
        return "是"
    if key is False:
        return "否"
    return str(key).replace("_", " ")


def markdown_cell(value: Any) -> str:
    return scalar_text(value).replace("|", "\\|")


def mermaid_text(value: Any) -> str:
    return (
        scalar_text(value)
        .replace("\\", "\\\\")
        .replace('"', "'")
        .replace("[", "（")
        .replace("]", "）")
        .replace("{", "（")
        .replace("}", "）")
    )


def condition_text(value: Any) -> str:
    """Render schema-0.3 conditions without relying on YAML emitter styling."""
    if isinstance(value, dict):
        parts = [f"{key_text(key)}={condition_text(value[key])}" for key in sorted(value, key=str)]
        return "；".join(parts)
    if isinstance(value, list):
        return "[" + "，".join(condition_text(item) for item in value) + "]"
    return scalar_text(value)


def page_nodes(page: dict[str, Any]) -> list[dict[str, Any]]:
    """Return active nodes, with a temporary legacy fallback during migration."""
    raw = page.get("nodes")
    if isinstance(raw, list):
        return [node for node in raw if isinstance(node, dict)]
    legacy = page.get("fields")
    if isinstance(legacy, list):
        return [node for node in legacy if isinstance(node, dict)]
    return []


def candidate_container(page: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    raw = page.get("unverified_candidate_nodes")
    if isinstance(raw, list):
        return {}, [node for node in raw if isinstance(node, dict)]
    if isinstance(raw, dict):
        nodes = raw.get("nodes")
        if not isinstance(nodes, list):
            nodes = []
        meta = {key: value for key, value in raw.items() if key != "nodes"}
        return meta, [node for node in nodes if isinstance(node, dict)]
    return {}, []


def node_children(node: dict[str, Any]) -> list[dict[str, Any]]:
    for key in NODE_CONTAINER_KEYS:
        raw = node.get(key)
        if isinstance(raw, list):
            return [child for child in raw if isinstance(child, dict)]
    return []


def node_kind(node: dict[str, Any]) -> str:
    declared = node.get("kind")
    if declared in NODE_KINDS:
        return str(declared)
    if node_children(node):
        return "group"
    if node.get("action") or str(node.get("id", "")).startswith(("add-", "remove-")):
        return "action"
    return "control"


def node_path(node: dict[str, Any], parent_path: str, index: int) -> str:
    explicit = node.get("path")
    if isinstance(explicit, str) and explicit.strip():
        return explicit.strip()
    node_id = node.get("id")
    segment = str(node_id).strip() if node_id is not None else f"node-{index}"
    return f"{parent_path}.{segment}" if parent_path else segment


def node_options(node: dict[str, Any]) -> list[Any]:
    raw = node.get("options")
    return raw if isinstance(raw, list) else []


def iter_records_for_nodes(
    nodes: Sequence[dict[str, Any]],
    *,
    page_id: str,
    page_label: str,
    parent_path: str,
    candidate: bool,
    start_index: int = 0,
) -> Iterator[NodeRecord]:
    sequence = start_index
    for index, node in enumerate(nodes, start=1):
        path = node_path(node, parent_path, index)
        record = NodeRecord(
            page_id=page_id,
            page_label=page_label,
            path=path,
            kind=node_kind(node),
            node=node,
            candidate=candidate,
            source_index=sequence,
        )
        sequence += 1
        yield record
        children = node_children(node)
        yield from iter_records_for_nodes(
            children,
            page_id=page_id,
            page_label=page_label,
            parent_path=path,
            candidate=candidate,
            start_index=sequence,
        )
        sequence += len(children)


def iter_all_records(pages: Sequence[dict[str, Any]]) -> Iterator[NodeRecord]:
    for page in pages:
        page_id = str(page.get("id", "unnamed-page"))
        page_label = str(page.get("label", page_id))
        yield from iter_records_for_nodes(
            page_nodes(page),
            page_id=page_id,
            page_label=page_label,
            parent_path=page_id,
            candidate=False,
        )
        _, candidates = candidate_container(page)
        yield from iter_records_for_nodes(
            candidates,
            page_id=page_id,
            page_label=page_label,
            parent_path=f"{page_id}.candidate",
            candidate=True,
        )


def inventory_counts(pages: Sequence[dict[str, Any]]) -> InventoryCounts:
    counts = InventoryCounts(pages=len(pages))
    for record in iter_all_records(pages):
        option_count = len(node_options(record.node))
        if record.candidate:
            counts.candidate_nodes += 1
            counts.candidate_options += option_count
        else:
            counts.active_nodes += 1
            counts.active_options += option_count
    return counts


def render_generic(value: Any, *, indent: int, lines: list[str]) -> None:
    prefix = "  " * indent
    if isinstance(value, dict):
        for key in sorted(value, key=str):
            child = value[key]
            label = key_text(key)
            if isinstance(child, (dict, list)):
                lines.append(f"{prefix}- **{label}**")
                render_generic(child, indent=indent + 1, lines=lines)
            else:
                lines.append(f"{prefix}- **{label}**：{scalar_text(child)}")
        return
    if isinstance(value, list):
        for index, child in enumerate(value, start=1):
            if isinstance(child, (dict, list)):
                lines.append(f"{prefix}- **第 {index} 项**")
                render_generic(child, indent=indent + 1, lines=lines)
            else:
                lines.append(f"{prefix}- {scalar_text(child)}")
        return
    lines.append(f"{prefix}- {scalar_text(value)}")


def render_options(
    options: Sequence[Any],
    *,
    indent: int,
    lines: list[str],
    candidate: bool,
    state: RenderState,
) -> None:
    prefix = "  " * indent
    for index, option in enumerate(options, start=1):
        if candidate:
            state.counts.candidate_options += 1
        else:
            state.counts.active_options += 1
        if isinstance(option, dict):
            option_id = option.get("id", f"option-{index}")
            label = option.get("label", option_id)
            lines.append(f"{prefix}- **{scalar_text(label)}** (`{scalar_text(option_id)}`)")
            remainder = {
                key: option[key]
                for key in sorted(option, key=str)
                if key not in {"id", "label"}
            }
            if remainder:
                render_generic(remainder, indent=indent + 1, lines=lines)
        else:
            lines.append(f"{prefix}- **{scalar_text(option)}**")


def render_node(
    node: dict[str, Any],
    *,
    parent_path: str,
    index: int,
    indent: int,
    lines: list[str],
    candidate: bool,
    state: RenderState,
) -> None:
    kind = node_kind(node)
    path = node_path(node, parent_path, index)
    label = node.get("label", node.get("id", f"未命名节点 {index}"))
    node_id = node.get("id", f"node-{index}")
    order = node.get("order", index)
    prefix = "  " * indent
    marker = "候选/不可达/需验证" if candidate else "活动"
    lines.append(
        f"{prefix}- **{scalar_text(order)}. {scalar_text(label)}** "
        f"(`{scalar_text(node_id)}` · `{kind}` · {marker})"
    )

    if candidate:
        state.counts.candidate_nodes += 1
    else:
        state.counts.active_nodes += 1

    detail_prefix = "  " * (indent + 1)
    lines.append(f"{detail_prefix}- **path**：`{path}`")
    for key in PRIMARY_NODE_KEYS:
        if key == "path":
            continue
        if key in node:
            value = node[key]
            if isinstance(value, (dict, list)):
                lines.append(f"{detail_prefix}- **{key_text(key)}**")
                render_generic(value, indent=indent + 2, lines=lines)
            else:
                lines.append(f"{detail_prefix}- **{key_text(key)}**：{scalar_text(value)}")

    options = node_options(node)
    if options:
        lines.append(f"{detail_prefix}- **options（逐项）**")
        render_options(
            options,
            indent=indent + 2,
            lines=lines,
            candidate=candidate,
            state=state,
        )

    excluded = {
        "kind",
        "id",
        "label",
        "options",
        *PRIMARY_NODE_KEYS,
        *NODE_CONTAINER_KEYS,
    }
    remainder = {key: node[key] for key in sorted(node, key=str) if key not in excluded}
    if remainder:
        lines.append(f"{detail_prefix}- **其他结构化规则**")
        render_generic(remainder, indent=indent + 2, lines=lines)

    children = node_children(node)
    if children:
        lines.append(f"{detail_prefix}- **children（逐控件）**")
        for child_index, child in enumerate(children, start=1):
            render_node(
                child,
                parent_path=path,
                index=child_index,
                indent=indent + 2,
                lines=lines,
                candidate=candidate,
                state=state,
            )


def collect_condition_refs(value: Any) -> set[str]:
    refs: set[str] = set()
    if isinstance(value, dict):
        control = value.get("control")
        if isinstance(control, str) and control:
            refs.add(control)
        for child in value.values():
            refs.update(collect_condition_refs(child))
    elif isinstance(value, list):
        for child in value:
            refs.update(collect_condition_refs(child))
    return refs


def node_conditions(node: dict[str, Any]) -> list[tuple[str, Any]]:
    conditions: list[tuple[str, Any]] = []
    for key in ("visible_if", "required", "required_if", "enabled_if"):
        value = node.get(key)
        if isinstance(value, dict):
            conditions.append((key, value))
    return conditions


def is_branch_record(record: NodeRecord, referenced_paths: set[str]) -> bool:
    if record.candidate or record.kind != "control":
        return False
    node = record.node
    branch_status = str(node.get("branch_status", "")).lower()
    dynamic_keys = {
        "branch_effect",
        "option_effect",
        "dynamic_effect",
        "dynamic_effects",
        "observed_effect",
        "content_variant_rules",
    }
    return (
        record.path in referenced_paths
        or "branch" in branch_status
        or bool(dynamic_keys.intersection(node))
    )


def render_mermaid(pages: Sequence[dict[str, Any]], records: Sequence[NodeRecord]) -> list[str]:
    lines = ["```mermaid", "flowchart TD"]
    page_ids: dict[str, str] = {}
    for index, page in enumerate(pages, start=1):
        page_id = str(page.get("id", f"page-{index}"))
        mermaid_id = f"P{index}"
        page_ids[page_id] = mermaid_id
        lines.append(f'  {mermaid_id}["{index}. {mermaid_text(page.get("label", page_id))}"]')
        if index > 1:
            lines.append(f"  P{index - 1} --> P{index}")

    active_records = [record for record in records if not record.candidate]
    referenced_paths: set[str] = set()
    for record in active_records:
        for _, condition in node_conditions(record.node):
            referenced_paths.update(collect_condition_refs(condition))

    relevant_paths = set(referenced_paths)
    for record in active_records:
        if is_branch_record(record, referenced_paths):
            relevant_paths.add(record.path)
        for _, condition in node_conditions(record.node):
            if collect_condition_refs(condition):
                relevant_paths.add(record.path)

    relevant = [record for record in active_records if record.path in relevant_paths]
    record_ids = {record.path: f"B{index}" for index, record in enumerate(relevant, start=1)}
    for record in relevant:
        mermaid_id = record_ids[record.path]
        label = record.node.get("label", record.node.get("id", record.path))
        page_id = page_ids.get(record.page_id)
        lines.append(f'  {mermaid_id}["{mermaid_text(label)}"]')
        if page_id:
            lines.append(f"  {page_id} -.-> {mermaid_id}")

        for option_index, option in enumerate(node_options(record.node), start=1):
            option_id = f"{mermaid_id}O{option_index}"
            option_label = option.get("label", option.get("id")) if isinstance(option, dict) else option
            lines.append(f'  {option_id}["{mermaid_text(option_label)}"]')
            lines.append(f"  {mermaid_id} --> {option_id}")

    edge_seen: set[tuple[str, str, str]] = set()
    for record in relevant:
        target_id = record_ids[record.path]
        for purpose, condition in node_conditions(record.node):
            for source_path in sorted(collect_condition_refs(condition)):
                source_id = record_ids.get(source_path)
                if not source_id:
                    continue
                label = f"{purpose}: {condition_text(condition)}"
                edge = (source_id, target_id, label)
                if edge in edge_seen:
                    continue
                edge_seen.add(edge)
                lines.append(f'  {source_id} -->|"{mermaid_text(label)}"| {target_id}')

    lines.append("```")
    return lines


def render_expanded(data: dict[str, Any], pages: Sequence[dict[str, Any]]) -> tuple[str, RenderState]:
    expected = inventory_counts(pages)
    state = RenderState()
    records = list(iter_all_records(pages))
    lines = [
        "# 医学研究登记完整展开树（生成视图）",
        "",
        "> 唯一输入为 `references/registration-tree.yaml`；本文件不得手工维护。",
        "> 活动节点与候选/不可达/需验证节点严格分区。候选节点不计入当前可见控件树。",
        "",
        "## 覆盖统计",
        "",
        f"- Schema：`{scalar_text(data.get('schema_version'))}`",
        f"- 页面：{expected.pages}",
        f"- 活动节点：{expected.active_nodes}",
        f"- 活动选项：{expected.active_options}",
        f"- 候选/不可达/需验证节点：{expected.candidate_nodes}",
        f"- 候选选项：{expected.candidate_options}",
        "",
        "## 页面索引",
        "",
    ]
    for index, page in enumerate(pages, start=1):
        page_id = str(page.get("id", f"page-{index}"))
        lines.append(f"{index}. [{page.get('label', page_id)}](#page-{index})")

    lines.extend(["", "## 主要条件 DAG", ""])
    lines.extend(render_mermaid(pages, records))

    for page_index, page in enumerate(pages, start=1):
        page_id = str(page.get("id", f"page-{page_index}"))
        page_label = str(page.get("label", page_id))
        state.page_ids.append(page_id)
        state.counts.pages += 1
        lines.extend(
            [
                "",
                f'<a id="page-{page_index}"></a>',
                f"## {page_index}. {page_label} (`{page_id}`)",
                "",
            ]
        )

        page_meta = {
            key: page[key]
            for key in sorted(page, key=str)
            if key not in {"id", "label", "nodes", "fields", "unverified_candidate_nodes"}
        }
        if page_meta:
            lines.extend(["### 页面级规则", ""])
            render_generic(page_meta, indent=0, lines=lines)
            lines.append("")

        lines.extend(["### 活动字段树", ""])
        active = page_nodes(page)
        if not active:
            lines.append("- 无活动节点。")
        for node_index, node in enumerate(active, start=1):
            render_node(
                node,
                parent_path=page_id,
                index=node_index,
                indent=0,
                lines=lines,
                candidate=False,
                state=state,
            )

        candidate_meta, candidates = candidate_container(page)
        lines.extend(["", "### 候选/不可达/需验证节点（不计入活动树）", ""])
        if candidate_meta:
            render_generic(candidate_meta, indent=0, lines=lines)
        if not candidates:
            lines.append("- 无。")
        for node_index, node in enumerate(candidates, start=1):
            render_node(
                node,
                parent_path=f"{page_id}.candidate",
                index=node_index,
                indent=0,
                lines=lines,
                candidate=True,
                state=state,
            )

    lines.extend(
        [
            "",
            "## 生成覆盖校验",
            "",
            f"- 活动节点：{state.counts.active_nodes} / {expected.active_nodes}",
            f"- 活动选项：{state.counts.active_options} / {expected.active_options}",
            f"- 候选节点：{state.counts.candidate_nodes} / {expected.candidate_nodes}",
            f"- 候选选项：{state.counts.candidate_options} / {expected.candidate_options}",
            "",
        ]
    )
    return "\n".join(lines), state


def option_label(option: Any, index: int) -> tuple[str, str]:
    if isinstance(option, dict):
        option_id = str(option.get("id", f"option-{index}"))
        return option_id, str(option.get("label", option_id))
    return str(option), str(option)


def status_for(
    node: dict[str, Any],
    fallback: dict[str, Any] | None = None,
    *,
    candidate: bool = False,
) -> str:
    parts = []
    for key in ("verification_status", "status", "branch_status"):
        if node.get(key) is not None:
            parts.append(f"{key_text(key)}={condition_text(node[key])}")
    if parts:
        return "；".join(parts)

    source_node = fallback if fallback is not None else node
    source = condition_text(source_node.get("source_classification", "")).lower()
    if candidate:
        return "候选/不可达；原因已记录且未计入已验证活动树"
    if source_node.get("enabled") is False or "disabled" in source:
        return "禁用/不可达"
    if "needs_live_verification" in source:
        return "结构已记录；具体长字典值不在声明范围内"
    if "live_verified" in source or "runtime" in source:
        return "实时已验证"
    if "derived_internal_control" in source:
        return "由已验证控制项机械派生"
    if any(token in source for token in ("code_and_existing_yaml", "source_inventory", "static_template")):
        return "实时页面或当前加载源码已验证"
    return "活动规则已纳入条件覆盖"


def source_for(node: dict[str, Any]) -> str:
    parts = []
    for key in ("source_classification", "value_source"):
        if node.get(key) is not None:
            parts.append(f"{key_text(key)}={condition_text(node[key])}")
    return "；".join(parts) if parts else "未标注"


def boundary_for(node: dict[str, Any]) -> str:
    keys = (
        "visible_if",
        "required_if",
        "enabled_if",
        "verification_boundary",
        "unverified_reason",
        "boundary",
        "caveat",
        "availability",
        "scope",
        "attachment_boundary",
    )
    parts = []
    for key in keys:
        if node.get(key) not in (None, True):
            parts.append(f"{key_text(key)}={condition_text(node[key])}")
    return "；".join(parts) if parts else "无额外边界"


def render_table(headers: Sequence[str], rows: Sequence[Sequence[Any]]) -> list[str]:
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(markdown_cell(value) for value in row) + " |")
    if not rows:
        lines.append("| " + " | ".join(["无"] + [""] * (len(headers) - 1)) + " |")
    return lines


def root_route_rows(pages: Sequence[dict[str, Any]], records: Sequence[NodeRecord]) -> list[list[Any]]:
    rows: list[list[Any]] = []
    seen: set[tuple[str, str]] = set()
    for record in records:
        if record.candidate or record.kind != "control":
            continue
        node_id = str(record.node.get("id", ""))
        label = str(record.node.get("label", ""))
        if node_id not in ROOT_ROUTE_ID_HINTS and label != "研究分类":
            continue
        for index, option in enumerate(node_options(record.node), start=1):
            option_id, label_text = option_label(option, index)
            key = (record.path, option_id)
            if key in seen:
                continue
            seen.add(key)
            option_node = option if isinstance(option, dict) else record.node
            rows.append(
                [
                    record.page_label,
                    record.path,
                    label_text,
                    status_for(option_node, record.node),
                    source_for(record.node),
                    boundary_for(option_node),
                ]
            )

    if rows:
        return rows

    # Transitional fallback for the pre-atomic canonical map.
    first_page = pages[0] if pages else {}
    for value in walk_values(first_page):
        if not isinstance(value, dict) or not isinstance(value.get("branch_routes"), list):
            continue
        for route in value["branch_routes"]:
            if not isinstance(route, dict):
                continue
            rows.append(
                [
                    str(first_page.get("label", "研究类别")),
                    str(route.get("id", "legacy-route")),
                    str(route.get("label", route.get("id", "未命名路线"))),
                    status_for(route),
                    source_for(route),
                    boundary_for(route),
                ]
            )
        break
    return rows


def disclosure_rows(records: Sequence[NodeRecord]) -> list[list[Any]]:
    rows: list[list[Any]] = []
    for record in records:
        if record.candidate or record.kind != "control":
            continue
        node_id = str(record.node.get("id", ""))
        label = str(record.node.get("label", ""))
        technical = str(record.node.get("technical_name", ""))
        if not (
            node_id in DISCLOSURE_ID_HINTS
            or "其他研究注册平台公开" in label
            or technical in {"syncPlatform", "registrationStatus"}
        ):
            continue
        options = node_options(record.node) or ["无枚举选项"]
        for index, option in enumerate(options, start=1):
            _, label_text = option_label(option, index)
            option_node = option if isinstance(option, dict) else record.node
            rows.append(
                [
                    record.page_label,
                    record.path,
                    label_text,
                    status_for(option_node, record.node),
                    source_for(record.node),
                    boundary_for(option_node),
                ]
            )
    return rows


def dynamic_branch_rows(records: Sequence[NodeRecord]) -> list[list[Any]]:
    active = [record for record in records if not record.candidate]
    refs: set[str] = set()
    for record in active:
        for _, condition in node_conditions(record.node):
            refs.update(collect_condition_refs(condition))

    excluded_paths = {
        record.path
        for record in active
        if str(record.node.get("id", "")) in ROOT_ROUTE_ID_HINTS | DISCLOSURE_ID_HINTS
        or "其他研究注册平台公开" in str(record.node.get("label", ""))
    }
    rows: list[list[Any]] = []
    for record in active:
        if record.path in excluded_paths or not is_branch_record(record, refs):
            continue
        options = node_options(record.node) or ["条件节点"]
        for index, option in enumerate(options, start=1):
            _, label_text = option_label(option, index)
            option_node = option if isinstance(option, dict) else record.node
            rows.append(
                [
                    record.page_label,
                    record.path,
                    label_text,
                    status_for(record.node),
                    source_for(record.node),
                    boundary_for(option_node),
                ]
            )
    return rows


def candidate_rows(records: Sequence[NodeRecord]) -> list[list[Any]]:
    rows: list[list[Any]] = []
    for record in records:
        if not record.candidate:
            continue
        rows.append(
            [
                record.page_label,
                record.path,
                record.node.get("label", record.node.get("id", "候选节点")),
                status_for(record.node, candidate=True),
                source_for(record.node),
                "候选/不可达/需验证；不计入活动树；" + boundary_for(record.node),
            ]
        )
    return rows


def walk_values(value: Any) -> Iterable[Any]:
    yield value
    if isinstance(value, dict):
        for key in sorted(value, key=str):
            yield from walk_values(value[key])
    elif isinstance(value, list):
        for child in value:
            yield from walk_values(child)


def render_matrix(data: dict[str, Any], pages: Sequence[dict[str, Any]]) -> tuple[str, list[str]]:
    records = list(iter_all_records(pages))
    counts = inventory_counts(pages)
    page_ids: list[str] = []
    page_rows: list[list[Any]] = []
    for index, page in enumerate(pages, start=1):
        page_id = str(page.get("id", f"page-{index}"))
        page_ids.append(page_id)
        page_records = [record for record in records if record.page_id == page_id]
        candidate_count = sum(record.candidate for record in page_records)
        page_rows.append(
            [
                index,
                page.get("label", page_id),
                page_id,
                sum(not record.candidate for record in page_records),
                candidate_count,
                page.get(
                    "status",
                    page.get(
                        "verification_status",
                        "活动结构在声明范围内完成；候选项另表隔离"
                        if candidate_count
                        else "声明范围内完成",
                    ),
                ),
            ]
        )

    headers = ["页面", "节点路径", "选择/路线", "状态", "来源", "边界"]
    lines = [
        "# 医学研究登记分支完成矩阵（生成视图）",
        "",
        "> 唯一输入为 `references/registration-tree.yaml`。候选/不可达/需验证节点与活动节点分开统计。",
        "",
        "## 汇总",
        "",
        f"- 页面：{counts.pages}",
        f"- 活动节点/选项：{counts.active_nodes} / {counts.active_options}",
        f"- 候选节点/选项：{counts.candidate_nodes} / {counts.candidate_options}",
        "",
        "## 页面覆盖",
        "",
    ]
    lines.extend(render_table(["顺序", "页面", "页面 ID", "活动节点", "候选节点", "页面状态"], page_rows))

    sections = (
        ("根研究路线", root_route_rows(pages, records)),
        ("公开策略", disclosure_rows(records)),
        ("关键动态分支", dynamic_branch_rows(records)),
        ("候选/不可达/需验证", candidate_rows(records)),
    )
    for title, rows in sections:
        lines.extend(["", f"## {title}", ""])
        lines.extend(render_table(headers, rows))

    lines.append("")
    return "\n".join(lines), page_ids


def ordered_pages(data: dict[str, Any]) -> list[dict[str, Any]]:
    workflow = data.get("workflow")
    if not isinstance(workflow, dict) or not isinstance(workflow.get("pages"), list):
        raise ValueError("canonical YAML must contain workflow.pages as a list")
    pages = [page for page in workflow["pages"] if isinstance(page, dict)]
    if len(pages) != len(workflow["pages"]):
        raise ValueError("every workflow.pages item must be a mapping")
    return pages


def build_artifacts(data: dict[str, Any]) -> Artifacts:
    schema_version = str(data.get("schema_version", ""))
    if not schema_version.startswith("0.3"):
        raise ValueError(f"expected schema 0.3 atomic canonical, found {schema_version!r}")
    pages = ordered_pages(data)
    expected = inventory_counts(pages)
    expanded, expanded_state = render_expanded(data, pages)
    matrix, matrix_page_ids = render_matrix(data, pages)
    return Artifacts(
        expanded=expanded,
        matrix=matrix,
        expected_counts=expected,
        expanded_counts=expanded_state.counts,
        expanded_page_ids=expanded_state.page_ids,
        matrix_page_ids=matrix_page_ids,
    )


def validate_artifacts(artifacts: Artifacts) -> None:
    errors: list[str] = []
    if not artifacts.expanded.strip():
        errors.append("expanded document is empty")
    if not artifacts.matrix.strip():
        errors.append("branch matrix is empty")
    if not artifacts.expanded_page_ids:
        errors.append("no pages were rendered")
    if artifacts.expanded_page_ids != artifacts.matrix_page_ids:
        errors.append(
            "page coverage mismatch between expanded tree and matrix: "
            f"expanded={artifacts.expanded_page_ids!r}, matrix={artifacts.matrix_page_ids!r}"
        )

    expected = artifacts.expected_counts
    rendered = artifacts.expanded_counts
    for key in (
        "pages",
        "active_nodes",
        "candidate_nodes",
        "active_options",
        "candidate_options",
    ):
        expected_value = getattr(expected, key)
        rendered_value = getattr(rendered, key)
        if expected_value != rendered_value:
            errors.append(f"{key} mismatch: expected={expected_value}, rendered={rendered_value}")

    if errors:
        raise RuntimeError("artifact validation failed:\n- " + "\n- ".join(errors))


def load_canonical() -> dict[str, Any]:
    data = yaml.safe_load(CANONICAL_YAML.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"canonical YAML must be a mapping: {CANONICAL_YAML}")
    return data


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="build and validate both artifacts in memory without writing files",
    )
    args = parser.parse_args()

    artifacts = build_artifacts(load_canonical())
    validate_artifacts(artifacts)
    counts = artifacts.expected_counts

    if args.check:
        print(
            "Expanded artifact check passed: "
            f"pages={counts.pages}, active_nodes={counts.active_nodes}, "
            f"active_options={counts.active_options}, candidate_nodes={counts.candidate_nodes}, "
            f"candidate_options={counts.candidate_options}; no files written"
        )
        return 0

    EXPANDED_OUTPUT.write_text(artifacts.expanded.rstrip() + "\n", encoding="utf-8")
    MATRIX_OUTPUT.write_text(artifacts.matrix.rstrip() + "\n", encoding="utf-8")
    # Printing the full path can fail in Windows terminals whose active code page
    # cannot encode every character in the workspace path. The files are already
    # resolved above, so a stable filename is sufficient for the CLI receipt.
    print(f"Wrote {EXPANDED_OUTPUT.name}")
    print(f"Wrote {MATRIX_OUTPUT.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
