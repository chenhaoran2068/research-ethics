#!/usr/bin/env python3
"""Mechanically repair canonical schema-0.3 paths after normalization.

This script intentionally does not normalize human-readable conditions, create
verification scenarios, or infer any live-only rule.  Run the normalization
step first.  ``--check`` builds and audits the repaired document entirely in
memory.  Without ``--check``, the validated result atomically replaces the
target YAML through a same-directory temporary file.
"""

from __future__ import annotations

import argparse
import copy
import os
import stat
import sys
import tempfile
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping, MutableMapping, Sequence

import yaml


PAGE_ID_MAP = {
    "tab0": "research-category",
    "tab1": "basic-information",
    "tab2": "implementation-information",
    "tab3": "research-content",
}

EXPECTED_PAGE_IDS = (
    "research-category",
    "basic-information",
    "implementation-information",
    "research-content",
    "research-design",
    "recruitment-information",
    "other-information",
    "data-sharing-and-public-disclosure",
    "related-attachments",
)

ACTIVE_NODE_KINDS = {"control", "group", "action"}
CONDITION_OPERATORS = {"equals", "in", "not_equals", "not_in", "is_set"}

CONDITION_CONTROL_ALIASES = {
    "basic-information.chictr-publication": "basic-information.sync-platform",
    "basic-information.other-registry-public-disclosure": "basic-information.sync-platform",
    # The canonical path contract is intentionally flat within each page.  Old
    # conditions retained authoring-group names which are not part of a stable
    # control path.
    "research-category.unmarketed-product-repeat.unmarketed-product-type":
        "research-category.unmarketed-product-type",
    "research-category.cell-preparation-information.cell-indication":
        "research-category.cell-indication",
    "research-category.cell-preparation-information.cell-preparation-type":
        "research-category.cell-preparation-type",
    "research-category.cell-preparation-information.cell-preparation-manufacturer":
        "research-category.cell-preparation-manufacturer",
    "research-category.cell-preparation-information.cell-preparation-ftz":
        "research-category.cell-preparation-ftz",
    "research-category.cell-preparation-information.cell-preparation-foreign-enterprise":
        "research-category.cell-preparation-foreign-enterprise",
    "cell-preparation-information.cell-indication": "research-category.cell-indication",
    "cell-preparation-information.cell-preparation-type": "research-category.cell-preparation-type",
    "cell-preparation-information.cell-preparation-manufacturer":
        "research-category.cell-preparation-manufacturer",
    "cell-preparation-information.cell-preparation-ftz": "research-category.cell-preparation-ftz",
    "cell-preparation-information.cell-preparation-foreign-enterprise":
        "research-category.cell-preparation-foreign-enterprise",
    "recruitment-information.overseas-recruitment.overseas-recruitment-flag":
        "recruitment-information.overseas-recruitment-flag",
    "other-information.other-platform-records.platform-name": "other-information.platform-name",
}

SYNC_OPTION_ALIASES = {
    "private": "private",
    "两个平台均不公开": "private",
    "两平台均不公开": "private",
    "public-on-chictr": "public-on-chictr",
    "yes": "public-on-chictr",
    "中国临床试验注册中心公开": "public-on-chictr",
    "traditional-disabled": "traditional-disabled",
    "国际传统医学临床试验注册平台公开（暂未开通）": "traditional-disabled",
}

DIAGNOSTIC_OPTION_ALIASES = {
    "yes": "yes",
    "是": "yes",
    "no": "no",
    "否": "no",
}

IIT_PRODUCT_OPTION_ALIASES = {
    "biomedical": "biomedical",
    "生物医学新技术临床研究": "biomedical",
    "unproduct": "unproduct",
    "涉及未上市的药品、疫苗、医疗器械等产品": "unproduct",
    "none": "none",
    "否": "none",
}

GCP_CELL_PRODUCT_OPTION_ALIASES = {
    "stem": "stem",
    "干细胞临床试验": "stem",
    "somatic": "somatic",
    "体细胞临床试验": "somatic",
    "none": "none",
    "否": "none",
}

