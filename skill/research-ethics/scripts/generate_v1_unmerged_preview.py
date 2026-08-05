#!/usr/bin/env python3
"""Generate the de-identified observational V1 evidence-tree preview.

This is deliberately a preview, not a claim that every branch was replayed
to the final attachment page.  The canonical YAML remains the only rule
source; this module only renders its observational V1 scope and the ledger's
de-identified evidence grades.
"""

from __future__ import annotations

import argparse
import html
import json
from pathlib import Path
from typing import Any

from generate_v1_candidate_queue import collect
from validate_dfs_ledger import DEFAULT_CANONICAL, DEFAULT_LEDGER, validate_ledger


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MARKDOWN = PROJECT_ROOT / "references" / "registration-tree-v1-unmerged.md"
DEFAULT_HTML = PROJECT_ROOT / "references" / "registration-tree-v1-unmerged.html"
OBSERVATIONAL_ROOT = "investigator-observational"


def route_matches(route: dict[str, Any], diagnostic: str) -> bool:
    selections = route.get("selections", {})
    return (
        selections.get("research-category.route-leaf") == OBSERVATIONAL_ROOT
        and selections.get("research-category.diagnostic-trial") == diagnostic
    )


def route_evidence(ledger: dict[str, Any], diagnostic: str) -> list[dict[str, Any]]:
    evidence: list[dict[str, Any]] = []
    for route in ledger.get("routes", []):
        if not isinstance(route, dict) or not route_matches(route, diagnostic):
            continue
        display = route.get("display", {})
        pages = [
            str(page["page_id"])
            for page in display.get("pages", [])
            if isinstance(page, dict) and page.get("disposition") == "visited"
        ]
        evidence.append(
            {
                "id": str(route.get("route_id", "unknown")),
                "grade": str(route.get("verification_level", route.get("evidence_grade", "ungraded"))),
                "pages": pages,
                "leaf": str(display.get("leaf", {}).get("status", "unknown")),
            }
        )
    return evidence


def label(index: Any, path: str) -> str:
    node = index.node_by_path.get(path, {})
    return str(node.get("label", path))


def observation_for(ledger: dict[str, Any], control_path: str) -> dict[str, Any] | None:
    for collection in ("live_current_page_observations", "manual_live_observations", "live_sampling_revisions"):
        for item in ledger.get(collection, []):
            if not isinstance(item, dict) or item.get("control_path") != control_path:
                continue
            selections = item.get("selections", {})
            if selections and selections.get("research-category.route-leaf") != OBSERVATIONAL_ROOT:
                continue
            return item
    return None


def note(index: Any, item: dict[str, Any] | None, fallback_grade: str = "inferred_from_initial_tree") -> dict[str, Any] | None:
    if not item:
        return None
    fields: list[str] = []
    compared = item.get("compared_options", {})
    if isinstance(compared, dict):
        for option, details in compared.items():
            if not isinstance(details, dict):
                continue
            for key in ("added_field_paths", "visible_field_paths", "hidden_field_paths"):
                values = details.get(key, [])
                if isinstance(values, list):
                    fields.extend(f"{option}: {value}" for value in values)
    if not fields:
        observed = item.get("observed_difference", {})
        if isinstance(observed, dict):
            for direction, values in observed.items():
                if isinstance(values, list):
                    fields.extend(f"{direction}: {value}" for value in values)
    return {
        "control": label(index, str(item.get("control_path", "unknown"))),
        "controlPath": str(item.get("control_path", "unknown")),
        "grade": str(item.get("verification_level", item.get("evidence_grade", fallback_grade))),
        "summary": str(item.get("current_page_comparison", item.get("boundary", "已记录脱敏当前页比较。"))),
        "fields": fields,
    }


def page_template(canonical: dict[str, Any]) -> list[dict[str, str]]:
    pages = canonical.get("workflow", {}).get("pages", [])
    return [
        {"id": str(page.get("id", "unknown")), "label": str(page.get("label", page.get("id", "unknown")))}
        for page in pages
        if isinstance(page, dict)
    ]


def branch(path: list[str], evidence: list[dict[str, Any]], notes: list[dict[str, Any] | None]) -> dict[str, Any]:
    return {
        "path": path,
        "evidence": evidence,
        "notes": [item for item in notes if item],
    }


