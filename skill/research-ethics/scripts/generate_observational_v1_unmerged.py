#!/usr/bin/env python3
"""Generate the human-first, never-rejoining V1 registration flow tree.

The canonical YAML remains the only rule source.  This generator creates two
review views from it:

* a vertical HTML flow tree which starts with the first visible platform field;
* a Markdown version with the same high-level tree plus expandable-route field
  inventories.

Choices become separate child routes only when the canonical evidence marks a
cross-page / structural difference.  Ordinary local questions stay as one
node with their options written in the node.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
from pathlib import Path
from typing import Any

import yaml

from validate_atomic_schema import AtomicSchemaValidator
from validate_dfs_ledger import DEFAULT_CANONICAL, DEFAULT_LEDGER, validate_ledger
from generate_v1_candidate_queue import collect


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MARKDOWN = PROJECT_ROOT / "references" / "registration-tree-v1-unmerged.md"
DEFAULT_HTML = PROJECT_ROOT / "references" / "registration-tree-v1-unmerged.html"
OBSERVATIONAL_ROUTE = "investigator-observational"


def find_node(value: Any, node_id: str) -> dict[str, Any] | None:
    if isinstance(value, dict):
        if value.get("id") == node_id:
            return value
        for item in value.values():
            found = find_node(item, node_id)
            if found:
                return found
    elif isinstance(value, list):
        for item in value:
            found = find_node(item, node_id)
            if found:
                return found
    return None


def label_for_option(option: Any) -> str:
    if isinstance(option, dict):
        return str(option.get("label") or option.get("id") or "未命名选项")
    return str(option)


def route_label(canonical: dict[str, Any], route_id: str) -> str:
    route_leaf = find_node(canonical, "route-leaf") or {}
    for option in route_leaf.get("options", []):
        if isinstance(option, dict) and option.get("id") == route_id:
            label = label_for_option(option)
            return label.split(">")[-1].strip()
    fallback = {
        "product-drug": "药品",
        "product-medical-device": "医疗器械",
        "product-ivd": "体外诊断试剂",
        "product-special-food": "特殊医学用途配方食品",
        "investigator-interventional": "干预性研究",
        OBSERVATIONAL_ROUTE: "观察性研究",
    }
    return fallback.get(route_id, route_id)


def condition_state(condition: Any, selections: dict[str, str]) -> bool | None:
    if isinstance(condition, bool):
        return condition
    if not isinstance(condition, dict):
        return None
    if "all" in condition and isinstance(condition["all"], list):
        states = [condition_state(item, selections) for item in condition["all"]]
        return False if False in states else True if states and all(item is True for item in states) else None
    if "any" in condition and isinstance(condition["any"], list):
        states = [condition_state(item, selections) for item in condition["any"]]
        return True if True in states else False if states and all(item is False for item in states) else None
    if "not" in condition:
        state = condition_state(condition["not"], selections)
        return None if state is None else not state
    control = condition.get("control")
    if not isinstance(control, str) or control not in selections:
        return None
    selected = selections[control]
    if "equals" in condition:
        return selected == condition["equals"]
    if "not_equals" in condition:
        return selected != condition["not_equals"]
    if "in" in condition and isinstance(condition["in"], list):
        return selected in condition["in"]
    if "not_in" in condition and isinstance(condition["not_in"], list):
        return selected not in condition["not_in"]
    if "is_set" in condition:
        return bool(selected) is bool(condition["is_set"])
    return None


def evidence(path: str) -> tuple[str, str, str]:
    if path == "research-category.diagnostic-trial":
        return "page_or_structure_changed", "confirmed_cross_page", "sample_verified"
    if path in {"research-category.tcm-guided", "research-category.invasive-bci"}:
        return "none", "not_checked", "assumption_expanded"
    if path == "research-category.implementing-organization":
        return "none", "not_checked", "sample_verified"
    if path == "basic-information.sync-platform":
        return "page_or_structure_changed", "confirmed_cross_page", "sample_verified"
    return "not_recorded", "not_checked", "inferred_from_initial_tree"


def control_summary(validator: AtomicSchemaValidator, selections: dict[str, str]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for page in validator.pages:
        if condition_state(page.visible_if, selections) is False:
            continue
        fields: list[dict[str, Any]] = []
        for control in page.controls:
            if not control.observable:
                continue
            if any(condition_state(item, selections) is False for item in control.visibility_chain):
                continue
            current, downstream, grade = evidence(control.path)
            fields.append(
                {
                    "label": control.label,
                    "path": control.path,
                    "widget": control.widget,
                    "required": control.required if isinstance(control.required, bool) else "conditional",
                    "options": len(control.options),
                    "grade": grade,
                    "current": current,
                    "downstream": downstream,
                }
            )
        result.append({"id": page.page_id, "label": page.label, "fields": fields})
    return result


def node(label: str, *, kind: str = "field", note: str = "", children: list[dict[str, Any]] | None = None,
         details: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return {"label": label, "kind": kind, "note": note, "children": children or [], "details": details or []}


def route_tail(canonical: dict[str, Any], validator: AtomicSchemaValidator, diagnostic: str) -> dict[str, Any]:
    base_selections = {
        "research-category.route-leaf": OBSERVATIONAL_ROUTE,
        "research-category.diagnostic-trial": diagnostic,
    }

    def selected_pages(public_strategy: str) -> list[dict[str, Any]]:
        return control_summary(validator, {**base_selections, "basic-information.sync-platform": public_strategy})

    def research_design_flow(tail: dict[str, Any], *, public_strategy: str) -> dict[str, Any]:
        """Return the verified current-page research-design sequence.

        These are local expansion blocks: they make a field appear or disappear
        on the research-design page, but are not claimed to create a new later
        page route.  The exceptional diagnostic yes/no route is already split
        before this function is reached.
        """
        is_chictr_public = public_strategy == "public-on-chictr"
        specimen_fields = (
            "样本名称*、Sample Name*、样本类型*、样本去向*、说明（非必填）"
            if is_chictr_public
            else "样本名称*、样本类型*、样本去向*、说明（非必填）"
        )
        outcome_fields = (
            "指标名称*、Outcome*、指标类型级联*、测量时间点*、Timepoint*、测量方法*、"
            "Metric/method of measurement*、描述（非必填）"
            if is_chictr_public
            else "指标名称*、指标类型级联*、测量时间点*、测量方法*、描述（非必填）"
        )
        biological_sample_template = node(
            "（仅选“是”时）生物标本（可重复）",
            kind="local",
            note=(
                f"显示 1 个生物标本组：{specimen_fields}，"
                "并显示“增加一项”。样本类型：细胞／组织／器官／血液／血清／细菌／其他；"
                "样本去向：使用后销毁／使用后保存／其他。"
            ),
            children=[tail],
        )
        biological_sample = node(
            "是否涉及生物样本采集*：是／否",
            kind="field",
            note="选“是”显示上述生物标本可重复组；选“否”整组消失。用户已核对其余本页及后续结构不变。",
            children=[biological_sample_template],
        )
        outcome_repeat = node(
            "结局指标（可重复）",
            kind="local",
            note=(
                f"初始 1 项；增加一项后复制：{outcome_fields}；删除追加项需二次确认。"
                "一级：主要／次要；已抽样确认主要指标下二级“治疗／安全”，"
                "治疗再显示三级：临床事件／客观化验或检查指标／主观指标。"
            ),
            children=[biological_sample],
        )
        statistics = node(
            "统计分析方法描述*",
            kind="field",
            children=[outcome_repeat],
        )
        allocation = node(
            "分配隐藏方法* → 分配隐藏方法描述*",
            kind="local",
            note="随机分组为“是”且盲法不是两种开放标签时显示；两种开放标签均隐藏本组。",
            children=[statistics],
        )
        unblinding = node(
            "（盲法为双盲／任一单盲／三盲时）揭盲或破盲原则和方法*",
            kind="local",
            note="两种开放标签均不显示此填空，并同时隐藏分配隐藏方法及其描述；其余四种盲法显示三项。",
            children=[allocation],
        )
        blinding = node(
            "盲法*",
            kind="field",
            note="可选双盲、两种单盲、两种开放标签、三盲。两种开放标签同时隐藏“揭盲或破盲原则和方法”与分配隐藏方法组；其余四种显示。",
            children=[unblinding],
        )
        random_description = node(
            "随机数列产生方法* → （随机分组方法不是“其他”时）Randomization Procedure*" if is_chictr_public else "随机数列产生方法*",
            kind="field",
            note="由何人、用什么方法产生随机数列。中国临床试验注册中心公开且随机方法不是“其他”时填写英文配对；方法为“其他”时该英文框隐藏。" if is_chictr_public else "由何人、用什么方法产生随机数列。",
            children=[blinding],
        )
        other_random_method = node(
            "（随机分组方法选“其他”时）请注明具体随机分组方法*",
            kind="local",
            note="只在本页增加该说明字段。",
            children=[random_description],
        )
        random_method = node(
            "（随机分组选“是”时）随机分组方法*",
            kind="local",
            note="简单随机、区组随机、分层随机、中央随机、其他；“其他”显示具体方法说明。",
            children=[other_random_method],
        )
        random_group = node(
            "是否随机分组*：是／否",
            kind="field",
            note="选“是”显示随机方法、随机数列产生方法与盲法局部块；选“否”直接继续统计分析方法。观察性路线中，研究设计类型不会自动选择或禁用本项。",
            children=[random_method],
        )
        if diagnostic == "yes":
            diagnostic_fields = node(
                "诊断研究字段*",
                kind="local",
                note=(
                    "临床参考标准、Gold Standard or Reference Standard、待评估诊断试验、Index test、目标人群、"
                    "Target condition、目标人群例数、易混淆疾病人群、Population with condition、易混淆疾病人群例数；"
                    "诊断试验是／否的跨页差异已在上游路线分开。"
                    if is_chictr_public
                    else "临床参考标准、待评估诊断试验、目标人群、目标人群例数、易混淆疾病人群、易混淆疾病人群例数；诊断试验是／否的跨页差异已在上游路线分开。"
                ),
                children=[random_group],
            )
        else:
            diagnostic_fields = node(
                "研究分组信息（可重复）",
                kind="local",
                note=(
                    "初始 1 组；增加一项复制分组名称*、Group*、样本量*、是否对照组*、干预措施／暴露因素名称*、"
                    "Intervention*、是否联合干预措施*、干预措施／暴露因素类型*、类型相关局部字段及描述。"
                    if is_chictr_public
                    else "初始 1 组；增加一项复制分组名称*、样本量*、是否对照组*、干预措施／暴露因素名称*、"
                    "是否联合干预措施*、干预措施／暴露因素类型*、类型相关局部字段及描述。"
                ),
                children=[random_group],
            )
        exempt_consent = node(
            "是否免除知情同意*：是／否",
            kind="field",
            note="选“否”时，本页增加“预期第一例研究对象签署知情同意日期*”；选“是”时该日期不显示。",
            children=[diagnostic_fields],
        )
        sample_basis = node(
            "样本量* → 样本量计算依据*",
            kind="field",
            children=[exempt_consent],
        )
        exclusion = node(
            "排除标准*（可重复）＋ Exclusion criteria*（可重复）" if is_chictr_public else "排除标准*（可重复）",
            kind="local",
            note="中英文各自初始 1 项；增加一项复制相同文本框；删除追加项需二次确认。" if is_chictr_public else "初始 1 项；增加一项复制相同文本框；删除追加项需二次确认。",
            children=[sample_basis],
        )
        inclusion = node(
            "纳入标准*（可重复）＋ Inclusion criteria*（可重复）" if is_chictr_public else "纳入标准*（可重复）",
            kind="local",
            note="中英文各自初始 1 项；增加一项复制相同文本框；删除追加项需二次确认。" if is_chictr_public else "初始 1 项；增加一项复制相同文本框；删除追加项需二次确认。",
            children=[exclusion],
        )
        vulnerable_types = node(
            "（涉及弱势群体选“是”时）弱势群体类型*",
            kind="local",
            note="儿童、孕期／哺乳期妇女、残障人士、其他弱势人群，为多选；同一行显示“其他弱势人群”的具体说明框。选“否”时整组隐藏。",
            children=[inclusion],
        )
        vulnerable = node(
            "涉及弱势群体*：是／否",
            kind="field",
            note="选“是”显示弱势群体类型；选“否”隐藏。其余本页字段不变。",
            children=[vulnerable_types],
        )
        healthy = node(
            "是否有健康受试者*：是／否",
            kind="field",
            note="现场未观察到额外字段。",
            children=[vulnerable],
        )
        age = node(
            "年龄范围*：最小年龄／单位或不限 → 最大年龄／单位或不限",
            kind="field",
            note="“不限”为本项局部选择；未在本轮观察到后续字段变化。",
            children=[healthy],
        )
        sex = node(
            "性别*：男性／女性／男性女性均可",
            kind="field",
            note="选项仅改变本项取值。",
            children=[age],
        )
        other_design = node(
            "（研究设计选“其他”时）请注明具体的研究设计*",
            kind="local",
            note="只在本页增加该说明字段。",
            children=[sex],
        )
        subtype = node(
            "（队列研究时）研究设计第二级*：回顾性／前瞻性／双向队列研究",
            kind="local",
            note="现场抽样未观察到该三项之间的额外字段变化；观察性路线的病例对照、随机对照和非随机对照均不显示第二级。",
            children=[other_design],
        )
        design = node(
            "研究设计*",
            kind="field",
            note="横断面研究、病例对照研究、队列研究、个案报告、生态学研究、诊断试验、其他、随机对照试验、非随机对照试验。队列显示第二级；“其他”显示具体设计说明。",
            children=[subtype],
        )
        return node(
            "研究设计",
            kind="continuation",
            note="按页面从上至下填写；下列条件均为本页局部结构，不把它们拆成独立后续路线。",
            children=[design],
        )

    def private_post_design_flow() -> dict[str, Any]:
        """Render the manually verified private-route pages after research design."""
        end = node(
            "本路线填写结束",
            kind="continuation",
            note="相关附件为当前路线的最后页；不在此树中执行保存、完成或上传。",
        )
        other_file = node(
            "其他文件（可选）",
            kind="field",
            note="按机构伦理／学术审查需要添加；仅 PDF，且不能同步至中国临床试验注册中心。",
            children=[end],
        )
        consent_file = node(
            "知情同意模板／知情同意豁免申请书*",
            kind="field",
            note="仅 PDF；同步注册中心时建议不超过 10 MB。免除知情同意时准备豁免申请书，否则准备知情同意模板。",
            children=[other_file],
        )
        protocol_file = node(
            "研究方案*",
            kind="field",
            note="上传伦理委员会审查通过后的最终版本；仅 PDF，仅供内部审查及抽查，不公示。",
            children=[consent_file],
        )
        attachments = node(
            "相关附件",
            kind="continuation",
            note="只记录附件要求；不上传文件。",
            children=[protocol_file],
        )
        release_other = node(
            "其他（结果发布方式说明）",
            kind="local",
            note="同行说明文本框始终可见，非必填；选择“其他”时填写相应说明。",
            children=[attachments],
        )
        release_methods = node(
            "结果发布方式*（多选）",
            kind="field",
            note="申请药品／器械、申请专利后公开、学术论文发表、其他；统计结果公开／不公开均不改变本组。",
            children=[release_other],
        )
        result_public = node(
            "是否公开试验完成后统计结果*：公开／不公开",
            kind="field",
            note="两个选项均保留相同的结果发布方式组。",
            children=[release_methods],
        )
        data_details = node(
            "（仅选“共享”时）数据共享详情",
            kind="local",
            note="共享原始数据的方式*、共享数据获取条件（可选）、网址（可选）、数据采集和管理*。选“不共享”时整组隐藏。",
            children=[result_public],
        )
        data_sharing = node(
            "研究数据共享声明*：共享／不共享",
            kind="field",
            note="本页唯一会显示或隐藏共享详情组的选择。",
            children=[data_details],
        )
        disclosure = node(
            "数据共享与信息公开",
            kind="continuation",
            children=[data_sharing],
        )
        record_number = node(
            "平台研究编号（可选）",
            kind="field",
            note="最长 80 个字符。",
            children=[disclosure],
        )
        other_platform_name = node(
            "（研究平台选“其他”时）其他平台名称（可选）",
            kind="local",
            note="中国临床试验注册中心、药物临床试验登记与信息公示平台、临床研究注册（NIH）均不显示该字段。",
            children=[record_number],
        )
        platform = node(
            "研究平台（可选）",
            kind="field",
            note="中国临床试验注册中心／药物临床试验登记与信息公示平台／临床研究注册（NIH）／其他。",
            children=[other_platform_name],
        )
        platform_repeat = node(
            "其他研究平台信息（可重复）",
            kind="local",
            note="初始 1 项；增加一项复制研究平台、条件“其他平台名称”和研究编号。新增项可删除，删除前有是／否确认。",
            children=[platform],
        )
        other_information = node(
            "其他信息",
            kind="continuation",
            children=[platform_repeat],
        )
        return node(
            "招募信息",
            kind="continuation",
            note="当前“观察性研究＋两个平台均不公开”未保存路线的导航中不出现此页；本路线直接进入其他信息。",
            children=[other_information],
        )

    def chictr_public_post_design_flow() -> dict[str, Any]:
        """Render the public-route pages after research design from current UI checks."""
        end = node(
            "本路线填写结束",
            kind="continuation",
            note="相关附件为当前路线的最后页；不在此树中执行保存、完成或上传。",
        )
        other_file = node(
            "其他文件（可选）",
            kind="field",
            note="按机构伦理／学术审查需要添加；仅 PDF，且不能同步至中国临床试验注册中心。",
            children=[end],
        )
        consent_file = node(
            "知情同意模板／知情同意豁免申请书*",
            kind="field",
            note="仅 PDF；同步注册中心时建议不超过 10 MB。免除知情同意时准备豁免申请书，否则准备知情同意模板。",
            children=[other_file],
        )
        protocol_file = node(
            "研究方案*",
            kind="field",
            note="上传伦理委员会审查通过后的最终版本；仅 PDF。此树只记录要求，不执行上传。",
            children=[consent_file],
        )
        attachments = node("相关附件", kind="continuation", note="公开与不公开路线当前均显示同一组三个附件槽位。", children=[protocol_file])
        release_other = node(
            "其他（结果发布方式说明）",
            kind="local",
            note="同行说明文本框始终可见，非必填；选择“其他”时填写相应说明。",
            children=[attachments],
        )
        release_methods = node(
            "结果发布方式*（多选）",
            kind="field",
            note="申请药品／器械、申请专利后公开、学术论文发表、其他；统计结果公开／不公开均不改变本组。",
            children=[release_other],
        )
        result_public = node(
            "是否公开试验完成后统计结果*：公开／不公开",
            kind="field",
            note="两个选项均保留相同的结果发布方式组。",
            children=[release_methods],
        )
        data_details = node(
            "数据共享详情（公开路线中“共享／不共享”均显示）",
            kind="local",
            note="共享原始数据的方式*、The way of sharing IPD*、共享数据获取条件（可选）、网址（可选）、数据采集和管理*、Data collection and Management*。当前公开路线中两个共享声明值均保留本组。",
            children=[result_public],
        )
        data_sharing = node(
            "研究数据共享声明*：共享／不共享",
            kind="field",
            note="与不公开路线不同：当前公开路线中两个选项均显示数据共享详情；因此本项不再拆出显示／隐藏分支。",
            children=[data_details],
        )
        disclosure = node("数据共享与信息公开", kind="continuation", children=[data_sharing])
        record_number = node("平台研究编号（可选）", kind="field", note="最长 80 个字符。", children=[disclosure])
        other_platform_name = node(
            "（研究平台选“其他”时）其他平台名称（可选）",
            kind="local",
            note="中国临床试验注册中心、药物临床试验登记与信息公示平台、临床研究注册（NIH）均不显示该字段。",
            children=[record_number],
        )
        platform = node(
            "研究平台（可选）",
            kind="field",
            note="中国临床试验注册中心／药物临床试验登记与信息公示平台／临床研究注册（NIH）／其他。",
            children=[other_platform_name],
        )
        platform_repeat = node(
            "其他研究平台信息（可重复）",
            kind="local",
            note="初始 1 项；增加一项复制研究平台、条件“其他平台名称”和研究编号。新增项可删除，删除前有是／否确认。",
            children=[platform],
        )
        other_information = node("其他信息", kind="continuation", children=[platform_repeat])
        return node(
            "招募信息",
            kind="continuation",
            note="当前“观察性研究＋中国临床试验注册中心公开”未保存路线的导航中同样不出现此页；本路线直接进入其他信息。",
            children=[other_information],
        )

    def strategy_branch(public_strategy: str, label: str) -> dict[str, Any]:
        pages = selected_pages(public_strategy)
        basic_information = next((page for page in pages if page["id"] == "basic-information"), None)
        later_pages = [page for page in pages if page["id"] not in {"research-category", "basic-information"}]
        continuation = node(
            "后续填写页面",
            kind="continuation",
            note="按该公开策略和当前诊断路线的顺序继续填写。",
            details=later_pages,
        )
        if public_strategy == "private":
            after_research_content = private_post_design_flow()
            research_design = research_design_flow(after_research_content, public_strategy="private")
            research_phase = node(
                "研究阶段*",
                kind="field",
                note="各选项只改变本项取值，不改变本页其他内容或后续页面。",
                children=[research_design],
            )
            extra_name = node(
                "（仅选“是”时）额外措施名称*",
                kind="local",
                note="选“否”时跳过本局部字段并继续研究阶段。",
                children=[research_phase],
            )
            extra_measures = node(
                "是否采用额外的检查、检验、诊断措施*：是／否",
                kind="field",
                note="本页唯一确认会增减字段的选择；选“是”显示额外措施名称。",
                children=[extra_name],
            )
            study_type = node(
                "研究类型*：探索性研究／确证性研究",
                kind="field",
                note="选项不改变本页其余内容或后续页面。",
                children=[extra_measures],
            )
            keywords = node(
                "关键词*（五个输入框）",
                kind="field",
                children=[study_type],
            )
            disease = node(
                "具体疾病或症状*",
                kind="field",
                children=[keywords],
            )
            icd11 = node(
                "国际疾病分类（ICD-11）*（可重复选择）",
                kind="local",
                note="按本版约定统一视为必填；选择具体分类不改变其他字段或后续页面。",
                children=[disease],
            )
            discipline = node(
                "学科分类*（可重复选择）",
                kind="local",
                note="可用“添加”追加；选择具体分类不改变其他字段或后续页面。",
                children=[icd11],
            )
            content_description = node(
                "研究内容*",
                kind="field",
                children=[discipline],
            )
            objective = node(
                "研究目的的具体描述*",
                kind="field",
                children=[content_description],
            )
            primary_purpose = node(
                "主要目的*",
                kind="field",
                note="病因、诊断、治疗、康复、预后、预防、控制、健康维护、筛查、基础研究、其他；仅改变本项取值。",
                children=[objective],
            )
            research_content = node(
                "研究内容",
                kind="continuation",
                note="按当前人工核对的本页顺序填写。",
                children=[primary_purpose],
            )
            study_status = node(
                "研究状态*：研究尚未开始／研究进行中／已结束研究",
                kind="field",
                note="三个选项不改变任何后续字段。",
                children=[research_content],
            )
            participating_repeat = node(
                "（仅选“有”时）临床研究参与单位（可重复）",
                kind="local",
                note="参与单位的机构、地址、负责人及联系方式等字段；可增加一项。选“无”时跳过本局部组。",
                children=[study_status],
            )
            participating = node(
                "临床研究参与单位：有／无",
                kind="field",
                note="多中心本页字段；其后仍进入研究状态。",
                children=[participating_repeat],
            )
            role_conditions = node(
                "本机构角色的局部条件字段",
                kind="local",
                note="角色为“国际参与”或“国内参与”时，填写牵头机构及牵头机构地域（国家；中国时再选省份）。地域选择只改变本页字段。所有角色之后均进入临床研究参与单位。",
                children=[participating],
            )
            multicenter_details = node(
                "（仅选“是”时）多中心信息",
                kind="local",
                note="多中心研究类别：国际多中心／国内多中心；本机构角色：国际总牵头、国际中国片区牵头、国内牵头、国际参与、国际中国片区平行、国内参与。各选择仅改变本页局部字段。",
                children=[role_conditions],
            )
            multicenter = node(
                "是否为多中心试验／研究*：是／否",
                kind="field",
                note="选“是”展开多中心信息；选“否”跳过该局部块并继续研究状态。",
                children=[multicenter_details],
            )
            team_members = node(
                "研究团队成员*",
                kind="field",
                note="成员选择／表格；本页填写项。",
                children=[multicenter],
            )
            contact = node(
                "项目联系人信息",
                kind="field",
                note="联系人、电话、邮箱、通讯地址、所在单位。",
                children=[team_members],
            )
            dsmb = node(
                "数据监察委员会*：具有／不具有",
                kind="field",
                note="两个选项不改变本页其余字段或后续页面。",
                children=[contact],
            )
            implementation = node(
                "实施信息",
                kind="continuation",
                note="按当前人工观察的本页顺序填写。",
                children=[dsmb],
            )
            recruitment_time = node(
                "征募研究对象时间*",
                kind="field",
                note="开始日期 → 结束日期。",
                children=[implementation],
            )
            study_duration = node(
                "研究预计持续时间*",
                kind="field",
                note="开始日期 → 结束日期。",
                children=[recruitment_time],
            )
            total_funds = node(
                "本研究总经费*",
                kind="field",
                note="金额，单位：万元。",
                children=[study_duration],
            )
            donated_material = node(
                "（仅选“是”时）捐赠材料（可重复）",
                kind="local",
                note="材料名称*；材料来源机构*；可用“增加一项”追加同结构材料。选“否”时跳过本局部块，直接继续本研究总经费。",
                children=[total_funds],
            )
            material_flag = node(
                "涉及材料捐献*：是／否",
                kind="field",
                note="只影响本页的“捐赠材料”局部组；不拆出独立后续路线。",
                children=[donated_material],
            )
            funding = node(
                "本研究经费来源（可重复项目组）",
                kind="local",
                note="资助级别（三级级联）*；一级选“其他”时显示“其他名称”；已抽样确认“国家级→国家重点研发计划”出现第三级专项字典。其余长字典值不逐项展开；随后填写立项名称*、立项编号*、涉及国际合作*（是／否）、立项时间*、资金额度*（万元）。",
                children=[material_flag],
            )
            public_name = node(
                "医学研究通俗名称*",
                kind="field",
                children=[funding],
            )
            brief_title = node(
                "医学研究题目简写",
                kind="field",
                children=[public_name],
            )
            private_form = node(
                "医学研究题目*",
                kind="field",
                children=[brief_title],
            )
            return node(
                label,
                kind="branch",
                note="公开策略分支；以下按人工确认的基本信息顺序填写。",
                children=[private_form],
            )
        if public_strategy == "public-on-chictr":
            after_research_content = chictr_public_post_design_flow()
            research_design = research_design_flow(after_research_content, public_strategy="public-on-chictr")
            research_phase = node(
                "研究阶段*",
                kind="field",
                note="各选项只改变本项取值，不改变本页其他内容或后续页面。",
                children=[research_design],
            )
            extra_name = node(
                "（仅选“是”时）额外措施名称*",
                kind="local",
                note="选“否”时跳过本局部字段并继续研究阶段。",
                children=[research_phase],
            )
            extra_measures = node(
                "是否采用额外的检查、检验、诊断措施*：是／否",
                kind="field",
                note="选“是”显示额外措施名称；该局部规则与不公开路线一致。",
                children=[extra_name],
            )
            study_type = node(
                "研究类型*：探索性研究／确证性研究",
                kind="field",
                note="选项不改变本页其余内容或后续页面。",
                children=[extra_measures],
            )
            keywords = node("关键词*（五个输入框）", kind="field", children=[study_type])
            target_disease = node("Target disease*", kind="field", children=[keywords])
            disease = node("具体疾病或症状*", kind="field", children=[target_disease])
            icd11 = node(
                "国际疾病分类（ICD-11）*（可重复选择）",
                kind="local",
                note="按本版约定统一视为必填；选择具体分类不改变其他字段或后续页面。",
                children=[disease],
            )
            discipline = node(
                "学科分类*（可重复选择）",
                kind="local",
                note="可用“添加”追加；选择具体分类不改变其他字段或后续页面。",
                children=[icd11],
            )
            content_description = node("研究内容*", kind="field", children=[discipline])
            objective_english = node("Objectives of Study*", kind="field", children=[content_description])
            objective = node("研究目的的具体描述*", kind="field", children=[objective_english])
            primary_purpose = node(
                "主要目的*",
                kind="field",
                note="病因、诊断、治疗、康复、预后、预防、控制、健康维护、筛查、基础研究、其他；仅改变本项取值。",
                children=[objective],
            )
            research_content = node(
                "研究内容",
                kind="continuation",
                note="中国临床试验注册中心公开时，本页需额外填写 Objectives of Study 与 Target disease。",
                children=[primary_purpose],
            )
            study_status = node(
                "研究状态*：研究尚未开始／研究进行中／已结束研究",
                kind="field",
                note="三个选项不改变任何后续字段。",
                children=[research_content],
            )
            participating_repeat = node(
                "（仅选“有”时）临床研究参与单位（可重复）",
                kind="local",
                note="参与单位的机构、地址、负责人及联系方式等字段；可增加一项。选“无”时跳过本局部组。已知英文机构字段按公开条件显示。",
                children=[study_status],
            )
            participating = node(
                "临床研究参与单位：有／无",
                kind="field",
                note="多中心本页字段；其后仍进入研究状态。",
                children=[participating_repeat],
            )
            role_conditions = node(
                "本机构角色的局部条件字段",
                kind="local",
                note="角色为“国际参与”或“国内参与”时，填写牵头机构及牵头机构地域（国家；中国时再选省份）。地域选择只改变本页字段。所有角色之后均进入临床研究参与单位。",
                children=[participating],
            )
            multicenter_details = node(
                "（仅选“是”时）多中心信息",
                kind="local",
                note="多中心研究类别：国际多中心／国内多中心；本机构角色：国际总牵头、国际中国片区牵头、国内牵头、国际参与、国际中国片区平行、国内参与。各选择仅改变本页局部字段。",
                children=[role_conditions],
            )
            multicenter = node(
                "是否为多中心试验／研究*：是／否",
                kind="field",
                note="选“是”展开多中心信息；选“否”跳过该局部块并继续研究状态。",
                children=[multicenter_details],
            )
            team_members = node("研究团队成员*", kind="field", note="成员选择／表格；本页填写项。", children=[multicenter])
            contact = node(
                "项目联系人信息*",
                kind="field",
                note="项目联系人* → Applicant*；电话*；邮箱*；通讯地址* → applicant's address*；所在单位* → Affiliation of the Registrant*。",
                children=[team_members],
            )
            dsmb = node(
                "数据监察委员会*：具有／不具有",
                kind="field",
                note="两个选项不改变本页其余字段或后续页面。",
                children=[contact],
            )
            implementation = node(
                "实施信息",
                kind="continuation",
                note="中国临床试验注册中心公开时，联系人、通讯地址和所在单位各增加英文配对；其他结构与不公开路线一致。",
                children=[dsmb],
            )
            recruitment_time = node(
                "征募研究对象时间*",
                kind="field",
                note="开始日期 → 结束日期。",
                children=[implementation],
            )
            study_duration = node(
                "研究预计持续时间*",
                kind="field",
                note="开始日期 → 结束日期。",
                children=[recruitment_time],
            )
            total_funds = node(
                "本研究总经费*",
                kind="field",
                note="金额，单位：万元。",
                children=[study_duration],
            )
            donated_material = node(
                "（仅选“是”时）捐赠材料（可重复）",
                kind="local",
                note="材料名称*；Materials*；材料来源机构*；Source(s) of materials*；可用“增加一项”追加同结构材料。选“否”时跳过本局部块。",
                children=[total_funds],
            )
            material_flag = node(
                "涉及材料捐献*：是／否",
                kind="field",
                note="只影响本页的“捐赠材料”局部组；不拆出独立后续路线。",
                children=[donated_material],
            )
            funding = node(
                "本研究经费来源（可重复项目组）",
                kind="local",
                note="资助级别（三级级联）*；一级选“其他”时显示“其他名称”；已抽样确认“国家级→国家重点研发计划”出现第三级专项字典。其余长字典值不逐项展开；随后填写 Source(s) of funding*、立项名称*、立项编号*、涉及国际合作*（是／否）、立项时间*、资金额度*（万元）。",
                children=[material_flag],
            )
            public_title = node("Public title*", kind="field", children=[funding])
            public_name = node("医学研究通俗名称*", kind="field", children=[public_title])
            english_acronym = node("English Acronym", kind="field", children=[public_name])
            brief_title = node("医学研究题目简写", kind="field", children=[english_acronym])
            scientific_title = node("Scientific title*", kind="field", children=[brief_title])
            research_title = node("医学研究题目*", kind="field", children=[scientific_title])
            registration_status = node(
                "填报状态*：预填报／补填报",
                kind="field",
                note="仅在中国临床试验注册中心公开时出现。",
                children=[research_title],
            )
            return node(
                label,
                kind="branch",
                note="公开非强制；国际传统医学平台注册需单独办理；是否获得注册号以对应平台审核意见为准。公开路线已直接抽样核对诊断试验“是”的英文诊断字段、随机方法、盲法与知情同意局部差异；资金长字典和重复组的每一个具体值不在本版本逐项展开。",
                children=[registration_status],
            )
        return node(
            label,
            kind="branch",
            note="公开策略分支；本页字段按所选平台策略显示。",
            details=[basic_information] if basic_information else [],
            children=[continuation],
        )

    sync_platform = find_node(canonical, "sync-platform") or {}
    public_choice = node(
        sync_platform.get("label", "是否需要在其他研究注册平台公开"),
        kind="branch",
        note="基本信息的第一个节点；两个选项可选，暂未开通的平台不可选择。",
        children=[
            strategy_branch("private", "两个平台均不公开"),
            strategy_branch("public-on-chictr", "中国临床试验注册中心公开"),
            node("国际传统医学临床试验注册平台公开（暂未开通）", kind="disabled", note="平台禁用／不可点击；不推断后续字段。"),
        ],
    )
    tcm = node(
        "干预措施（暴露因素）是否以中医理论为指导：是／否",
        kind="local",
        note="用户确认：V1 暂不影响后续流程；保留为单个填写节点。",
    )
    bci = node(
        "是否为侵入式脑机接口用于治疗神经精神疾病的临床研究：是／否",
        kind="local",
        note="用户确认：V1 暂不影响后续流程；保留为单个填写节点。",
        children=[
            node(
                "基本信息",
                kind="continuation",
                note="用户当前观察：诊断试验是／否进入的本页模板相同；此结论不覆盖研究设计页。",
                children=[public_choice],
            )
        ],
    )
    tcm["children"] = [bci]
    return tcm


def build_model(canonical: dict[str, Any], validated: dict[str, Any]) -> dict[str, Any]:
    validator = AtomicSchemaValidator(canonical)
    errors = validator.validate()
    if errors:
        raise ValueError("canonical cannot build flow tree: " + "; ".join(errors[:4]))

    org = find_node(canonical, "implementing-organization") or {}
    classification = find_node(canonical, "research-classification") or {}
    diagnostic = find_node(canonical, "diagnostic-trial") or {}
    product_label = "以产品注册为目的的临床研究"
    investigator_label = "研究者发起的临床研究"
    for option in (find_node(canonical, "research-classification-level-1") or {}).get("options", []):
        text = label_for_option(option)
        if "产品" in text:
            product_label = text
        if "研究者" in text:
            investigator_label = text

    device_children = [
        node("I 类", kind="v2", note="V2 范围，尚未展开"),
        node("II 类", kind="v2", note="V2 范围，尚未展开"),
        node("III 类", kind="v2", note="V2 范围，尚未展开"),
    ]
    ivd_children = [
        node("I 类", kind="v2", note="V2 范围，尚未展开"),
        node("II 类", kind="v2", note="V2 范围，尚未展开"),
        node("III 类", kind="v2", note="V2 范围，尚未展开"),
    ]
    product = node(
        product_label,
        kind="branch-v2",
        note="第二层单选；全部属于 V2，展示分类但不套用观察性规则。",
        children=[
            node(route_label(canonical, "product-drug"), kind="v2", note="V2 范围，尚未展开"),
            node(route_label(canonical, "product-medical-device"), kind="v2", note="V2 范围，尚未展开", children=device_children),
            node(route_label(canonical, "product-ivd"), kind="v2", note="V2 范围，尚未展开", children=ivd_children),
            node(route_label(canonical, "product-special-food"), kind="v2", note="V2 范围，尚未展开"),
        ],
    )
    diagnostic_yes = node(
        f"{diagnostic.get('label', '是否是诊断试验')}：是",
        kind="branch",
        note="已确认后续研究设计结构不同。",
        children=[route_tail(canonical, validator, "yes")],
    )
    diagnostic_no = node(
        f"{diagnostic.get('label', '是否是诊断试验')}：否",
        kind="branch",
        note="已确认后续研究设计结构不同。",
        children=[route_tail(canonical, validator, "no")],
    )
    observational = node(
        route_label(canonical, OBSERVATIONAL_ROUTE),
        kind="branch",
        note="第二层单选；诊断试验是／否形成独立后续路线。",
        children=[diagnostic_yes, diagnostic_no],
    )
    investigator = node(
        investigator_label,
        kind="branch",
        note="第二层单选。",
        children=[
            node(route_label(canonical, "investigator-interventional"), kind="v2", note="V2 范围，尚未展开"),
            observational,
        ],
    )
    root = node(
        org.get("label", "研究实施单位"),
        kind="root",
        note="必填；由登录账号所属机构自动带入。如与实际实施单位不一致，需用户确认；不记录具体机构名称。",
        children=[node(classification.get("label", "研究分类"), kind="classification", note="当前确认两层单选；第三层仅在平台实际出现时加在对应小类下。", children=[product, investigator])],
    )
    return {
        "title": "医学研究登记：纵向填写流程树（V1.0）",
        "canonicalHash": validated["canonical_sha256"],
        "root": root,
        "metrics": {
            "displayRoutes": 2,
            "v2Roots": 5,
            "observationalPages": 4 * len(validator.pages),
            "candidateCount": len(collect(canonical)),
        },
    }


def markdown_node(item: dict[str, Any], depth: int = 0) -> list[str]:
    prefix = "  " * depth + "- "
    suffix = f" — {item['note']}" if item.get("note") else ""
    lines = [prefix + item["label"] + suffix]
    for page in item.get("details", []):
        lines.append("  " * (depth + 1) + f"- {page['label']}（{len(page['fields'])} 个可见字段）")
        for field in page["fields"]:
            required = "必填" if field["required"] is True else "条件必填" if field["required"] == "conditional" else "非必填／待前端校验"
            lines.append(
                "  " * (depth + 2)
                + f"- {field['label']}（`{field['path']}`；{field['widget']}；{required}；{field['grade']}）"
            )
    for child in item.get("children", []):
        lines.extend(markdown_node(child, depth + 1))
    return lines


def markdown(model: dict[str, Any]) -> str:
    return "\n".join(
        [
            f"# {model['title']}",
            "",
            "> 读法：每个框对应一个平台填写节点。只有会改变后续结构的选择才分叉；不影响后续的选项保留在同一个框内。",
            "> 观察性研究的诊断试验“是／否”已确认分叉；中医理论与侵入式脑机接口按用户确认的 V1 局部性假设，不分出后续子树。",
            f"> Canonical SHA-256：`{model['canonicalHash']}`",
            f"> 现有待核验候选条件数：{model['metrics']['candidateCount']}",
            "",
            *markdown_node(model["root"]),
            "",
            "## 证据边界",
            "",
            "- V2 节点仅展示分类，不表示已核验或可填写。",
            "- 页面详情保留 canonical 字段清单；具体未完成核验项仍以覆盖矩阵和账本为准。",
            "",
        ]
    )


def html_document(model: dict[str, Any]) -> str:
    payload = json.dumps(model, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    title = html.escape(model["title"])
    return f'''<!doctype html>
<html lang="zh-CN">
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title>
<style>
:root {{ --bg:#fff; --ink:#111; --line:#111; --root:#fff; }}
* {{ box-sizing:border-box; }}
body {{ margin:0; background:var(--bg); color:var(--ink); font:14px/1.45 "Microsoft YaHei",system-ui,sans-serif; }}
.toolbar {{ position:sticky; top:0; z-index:3; display:flex; gap:8px; align-items:center; flex-wrap:wrap; padding:10px 14px; background:#fff; border-bottom:1px solid #111; }}
.toolbar strong {{ margin-right:6px; }}
button,input {{ font:inherit; }} button {{ padding:6px 10px; border:1px solid #111; background:#fff; border-radius:0; cursor:pointer; }}
.viewport {{ height:calc(100vh - 58px); overflow:auto; cursor:grab; padding:30px 36px 80px; }} .viewport.drag {{ cursor:grabbing; user-select:none; }}
.canvas {{ min-width:1260px; width:max-content; transform-origin:top left; }}
.tree, .tree ul {{ padding:0; margin:0; list-style:none; }}
.tree > li {{ text-align:center; }}
.tree ul {{ display:flex; justify-content:center; padding-top:28px; position:relative; }}
.tree ul::before {{ content:""; position:absolute; top:11px; left:50%; width:1px; height:17px; background:var(--line); }}
.tree li {{ position:relative; text-align:center; padding:28px 10px 0; }}
.tree li::before, .tree li::after {{ content:""; position:absolute; top:11px; width:50%; height:1px; background:var(--line); }}
.tree li::before {{ right:50%; }} .tree li::after {{ left:50%; }}
.tree li:only-child::before, .tree li:only-child::after {{ display:none; }}
.tree li:first-child::before, .tree li:last-child::after {{ background:transparent; }}
.box {{ display:inline-block; max-width:265px; min-width:150px; padding:8px 10px; background:var(--root); border:2px solid #111; border-radius:0; text-align:left; vertical-align:top; }}
.root > .box {{ font-size:20px; font-weight:700; text-align:center; min-width:210px; }}
.classification > .box, .branch > .box {{ border-width:3px; }}
.local > .box {{ border-style:dashed; }}
.v2 > .box {{ border-style:dotted; }}
.disabled > .box {{ border-style:dotted; }}
.continuation > .box {{ border-width:1px; }}
.label {{ font-weight:650; }} .note {{ margin-top:3px; font-size:12px; color:#111; }}
.status {{ display:inline-block; margin-top:5px; padding:1px 5px; border-radius:0; font-size:11px; background:#fff; border:1px solid #111; color:#111; }}
details {{ margin-top:6px; font-size:12px; }} summary {{ cursor:pointer; color:#111; text-decoration:underline; }} .fields {{ margin:5px 0 0; padding-left:16px; text-align:left; max-width:410px; }} .fields li {{ padding:2px 0; text-align:left; }} .fields li::before,.fields li::after {{ display:none; }} code {{ font-family:ui-monospace,Consolas,monospace; font-size:11px; }}
.collapsed > ul {{ display:none; }} .hidden {{ display:none !important; }}
@media (max-width:720px) {{ .viewport {{ padding:20px 12px 60px; }} .canvas {{ min-width:980px; }} }}
</style>
<div class="toolbar">
  <strong>{title}</strong>
  <button id="expand" type="button">全部展开</button>
  <button id="collapse" type="button">折叠页面详情</button>
  <label>缩放 <input id="zoom" type="range" min="45" max="135" value="90"></label>
  <span id="summary"></span>
</div>
<main id="viewport" class="viewport" aria-label="医学研究登记纵向填写流程树"><div id="canvas" class="canvas"></div></main>
<script>
const DATA={payload};
const canvas=document.getElementById('canvas'), viewport=document.getElementById('viewport');
const escapeHtml=s=>String(s).replace(/[&<>"']/g,c=>({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}}[c]));
function status(kind) {{ return kind==='v2'?'V2，未展开':kind==='disabled'?'暂未开通':kind==='local'?'不分支的本地节点':kind==='branch'?'后续结构分支':kind==='continuation'?'后续页面':'填写节点'; }}
function makeNode(item) {{
  const li=document.createElement('li'); li.className=item.kind || 'field';
  const box=document.createElement('div'); box.className='box';
  box.innerHTML='<div class="label">'+escapeHtml(item.label)+'</div>'+(item.note?'<div class="note">'+escapeHtml(item.note)+'</div>':'')+'<span class="status">'+status(item.kind)+'</span>';
  if(item.details && item.details.length) {{
    const details=document.createElement('details'); details.innerHTML='<summary>展开后续页面与字段</summary>';
    const list=document.createElement('ul'); list.className='fields';
    item.details.forEach(page=>{{ const pageItem=document.createElement('li'); pageItem.innerHTML='<strong>'+escapeHtml(page.label)+'</strong>（'+page.fields.length+' 个字段）'; const fieldList=document.createElement('ul'); page.fields.forEach(f=>{{ const x=document.createElement('li'); x.innerHTML=escapeHtml(f.label)+' <code>'+escapeHtml(f.path)+'</code> · '+escapeHtml(f.grade); fieldList.append(x); }}); pageItem.append(fieldList); list.append(pageItem); }});
    details.append(list); box.append(details);
  }}
  li.append(box);
  if(item.children && item.children.length) {{ const ul=document.createElement('ul'); item.children.forEach(child=>ul.append(makeNode(child))); li.append(ul); }}
  return li;
}}
const tree=document.createElement('ul'); tree.className='tree'; tree.append(makeNode(DATA.root)); canvas.append(tree);
document.getElementById('summary').textContent='观察性展示路线 '+DATA.metrics.displayRoutes+' 条；V2 分类节点 '+DATA.metrics.v2Roots+' 个';
document.getElementById('expand').onclick=()=>document.querySelectorAll('details').forEach(x=>x.open=true);
document.getElementById('collapse').onclick=()=>document.querySelectorAll('details').forEach(x=>x.open=false);
document.getElementById('zoom').oninput=e=>canvas.style.transform='scale('+(e.target.value/100)+')';
let drag=null; viewport.onpointerdown=e=>{{ if(e.target.closest('.box')) return; drag={{x:e.clientX,y:e.clientY,left:viewport.scrollLeft,top:viewport.scrollTop}}; viewport.classList.add('drag'); viewport.setPointerCapture(e.pointerId); }};
viewport.onpointermove=e=>{{ if(!drag)return; viewport.scrollLeft=drag.left-(e.clientX-drag.x); viewport.scrollTop=drag.top-(e.clientY-drag.y); }};
viewport.onpointerup=()=>{{ drag=null; viewport.classList.remove('drag'); }};
</script>
</html>'''


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--canonical", type=Path, default=DEFAULT_CANONICAL)
    parser.add_argument("--ledger", type=Path, default=DEFAULT_LEDGER)
    parser.add_argument("--markdown-output", type=Path, default=DEFAULT_MARKDOWN)
    parser.add_argument("--html-output", type=Path, default=DEFAULT_HTML)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    loader = getattr(yaml, "CSafeLoader", yaml.SafeLoader)
    canonical = yaml.load(args.canonical.read_text(encoding="utf-8"), Loader=loader)
    if not isinstance(canonical, dict):
        raise SystemExit("canonical root is not a mapping")
    model = build_model(canonical, validate_ledger(args.canonical, args.ledger))
    if args.check:
        print("Human-first V1 flow tree check passed: " + ", ".join(f"{k}={v}" for k, v in model["metrics"].items()))
        return 0
    args.markdown_output.write_text(markdown(model), encoding="utf-8", newline="\n")
    args.html_output.write_text(html_document(model), encoding="utf-8", newline="\n")
    print("Wrote human-first observational V1 flow tree")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
