#!/usr/bin/env python3
"""Assemble the atomic registration tree from reviewed page fragments.

The builder keeps the canonical document's project metadata, scope, evidence
policy, collection rules, and completion boundary.  It replaces only
``workflow.pages`` with the three atomic draft fragments.

By default the command atomically replaces ``registration-tree.yaml`` after
all checks pass.  Use ``--check`` to exercise the complete assembly and
temporary-file validation path without changing the canonical file.
"""

from __future__ import annotations

import argparse
import copy
import os
import re
import stat
import sys
import tempfile
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import yaml


SCHEMA_VERSION = "0.3-draft"
BUILD_STATUS = "atomicity_audit_in_progress"

FRAGMENT_FILENAMES = (
    "pages-0-3.atomic.yaml",
    "pages-4-5.atomic.yaml",
    "pages-6-8.atomic.yaml",
)

# Fragment page IDs are intentionally checked before assembly.  The first
# fragment still uses tab IDs while later fragments already use semantic IDs.
EXPECTED_FRAGMENT_PAGE_IDS = (
    ("tab0", "tab1", "tab2", "tab3"),
    ("research-design", "recruitment-information"),
    (
        "other-information",
        "data-sharing-and-public-disclosure",
        "related-attachments",
    ),
)

EXPECTED_PAGE_IDS = tuple(
    page_id
    for fragment_page_ids in EXPECTED_FRAGMENT_PAGE_IDS
    for page_id in fragment_page_ids
)

EXPECTED_PAGE_LABELS = (
    "研究类别",
    "基本信息",
    "实施信息",
    "研究内容",
    "研究设计",
    "招募信息",
    "其他信息",
    "数据共享与信息公开",
    "相关附件",
)

NODE_KINDS_WITH_GLOBAL_IDS = {"control", "group", "action"}


class AtomicBuildError(RuntimeError):
    """Raised when an input or assembled document violates the contract."""


def _load_yaml_mapping(path: Path) -> dict[str, Any]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise AtomicBuildError(f"Cannot read {path}: {exc}") from exc

    try:
        value = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise AtomicBuildError(f"YAML parse failed for {path}: {exc}") from exc

    if not isinstance(value, dict):
        raise AtomicBuildError(f"Expected a YAML mapping at {path}")
    return value


def _fragment_pages(fragment: Mapping[str, Any], source: Path) -> list[dict[str, Any]]:
    """Return the fragment page list without accepting ambiguous layouts."""

    top_level_pages = fragment.get("pages")
    workflow = fragment.get("workflow")
    workflow_pages = workflow.get("pages") if isinstance(workflow, dict) else None

    present = [pages for pages in (top_level_pages, workflow_pages) if pages is not None]
    if len(present) != 1:
        raise AtomicBuildError(
            f"{source} must define exactly one of pages or workflow.pages"
        )

    pages = present[0]
    if not isinstance(pages, list) or not all(isinstance(page, dict) for page in pages):
        raise AtomicBuildError(f"{source} pages must be a list of mappings")
    return copy.deepcopy(pages)


def _validate_fragment_sequence(
    pages: Sequence[Mapping[str, Any]],
    expected_ids: Sequence[str],
    source: Path,
) -> None:
    actual_ids = tuple(page.get("id") for page in pages)
    if actual_ids != tuple(expected_ids):
        raise AtomicBuildError(
            f"Unexpected page sequence in {source}: {actual_ids!r}; "
            f"expected {tuple(expected_ids)!r}"
        )


def _contains_key(value: Any, key: str) -> bool:
    if isinstance(value, dict):
        return key in value or any(_contains_key(child, key) for child in value.values())
    if isinstance(value, list):
        return any(_contains_key(child, key) for child in value)
    return False