def data_model(validated: dict[str, Any]) -> dict[str, Any]:
    canonical, ledger, index = validated["canonical"], validated["ledger"], validated["index"]
    scope = canonical.get("version_scope", {})
    policy = scope.get("verification_policy", {}) if isinstance(scope, dict) else {}
    common = [
        note(index, observation_for(ledger, "basic-information.sync-platform")),
        note(index, observation_for(ledger, "implementation-information.multicenter-flag")),
        note(index, observation_for(ledger, "basic-information.material-donation-flag")),
        note(index, observation_for(ledger, "data-sharing-and-public-disclosure.data-share-statement")),
    ]
    return {
        "title": "观察性研究 V1.0：不汇合纵向树（核验证据预览）",
        "isPreview": True,
        "canonicalHash": validated["canonical_sha256"],
        "candidateCount": len(collect(canonical)),
        "pageTemplate": page_template(canonical),
        "assumption": policy.get("locality_assumption", {}),
        "branches": [
            branch(
                ["开始新建医学研究", "研究者发起的临床研究", "观察性研究", "是否为诊断试验：是"],
                route_evidence(ledger, "yes"),
                [
                    note(index, observation_for(ledger, "research-category.diagnostic-trial")),
                    note(index, observation_for(ledger, "research-design.exempt-consent")),
                    note(index, observation_for(ledger, "research-design.biological-sample-collection")),
                    *common,
                ],
            ),
            branch(
                ["开始新建医学研究", "研究者发起的临床研究", "观察性研究", "是否为诊断试验：否"],
                route_evidence(ledger, "no"),
                [
                    note(index, observation_for(ledger, "research-category.diagnostic-trial")),
                    note(index, observation_for(ledger, "research-design.control-group-flag")),
                    note(index, observation_for(ledger, "research-design.joint-measures")),
                    note(index, observation_for(ledger, "research-design.biological-sample-collection")),
                    *common,
                ],
            ),
        ],
        "deferred": ["研究者发起的临床研究 → 干预性研究", "产品注册目的的临床试验全部路线"],
        "blocked": ["数据共享／结果发布方式＝其他"],
    }


def markdown(model: dict[str, Any]) -> str:
    lines = [
        f"# {model['title']}",
        "",
        "> 这是可审计预览，不是穷举全部组合的现场完成声明。最终不汇合树会在每个真实结构分支下机械复制后续模板；当前未完整重放的复制内容必须保留证据等级。",
        f"> Canonical SHA-256：`{model['canonicalHash']}`；观察性候选核验项：`{model['candidateCount']}`。",
        "",
        "## V1.0 局部性假设",
        "",
        str(model.get("assumption", {}).get("statement", "尚未声明。")),
        "",
    ]
    for item in model["branches"]:
        lines.append("## " + " → ".join(item["path"]))
        lines.append("")
        lines.append("### 独立路线证据")
        if item["evidence"]:
            for evidence in item["evidence"]:
                pages = "、".join(evidence["pages"]) or "尚无已访问页面签名"
                lines.append(f"- `{evidence['id']}`：`{evidence['grade']}`；页面：{pages}；叶状态：`{evidence['leaf']}`。")
        else:
            lines.append("- 尚无独立根到叶账本记录；仅可使用当前页比较和初版规则，不得宣称路线完成。")
        lines.append("")
        lines.append("### 已记录的脱敏结构差异")
        if item["notes"]:
            for note_item in item["notes"]:
                lines.append(f"- `{note_item['controlPath']}`（{note_item['control']}）：`{note_item['grade']}`。")
                if note_item["fields"]:
                    lines.append("  - 当前页字段：" + "；".join(f"`{field}`" for field in note_item["fields"]))
                else:
                    lines.append("  - " + note_item["summary"])
        else:
            lines.append("- 尚无可归属到本观察性根路线的当前页比较。")
        lines.append("")
        lines.append("### 纵向页面模板（后续按证据等级独立复制）")
        for page in model["pageTemplate"]:
            lines.append(f"- `{page['id']}`：{page['label']}")
        lines.append("")
    lines += [
        "## V2 与阻塞边界",
        "",
        *[f"- `{item}`：`deferred_to_v2`。" for item in model["deferred"]],
        *[f"- `{item}`：`out_of_scope_or_blocked`。" for item in model["blocked"]],
        "",
    ]
    return "\n".join(lines)


