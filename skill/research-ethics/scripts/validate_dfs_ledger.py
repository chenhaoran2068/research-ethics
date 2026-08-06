#!/usr/bin/env python3
"""Validate the de-identified DFS ledger used by the unmerged-tree generator.

The ledger is *evidence and route coverage*, not a second form-rule source.
All field labels, widgets, required states and conditions continue to come from
``references/registration-tree.yaml``.  A ledger route records the observed,
ordered canonical field paths for one verified structural leaf.

The file is deliberately optional while live exploration is under way.  Running
this program without it gives a concise, non-zero diagnostic rather than
creating a guessed tree.  Use ``--print-schema-example`` to obtain a commented,
de-identified starting shape; do not copy real account or study values into it.
"""

from __future__ import annotations

import argparse
import hashlib
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import yaml


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CANONICAL = PROJECT_ROOT / "references" / "registration-tree.yaml"
DEFAULT_LEDGER = PROJECT_ROOT / "references" / "dfs-exploration-ledger.yaml"

ROUTE_STATUSES = {
    "live_verified",
    "safe_merge_representative",
    "safe_merge_equivalent",
    "disabled_unreachable",
    "out_of_unsaved_draft_scope",
    "partially_verified",
    "deferred_to_v2",
}
PAGE_DISPOSITIONS = {"visited", "skipped", "blocked"}
LEAF_STATUSES = {"reached", "blocked", "disabled_unreachable", "out_of_unsaved_draft_scope"}
EVIDENCE_GRADES = {
    "current_page_verified",
    "downstream_spot_checked",
    "reused_downstream_structure",
    "full_leaf_replay",
    "high_risk_deeper_check_required",
}
VERIFICATION_LEVELS = {
    "fully_live_verified",
    "sample_verified",
    "assumption_expanded",
    "inferred_from_initial_tree",
    "mismatch_found",
    "out_of_scope_or_blocked",
    "deferred_to_v2",
}
SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")
UUID = re.compile(r"(?i)\b[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}\b")
EMAIL = re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b")
PHONE = re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")


class LedgerValidationError(ValueError):
    """An input issue that prevents deterministic, privacy-safe generation."""


def yaml_load(path: Path) -> Any:
    loader = getattr(yaml, "CSafeLoader", yaml.SafeLoader)
    return yaml.load(path.read_text(encoding="utf-8"), Loader=loader)


def sha256_file(path: Path) -> str:
    """Hash UTF-8 text after normalizing line endings.

    The ledger is a content-integrity record, not a record of a checkout's
    CRLF/LF policy.  Git archives and Windows worktrees may legitimately use
    different line endings for the same canonical YAML, so raw-byte hashing
    would make a valid public release fail after installation.
    """
    normalized = path.read_text(encoding="utf-8").replace("\r\n", "\n").replace("\r", "\n")
    return "sha256:" + hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def children_of(node: dict[str, Any]) -> Iterable[dict[str, Any]]:
    for key in ("nodes", "children"):
        raw = node.get(key)
        if isinstance(raw, list):
            yield from (item for item in raw if isinstance(item, dict))


def node_path(node: dict[str, Any], parent: str, index: int) -> str:
    explicit = node.get("path")
    if isinstance(explicit, str) and explicit:
        return explicit
    return f"{parent}.{node.get('id', f'node-{index}')}"


@dataclass(frozen=True)
class CanonicalIndex:
    pages: dict[str, dict[str, Any]]
    node_by_path: dict[str, dict[str, Any]]
    page_of_path: dict[str, str]
    option_values: dict[str, set[str]]


def _option_value(value: Any) -> str:
    if isinstance(value, dict):
        return str(value.get("id", value.get("value", value.get("label", ""))))
    return str(value)