def _validate_candidate_separation(pages: Sequence[Mapping[str, Any]]) -> None:
    """Ensure candidates remain beside, never inside, current page nodes."""

    for page in pages:
        page_id = page.get("id", "<missing-page-id>")
        nodes = page.get("nodes")
        if not isinstance(nodes, list):
            raise AtomicBuildError(f"Page {page_id!r} must contain a nodes list")

        if _contains_key(nodes, "unverified_candidate_nodes"):
            raise AtomicBuildError(
                f"Page {page_id!r} mixes unverified_candidate_nodes into nodes"
            )

        if "unverified_candidate_nodes" in page:
            candidates = page["unverified_candidate_nodes"]
            if not isinstance(candidates, (dict, list)):
                raise AtomicBuildError(
                    f"Page {page_id!r} unverified_candidate_nodes must be a mapping or list"
                )


def _iter_global_node_ids(value: Any, path: str = "$") -> Iterable[tuple[str, str]]:
    """Yield IDs for pages and structural nodes, excluding reusable option IDs."""

    if isinstance(value, dict):
        kind = value.get("kind")
        # A page is only the list item itself.  Descendants such as
        # ``$.workflow.pages[5].visible_if`` share the same bracket count, so
        # bracket counting alone incorrectly classifies condition mappings as
        # pages and demands an ``id`` from them.
        is_page = bool(re.fullmatch(r"\$\.workflow\.pages\[\d+\]", path))
        if is_page or kind in NODE_KINDS_WITH_GLOBAL_IDS:
            node_id = value.get("id")
            if not isinstance(node_id, str) or not node_id:
                raise AtomicBuildError(f"Structural node at {path} has no non-empty id")
            yield node_id, path

        for key, child in value.items():
            yield from _iter_global_node_ids(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _iter_global_node_ids(child, f"{path}[{index}]")


def _validate_global_ids(document: Mapping[str, Any]) -> None:
    paths_by_id: defaultdict[str, list[str]] = defaultdict(list)
    for node_id, path in _iter_global_node_ids(document):
        paths_by_id[node_id].append(path)

    duplicates = {
        node_id: paths
        for node_id, paths in paths_by_id.items()
        if len(paths) > 1
    }
    if duplicates:
        details = "; ".join(
            f"{node_id}: {', '.join(paths)}"
            for node_id, paths in sorted(duplicates.items())
        )
        raise AtomicBuildError(f"Duplicate global structural IDs: {details}")


def _validate_page_order(document: Mapping[str, Any]) -> None:
    workflow = document.get("workflow")
    pages = workflow.get("pages") if isinstance(workflow, dict) else None
    if not isinstance(pages, list):
        raise AtomicBuildError("Assembled document has no workflow.pages list")

    actual_ids = tuple(page.get("id") for page in pages if isinstance(page, dict))
    if actual_ids != EXPECTED_PAGE_IDS:
        raise AtomicBuildError(
            f"Assembled page IDs are {actual_ids!r}; expected {EXPECTED_PAGE_IDS!r}"
        )

    actual_labels = tuple(page.get("label") for page in pages if isinstance(page, dict))
    if actual_labels != EXPECTED_PAGE_LABELS:
        raise AtomicBuildError(
            f"Assembled page labels are {actual_labels!r}; "
            f"expected {EXPECTED_PAGE_LABELS!r}"
        )

    actual_orders = tuple(page.get("order") for page in pages)
    expected_orders = tuple(range(len(EXPECTED_PAGE_IDS)))
    if actual_orders != expected_orders:
        raise AtomicBuildError(
            f"Assembled page orders are {actual_orders!r}; expected {expected_orders!r}"
        )


def _validate_root_contract(document: Mapping[str, Any]) -> None:
    if document.get("schema_version") != SCHEMA_VERSION:
        raise AtomicBuildError(
            f"schema_version must be {SCHEMA_VERSION!r}, got "
            f"{document.get('schema_version')!r}"
        )
    if document.get("status") != BUILD_STATUS:
        raise AtomicBuildError(
            f"status must be {BUILD_STATUS!r}, got {document.get('status')!r}"
        )


def validate_document(document: Mapping[str, Any]) -> None:
    _validate_root_contract(document)
    _validate_page_order(document)
    pages = document["workflow"]["pages"]
    _validate_candidate_separation(pages)
    _validate_global_ids(document)


def assemble_document(
    canonical: Mapping[str, Any],
    fragment_documents: Sequence[tuple[Path, Mapping[str, Any]]],
) -> dict[str, Any]:
    """Return a new canonical document without mutating any input mapping."""

    if len(fragment_documents) != len(EXPECTED_FRAGMENT_PAGE_IDS):
        raise AtomicBuildError(
            f"Expected {len(EXPECTED_FRAGMENT_PAGE_IDS)} fragments, "
            f"got {len(fragment_documents)}"
        )

    merged_pages: list[dict[str, Any]] = []
    for (source, fragment), expected_ids in zip(
        fragment_documents, EXPECTED_FRAGMENT_PAGE_IDS
    ):
        pages = _fragment_pages(fragment, source)
        _validate_fragment_sequence(pages, expected_ids, source)
        merged_pages.extend(pages)

    if len(merged_pages) != len(EXPECTED_PAGE_IDS):
        raise AtomicBuildError(
            f"Expected {len(EXPECTED_PAGE_IDS)} assembled pages, got {len(merged_pages)}"
        )

    # Fragment source files use mixed zero- and one-based page orders.  The
    # canonical order is normalized deterministically to tab0..tab8.
    for index, page in enumerate(merged_pages):
        page["order"] = index

    _validate_candidate_separation(merged_pages)

    assembled = copy.deepcopy(dict(canonical))
    workflow = assembled.get("workflow")
    if not isinstance(workflow, dict):
        raise AtomicBuildError("Canonical document must contain a workflow mapping")

    assembled["schema_version"] = SCHEMA_VERSION
    assembled["status"] = BUILD_STATUS
    workflow["pages"] = merged_pages

    validate_document(assembled)
    return assembled


def _dump_yaml(document: Mapping[str, Any]) -> str:
    text = yaml.safe_dump(
        dict(document),
        allow_unicode=True,
        default_flow_style=False,
        sort_keys=False,
        width=120,
    )
    # Keep a stable final newline across platforms.
    return text.rstrip("\n") + "\n"


def _write_validated_temp(
    target: Path,
    yaml_text: str,
) -> tuple[Path, dict[str, Any]]:
    """Write, fsync, parse, and validate a same-directory temporary file."""

    target.parent.mkdir(parents=True, exist_ok=True)
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

        parsed = _load_yaml_mapping(temp_path)
        validate_document(parsed)
        return temp_path, parsed
    except Exception:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)
        raise