def html_document(model: dict[str, Any]) -> str:
    payload = json.dumps(model, ensure_ascii=False).replace("</", "<\\/")
    title = html.escape(model["title"])
    return f'''<!doctype html>
<html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title>
<style>
body{{font:15px/1.55 system-ui,"Microsoft YaHei",sans-serif;margin:0;color:#17212b;background:#f5f7fa}}main{{max-width:1100px;margin:auto;padding:24px}}.notice{{padding:12px;border-left:4px solid #a76800;background:#fff7df}}.toolbar{{position:sticky;top:0;background:#fff;padding:10px 0}}input{{padding:7px;width:min(460px,100%);border:1px solid #9aa8b8;border-radius:5px}}.branch{{margin:18px 0;padding:14px 18px;border-left:3px solid #3b82f6;background:#fff;border-radius:6px}}.path{{font-weight:700}}.grade{{font-family:ui-monospace,monospace;background:#e8eef5;border-radius:3px;padding:1px 4px}}code{{overflow-wrap:anywhere}}.page{{margin:4px 0 0 14px}}.scope{{color:#8b2442}}</style>
<main><h1>{title}</h1><p class="notice">仅呈现脱敏规则与证据等级。此页面不是“所有组合已完整现场验证”的声明。</p><div class="toolbar"><input id="q" placeholder="搜索字段路径、页面或路线"></div><section id="tree"></section></main>
<script>const data={payload};const esc=s=>String(s).replace(/[&<>"']/g,c=>({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}}[c]));const tree=document.querySelector('#tree');for(const b of data.branches){{const e=document.createElement('article');e.className='branch';e.dataset.search=JSON.stringify(b).toLowerCase();e.innerHTML='<div class="path">'+b.path.map(esc).join(' → ')+'</div><h3>路线证据</h3><ul>'+((b.evidence.length?b.evidence:[{{id:'无独立根到叶账本记录',grade:'inferred_from_initial_tree',pages:[],leaf:'partial'}}]).map(x=>'<li><code>'+esc(x.id)+'</code> <span class="grade">'+esc(x.grade)+'</span> 页面：'+esc(x.pages.join('、')||'未记录')+'；叶：<code>'+esc(x.leaf)+'</code></li>').join(''))+'</ul><h3>当前页差异</h3><ul>'+((b.notes.length?b.notes:[{{control:'暂无可归属观察性根路线的比较',controlPath:'',grade:'inferred_from_initial_tree',fields:[]}}]).map(n=>'<li><code>'+esc(n.controlPath)+'</code> '+esc(n.control)+' <span class="grade">'+esc(n.grade)+'</span><br>'+n.fields.map(v=>'<code>'+esc(v)+'</code>').join('；')+'</li>').join(''))+'</ul><details><summary>纵向页面模板（在最终不汇合树中独立复制）</summary>'+data.pageTemplate.map(p=>'<div class="page"><code>'+esc(p.id)+'</code>：'+esc(p.label)+'</div>').join('')+'</details>';tree.append(e)}}const scope=document.createElement('section');scope.innerHTML='<h2>V2 与阻塞边界</h2><ul class="scope">'+data.deferred.map(x=>'<li>'+esc(x)+'：<code>deferred_to_v2</code></li>').join('')+data.blocked.map(x=>'<li>'+esc(x)+'：<code>out_of_scope_or_blocked</code></li>').join('')+'</ul>';tree.append(scope);document.querySelector('#q').addEventListener('input',e=>{{const q=e.target.value.toLowerCase();document.querySelectorAll('.branch').forEach(x=>x.hidden=q&&!x.dataset.search.includes(q))}});</script></html>\n'''


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--canonical", type=Path, default=DEFAULT_CANONICAL)
    parser.add_argument("--ledger", type=Path, default=DEFAULT_LEDGER)
    parser.add_argument("--markdown-output", type=Path, default=DEFAULT_MARKDOWN)
    parser.add_argument("--html-output", type=Path, default=DEFAULT_HTML)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    model = data_model(validate_ledger(args.canonical, args.ledger))
    if args.check:
        print(f"V1 observational preview check passed: branches={len(model['branches'])}, candidates={model['candidateCount']}")
        return 0
    args.markdown_output.write_text(markdown(model), encoding="utf-8", newline="\n")
    args.html_output.write_text(html_document(model), encoding="utf-8", newline="\n")
    print("Wrote observational V1 unmerged evidence preview")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