def make_canonical_index(canonical: dict[str, Any]) -> CanonicalIndex:
    workflow = canonical.get("workflow") if isinstance(canonical, dict) else None
    pages_raw = workflow.get("pages") if isinstance(workflow, dict) else None
    if not isinstance(pages_raw, list):
        raise LedgerValidationError("canonical YAML must contain workflow.pages")
    pages: dict[str, dict[str, Any]] = {}
    nodes: dict[str, dict[str, Any]] = {}
    page_of: dict[str, str] = {}
    options: dict[str, set[str]] = {}

    def visit(page_id: str, node: dict[str, Any], parent: str, index: int) -> None:
        path = node_path(node, parent, index)
        if path in nodes:
            raise LedgerValidationError(f"canonical has duplicate node path: {path}")
        # Candidate controls are still indexed for a route snapshot, but retain
        # their display state.  Their labels and field rules remain canonical.
        nodes[path] = node
        page_of[path] = page_id
        values: set[str] = set()
        if isinstance(node.get("options"), list):
            values.update(_option_value(item) for item in node["options"])
        if isinstance(node.get("options_by_parent"), dict):
            for group in node["options_by_parent"].values():
                if isinstance(group, list):
                    values.update(_option_value(item) for item in group)
        options[path] = values
        for child_index, child in enumerate(children_of(node), start=1):
            visit(page_id, child, path, child_index)

    for page in pages_raw:
        if not isinstance(page, dict) or not isinstance(page.get("id"), str):
            raise LedgerValidationError("each canonical page requires a string id")
        page_id = page["id"]
        if page_id in pages:
            raise LedgerValidationError(f"canonical has duplicate page id: {page_id}")
        pages[page_id] = page
        for index, node in enumerate(page.get("nodes", []), start=1):
            if isinstance(node, dict):
                visit(page_id, node, page_id, index)
        candidates = page.get("unverified_candidate_nodes")
        if isinstance(candidates, dict):
            for index, node in enumerate(candidates.get("nodes", []), start=1):
                if isinstance(node, dict):
                    candidate = dict(node)
                    candidate["_ledger_candidate"] = True
                    visit(page_id, candidate, f"{page_id}.candidate", index)
    return CanonicalIndex(pages, nodes, page_of, options)


