#!/usr/bin/env python3
"""Generate the complete interactive registration tree from the canonical YAML."""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Iterable

import yaml

from generate_expanded_tree import inventory_counts, ordered_pages


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CANONICAL = PROJECT_ROOT / "references" / "registration-tree.yaml"
MAX_FRAGMENT_BYTES = 2 * 1024 * 1024
CHILD_KEYS = ("nodes", "children")
OMITTED_NODE_KEYS = {"id", "label", "kind", "path", "nodes", "children", "options", "options_by_parent"}


def option_record(value: Any, index: int) -> dict[str, Any]:
    if isinstance(value, dict):
        option_id = str(value.get("id", value.get("value", f"option-{index}")))
        label = str(value.get("label", value.get("name", option_id)))
        meta = {key: item for key, item in value.items() if key not in {"id", "label", "name", "value"}}
        return {"id": option_id, "label": label, "meta": meta}
    return {"id": str(value), "label": str(value), "meta": {}}


def node_children(node: dict[str, Any]) -> Iterable[dict[str, Any]]:
    seen: set[int] = set()
    for key in CHILD_KEYS:
        value = node.get(key)
        if not isinstance(value, list):
            continue
        for child in value:
            if isinstance(child, dict) and id(child) not in seen:
                seen.add(id(child))
                yield child


def serialize_node(
    node: dict[str, Any],
    *,
    parent_path: str,
    candidate: bool,
    sequence: list[int],
) -> dict[str, Any]:
    node_id = str(node.get("id", f"node-{sequence[0] + 1}"))
    path = str(node.get("path") or f"{parent_path}.{node_id}")
    sequence[0] += 1
    record: dict[str, Any] = {
        "uid": f"n{sequence[0]}",
        "id": node_id,
        "path": path,
        "label": str(node.get("label", node_id)),
        "kind": str(node.get("kind", "control")),
        "candidate": candidate,
        "meta": {key: value for key, value in node.items() if key not in OMITTED_NODE_KEYS},
        "options": [],
        "optionGroups": [],
        "children": [],
        "affects": [],
    }
    options = node.get("options")
    if isinstance(options, list):
        record["options"] = [option_record(option, index) for index, option in enumerate(options, start=1)]
    option_groups = node.get("options_by_parent")
    if isinstance(option_groups, dict):
        for parent, values in option_groups.items():
            group_options = values if isinstance(values, list) else [values]
            record["optionGroups"].append(
                {
                    "parent": str(parent),
                    "options": [option_record(option, index) for index, option in enumerate(group_options, start=1)],
                }
            )
    record["children"] = [
        serialize_node(child, parent_path=path, candidate=candidate, sequence=sequence)
        for child in node_children(node)
    ]
    return record


def collect_control_refs(value: Any) -> set[str]:
    refs: set[str] = set()
    if isinstance(value, dict):
        control = value.get("control")
        if isinstance(control, str):
            refs.add(control)
        for child in value.values():
            refs.update(collect_control_refs(child))
    elif isinstance(value, list):
        for child in value:
            refs.update(collect_control_refs(child))
    return refs


def walk_serialized(nodes: Iterable[dict[str, Any]]) -> Iterable[dict[str, Any]]:
    for node in nodes:
        yield node
        yield from walk_serialized(node["children"])