def build(root: Path, canonical_path: Path, check_only: bool) -> None:
    drafts_dir = root / "references" / "drafts"
    fragment_paths = [drafts_dir / name for name in FRAGMENT_FILENAMES]

    canonical = _load_yaml_mapping(canonical_path)
    fragments = [(path, _load_yaml_mapping(path)) for path in fragment_paths]
    assembled = assemble_document(canonical, fragments)
    yaml_text = _dump_yaml(assembled)

    temp_path, parsed_temp = _write_validated_temp(canonical_path, yaml_text)
    try:
        # Validate once more against the parsed temporary content immediately
        # before either deleting it (--check) or atomically replacing target.
        validate_document(parsed_temp)
        if check_only:
            print(
                f"CHECK OK: {len(parsed_temp['workflow']['pages'])} pages; "
                f"canonical unchanged: {canonical_path.name}"
            )
            return

        os.replace(temp_path, canonical_path)
        temp_path = None
        print(f"BUILD OK: atomically replaced {canonical_path.name}")
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)


def _default_root() -> Path:
    return Path(__file__).resolve().parents[1]


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=_default_root(),
        help="research-ethics project root (default: parent of scripts directory)",
    )
    parser.add_argument(
        "--canonical",
        type=Path,
        default=None,
        help="canonical YAML path (default: ROOT/references/registration-tree.yaml)",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="assemble and validate through a temporary file without replacing canonical",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    root = args.root.resolve()
    canonical = (
        args.canonical.resolve()
        if args.canonical is not None
        else root / "references" / "registration-tree.yaml"
    )

    try:
        build(root, canonical, args.check)
    except AtomicBuildError as exc:
        print(f"BUILD FAILED: {exc}", file=sys.stderr)
        return 2
    except OSError as exc:
        print(f"BUILD FAILED: filesystem error: {exc}", file=sys.stderr)
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
