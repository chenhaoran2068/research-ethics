#!/usr/bin/env python3
"""Small isolated regression test for the ledger and unmerged-tree scripts."""

from __future__ import annotations

import hashlib
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

from generate_unmerged_vertical_tree import build_tree, html_document, markdown_index
from validate_dfs_ledger import LedgerValidationError, validate_ledger


def digest(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def signature(letter: str) -> str:
    return "sha256:" + (letter * 64)


CANONICAL = {
    "schema_version": "0.3",
    "workflow": {
        "pages": [
            {
                "id": "research-category",
                "label": "研究类别",
                "nodes": [
                    {
                        "kind": "control",
                        "id": "route-leaf",
                        "path": "research-category.route-leaf",
                        "label": "研究分类",
                        "widget": "select",
                        "options": [{"id": "a", "label": "路线 A"}, {"id": "b", "label": "路线 B"}],
                    }
                ],
            },
            {
                "id": "basic-information",
                "label": "基本信息",
                "nodes": [
                    {
                        "kind": "control",
                        "id": "title",
                        "path": "basic-information.title",
                        "label": "研究题目",
                        "widget": "text",
                        "required": True,
                    }
                ],
            },
        ]
    },
}


class UnmergedTreeTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.canonical = self.root / "canonical.yaml"
        self.ledger = self.root / "ledger.yaml"
        self.canonical.write_text(yaml.safe_dump(CANONICAL, allow_unicode=True, sort_keys=False), encoding="utf-8")
        ledger = {
            "ledger_schema_version": "1.0",
            "canonical": {"path": "references/registration-tree.yaml", "sha256": digest(self.canonical)},
            "structural_branches": [
                {"control_path": "research-category.route-leaf", "structural_options": ["a", "b"]}
            ],
            "routes": [
                self.route("route-a", "a", "a"),
                self.route("route-b", "b", "b"),
            ],
            "safe_merges": [],
        }
        self.ledger.write_text(yaml.safe_dump(ledger, allow_unicode=True, sort_keys=False), encoding="utf-8")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def route(self, route_id: str, option: str, hash_letter: str) -> dict:
        return {
            "route_id": route_id,
            "status": "live_verified",
            "selections": {"research-category.route-leaf": option},
            "structural_decisions": [{"control_path": "research-category.route-leaf", "option_id": option}],
            "display": {
                "complete": True,
                "pages": [
                    {
                        "page_id": "research-category",
                        "disposition": "visited",
                        "field_paths": ["research-category.route-leaf"],
                        "signature_hash": signature(hash_letter),
                    },
                    {
                        "page_id": "basic-information",
                        "disposition": "visited",
                        "field_paths": ["basic-information.title"],
                        "signature_hash": signature(hash_letter),
                    },
                ],
                "leaf": {"status": "reached"},
            },
        }

    def test_post_branch_fields_are_copied_not_rejoined(self) -> None:
        validated = validate_ledger(self.canonical, self.ledger)
        tree, metrics = build_tree(validated)
        self.assertEqual(metrics["leaves"], 2)
        copies: list[dict] = []

        def walk(node: dict) -> None:
            if node.get("canonicalPath") == "basic-information.title":
                copies.append(node)
            for child in node.get("children", []):
                walk(child)

        walk(tree)
        self.assertEqual(len(copies), 2)
        self.assertNotEqual(copies[0]["instanceId"], copies[1]["instanceId"])
        self.assertEqual({item["routeIds"][0] for item in copies}, {"route-a", "route-b"})
        self.assertIn("route-a", markdown_index(validated, metrics))
        self.assertIn("点击任一终点", html_document(tree, metrics))

    def test_rejects_privacy_like_email_in_ledger(self) -> None:
        data = yaml.safe_load(self.ledger.read_text(encoding="utf-8"))
        data["routes"][0]["note"] = "person@example.com"
        self.ledger.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
        with self.assertRaises(LedgerValidationError):
            validate_ledger(self.canonical, self.ledger)

    def test_rejects_declared_structural_option_without_display_coverage(self) -> None:
        data = yaml.safe_load(self.ledger.read_text(encoding="utf-8"))
        data["routes"] = [data["routes"][0]]
        self.ledger.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
        with self.assertRaisesRegex(LedgerValidationError, "lacks display-route coverage"):
            validate_ledger(self.canonical, self.ledger)

    def test_safe_merge_expansion_creates_a_separate_final_route(self) -> None:
        data = yaml.safe_load(self.ledger.read_text(encoding="utf-8"))
        equivalent = self.route("route-b", "b", "b")
        equivalent.pop("route_id")
        equivalent["status"] = "safe_merge_equivalent"
        data["routes"] = [data["routes"][0]]
        data["safe_merges"] = [
            {
                "representative_route_id": "route-a",
                "equivalent_route_id": "route-b",
                "proof_hash": signature("c"),
                "display_route": equivalent,
            }
        ]
        self.ledger.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")

        validated = validate_ledger(self.canonical, self.ledger)
        self.assertEqual(validated["representative_route_count"], 1)
        self.assertEqual(validated["route_count"], 2)
        tree, metrics = build_tree(validated)
        self.assertEqual(metrics["leaves"], 2)
        copies: list[dict] = []

        def walk(node: dict) -> None:
            if node.get("canonicalPath") == "basic-information.title":
                copies.append(node)
            for child in node.get("children", []):
                walk(child)

        walk(tree)
        self.assertEqual(len(copies), 2)
        self.assertEqual({item["routeIds"][0] for item in copies}, {"route-a", "route-b"})
        document = html_document(tree, metrics)
        self.assertIn("for(const el of canvas.querySelectorAll('.node .children'))el.classList.remove('hidden');", document)

    def test_partial_route_is_retained_as_evidence_but_excluded_from_final_tree(self) -> None:
        data = yaml.safe_load(self.ledger.read_text(encoding="utf-8"))
        partial = self.route("route-partial", "a", "d")
        partial["status"] = "partially_verified"
        partial["display"]["complete"] = False
        partial["display"]["pages"] = partial["display"]["pages"][:1]
        partial["display"]["leaf"] = {"status": "blocked"}
        data["routes"].append(partial)
        self.ledger.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")

        validated = validate_ledger(self.canonical, self.ledger)
        self.assertEqual(validated["partial_route_count"], 1)
        self.assertEqual(validated["route_count"], 2)
        tree, metrics = build_tree(validated)
        self.assertEqual(metrics["leaves"], 2)

    def test_partial_route_requires_complete_false(self) -> None:
        data = yaml.safe_load(self.ledger.read_text(encoding="utf-8"))
        data["routes"][0]["status"] = "partially_verified"
        with self.assertRaisesRegex(LedgerValidationError, "complete: false"):
            self.ledger.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
            validate_ledger(self.canonical, self.ledger)

    def test_v1_scope_rejects_deferred_root_route(self) -> None:
        canonical = yaml.safe_load(self.canonical.read_text(encoding="utf-8"))
        canonical["version_scope"] = {
            "version": "v1",
            "supported_root_routes": ["a"],
        }
        self.canonical.write_text(yaml.safe_dump(canonical, allow_unicode=True, sort_keys=False), encoding="utf-8")
        data = yaml.safe_load(self.ledger.read_text(encoding="utf-8"))
        data["canonical"]["sha256"] = digest(self.canonical)
        self.ledger.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
        with self.assertRaisesRegex(LedgerValidationError, "deferred or unsupported root route"):
            validate_ledger(self.canonical, self.ledger)


if __name__ == "__main__":
    unittest.main()