def build_data(document: dict[str, Any]) -> dict[str, Any]:
    pages = ordered_pages(document)
    counts = inventory_counts(pages)
    sequence = [0]
    serialized_pages: list[dict[str, Any]] = []
    all_nodes: list[dict[str, Any]] = []

    for page in pages:
        page_id = str(page.get("id"))
        active_nodes = [
            serialize_node(node, parent_path=page_id, candidate=False, sequence=sequence)
            for node in page.get("nodes", [])
            if isinstance(node, dict)
        ]
        candidate_container = page.get("unverified_candidate_nodes")
        candidate_nodes: list[dict[str, Any]] = []
        candidate_meta: dict[str, Any] = {}
        if isinstance(candidate_container, dict):
            candidate_meta = {key: value for key, value in candidate_container.items() if key != "nodes"}
            candidate_nodes = [
                serialize_node(node, parent_path=f"{page_id}.candidate", candidate=True, sequence=sequence)
                for node in candidate_container.get("nodes", [])
                if isinstance(node, dict)
            ]
        page_meta = {
            key: value
            for key, value in page.items()
            if key not in {"id", "label", "nodes", "fields", "unverified_candidate_nodes"}
        }
        page_record = {
            "id": page_id,
            "label": str(page.get("label", page_id)),
            "order": page.get("order"),
            "visibleIf": page.get("visible_if", True),
            "meta": page_meta,
            "active": active_nodes,
            "candidate": candidate_nodes,
            "candidateMeta": candidate_meta,
        }
        serialized_pages.append(page_record)
        all_nodes.extend(walk_serialized(active_nodes))
        all_nodes.extend(walk_serialized(candidate_nodes))

    path_index: dict[str, list[dict[str, Any]]] = {}
    for node in all_nodes:
        path_index.setdefault(node["path"], []).append(node)
    for target in all_nodes:
        refs = collect_control_refs(target["meta"])
        derived_from = target["meta"].get("derived_from")
        if isinstance(derived_from, list):
            refs.update(str(item) for item in derived_from)
        for source_path in refs:
            for source in path_index.get(source_path, []):
                source["affects"].append(
                    {"path": target["path"], "label": target["label"], "candidate": target["candidate"]}
                )
    for node in all_nodes:
        unique: dict[tuple[str, str], dict[str, Any]] = {}
        for effect in node["affects"]:
            unique[(effect["path"], effect["label"])] = effect
        node["affects"] = list(unique.values())

    grouped_active_options = sum(
        len(group["options"])
        for node in all_nodes
        if not node["candidate"]
        for group in node["optionGroups"]
    )
    grouped_candidate_options = sum(
        len(group["options"])
        for node in all_nodes
        if node["candidate"]
        for group in node["optionGroups"]
    )

    route_options: list[dict[str, str]] = []
    for node in all_nodes:
        if node["path"] == "research-category.route-leaf":
            route_options = [{"id": item["id"], "label": item["label"]} for item in node["options"]]
            break

    return {
        "schemaVersion": str(document.get("schema_version")),
        "status": str(document.get("status")),
        "counts": {
            "pages": counts.pages,
            "activeNodes": counts.active_nodes,
            "activeOptions": counts.active_options,
            "candidateNodes": counts.candidate_nodes,
            "candidateOptions": counts.candidate_options,
            "groupedActiveOptions": grouped_active_options,
            "groupedCandidateOptions": grouped_candidate_options,
        },
        "routes": route_options,
        "pages": serialized_pages,
    }