REPRESENTATIVE_OPTION_ALIASES = {
    "research-category.cell-indication": {
        "1091.99": "1091.99",
        "其他": "1091.99",
        "other": "1091.99",
        "1091.061": "1091.061",
    },
    "research-category.cell-preparation-type": {
        "1092.99": "1092.99",
        "其他": "1092.99",
        "other": "1092.99",
        "1092.016": "1092.016",
    },
    "research-category.cell-preparation-manufacturer": {
        "1093.99": "1093.99",
        "其他": "1093.99",
        "other": "1093.99",
        "1093.029": "1093.029",
    },
    "research-content.research-phase": {
        "1005.14": "1005.14",
        "其他": "1005.14",
        "other": "1005.14",
        "1005.20": "1005.20",
    },
}

ROUTE_LEAF_OPTIONS = (
    ("product-drug", "以产品注册为目的的临床试验 > 药品"),
    ("product-medical-device", "以产品注册为目的的临床试验 > 医疗器械"),
    ("product-ivd", "以产品注册为目的的临床试验 > 体外诊断试剂"),
    ("product-special-food", "以产品注册为目的的临床试验 > 特殊医学用途配方食品"),
    ("investigator-interventional", "研究者发起的临床研究 > 干预性研究"),
    ("investigator-observational", "研究者发起的临床研究 > 观察性研究"),
)


class RepairError(RuntimeError):
    """Raised when a mechanical repair would require guessing."""


