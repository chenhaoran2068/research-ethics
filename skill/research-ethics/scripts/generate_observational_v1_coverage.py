#!/usr/bin/env python3
"""Generate the observational-only V1 evidence and assumption matrix.

The matrix is derived from the canonical conditional-driver queue plus a small,
explicit policy map.  It never promotes a field merely because it exists in the
initial model.  The matrix is a review artifact; canonical YAML remains the
only form-rule source and the DFS ledger remains the evidence source.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from generate_v1_candidate_queue import HIGH_RISK_DRIVERS, collect
from validate_dfs_ledger import DEFAULT_CANONICAL, DEFAULT_LEDGER, validate_ledger


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = PROJECT_ROOT / "references" / "dfs-coverage-matrix.md"


# Only facts independently supported by the present de-identified ledger are
# promoted here.  All other canonical drivers remain clearly marked pending.
ASSESSMENTS: dict[str, dict[str, str]] = {
    "research-category.route-leaf": {
        "current": "page_or_structure_changed",
        "downstream": "confirmed_cross_page",
        "grade": "sample_verified",
        "note": "观察性根路线与诊断是/否均有独立未保存草稿的当前页和研究设计页比较。",
    },
    "research-category.diagnostic-trial": {
        "current": "page_or_structure_changed",
        "downstream": "confirmed_cross_page",
        "grade": "sample_verified",
        "note": "诊断是显示诊断相关字段；否显示普通分组/暴露相关字段。两者不可合并。",
    },
    "research-category.tcm-guided": {
        "current": "none",
        "downstream": "not_checked",
        "grade": "assumption_expanded",
        "note": "V1.0 局部性假设：暂视为仅本页普通条件；未进行后续穷举。",
    },
    "research-category.invasive-bci": {
        "current": "none",
        "downstream": "not_checked",
        "grade": "assumption_expanded",
        "note": "V1.0 局部性假设：暂视为仅本页普通条件；未进行后续穷举。",
    },
    "basic-information.sync-platform": {
        "current": "page_or_structure_changed",
        "downstream": "confirmed_cross_page",
        "grade": "sample_verified",
        "note": "私有/ChiCTR 公开的中英文配对和填报状态差异已存在现场样本；观察性后续抽查仍在队列。",
    },
    "implementation-information.multicenter-flag": {
        "current": "local_fields_changed",
        "downstream": "not_checked",
        "grade": "sample_verified",
        "note": "是/否当前页结构差异已记录；深层国家、角色和参与机构按局部性假设展开。",
    },
    "research-design.exempt-consent": {
        "current": "local_fields_changed",
        "downstream": "not_checked",
        "grade": "sample_verified",
        "note": "否显示首例知情同意日期；是隐藏。",
    },
    "research-design.control-group-flag": {
        "current": "none",
        "downstream": "not_checked",
        "grade": "sample_verified",
        "note": "诊断否路线当前页是/否字段签名相同；仅完成当前页比较。",
    },
    "research-design.joint-measures": {
        "current": "none",
        "downstream": "not_checked",
        "grade": "sample_verified",
        "note": "诊断否路线当前页是/否字段签名相同；仅完成当前页比较。",
    },
    "research-design.vulnerable-group": {
        "current": "local_fields_changed",
        "downstream": "not_checked",
        "grade": "sample_verified",
        "note": "是显示弱势群体类型；普通类型按局部性假设展开。",
    },
    "research-design.biological-sample-collection": {
        "current": "local_fields_changed",
        "downstream": "not_checked",
        "grade": "sample_verified",
        "note": "是显示生物样本重复模板；新增/删除和下游尚待抽查。",
    },
    "data-sharing-and-public-disclosure.data-share-statement": {
        "current": "local_fields_changed",
        "downstream": "not_checked",
        "grade": "sample_verified",
        "note": "共享显示共享计划、获取条件、网址等字段；公开策略组合待抽查。",
    },
    "data-sharing-and-public-disclosure.result-release-method": {
        "current": "local_fields_changed",
        "downstream": "out_of_scope_or_blocked",
        "grade": "out_of_scope_or_blocked",
        "note": "发布方式=其他按用户决定保持范围外/阻塞，不再现场继续。",
    },
}


def assessment(driver: str, priority: str) -> dict[str, str]:
    if driver in ASSESSMENTS:
        return ASSESSMENTS[driver]
    if driver in HIGH_RISK_DRIVERS or priority == "high_risk_deeper_check_required":
        return {
            "current": "not_recorded",
            "downstream": "not_checked",
            "grade": "inferred_from_initial_tree",
            "note": "高风险候选：需要当前页比较及代表性后续抽查。",
        }
    return {
        "current": "not_recorded",
        "downstream": "not_checked",
        "grade": "inferred_from_initial_tree",
        "note": "初版 canonical 候选；按 V1.0 局部性策略排队，尚未独立抽样。",
    }


def render(validated: dict[str, Any]) -> str:
    rows = collect(validated["canonical"])
    lines = [
        "# 观察性研究 V1.0：DFS 覆盖矩阵",
        "",
        "> 范围仅为“研究者发起的临床研究 → 观察性研究 → 诊断试验是/否”。此矩阵不把当前页比较或局部性假设误写成全路径现场验证。",
        "> 干预性研究和产品注册路线均为 `deferred_to_v2`；数据共享/结果发布方式=其他为 `out_of_scope_or_blocked`。",
        "",
        "## 已确认的根路线",
        "",
        "- `investigator-observational / diagnostic=yes`：`sample_verified`，研究设计结构与诊断否不同。",
        "- `investigator-observational / diagnostic=no`：`sample_verified`，研究设计结构与诊断是不同。",
        "",
        "## 条件驱动与验证状态",
        "",
        "| 页面 | 控制路径 | 当前页影响 | 后续影响 | 证据等级 | 现场/假设结论 |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for page, driver, _dependents, priority, _status in rows:
        item = assessment(driver, priority)
        if driver == "basic-information.sync-platform":
            item = {
                **item,
                "note": "私有/ChiCTR 公开的中英文配对、填报状态和数据公开页字段组已完成代表性现场比较；附件类别在本次对照中一致。",
            }
        lines.append(
            f"| `{page}` | `{driver}` | `{item['current']}` | `{item['downstream']}` | "
            f"`{item['grade']}` | {item['note']} |"
        )
    lines += [
        "",
        "## V1.0 局部性假设",
        "",
        "除研究分类、诊断试验、公开策略、页面跳过、已发现不一致及招募/数据/附件风险条件外，普通动态选项默认只改变所在页；最终不汇合树在各分支下复制后续模板，并标记 `assumption_expanded`。任何现场下游差异都会触发该分支以下局部 DFS。",
        "",
        "## 当前未完成队列",
        "",
        "- 观察性公开策略的后续代表路线；",
        "- 招募页出现条件、招募状态及境外招募；",
        "- 多中心深层国家/角色/参与单位与重复项模板；",
        "- 每条诊断路线不依赖直接页签的前向末页重放；",
        "- 附件字段标签、必填性和格式的页面级读取（不上传）。",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--canonical", type=Path, default=DEFAULT_CANONICAL)
    parser.add_argument("--ledger", type=Path, default=DEFAULT_LEDGER)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    text = render(validate_ledger(args.canonical, args.ledger))
    if args.check:
        print(f"Observational V1 coverage matrix check passed: rows={text.count('| `')}")
        return 0
    args.output.write_text(text, encoding="utf-8", newline="\n")
    print("Wrote observational V1 DFS coverage matrix")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