FRAGMENT_TEMPLATE = r'''
<div id="research-ethics-complete-tree">
  <div class="viz-controls" aria-label="完整登记树筛选器">
    <label class="form-label" for="re-tree-search">搜索
      <input id="re-tree-search" class="form-control" type="search" placeholder="字段、技术名、路径或规则">
    </label>
    <label class="form-label" for="re-tree-route">研究路线
      <select id="re-tree-route" class="form-select"></select>
    </label>
    <label class="form-label" for="re-tree-page">页面
      <select id="re-tree-page" class="form-select"></select>
    </label>
    <label class="form-label" for="re-tree-scope">范围
      <select id="re-tree-scope" class="form-select">
        <option value="all">活动 + 候选</option>
        <option value="active">仅活动节点</option>
        <option value="candidate">仅候选/不可达</option>
      </select>
    </label>
  </div>
  <div class="viz-row re-tree-actions">
    <button type="button" class="btn btn-primary" id="re-tree-expand">全部展开</button>
    <button type="button" class="btn" id="re-tree-collapse">全部折叠</button>
    <button type="button" class="btn btn-ghost" id="re-tree-reset">重置筛选</button>
  </div>
  <div class="re-tree-summary" id="re-tree-summary" aria-live="polite"></div>
  <div class="viz-row re-tree-legend" aria-label="图例">
    <span><span class="re-shape">◆</span> 字段组</span>
    <span><span class="re-shape">●</span> 控件</span>
    <span><span class="re-shape">↻</span> 操作</span>
    <span><span class="re-shape">○</span> 选项</span>
    <span class="viz-badge">候选/不可达</span>
  </div>
  <div id="re-tree-view" class="re-tree-view"></div>
  <p id="re-tree-empty" class="text-muted" hidden>没有符合当前筛选条件的节点。</p>
</div>

<style>
  #research-ethics-complete-tree {
    color: var(--foreground);
    width: 100%;
  }
  #research-ethics-complete-tree .re-tree-actions {
    margin-block: 0.75rem;
  }
  #research-ethics-complete-tree .re-tree-summary {
    margin-block: 0.5rem;
    color: var(--muted-foreground);
  }
  #research-ethics-complete-tree .re-tree-legend {
    margin-block: 0.5rem 0.9rem;
    color: var(--muted-foreground);
  }
  #research-ethics-complete-tree .re-shape {
    color: var(--viz-series-1);
  }
  #research-ethics-complete-tree .re-page,
  #research-ethics-complete-tree .re-candidate-section,
  #research-ethics-complete-tree .re-node {
    margin-block: 0.25rem;
  }
  #research-ethics-complete-tree .re-page > summary,
  #research-ethics-complete-tree .re-candidate-section > summary,
  #research-ethics-complete-tree .re-node > summary {
    cursor: pointer;
    padding: 0.4rem 0.5rem;
    border-radius: 0.35rem;
  }
  #research-ethics-complete-tree .re-page > summary {
    background: color-mix(in srgb, var(--viz-series-1) 10%, transparent);
  }
  #research-ethics-complete-tree .re-candidate-section > summary,
  #research-ethics-complete-tree .re-node.is-candidate > summary {
    background: color-mix(in srgb, var(--viz-series-5) 10%, transparent);
  }
  #research-ethics-complete-tree .re-node > summary:hover {
    background: var(--accent);
    color: var(--accent-foreground);
  }
  #research-ethics-complete-tree .re-tree-list,
  #research-ethics-complete-tree .re-option-list {
    list-style: none;
    margin: 0.2rem 0 0.5rem 0.8rem;
    padding-left: 1rem;
    border-left: 1px solid var(--border);
  }
  #research-ethics-complete-tree .re-tree-list > li,
  #research-ethics-complete-tree .re-option-list > li {
    position: relative;
  }
  #research-ethics-complete-tree .re-tree-list > li::before,
  #research-ethics-complete-tree .re-option-list > li::before {
    content: "";
    position: absolute;
    left: -1rem;
    top: 1.05rem;
    width: 0.75rem;
    border-top: 1px solid var(--border);
  }
  #research-ethics-complete-tree .re-page-label,
  #research-ethics-complete-tree .re-node-label {
    font-weight: 500;
  }
  #research-ethics-complete-tree .re-path {
    margin-left: 0.45rem;
    color: var(--muted-foreground);
    overflow-wrap: anywhere;
  }
  #research-ethics-complete-tree .re-inline-meta {
    margin-left: 0.45rem;
    color: var(--muted-foreground);
  }
  #research-ethics-complete-tree .re-detail {
    margin: 0.35rem 0 0.65rem 1.4rem;
  }
  #research-ethics-complete-tree .re-meta-grid {
    display: grid;
    grid-template-columns: minmax(7rem, 0.3fr) minmax(0, 1fr);
    gap: 0.25rem 0.75rem;
    margin-block: 0.4rem;
  }
  #research-ethics-complete-tree .re-meta-grid dt {
    color: var(--muted-foreground);
  }
  #research-ethics-complete-tree .re-meta-grid dd {
    margin: 0;
    overflow-wrap: anywhere;
    white-space: pre-wrap;
  }
  #research-ethics-complete-tree .re-option {
    padding: 0.3rem 0.45rem;
  }
  #research-ethics-complete-tree .re-option-parent {
    margin-block: 0.35rem;
  }
  #research-ethics-complete-tree .re-option-parent > summary {
    cursor: pointer;
    color: var(--muted-foreground);
  }
  #research-ethics-complete-tree .re-effects {
    margin-block: 0.5rem;
    padding-left: 1.2rem;
  }
  #research-ethics-complete-tree .re-match > details > summary,
  #research-ethics-complete-tree details.re-match > summary {
    background: color-mix(in srgb, var(--viz-series-2) 16%, transparent);
  }
  #research-ethics-complete-tree code {
    overflow-wrap: anywhere;
  }
  @media (max-width: 520px) {
    #research-ethics-complete-tree .re-meta-grid {
      grid-template-columns: 1fr;
      gap: 0.1rem;
    }
    #research-ethics-complete-tree .re-meta-grid dd {
      margin-bottom: 0.35rem;
    }
    #research-ethics-complete-tree .re-tree-list,
    #research-ethics-complete-tree .re-option-list {
      margin-left: 0.25rem;
      padding-left: 0.65rem;
    }
  }
</style>

<script>
(() => {
  const DATA = __TREE_DATA__;
  const root = document.getElementById('research-ethics-complete-tree');
  const searchInput = root.querySelector('#re-tree-search');
  const routeSelect = root.querySelector('#re-tree-route');
  const pageSelect = root.querySelector('#re-tree-page');
  const scopeSelect = root.querySelector('#re-tree-scope');
  const treeView = root.querySelector('#re-tree-view');
  const summary = root.querySelector('#re-tree-summary');
  const empty = root.querySelector('#re-tree-empty');
  let expansion = 'default';

  const keyLabels = {
    order: '显示顺序', technical_name: '技术字段名', widget: '控件类型', required: '必填',
    required_if: '必填条件', visible_if: '出现条件', enabled_if: '启用条件', value_source: '内容来源',
    source_classification: '证据分类', verification_status: '验证状态', status: '状态',
    repeatable: '可重复填写', repeat_behavior: '重复结构', minimum_instances: '最少项目数',
    maximum_instances: '最多项目数', user_copyable: '用户可复制', candidate_reason: '候选原因',
    candidate_parent_path: '候选父路径', derived_from: '派生自', needs_live_verification: '需要现场验证'
  };
  const state = { search: '', route: 'all', page: 'all', scope: 'all' };

  function make(tag, className, text) {
    const element = document.createElement(tag);
    if (className) element.className = className;
    if (text !== undefined) element.textContent = text;
    return element;
  }

  function plain(value) {
    if (value === true) return '是';
    if (value === false) return '否';
    if (value === null || value === undefined) return '—';
    if (Array.isArray(value)) return value.map(plain).join('；');
    if (typeof value !== 'object') return String(value);
    if (value.all) return `全部满足：${value.all.map(plain).join('；')}`;
    if (value.any) return `任一满足：${value.any.map(plain).join('；')}`;
    if (value.not) return `不满足（${plain(value.not)}）`;
    if (value.control) {
      const tests = [];
      if (Object.prototype.hasOwnProperty.call(value, 'equals')) tests.push(`等于 ${plain(value.equals)}`);
      if (Object.prototype.hasOwnProperty.call(value, 'not_equals')) tests.push(`不等于 ${plain(value.not_equals)}`);
      if (Object.prototype.hasOwnProperty.call(value, 'in')) tests.push(`属于 [${plain(value.in)}]`);
      if (Object.prototype.hasOwnProperty.call(value, 'not_in')) tests.push(`不属于 [${plain(value.not_in)}]`);
      return `${value.control} ${tests.join('，')}`.trim();
    }
    return Object.entries(value).map(([key, item]) => `${keyLabels[key] || key}：${plain(item)}`).join('；');
  }

  function tri(condition, route) {
    if (route === 'all' || condition === undefined || condition === null) return [true, true];
    if (condition === true) return [true, false];
    if (condition === false) return [false, true];
    if (Array.isArray(condition)) {
      const values = condition.map(item => tri(item, route));
      return [values.every(item => item[0]), values.some(item => item[1])];
    }
    if (typeof condition !== 'object') return [true, true];
    if (condition.all) {
      const values = condition.all.map(item => tri(item, route));
      return [values.every(item => item[0]), values.some(item => item[1])];
    }
    if (condition.any) {
      const values = condition.any.map(item => tri(item, route));
      return [values.some(item => item[0]), values.every(item => item[1])];
    }
    if (condition.not) {
      const value = tri(condition.not, route);
      return [value[1], value[0]];
    }
    if (condition.control !== 'research-category.route-leaf') return [true, true];
    let result = true;
    if (Object.prototype.hasOwnProperty.call(condition, 'equals')) result = result && route === String(condition.equals);
    if (Object.prototype.hasOwnProperty.call(condition, 'not_equals')) result = result && route !== String(condition.not_equals);
    if (Object.prototype.hasOwnProperty.call(condition, 'in')) result = result && condition.in.map(String).includes(route);
    if (Object.prototype.hasOwnProperty.call(condition, 'not_in')) result = result && !condition.not_in.map(String).includes(route);
    return [result, !result];
  }

  function possible(condition) {
    return tri(condition, state.route)[0];
  }

  function allOptionText(node) {
    const direct = node.options.flatMap(option => [option.id, option.label, plain(option.meta)]);
    const grouped = node.optionGroups.flatMap(group => [group.parent, ...group.options.flatMap(option => [option.id, option.label, plain(option.meta)])]);
    return direct.concat(grouped).join(' ');
  }

  function nodeSearchText(node) {
    return [node.id, node.path, node.label, node.kind, plain(node.meta), allOptionText(node), ...node.affects.flatMap(item => [item.path, item.label])]
      .join(' ').toLocaleLowerCase('zh-CN');
  }

  function scopeAllows(candidate) {
    return state.scope === 'all' || (state.scope === 'candidate' ? candidate : !candidate);
  }

  function filteredNode(node) {
    if (!scopeAllows(node.candidate) || !possible(node.meta.visible_if)) return null;
    const children = node.children.map(filteredNode).filter(Boolean);
    const ownMatch = !state.search || nodeSearchText(node).includes(state.search);
    if (state.search && !ownMatch && children.length === 0) return null;
    return { ...node, children, ownMatch };
  }

  function addMeta(container, meta, extraRows = []) {
    const entries = Object.entries(meta || {}).filter(([, value]) => value !== undefined && value !== null && value !== '');
    const rows = extraRows.concat(entries);
    if (!rows.length) return;
    const dl = make('dl', 're-meta-grid text-small');
    rows.forEach(([key, value]) => {
      dl.append(make('dt', '', keyLabels[key] || key));
      const dd = make('dd');
      if (key === 'technical_name' || key === 'path') dd.append(make('code', '', plain(value)));
      else dd.textContent = plain(value);
      dl.append(dd);
    });
    container.append(dl);
  }

  function optionElement(option) {
    const li = make('li', 're-option');
    const line = make('div');
    line.append(make('span', 're-shape', '○'));
    line.append(document.createTextNode(` ${option.label}`));
    if (option.id !== option.label) line.append(make('code', 're-path text-small', option.id));
    if (option.meta && Object.keys(option.meta).length) {
      const details = make('details', 're-option-parent');
      const optionSummary = make('summary', 'text-small', '选项规则');
      details.append(optionSummary);
      addMeta(details, option.meta);
      li.append(line, details);
    } else li.append(line);
    return li;
  }

  function renderOptions(node, detail) {
    if (node.options.length) {
      const list = make('ul', 're-option-list');
      node.options.forEach(option => list.append(optionElement(option)));
      detail.append(list);
    }
    node.optionGroups.forEach(group => {
      const groupDetails = make('details', 're-option-parent');
      if (expansion === 'all' || state.search) groupDetails.open = true;
      groupDetails.append(make('summary', '', `父选项：${group.parent}`));
      const list = make('ul', 're-option-list');
      group.options.forEach(option => list.append(optionElement(option)));
      groupDetails.append(list);
      detail.append(groupDetails);
    });
  }

  function nodeElement(node, visibleCounts) {
    visibleCounts.nodes += 1;
    visibleCounts.options += node.options.length + node.optionGroups.reduce((sum, group) => sum + group.options.length, 0);
    visibleCounts.groupedOptions += node.optionGroups.reduce((sum, group) => sum + group.options.length, 0);
    if (node.candidate) visibleCounts.candidates += 1;
    const li = make('li', node.ownMatch && state.search ? 're-match' : '');
    const details = make('details', `re-node${node.candidate ? ' is-candidate' : ''}`);
    details.open = expansion === 'all' || Boolean(state.search);
    const summaryElement = make('summary');
    const symbol = node.kind === 'group' ? '◆' : node.kind === 'action' ? '↻' : '●';
    summaryElement.append(make('span', 're-shape', symbol));
    summaryElement.append(make('span', 're-node-label', ` ${node.label}`));
    summaryElement.append(make('code', 're-path text-small', node.path));
    if (node.meta.required === true) summaryElement.append(make('span', 'viz-badge re-inline-meta', '必填'));
    if (node.candidate) summaryElement.append(make('span', 'viz-badge re-inline-meta', '候选/不可达'));
    if (node.affects.length) summaryElement.append(make('span', 're-inline-meta text-small', `影响 ${node.affects.length} 项`));
    details.append(summaryElement);

    const detail = make('div', 're-detail');
    addMeta(detail, node.meta, [['path', node.path], ['kind', node.kind]]);
    if (node.affects.length) {
      const effects = make('details');
      if (expansion === 'all' && node.affects.length <= 6) effects.open = true;
      effects.append(make('summary', 'text-small', `受此节点影响的字段/组（${node.affects.length}）`));
      const list = make('ul', 're-effects text-small');
      node.affects.forEach(item => {
        const effect = make('li');
        effect.append(document.createTextNode(item.label + ' '));
        effect.append(make('code', '', item.path));
        list.append(effect);
      });
      effects.append(list);
      detail.append(effects);
    }
    renderOptions(node, detail);
    if (node.children.length) {
      const list = make('ul', 're-tree-list');
      node.children.forEach(child => list.append(nodeElement(child, visibleCounts)));
      detail.append(list);
    }
    details.append(detail);
    li.append(details);
    return li;
  }

  function sectionElement(label, nodes, candidate, visibleCounts) {
    if (!nodes.length) return null;
    const wrapper = make('details', candidate ? 're-candidate-section' : 're-active-section');
    wrapper.open = !candidate || expansion === 'all' || state.scope === 'candidate' || Boolean(state.search);
    wrapper.append(make('summary', '', `${candidate ? '候选/不可达/声明边界' : '活动字段'}（${nodes.length} 个顶层节点）`));
    const list = make('ul', 're-tree-list');
    nodes.forEach(node => list.append(nodeElement(node, visibleCounts)));
    wrapper.append(list);
    return wrapper;
  }

  function render() {
    treeView.replaceChildren();
    const counts = { pages: 0, nodes: 0, options: 0, groupedOptions: 0, candidates: 0 };
    DATA.pages.forEach((page, pageIndex) => {
      if (state.page !== 'all' && page.id !== state.page) return;
      if (!possible(page.visibleIf)) return;
      const active = state.scope === 'candidate' ? [] : page.active.map(filteredNode).filter(Boolean);
      const candidate = state.scope === 'active' ? [] : page.candidate.map(filteredNode).filter(Boolean);
      if (!active.length && !candidate.length) return;
      counts.pages += 1;
      const pageDetails = make('details', 're-page');
      pageDetails.open = expansion === 'all' || Boolean(state.search) || state.page !== 'all' || (expansion === 'default' && pageIndex === 0);
      const pageSummary = make('summary');
      pageSummary.append(make('span', 're-page-label', `${Number(page.order) + 1}. ${page.label}`));
      pageSummary.append(make('code', 're-path text-small', page.id));
      pageDetails.append(pageSummary);
      const pageDetail = make('div', 're-detail');
      addMeta(pageDetail, page.meta);
      const activeSection = sectionElement('活动字段', active, false, counts);
      const candidateSection = sectionElement('候选字段', candidate, true, counts);
      if (activeSection) pageDetail.append(activeSection);
      if (candidateSection) pageDetail.append(candidateSection);
      pageDetails.append(pageDetail);
      treeView.append(pageDetails);
    });
    const routeLabel = state.route === 'all' ? '全部研究路线' : routeSelect.selectedOptions[0].textContent;
    summary.textContent = `${routeLabel} · 显示 ${counts.pages}/${DATA.counts.pages} 页、${counts.nodes} 个节点、${counts.options} 个选项条目（其中 ${counts.groupedOptions} 个按父选项分组），候选节点 ${counts.candidates} 个。完整库存：活动 ${DATA.counts.activeNodes} 节点/${DATA.counts.activeOptions} 个标准选项，候选 ${DATA.counts.candidateNodes} 节点/${DATA.counts.candidateOptions} 个标准选项；另有 ${DATA.counts.groupedActiveOptions + DATA.counts.groupedCandidateOptions} 个父级联动选项。`;
    empty.hidden = counts.nodes !== 0;
  }

  routeSelect.append(new Option('全部研究路线', 'all'));
  DATA.routes.forEach(route => routeSelect.append(new Option(route.label, route.id)));
  pageSelect.append(new Option('全部页面', 'all'));
  DATA.pages.forEach(page => pageSelect.append(new Option(`${Number(page.order) + 1}. ${page.label}`, page.id)));

  searchInput.addEventListener('input', () => {
    state.search = searchInput.value.trim().toLocaleLowerCase('zh-CN');
    render();
  });
  routeSelect.addEventListener('change', () => { state.route = routeSelect.value; render(); });
  pageSelect.addEventListener('change', () => { state.page = pageSelect.value; render(); });
  scopeSelect.addEventListener('change', () => { state.scope = scopeSelect.value; render(); });
  root.querySelector('#re-tree-expand').addEventListener('click', () => { expansion = 'all'; render(); });
  root.querySelector('#re-tree-collapse').addEventListener('click', () => { expansion = 'none'; render(); });
  root.querySelector('#re-tree-reset').addEventListener('click', () => {
    state.search = '';
    state.route = 'all';
    state.page = 'all';
    state.scope = 'all';
    searchInput.value = '';
    routeSelect.value = 'all';
    pageSelect.value = 'all';
    scopeSelect.value = 'all';
    expansion = 'default';
    render();
  });

  render();
})();
</script>
'''.strip()