def load_yaml_mapping(path: Path) -> dict[str, Any]:
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise RepairError(f"cannot read YAML {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise RepairError(f"expected a YAML mapping at {path}")
    return value


def workflow_pages(document: Mapping[str, Any]) -> list[MutableMapping[str, Any]]:
    workflow = document.get("workflow")
    pages = workflow.get("pages") if isinstance(workflow, dict) else None
    if not isinstance(pages, list) or not all(isinstance(page, dict) for page in pages):
        raise RepairError("document must contain workflow.pages as a list of mappings")
    return pages  # type: ignore[return-value]


def child_nodes(node: Mapping[str, Any], location: str) -> list[MutableMapping[str, Any]]:
    present = [key for key in ("nodes", "children") if key in node]
    if len(present) != 1:
        raise RepairError(
            f"{location}: group must contain exactly one of nodes/children after normalization"
        )
    children = node[present[0]]
    if not isinstance(children, list) or not all(isinstance(child, dict) for child in children):
        raise RepairError(f"{location}.{present[0]} must be a list of mappings")
    return children  # type: ignore[return-value]


def iter_active_nodes(
    page: Mapping[str, Any],
    page_index: int,
) -> Iterable[tuple[MutableMapping[str, Any], str]]:
    nodes = page.get("nodes")
    if not isinstance(nodes, list) or not all(isinstance(node, dict) for node in nodes):
        raise RepairError(f"workflow.pages[{page_index}].nodes must be a list of mappings")

    def walk(
        values: list[MutableMapping[str, Any]],
        location: str,
    ) -> Iterable[tuple[MutableMapping[str, Any], str]]:
        for index, node in enumerate(values):
            node_location = f"{location}[{index}]"
            kind = node.get("kind")
            if kind not in ACTIVE_NODE_KINDS:
                raise RepairError(
                    f"{node_location}.kind must be one of {sorted(ACTIVE_NODE_KINDS)}, "
                    f"found {kind!r}"
                )
            yield node, node_location
            if kind == "group":
                yield from walk(child_nodes(node, node_location), f"{node_location}.children")

    yield from walk(nodes, f"workflow.pages[{page_index}].nodes")


def validate_normalization_precondition(document: Mapping[str, Any]) -> None:
    """Reject pre-normalized order shapes instead of silently inventing order."""

    pages = workflow_pages(document)
    page_orders: set[int] = set()
    for page_index, page in enumerate(pages):
        order = page.get("order")
        if isinstance(order, bool) or not isinstance(order, int) or order < 0:
            raise RepairError(
                f"workflow.pages[{page_index}].order must be a normalized non-negative integer"
            )
        if order in page_orders:
            raise RepairError(f"duplicate page order {order}")
        page_orders.add(order)

        sibling_stack: list[tuple[list[MutableMapping[str, Any]], str]] = []
        nodes = page.get("nodes")
        if not isinstance(nodes, list):
            raise RepairError(f"workflow.pages[{page_index}].nodes must be normalized first")
        sibling_stack.append((nodes, f"workflow.pages[{page_index}].nodes"))
        while sibling_stack:
            siblings, location = sibling_stack.pop()
            orders: set[int] = set()
            for node_index, node in enumerate(siblings):
                node_location = f"{location}[{node_index}]"
                if not isinstance(node, dict):
                    raise RepairError(f"{node_location} must be a mapping")
                node_order = node.get("order")
                if (
                    isinstance(node_order, bool)
                    or not isinstance(node_order, int)
                    or node_order < 0
                ):
                    raise RepairError(
                        f"{node_location}.order must be a normalized non-negative integer"
                    )
                if node_order in orders:
                    raise RepairError(f"{node_location}.order duplicates sibling order {node_order}")
                orders.add(node_order)
                if node.get("kind") == "group":
                    children = child_nodes(node, node_location)
                    sibling_stack.append((children, f"{node_location}.children"))


def rename_pages(document: MutableMapping[str, Any]) -> dict[str, str]:
    pages = workflow_pages(document)
    rename_map: dict[str, str] = {}
    for index, page in enumerate(pages):
        old_id = page.get("id")
        if not isinstance(old_id, str) or not old_id:
            raise RepairError(f"workflow.pages[{index}].id must be a non-empty string")
        new_id = PAGE_ID_MAP.get(old_id, old_id)
        page["id"] = new_id
        rename_map[old_id] = new_id

    actual_ids = tuple(page.get("id") for page in pages)
    if actual_ids != EXPECTED_PAGE_IDS:
        raise RepairError(
            f"page IDs after deterministic rename are {actual_ids!r}; "
            f"expected {EXPECTED_PAGE_IDS!r}"
        )
    return rename_map


def expected_node_path(page_id: str, node: Mapping[str, Any]) -> str:
    node_id = node.get("id")
    if not isinstance(node_id, str) or not node_id:
        raise RepairError(f"active node on page {page_id!r} has no non-empty id")
    if page_id == "research-category" and node_id == "diagnostic-test-classification":
        return "research-category.diagnostic-trial"
    return f"{page_id}.{node_id}"


def assign_stable_paths(document: MutableMapping[str, Any]) -> None:
    seen: dict[str, str] = {}
    for page_index, page in enumerate(workflow_pages(document)):
        page_id = str(page["id"])
        for node, location in iter_active_nodes(page, page_index):
            expected = expected_node_path(page_id, node)
            existing = node.get("path")
            if existing is not None and existing != expected:
                raise RepairError(
                    f"{location}.path is {existing!r}, expected {expected!r}; "
                    "existing paths are never guessed or overwritten"
                )
            if expected in seen:
                raise RepairError(
                    f"duplicate stable path {expected!r}: {seen[expected]} and {location}"
                )
            node["path"] = expected
            seen[expected] = location


def structured_options(
    options: Sequence[tuple[str, str]],
    *,
    disabled_id: str | None = None,
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for option_id, label in options:
        item: dict[str, Any] = {"id": option_id, "label": label}
        if option_id == disabled_id:
            item["enabled"] = False
            item["status"] = "disabled_unavailable"
        result.append(item)
    return result


def find_active_node(
    document: Mapping[str, Any],
    page_id: str,
    node_id: str,
) -> MutableMapping[str, Any]:
    matches: list[MutableMapping[str, Any]] = []
    for page_index, page in enumerate(workflow_pages(document)):
        if page.get("id") != page_id:
            continue
        for node, _ in iter_active_nodes(page, page_index):
            if node.get("id") == node_id:
                matches.append(node)
    if len(matches) != 1:
        raise RepairError(
            f"expected exactly one active node {page_id}.{node_id}, found {len(matches)}"
        )
    return matches[0]


def add_route_leaf(document: MutableMapping[str, Any]) -> None:
    page = next(
        (page for page in workflow_pages(document) if page.get("id") == "research-category"),
        None,
    )
    if page is None:
        raise RepairError("research-category page not found")
    nodes = page.get("nodes")
    if not isinstance(nodes, list):
        raise RepairError("research-category.nodes must be a list")

    existing = [node for node in nodes if isinstance(node, dict) and node.get("id") == "route-leaf"]
    if len(existing) > 1:
        raise RepairError("multiple research-category.route-leaf nodes found")
    if existing:
        node = existing[0]
        expected_options = structured_options(ROUTE_LEAF_OPTIONS)
        expected_contract = {
            "kind": "control",
            "id": "route-leaf",
            "path": "research-category.route-leaf",
            "widget": "hidden",
            "required": False,
            "visible_if": False,
            "options": expected_options,
        }
        for key, expected in expected_contract.items():
            if node.get(key) != expected:
                raise RepairError(
                    f"existing route-leaf.{key} is {node.get(key)!r}, expected {expected!r}"
                )
        return

    active_orders = [
        node.get("order")
        for node in nodes
        if isinstance(node, dict) and isinstance(node.get("order"), int)
    ]
    if len(active_orders) != len(nodes):
        raise RepairError("research-category node orders must be normalized before route-leaf insertion")
    order = max(active_orders, default=-1) + 1
    nodes.append(
        {
            "kind": "control",
            "id": "route-leaf",
            "path": "research-category.route-leaf",
            "label": "研究分类（派生根叶）",
            "technical_name": None,
            "widget": "hidden",
            "order": order,
            "required": False,
            "visible_if": False,
            "options": structured_options(ROUTE_LEAF_OPTIONS),
            "value_source": "由研究分类一级、二级及必要时三级选择机械派生",
            "source_classification": "derived_internal_control",
            "user_copyable": False,
            "derived_from": [
                "research-category.research-classification-level-1",
                "research-category.research-classification-level-2",
                "research-category.research-classification-level-3",
            ],
        }
    )


def normalize_cross_page_controls(document: MutableMapping[str, Any]) -> None:
    diagnostic = find_active_node(
        document,
        "research-category",
        "diagnostic-test-classification",
    )
    diagnostic["path"] = "research-category.diagnostic-trial"
    diagnostic["options"] = structured_options((("yes", "是"), ("no", "否")))

    sync = find_active_node(document, "basic-information", "sync-platform")
    if sync.get("path") != "basic-information.sync-platform":
        raise RepairError(
            f"sync-platform path is {sync.get('path')!r}, expected "
            "'basic-information.sync-platform'"
        )
    sync["options"] = structured_options(
        (
            ("private", "两个平台均不公开"),
            ("public-on-chictr", "中国临床试验注册中心公开"),
            (
                "traditional-disabled",
                "国际传统医学临床试验注册平台公开（暂未开通）",
            ),
        ),
        disabled_id="traditional-disabled",
    )

    iit_product = find_active_node(document, "research-category", "iit-product-attribute")
    iit_product["options"] = structured_options(
        (
            ("biomedical", "生物医学新技术临床研究"),
            ("unproduct", "涉及未上市的药品、疫苗、医疗器械等产品"),
            ("none", "否"),
        )
    )

    gcp_cell_product = find_active_node(
        document,
        "research-category",
        "gcp-cell-product-attribute",
    )
    gcp_cell_product["options"] = structured_options(
        (
            ("stem", "干细胞临床试验"),
            ("somatic", "体细胞临床试验"),
            ("none", "否"),
        )
    )

    representative_dictionaries = (
        (
            "research-category",
            "cell-indication",
            (("1091.99", "其他"), ("1091.061", "视神经脊髓炎")),
        ),
        (
            "research-category",
            "cell-preparation-type",
            (("1092.99", "其他"), ("1092.016", "人iPSC来源心肌细胞")),
        ),
        (
            "research-category",
            "cell-preparation-manufacturer",
            (("1093.99", "其他"), ("1093.029", "湖南光琇高新生命科技有限公司")),
        ),
        (
            "implementation-information",
            "leading-country",
            (("1", "中国"), ("28", "日本")),
        ),
        (
            "implementation-information",
            "branch-country",
            (("1", "中国"), ("28", "日本")),
        ),
    )
    for page_id, node_id, options in representative_dictionaries:
        control = find_active_node(document, page_id, node_id)
        control["options"] = structured_options(options)
        control["options_scope"] = "condition_and_branch_representatives"

    organization_role = find_active_node(
        document,
        "implementation-information",
        "organization-role",
    )
    organization_role["options"] = structured_options(
        (
            ("1", "国际总牵头"),
            ("2", "国际中国片区牵头"),
            ("3", "国内牵头"),
            ("4", "国际参与"),
            ("5", "国际中国片区平行"),
            ("6", "国内参与"),
        )
    )

    research_phase = find_active_node(document, "research-content", "research-phase")
    research_phase["options"] = structured_options(
        (("1005.14", "其他"), ("1005.20", "不适用"))
    )
    research_phase["options_scope"] = "condition_and_branch_representatives"


def rewrite_control_reference(reference: str, page_renames: Mapping[str, str]) -> str:
    if reference in CONDITION_CONTROL_ALIASES:
        return CONDITION_CONTROL_ALIASES[reference]
    for old_page, new_page in page_renames.items():
        prefix = f"{old_page}."
        if old_page != new_page and reference.startswith(prefix):
            reference = f"{new_page}.{reference[len(prefix):]}"
            break
    # Legacy tab0.* references need page renaming before their obsolete group
    # segment can be recognized and flattened.
    return CONDITION_CONTROL_ALIASES.get(reference, reference)


def normalize_condition_value(control: str, value: Any, location: str) -> Any:
    if control == "basic-information.sync-platform":
        if not isinstance(value, str) or value not in SYNC_OPTION_ALIASES:
            raise RepairError(
                f"{location}: cannot unambiguously map sync-platform value {value!r}"
            )
        return SYNC_OPTION_ALIASES[value]
    if control == "research-category.diagnostic-trial":
        if not isinstance(value, str) or value not in DIAGNOSTIC_OPTION_ALIASES:
            raise RepairError(
                f"{location}: cannot unambiguously map diagnostic value {value!r}"
            )
        return DIAGNOSTIC_OPTION_ALIASES[value]
    if control == "research-category.iit-product-attribute":
        if not isinstance(value, str) or value not in IIT_PRODUCT_OPTION_ALIASES:
            raise RepairError(
                f"{location}: cannot unambiguously map IIT product attribute value {value!r}"
            )
        return IIT_PRODUCT_OPTION_ALIASES[value]
    if control == "research-category.gcp-cell-product-attribute":
        if not isinstance(value, str) or value not in GCP_CELL_PRODUCT_OPTION_ALIASES:
            raise RepairError(
                f"{location}: cannot unambiguously map GCP cell product attribute value {value!r}"
            )
        return GCP_CELL_PRODUCT_OPTION_ALIASES[value]
    if control in REPRESENTATIVE_OPTION_ALIASES:
        aliases = REPRESENTATIVE_OPTION_ALIASES[control]
        if not isinstance(value, str) or value not in aliases:
            raise RepairError(
                f"{location}: cannot unambiguously map representative dictionary "
                f"value {value!r} for {control!r}"
            )
        return aliases[value]
    return value


def rewrite_condition_references(
    value: Any,
    page_renames: Mapping[str, str],
    location: str = "$",
) -> None:
    if isinstance(value, dict):
        control = value.get("control")
        if isinstance(control, str):
            rewritten = rewrite_control_reference(control, page_renames)
            value["control"] = rewritten
            for operator in ("equals", "not_equals"):
                if operator in value:
                    value[operator] = normalize_condition_value(
                        rewritten,
                        value[operator],
                        f"{location}.{operator}",
                    )
            for operator in ("in", "not_in"):
                if operator in value:
                    items = value[operator]
                    if not isinstance(items, list):
                        raise RepairError(f"{location}.{operator} must be a list")
                    value[operator] = [
                        normalize_condition_value(
                            rewritten,
                            item,
                            f"{location}.{operator}[{index}]",
                        )
                        for index, item in enumerate(items)
                    ]
        for key, child in value.items():
            rewrite_condition_references(child, page_renames, f"{location}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            rewrite_condition_references(child, page_renames, f"{location}[{index}]")


def option_ids(control: Mapping[str, Any]) -> set[str]:
    options = control.get("options")
    if not isinstance(options, list):
        return set()
    result: set[str] = set()
    for option in options:
        if isinstance(option, str):
            result.add(option)
        elif isinstance(option, dict) and isinstance(option.get("id"), str):
            result.add(option["id"])
    return result


def condition_reference_audit(document: Mapping[str, Any]) -> tuple[list[str], list[str]]:
    """Return unknown control and option references without inferring repairs."""

    controls: dict[str, Mapping[str, Any]] = {}
    for page_index, page in enumerate(workflow_pages(document)):
        for node, location in iter_active_nodes(page, page_index):
            if node.get("kind") != "control":
                continue
            path = node.get("path")
            if not isinstance(path, str) or not path:
                raise RepairError(f"{location}.path is missing after path assignment")
            if path in controls:
                raise RepairError(f"duplicate active control path {path!r}")
            controls[path] = node

    unknown_controls: list[str] = []
    unknown_options: list[str] = []

    def walk(value: Any, location: str) -> None:
        if isinstance(value, dict):
            control_ref = value.get("control")
            operators = [operator for operator in CONDITION_OPERATORS if operator in value]
            if control_ref is not None:
                if not isinstance(control_ref, str) or not control_ref:
                    unknown_controls.append(
                        f"{location}.control: unresolved non-string reference {control_ref!r}"
                    )
                elif control_ref not in controls:
                    unknown_controls.append(
                        f"{location}.control: unknown control {control_ref!r}"
                    )
                elif operators:
                    declared = option_ids(controls[control_ref])
                    if declared:
                        for operator in operators:
                            if operator == "is_set":
                                continue
                            raw = value[operator]
                            candidates = raw if operator in {"in", "not_in"} else [raw]
                            if not isinstance(candidates, list):
                                unknown_options.append(
                                    f"{location}.{operator}: expected option list, found {raw!r}"
                                )
                                continue
                            for candidate in candidates:
                                if candidate not in declared:
                                    unknown_options.append(
                                        f"{location}.{operator}: unknown option {candidate!r} "
                                        f"for {control_ref!r}"
                                    )
            for key, child in value.items():
                walk(child, f"{location}.{key}")
        elif isinstance(value, list):
            for index, child in enumerate(value):
                walk(child, f"{location}[{index}]")

    walk(document, "$")
    return unknown_controls, unknown_options


def repair_document(source: Mapping[str, Any]) -> dict[str, Any]:
    document = copy.deepcopy(dict(source))
    if document.get("schema_version") not in {"0.3", "0.3-draft"}:
        raise RepairError(
            f"expected schema_version 0.3 or 0.3-draft, found "
            f"{document.get('schema_version')!r}"
        )
    validate_normalization_precondition(document)
    page_renames = rename_pages(document)
    assign_stable_paths(document)
    add_route_leaf(document)
    normalize_cross_page_controls(document)
    rewrite_condition_references(document, page_renames)

    unknown_controls, unknown_options = condition_reference_audit(document)
    if unknown_controls or unknown_options:
        details = "\n".join([*unknown_controls, *unknown_options])
        raise RepairError(
            "path repair left unresolved references; no replacement was written:\n" + details
        )
    return document


def dump_yaml(document: Mapping[str, Any]) -> str:
    return yaml.safe_dump(
        dict(document),
        allow_unicode=True,
        default_flow_style=False,
        sort_keys=False,
        width=120,
    ).rstrip("\n") + "\n"


def console_safe_path(path: Path, *, stream: Any = sys.stdout) -> str:
    """Render Unicode paths even when Windows stdout/stderr uses CP932."""

    encoding = getattr(stream, "encoding", None) or "utf-8"
    return str(path).encode(encoding, errors="backslashreplace").decode(encoding)


def write_validated_temp(target: Path, yaml_text: str) -> Path:
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            dir=target.parent,
            prefix=f".{target.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            handle.write(yaml_text)
            handle.flush()
            os.fsync(handle.fileno())
            temp_path = Path(handle.name)
        if target.exists():
            os.chmod(temp_path, stat.S_IMODE(target.stat().st_mode))

        parsed = load_yaml_mapping(temp_path)
        repaired_again = repair_document(parsed)
        if repaired_again != parsed:
            raise RepairError("temporary output is not idempotently repaired")
        return temp_path
    except Exception:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)
        raise


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--canonical",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "references" / "registration-tree.yaml",
        help="target canonical YAML",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="repair and audit in memory without replacing the YAML",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    target = args.canonical.resolve()
    temp_path: Path | None = None
    try:
        source = load_yaml_mapping(target)
        repaired = repair_document(source)
        changed = repaired != source
        if args.check:
            print(
                "PATH CHECK OK: unknown_control_refs=0, unknown_option_refs=0, "
                f"changed={str(changed).lower()}, "
                f"canonical_unchanged={console_safe_path(target)}"
            )
            return 0
        if not changed:
            print(f"PATH REPAIR OK: no changes required: {console_safe_path(target)}")
            return 0

        temp_path = write_validated_temp(target, dump_yaml(repaired))
        os.replace(temp_path, target)
        temp_path = None
        print(
            "PATH REPAIR OK: atomically replaced canonical; "
            "unknown_control_refs=0, unknown_option_refs=0; "
            "verification.scenarios unchanged"
        )
        return 0
    except RepairError as exc:
        print(f"PATH REPAIR FAILED: {exc}", file=sys.stderr)
        return 2
    except OSError as exc:
        print(f"PATH REPAIR FAILED: filesystem error: {exc}", file=sys.stderr)
        return 3
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)


if __name__ == "__main__":
    raise SystemExit(main())