def _require_mapping(value: Any, description: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise LedgerValidationError(f"{description} must be a mapping")
    return value


def _require_list(value: Any, description: str) -> list[Any]:
    if not isinstance(value, list):
        raise LedgerValidationError(f"{description} must be a list")
    return value


def _privacy_hits(value: Any, location: str = "ledger") -> list[str]:
    hits: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            lower = str(key).lower()
            if lower in {"name", "real_name", "organization", "telephone", "phone", "email", "account", "cookie", "token", "password", "html", "source", "screenshot"}:
                # Generic keys can occur as technical field labels only in canonical,
                # never in the de-identified ledger evidence.
                hits.append(f"{location}.{key}: prohibited evidence key")
            hits.extend(_privacy_hits(child, f"{location}.{key}"))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            hits.extend(_privacy_hits(child, f"{location}[{index}]"))
    elif isinstance(value, str):
        if EMAIL.search(value):
            hits.append(f"{location}: email-like text")
        if PHONE.search(value):
            hits.append(f"{location}: phone-like text")
        if UUID.search(value):
            hits.append(f"{location}: UUID-like text")
        if "<html" in value.lower() or "<!doctype" in value.lower():
            hits.append(f"{location}: raw HTML-like text")
    return hits


def validate_ledger(canonical_path: Path, ledger_path: Path) -> dict[str, Any]:
    if not canonical_path.exists():
        raise LedgerValidationError(f"canonical YAML does not exist: {canonical_path}")
    if not ledger_path.exists():
        raise LedgerValidationError(
            f"DFS ledger does not exist: {ledger_path}. Live exploration must create it first; "
            "use --print-schema-example for the required de-identified shape."
        )
    canonical = _require_mapping(yaml_load(canonical_path), "canonical YAML")
    ledger = _require_mapping(yaml_load(ledger_path), "DFS ledger")
    index = make_canonical_index(canonical)
    version_scope = canonical.get("version_scope")
    v1_supported_roots: set[str] | None = None
    if isinstance(version_scope, dict) and version_scope.get("version") == "v1":
        raw_supported = version_scope.get("supported_root_routes")
        if not isinstance(raw_supported, list) or not raw_supported:
            raise LedgerValidationError("v1 canonical must declare non-empty version_scope.supported_root_routes")
        v1_supported_roots = {str(item) for item in raw_supported}
    if str(ledger.get("ledger_schema_version")) != "1.0":
        raise LedgerValidationError("ledger_schema_version must be the string '1.0'")
    source = _require_mapping(ledger.get("canonical"), "ledger.canonical")
    expected_hash = sha256_file(canonical_path)
    if source.get("sha256") != expected_hash:
        raise LedgerValidationError(
            "ledger.canonical.sha256 does not match the current canonical YAML; "
            "replay or explicitly regenerate the ledger after canonical changes"
        )

    branches = _require_list(ledger.get("structural_branches"), "ledger.structural_branches")
    branch_paths: set[str] = set()
    for number, raw in enumerate(branches, start=1):
        branch = _require_mapping(raw, f"structural_branches[{number}]")
        path = branch.get("control_path")
        if not isinstance(path, str) or path not in index.node_by_path:
            raise LedgerValidationError(f"structural_branches[{number}].control_path is not canonical")
        if path in branch_paths:
            raise LedgerValidationError(f"duplicate structural branch control_path: {path}")
        branch_paths.add(path)
        options = _require_list(branch.get("structural_options"), f"structural_branches[{number}].structural_options")
        if not options:
            raise LedgerValidationError(f"structural branch has no structural_options: {path}")
        known = index.option_values.get(path, set())
        for option in options:
            if str(option) not in known:
                raise LedgerValidationError(f"unknown structural option {option!r} for {path}")

    routes = _require_list(ledger.get("routes"), "ledger.routes")
    if not routes:
        raise LedgerValidationError("ledger.routes must contain at least one verified/blocked route")
    route_ids: set[str] = set()
    raw_route_ids: set[str] = set()
    raw_routes_by_id: dict[str, dict[str, Any]] = {}
    display_routes: list[dict[str, Any]] = []
    all_route_page_count = 0

    def validate_display_route(route: dict[str, Any], description: str) -> None:
        """Validate one complete, de-identified route usable in the final tree."""
        nonlocal all_route_page_count
        route_id = route.get("route_id")
        if not isinstance(route_id, str) or not re.fullmatch(r"[a-z0-9][a-z0-9._-]{1,127}", route_id):
            raise LedgerValidationError(f"{description}.route_id must be a stable lowercase identifier")
        if route_id in route_ids:
            raise LedgerValidationError(f"duplicate route_id: {route_id}")
        route_ids.add(route_id)
        if route.get("status") not in ROUTE_STATUSES:
            raise LedgerValidationError(f"{description}.status is not an allowed explicit status")
        evidence_grade = route.get("evidence_grade")
        if evidence_grade is not None and evidence_grade not in EVIDENCE_GRADES:
            raise LedgerValidationError(f"{description}.evidence_grade is not an allowed evidence grade")
        verification_level = route.get("verification_level")
        if verification_level is not None and verification_level not in VERIFICATION_LEVELS:
            raise LedgerValidationError(f"{description}.verification_level is not an allowed verification level")
        selections = _require_mapping(route.get("selections"), f"{description}.selections")
        for path, selected in selections.items():
            if path not in index.node_by_path:
                raise LedgerValidationError(f"route {route_id} selects unknown canonical control: {path}")
            known = index.option_values.get(path, set())
            if known and str(selected) not in known:
                raise LedgerValidationError(f"route {route_id} uses unknown option {selected!r} for {path}")
        if v1_supported_roots is not None and "research-category.route-leaf" in selections:
            selected_root = str(selections["research-category.route-leaf"])
            if selected_root not in v1_supported_roots:
                raise LedgerValidationError(
                    f"v1 ledger route {route_id} selects deferred or unsupported root route: {selected_root}"
                )

        decisions = _require_list(route.get("structural_decisions"), f"{description}.structural_decisions")
        decision_paths: set[str] = set()
        for item in decisions:
            decision = _require_mapping(item, f"route {route_id}.structural_decisions item")
            path = decision.get("control_path")
            if path not in branch_paths:
                raise LedgerValidationError(f"route {route_id} declares non-structural or unknown decision: {path}")
            if path in decision_paths:
                raise LedgerValidationError(f"route {route_id} repeats structural decision: {path}")
            decision_paths.add(path)
            if decision.get("option_id") != selections.get(path):
                raise LedgerValidationError(f"route {route_id} decision option must match selections[{path!r}]")

        for path in branch_paths:
            if path in selections and path not in decision_paths:
                raise LedgerValidationError(
                    f"route {route_id} selects structural control {path}, but omits its structural_decision"
                )

        display = _require_mapping(route.get("display"), f"{description}.display")
        is_partial = route.get("status") == "partially_verified"
        if is_partial:
            if display.get("complete") is not False:
                raise LedgerValidationError(
                    f"partial route {route_id} must explicitly declare display.complete: false"
                )
        elif display.get("complete") is not True:
            raise LedgerValidationError(f"route {route_id} must explicitly declare display.complete: true")
        pages = _require_list(display.get("pages"), f"route {route_id}.display.pages")
        seen_pages: set[str] = set()
        for page_number, raw_page in enumerate(pages, start=1):
            snapshot = _require_mapping(raw_page, f"route {route_id}.display.pages[{page_number}]")
            page_id = snapshot.get("page_id")
            if page_id not in index.pages or page_id in seen_pages:
                raise LedgerValidationError(f"route {route_id} has invalid or duplicate page_id: {page_id!r}")
            seen_pages.add(page_id)
            if snapshot.get("disposition") not in PAGE_DISPOSITIONS:
                raise LedgerValidationError(f"route {route_id}, page {page_id}: invalid disposition")
            fields = _require_list(snapshot.get("field_paths"), f"route {route_id}, page {page_id}.field_paths")
            if snapshot.get("disposition") == "visited" and not SHA256.match(str(snapshot.get("signature_hash", ""))):
                raise LedgerValidationError(f"route {route_id}, visited page {page_id}: signature_hash must be sha256:<64 hex>")
            seen_fields: set[str] = set()
            for field_path in fields:
                if not isinstance(field_path, str) or field_path not in index.node_by_path:
                    raise LedgerValidationError(f"route {route_id}, page {page_id}: unknown field path {field_path!r}")
                if index.page_of_path[field_path] != page_id:
                    raise LedgerValidationError(f"route {route_id}: {field_path} belongs to another page")
                if field_path in seen_fields:
                    raise LedgerValidationError(f"route {route_id}, page {page_id}: duplicate field path {field_path}")
                seen_fields.add(field_path)
            all_route_page_count += 1
        for path in branch_paths:
            if path not in selections:
                continue
            page_id = index.page_of_path[path]
            matching = [item for item in pages if item["page_id"] == page_id]
            if not matching or matching[0]["disposition"] != "visited" or path not in matching[0]["field_paths"]:
                raise LedgerValidationError(
                    f"route {route_id} selects structural control {path}, but its visited page snapshot does not include it"
                )
        leaf = _require_mapping(display.get("leaf"), f"route {route_id}.display.leaf")
        if leaf.get("status") not in LEAF_STATUSES:
            raise LedgerValidationError(f"route {route_id}.display.leaf.status is required")
        if not pages:
            raise LedgerValidationError(f"route {route_id} has no observed page snapshots")
        if evidence_grade == "full_leaf_replay" and leaf.get("status") != "reached":
            raise LedgerValidationError(f"route {route_id}: full_leaf_replay requires a reached leaf")
        if verification_level == "fully_live_verified" and leaf.get("status") != "reached":
            raise LedgerValidationError(f"route {route_id}: fully_live_verified requires a reached leaf")

    for number, raw in enumerate(routes, start=1):
        route = _require_mapping(raw, f"routes[{number}]")
        if route.get("status") == "deferred_to_v2":
            route_id = route.get("route_id")
            if not isinstance(route_id, str) or not route_id:
                raise LedgerValidationError(f"routes[{number}].route_id is required")
            raw_route_ids.add(route_id)
            raw_routes_by_id[route_id] = route
            continue
        validate_display_route(route, f"routes[{number}]")
        if route["status"] == "safe_merge_equivalent":
            raise LedgerValidationError(
                f"routes[{number}] must not use safe_merge_equivalent; put it under safe_merges.display_route"
            )
        raw_route_ids.add(route["route_id"])
        raw_routes_by_id[route["route_id"]] = route
        # A partial route is durable exploration evidence, but is deliberately
        # excluded from final-tree construction and structural-option coverage.
        if route["status"] != "partially_verified":
            display_routes.append(route)

    merges = ledger.get("safe_merges", [])
    if not isinstance(merges, list):
        raise LedgerValidationError("ledger.safe_merges must be a list when provided")
    for number, raw in enumerate(merges, start=1):
        item = _require_mapping(raw, f"safe_merges[{number}]")
        for key in ("representative_route_id", "equivalent_route_id", "proof_hash"):
            if not isinstance(item.get(key), str) or not item[key]:
                raise LedgerValidationError(f"safe_merges[{number}].{key} is required")
        if item["representative_route_id"] not in raw_route_ids:
            raise LedgerValidationError(f"safe_merges[{number}] representative route is unknown")
        if item["equivalent_route_id"] in route_ids:
            raise LedgerValidationError(
                f"safe_merges[{number}] equivalent_route_id must be omitted from routes; "
                "it is supplied only by this safe-merge display expansion"
            )
        if not SHA256.match(item["proof_hash"]):
            raise LedgerValidationError(f"safe_merges[{number}].proof_hash must be sha256:<64 hex>")
        raw_display = _require_mapping(item.get("display_route"), f"safe_merges[{number}].display_route")
        if "route_id" in raw_display:
            raise LedgerValidationError(
                f"safe_merges[{number}].display_route must not repeat route_id; "
                "use equivalent_route_id as its only identity"
            )
        if raw_display.get("status") != "safe_merge_equivalent":
            raise LedgerValidationError(
                f"safe_merges[{number}].display_route.status must be 'safe_merge_equivalent'"
            )
        expanded = {"route_id": item["equivalent_route_id"], **raw_display}
        validate_display_route(expanded, f"safe_merges[{number}].display_route")
        representative_decisions = {
            (decision["control_path"], str(decision["option_id"]))
            for decision in raw_routes_by_id[item["representative_route_id"]]["structural_decisions"]
        }
        equivalent_decisions = {
            (decision["control_path"], str(decision["option_id"]))
            for decision in expanded["structural_decisions"]
        }
        if representative_decisions == equivalent_decisions:
            raise LedgerValidationError(
                f"safe_merges[{number}] display route must differ from its representative at a structural decision"
            )
        display_routes.append(expanded)

    for collection_name in ("manual_live_observations", "live_current_page_observations"):
        observations = ledger.get(collection_name, [])
        if not isinstance(observations, list):
            raise LedgerValidationError(f"{collection_name} must be a list when provided")
        for number, observation in enumerate(observations, start=1):
            item = _require_mapping(observation, f"{collection_name}[{number}]")
            if item.get("evidence_grade") not in EVIDENCE_GRADES:
                raise LedgerValidationError(
                    f"{collection_name}[{number}].evidence_grade is required and must be known"
                )
            if item.get("verification_level") not in VERIFICATION_LEVELS:
                raise LedgerValidationError(
                    f"{collection_name}[{number}].verification_level is required and must be known"
                )
            path = item.get("control_path")
            if path not in index.node_by_path:
                raise LedgerValidationError(f"{collection_name}[{number}].control_path is not canonical")
            selections = item.get("selections", {})
            if not isinstance(selections, dict):
                raise LedgerValidationError(f"{collection_name}[{number}].selections must be a mapping when present")
            for selected_path, selected_value in selections.items():
                if selected_path not in index.node_by_path:
                    raise LedgerValidationError(
                        f"{collection_name}[{number}] selects unknown canonical control: {selected_path}"
                    )
                known = index.option_values.get(selected_path, set())
                if known and str(selected_value) not in known:
                    raise LedgerValidationError(
                        f"{collection_name}[{number}] uses unknown option {selected_value!r} for {selected_path}"
                    )

    # A structural branch is not covered merely because its options are declared.
    # Every declared option must have a complete display route, including routes
    # represented by a verified safe merge, before a final tree can be generated.
    for branch in branches:
        path = branch["control_path"]
        expected = {str(option) for option in branch["structural_options"]}
        covered = {
            str(route["selections"][path])
            for route in display_routes
            if path in route["selections"] and str(route["selections"][path]) in expected
        }
        missing = sorted(expected - covered)
        if missing:
            raise LedgerValidationError(
                f"structural branch {path} lacks display-route coverage for option(s): {', '.join(missing)}"
            )

    privacy = _privacy_hits(ledger)
    if privacy:
        raise LedgerValidationError("privacy scan failed:\n- " + "\n- ".join(privacy[:20]))
    return {
        "canonical": canonical,
        "ledger": ledger,
        "index": index,
        "canonical_sha256": expected_hash,
        "route_count": len(display_routes),
        "representative_route_count": len(routes),
        "partial_route_count": sum(1 for route in routes if route["status"] == "partially_verified"),
        "branch_count": len(branches),
        "route_page_count": all_route_page_count,
        "display_routes": display_routes,
    }


SCHEMA_EXAMPLE = """# De-identified DFS exploration ledger; evidence only, never a second rules source.
ledger_schema_version: '1.0'
canonical:
  path: references/registration-tree.yaml
  # Exact SHA-256 of the canonical file at the time routes were replayed.
  sha256: sha256:REPLACE_WITH_64_LOWERCASE_HEX
structural_branches:
  - control_path: research-category.route-leaf
    structural_options: [investigator-observational]
    verification_status: live_verified
  - control_path: research-category.diagnostic-trial
    structural_options: ['no', 'yes']
    verification_status: live_verified
routes:
  - route_id: investigator-observational.diagnostic-no.example
    status: live_verified
    selections:
      research-category.route-leaf: investigator-observational
      research-category.diagnostic-trial: 'no'
    # Only controls shown here create final display forks.
    structural_decisions:
      - control_path: research-category.route-leaf
        option_id: investigator-observational
      - control_path: research-category.diagnostic-trial
        option_id: 'no'
    display:
      complete: true
      pages:
        - page_id: research-category
          disposition: visited
          # Ordered canonical paths only; labels/widgets come from canonical YAML.
          field_paths: [research-category.implementing-organization, research-category.route-leaf, research-category.diagnostic-trial]
          signature_hash: sha256:REPLACE_WITH_64_LOWERCASE_HEX
      leaf:
        status: reached
# A safe merge saves exploration work but does not remove a final visual route.
# Its display_route is a complete de-identified route payload (status,
# selections, structural_decisions, display) without route_id. The identity is
# equivalent_route_id, and status must be safe_merge_equivalent.
safe_merges:
  - representative_route_id: investigator-observational.diagnostic-no.example
    equivalent_route_id: investigator-observational.diagnostic-yes.example
    proof_hash: sha256:REPLACE_WITH_64_LOWERCASE_HEX
    display_route:
      status: safe_merge_equivalent
      selections:
        research-category.route-leaf: investigator-observational
        research-category.diagnostic-trial: 'yes'
      structural_decisions:
        - control_path: research-category.route-leaf
          option_id: investigator-observational
        - control_path: research-category.diagnostic-trial
          option_id: 'yes'
      display:
        complete: true
        pages:
          - page_id: research-category
            disposition: visited
            field_paths: [research-category.implementing-organization, research-category.route-leaf, research-category.diagnostic-trial]
            signature_hash: sha256:REPLACE_WITH_64_LOWERCASE_HEX
        leaf:
          status: reached
"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--canonical", type=Path, default=DEFAULT_CANONICAL)
    parser.add_argument("--ledger", type=Path, default=DEFAULT_LEDGER)
    parser.add_argument("--print-schema-example", action="store_true")
    args = parser.parse_args()
    if args.print_schema_example:
        print(SCHEMA_EXAMPLE, end="")
        return 0
    try:
        result = validate_ledger(args.canonical, args.ledger)
    except LedgerValidationError as error:
        print(f"DFS ledger validation failed: {error}", file=sys.stderr)
        return 2
    print(
        "DFS ledger validation passed: "
        f"routes={result['route_count']}, structural_branches={result['branch_count']}, "
        f"page_snapshots={result['route_page_count']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