def build_fragment(document: dict[str, Any]) -> str:
    data = build_data(document)
    encoded = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    fragment = FRAGMENT_TEMPLATE.replace("__TREE_DATA__", encoded) + "\n"
    if "__TREE_DATA__" in fragment:
        raise RuntimeError("visualization data placeholder was not replaced")
    if not fragment.startswith('<div id="research-ethics-complete-tree">'):
        raise RuntimeError("visualization must be an HTML fragment with the expected root")
    if any(token in fragment.lower() for token in ("<!doctype", "<html", "<head", "<body")):
        raise RuntimeError("visualization output must be a fragment, not a standalone document")
    size = len(fragment.encode("utf-8"))
    if size >= MAX_FRAGMENT_BYTES:
        raise RuntimeError(f"visualization is too large: {size} bytes")
    return fragment


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--check", action="store_true", help="validate in memory without writing")
    args = parser.parse_args()

    document = yaml.safe_load(CANONICAL.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise RuntimeError("canonical YAML must be a mapping")
    fragment = build_fragment(document)
    data = build_data(document)
    byte_count = len(fragment.encode("utf-8"))
    if args.check:
        print(
            "Visualization check passed: "
            f"pages={data['counts']['pages']}, active_nodes={data['counts']['activeNodes']}, "
            f"candidate_nodes={data['counts']['candidateNodes']}, bytes={byte_count}"
        )
        return 0

    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=output.stem + ".", suffix=".tmp", dir=output.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(fragment)
        os.replace(temp_name, output)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)
    print(f"Wrote {output.name}: {byte_count} bytes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
