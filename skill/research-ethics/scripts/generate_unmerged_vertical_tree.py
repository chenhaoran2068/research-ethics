#!/usr/bin/env python3
"""Generate the final root-to-leaf, never-rejoining registration form tree.

This program has exactly two read inputs: the canonical form rules and the
de-identified DFS ledger.  It never reads raw page source, screenshots, browser
state or account information.  The resulting HTML and Markdown are generated
views, not a second source of form rules.

The display is a prefix tree.  Therefore common steps may be shared *before* a
ledger-declared structural choice, but after a structural-option edge every
subsequent page/field instance belongs only to that branch.  Identical canonical
field paths are copied as separate display instances below different branches.
"""

from __future__ import annotations

import argparse
import html
import json
import os
import tempfile
from pathlib import Path
from typing import Any

from validate_dfs_ledger import (
    DEFAULT_CANONICAL,
    DEFAULT_LEDGER,
    LedgerValidationError,
    validate_ledger,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_HTML = PROJECT_ROOT / "references" / "registration-tree-unmerged.html"
DEFAULT_MARKDOWN = PROJECT_ROOT / "references" / "registration-tree-unmerged.md"


def scalar(value: Any) -> str:
    if value is True:
        return "是"
    if value is False:
        return "否"
    if value is None:
        return "—"
    return str(value)


def option_label(node: dict[str, Any], selected: Any) -> str:
    wanted = str(selected)
    options = node.get("options") if isinstance(node.get("options"), list) else []
    groups = node.get("options_by_parent") if isinstance(node.get("options_by_parent"), dict) else {}
    for item in list(options) + [item for group in groups.values() if isinstance(group, list) for item in group]:
        if isinstance(item, dict):
            item_id = str(item.get("id", item.get("value", item.get("label", ""))))
            if item_id == wanted:
                return str(item.get("label", item_id))
        elif str(item) == wanted:
            return str(item)
    return wanted


def visual_status(node: dict[str, Any]) -> str:
    if node.get("_ledger_candidate") is True:
        return "candidate"
    if node.get("enabled") is False:
        return "disabled"
    status = " ".join(str(node.get(key, "")) for key in ("status", "verification_status", "source_classification")).lower()
    if "candidate" in status or "unverified" in status or "待验证" in status:
        return "candidate"
    if "out_of" in status or "范围外" in status:
        return "out_of_scope"
    return "active"


def node_payload(path: str, node: dict[str, Any]) -> dict[str, Any]:
    return {
        "canonicalPath": path,
        "label": str(node.get("label", node.get("id", path))),
        "widget": scalar(node.get("widget", "control")),
        "required": node.get("required", False),
        "status": visual_status(node),
    }


def route_tokens(route: dict[str, Any], index: Any, structural_paths: set[str]) -> list[dict[str, Any]]:
    """Turn one verified representative route into ordered display tokens."""
    tokens: list[dict[str, Any]] = []
    selections = route["selections"]
    for snapshot in route["display"]["pages"]:
        page_id = snapshot["page_id"]
        page = index.pages[page_id]
        disposition = snapshot["disposition"]
        if disposition != "visited":
            tokens.append(
                {
                    "key": f"page:{page_id}:{disposition}",
                    "kind": "page-boundary",
                    "pageId": page_id,
                    "label": str(page.get("label", page_id)),
                    "status": "out_of_scope" if disposition == "blocked" else "disabled",
                    "disposition": disposition,
                }
            )
            continue
        tokens.append(
            {
                "key": f"page:{page_id}:visited",
                "kind": "page-boundary",
                "pageId": page_id,
                "label": str(page.get("label", page_id)),
                "status": "active",
                "disposition": "visited",
            }
        )
        for path in snapshot["field_paths"]:
            node = index.node_by_path[path]
            if path in structural_paths:
                selected = selections[path]
                tokens.append(
                    {
                        "key": f"branch:{path}:{selected}",
                        "kind": "structural-branch",
                        "pageId": page_id,
                        "selected": scalar(selected),
                        "selectedLabel": option_label(node, selected),
                        **node_payload(path, node),
                    }
                )
            else:
                tokens.append({"key": f"field:{path}", "kind": "field", "pageId": page_id, **node_payload(path, node)})
    return tokens


def make_instance(kind: str, key: str, **payload: Any) -> dict[str, Any]:
    return {"kind": kind, "key": key, "children": [], "childIndex": {}, "routeIds": set(), **payload}


def add_route(root: dict[str, Any], route: dict[str, Any], tokens: list[dict[str, Any]]) -> None:
    cursor = root
    cursor["routeIds"].add(route["route_id"])
    for token in tokens:
        child = cursor["childIndex"].get(token["key"])
        if child is None:
            child = make_instance(
                token["kind"],
                token["key"],
                **{key: value for key, value in token.items() if key not in {"key", "kind"}},
            )
            cursor["childIndex"][token["key"]] = child
            cursor["children"].append(child)
        child["routeIds"].add(route["route_id"])
        cursor = child
    leaf = make_instance(
        "leaf",
        f"leaf:{route['route_id']}",
        routeId=route["route_id"],
        leafStatus=route["display"]["leaf"]["status"],
        evidenceGrade=route.get("evidence_grade", route["status"]),
        status="active" if route["display"]["leaf"]["status"] == "reached" else "out_of_scope",
        label=f"路线终点：{route['route_id']}",
    )
    leaf["routeIds"].add(route["route_id"])
    cursor["children"].append(leaf)


def serialise_tree(node: dict[str, Any], counter: list[int]) -> dict[str, Any]:
    counter[0] += 1
    output = {key: value for key, value in node.items() if key not in {"childIndex", "routeIds", "children"}}
    output["instanceId"] = f"display-{counter[0]}"
    output["routeIds"] = sorted(node["routeIds"])
    output["children"] = [serialise_tree(child, counter) for child in node["children"]]
    return output


def validate_tree(tree: dict[str, Any], expected_routes: set[str]) -> dict[str, int]:
    """Prove the generated *display* graph is a single-parent rooted tree."""
    seen: set[str] = set()
    leaf_routes: set[str] = set()
    instances = 0
    structural_instances = 0

    def visit(node: dict[str, Any], parent: str | None, ancestors: set[str]) -> None:
        nonlocal instances, structural_instances
        instance_id = node.get("instanceId")
        if not isinstance(instance_id, str) or instance_id in seen:
            raise LedgerValidationError("generated display tree has duplicate instance IDs")
        if instance_id in ancestors:
            raise LedgerValidationError("generated display tree has a cycle")
        seen.add(instance_id)
        instances += 1
        if node.get("kind") == "structural-branch":
            structural_instances += 1
        if node.get("kind") == "leaf":
            route = node.get("routeId")
            if route in leaf_routes:
                raise LedgerValidationError(f"generated tree repeats leaf route {route}")
            leaf_routes.add(route)
        for child in node.get("children", []):
            # JSON nesting gives exactly one parent.  This explicit assertion
            # protects against future changes that might introduce references.
            if not isinstance(child, dict):
                raise LedgerValidationError("generated tree contains a non-object child")
            visit(child, instance_id, ancestors | {instance_id})

    if tree.get("kind") != "root":
        raise LedgerValidationError("generated tree must have exactly one root")
    visit(tree, None, set())
    if leaf_routes != expected_routes:
        raise LedgerValidationError("generated leaf route set does not equal ledger routes")
    return {"instances": instances, "leaves": len(leaf_routes), "structural_instances": structural_instances}


def build_tree(validated: dict[str, Any]) -> tuple[dict[str, Any], dict[str, int]]:
    ledger = validated["ledger"]
    index = validated["index"]
    structural_paths = {item["control_path"] for item in ledger["structural_branches"]}
    root = make_instance("root", "root", label="开始新建医学研究", status="active")
    for route in validated["display_routes"]:
        add_route(root, route, route_tokens(route, index, structural_paths))
    tree = serialise_tree(root, [0])
    metrics = validate_tree(tree, {route["route_id"] for route in validated["display_routes"]})
    return tree, metrics


def markdown_index(validated: dict[str, Any], metrics: dict[str, int]) -> str:
    ledger = validated["ledger"]
    index = validated["index"]
    lines = [
        "# 医学研究登记：完整纵向不汇合路线索引",
        "",
        "> 本文件由 `registration-tree.yaml` 与脱敏 DFS 探索账本机械生成；不是第二套规则。",
        "> 每个路线条目代表一个已安全合并后的结构等价类。结构分支一旦发生，HTML 中后续节点均为独立显示实例，不重新汇合。",
        "",
        f"- Canonical SHA-256：`{validated['canonical_sha256']}`",
        f"- 显示路线（叶）数：{metrics['leaves']}",
        f"- 显示实例数：{metrics['instances']}",
        f"- 结构分支显示实例数：{metrics['structural_instances']}",
        "",
        "## 路线目录",
        "",
    ]
    for route in validated["display_routes"]:
        lines.append(f"- [{route['route_id']}](#{route['route_id']}) — `{route['status']}`")
    for route in validated["display_routes"]:
        lines.extend(["", f"<a id=\"{html.escape(route['route_id'])}\"></a>", f"## {route['route_id']}", ""])
        lines.append(f"- 路线状态：`{route['status']}`")
        lines.append(f"- 叶状态：`{route['display']['leaf']['status']}`")
        lines.append("- 结构选择：")
        for decision in route["structural_decisions"]:
            path = decision["control_path"]
            node = index.node_by_path[path]
            selected = decision["option_id"]
            lines.append(f"  - `{path}`：{option_label(node, selected)} (`{selected}`)")
        lines.append("- 页面与字段顺序：")
        for snapshot in route["display"]["pages"]:
            page_id = snapshot["page_id"]
            page = index.pages[page_id]
            lines.append(f"  - **{page.get('label', page_id)}** (`{page_id}`) — `{snapshot['disposition']}`")
            for path in snapshot["field_paths"]:
                node = index.node_by_path[path]
                lines.append(f"    - {node.get('label', node.get('id', path))} (`{path}`；{node.get('widget', 'control')})")
    return "\n".join(lines) + "\n"


HTML_TEMPLATE = r'''<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>医学研究登记：纵向不汇合流程树</title>
<style>
:root{--line:#b7c3d0;--text:#17212b;--muted:#526171;--surface:#fff;--page:#e8f2ff;--branch:#fff2c8;--active:#dff5e5;--candidate:#f8e4a8;--disabled:#e8eaed;--scope:#f5e2e9;--highlight:#ff7a00}*{box-sizing:border-box}body{margin:0;background:#f4f7fa;color:var(--text);font:14px/1.45 system-ui,"Microsoft YaHei",sans-serif}.toolbar{position:sticky;top:0;z-index:3;padding:12px 16px;background:rgba(255,255,255,.96);border-bottom:1px solid #d7e0e8;display:flex;flex-wrap:wrap;gap:9px;align-items:center}.toolbar input,.toolbar select,.toolbar button{font:inherit;padding:6px 9px;border:1px solid #b7c3d0;border-radius:6px;background:white}.toolbar button{cursor:pointer}.summary{color:var(--muted);margin-left:auto}.viewport{height:calc(100vh - 68px);overflow:auto;cursor:grab;padding:24px}.viewport.dragging{cursor:grabbing;user-select:none}.canvas{width:max-content;min-width:100%;transform-origin:top left;padding:4px 18px 80px}.node{position:relative;margin-left:22px;padding-left:20px}.node:before{content:"";position:absolute;left:0;top:-12px;height:31px;border-left:1px solid var(--line)}.node:after{content:"";position:absolute;left:0;top:19px;width:18px;border-top:1px solid var(--line)}.node.root{margin-left:0;padding-left:0}.node.root:before,.node.root:after{display:none}.card{display:inline-flex;gap:8px;align-items:center;max-width:760px;padding:6px 9px;margin:4px 0;border:1px solid #cad4de;border-radius:7px;background:var(--surface);box-shadow:0 1px 1px #0000000a}.kind-page-boundary .card{background:var(--page);font-weight:650}.kind-structural-branch .card{background:var(--branch);border-color:#debd58;font-weight:650}.kind-leaf .card{background:#e9eef4;font-weight:650}.status-active .card{border-left:5px solid #299b51}.status-candidate .card{border-left:5px solid #d49b00;background:var(--candidate)}.status-disabled .card{border-left:5px solid #8995a3;background:var(--disabled)}.status-out_of_scope .card{border-left:5px solid #ad4b69;background:var(--scope)}.node.highlight .card{outline:3px solid var(--highlight);outline-offset:2px}.label{font-weight:600}.path,.meta,.edge{font-size:12px;color:var(--muted);overflow-wrap:anywhere}.edge{padding:1px 0 0 6px;color:#7b5900}.children{margin-left:0}.hidden{display:none!important}.legend{font-size:12px;color:var(--muted);padding:0 16px 10px;background:#fff}.dot{display:inline-block;width:9px;height:9px;border-radius:50%;margin-left:8px}.active{background:#299b51}.candidate{background:#d49b00}.disabled{background:#8995a3}.scope{background:#ad4b69}@media(max-width:640px){.summary{width:100%;margin-left:0}.viewport{padding:12px}.card{max-width:calc(100vw - 65px)}}
</style></head><body>
<div class="toolbar"><strong>医学研究登记：纵向不汇合流程树</strong><input id="search" type="search" placeholder="搜索字段、页面或路径"><select id="route"><option value="">全部路线</option></select><button id="expand">全部展开</button><button id="collapse">全部折叠</button><label>缩放 <input id="zoom" type="range" min="40" max="140" value="85"></label><span id="summary" class="summary"></span></div>
<div class="legend"><span class="dot active"></span>活动 <span class="dot candidate"></span>候选 <span class="dot disabled"></span>禁用/跳过 <span class="dot scope"></span>范围外/阻塞。点击任一终点，高亮完整根到叶路径；可拖动画布平移。</div><div id="viewport" class="viewport"><div id="canvas" class="canvas"></div></div>
<script>const DATA=__DATA__;const canvas=document.querySelector('#canvas'),viewport=document.querySelector('#viewport'),search=document.querySelector('#search'),route=document.querySelector('#route'),summary=document.querySelector('#summary'),zoom=document.querySelector('#zoom');let selectedLeaf=null;for(const id of DATA.routeIds){const o=document.createElement('option');o.value=id;o.textContent=id;route.append(o)}function nodeText(n){return [n.label,n.canonicalPath,n.pageId,n.selected,n.selectedLabel,n.routeId,n.widget].filter(Boolean).join(' ').toLowerCase()}function render(n,parent){const el=document.createElement('div');el.className=`node kind-${n.kind} status-${n.status||'active'}`;el.dataset.routes=(n.routeIds||[]).join('|');el.dataset.text=nodeText(n);el.dataset.id=n.instanceId;const card=document.createElement('div');card.className='card';const kind=n.kind==='page-boundary'?'页面':n.kind==='structural-branch'?'结构分支':n.kind==='leaf'?'终点':'字段';card.innerHTML=`<span class="label">${kind} · ${escapeHtml(n.label||'')}</span>${n.kind==='structural-branch'?`<span class="edge">选择：${escapeHtml(n.selectedLabel||n.selected||'')}</span>`:''}${n.canonicalPath?`<span class="path">${escapeHtml(n.canonicalPath)}</span>`:''}${n.widget?`<span class="meta">${escapeHtml(String(n.widget))}${n.required===true?' · 必填':''}</span>`:''}`;if(n.kind==='leaf'){card.tabIndex=0;card.title='点击高亮根到此终点的路径';card.addEventListener('click',()=>highlight(el));card.addEventListener('keydown',e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();highlight(el)}})}else if(n.children&&n.children.length){card.title='点击折叠/展开后续节点';card.addEventListener('click',()=>el.classList.toggle('collapsed'))}el.append(card);if(n.children&&n.children.length){const children=document.createElement('div');children.className='children';for(const child of n.children)render(child,children);el.append(children)}parent.append(el)}function escapeHtml(s){return String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))}function applyFilter(){const q=search.value.trim().toLowerCase(),r=route.value;for(const el of canvas.querySelectorAll('.node')){const routeOk=!r||el.dataset.routes.split('|').includes(r);const textOk=!q||el.dataset.text.includes(q);el.classList.toggle('hidden',!(routeOk&&textOk))}for(const el of canvas.querySelectorAll('.node.collapsed .children'))el.classList.add('hidden');summary.textContent=`${DATA.metrics.leaves} 个结构叶；${DATA.metrics.instances} 个显示实例；${r?'路线 '+r:'全部路线'}`}function highlight(leaf){for(const el of canvas.querySelectorAll('.highlight'))el.classList.remove('highlight');selectedLeaf=leaf;let current=leaf;while(current){current.classList.add('highlight');current=current.parentElement?.closest('.node')}leaf.scrollIntoView({block:'center',behavior:'smooth'})}render(DATA.tree,canvas);search.addEventListener('input',applyFilter);route.addEventListener('change',applyFilter);document.querySelector('#expand').onclick=()=>{for(const n of canvas.querySelectorAll('.collapsed'))n.classList.remove('collapsed');applyFilter()};document.querySelector('#collapse').onclick=()=>{for(const n of canvas.querySelectorAll('.node:not(.root)'))if(n.querySelector(':scope > .children'))n.classList.add('collapsed');applyFilter()};zoom.addEventListener('input',()=>canvas.style.transform=`scale(${zoom.value/100})`);let drag=null;viewport.addEventListener('pointerdown',e=>{if(e.target.closest('.card'))return;drag={x:e.clientX,y:e.clientY,l:viewport.scrollLeft,t:viewport.scrollTop};viewport.classList.add('dragging');viewport.setPointerCapture(e.pointerId)});viewport.addEventListener('pointermove',e=>{if(!drag)return;viewport.scrollLeft=drag.l-(e.clientX-drag.x);viewport.scrollTop=drag.t-(e.clientY-drag.y)});viewport.addEventListener('pointerup',()=>{drag=null;viewport.classList.remove('dragging')});applyFilter();</script></body></html>'''


def html_document(tree: dict[str, Any], metrics: dict[str, int]) -> str:
    data = {
        "tree": tree,
        "metrics": metrics,
        "routeIds": sorted(route["routeId"] for route in _iter_leaves(tree)),
    }
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    # `applyFilter` must clear stale collapse-only hiding before it reapplies
    # current collapse state; otherwise "expand all" cannot restore descendants.
    template = HTML_TEMPLATE.replace(
        "for(const el of canvas.querySelectorAll('.node.collapsed .children'))el.classList.add('hidden');",
        "for(const el of canvas.querySelectorAll('.node .children'))el.classList.remove('hidden');"
        "for(const el of canvas.querySelectorAll('.node.collapsed .children'))el.classList.add('hidden');",
    )
    return template.replace("__DATA__", payload) + "\n"


def _iter_leaves(node: dict[str, Any]):
    if node.get("kind") == "leaf":
        yield node
    for child in node.get("children", []):
        yield from _iter_leaves(child)


def atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=path.stem + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--canonical", type=Path, default=DEFAULT_CANONICAL)
    parser.add_argument("--ledger", type=Path, default=DEFAULT_LEDGER)
    parser.add_argument("--html-output", type=Path, default=DEFAULT_HTML)
    parser.add_argument("--markdown-output", type=Path, default=DEFAULT_MARKDOWN)
    parser.add_argument("--check", action="store_true", help="validate and build in memory without writing")
    args = parser.parse_args()
    try:
        validated = validate_ledger(args.canonical, args.ledger)
        tree, metrics = build_tree(validated)
        markdown = markdown_index(validated, metrics)
        document = html_document(tree, metrics)
    except LedgerValidationError as error:
        raise SystemExit(f"Unmerged tree generation failed: {error}")
    if args.check:
        print("Unmerged vertical tree check passed: " + ", ".join(f"{key}={value}" for key, value in metrics.items()))
        return 0
    atomic_write(args.html_output, document)
    atomic_write(args.markdown_output, markdown)
    print(f"Wrote {args.html_output} and {args.markdown_output}; leaves={metrics['leaves']}, instances={metrics['instances']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
