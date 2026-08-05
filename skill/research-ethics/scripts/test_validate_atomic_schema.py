#!/usr/bin/env python3
"""Focused tests for the schema-0.3 atomic validator."""

from __future__ import annotations

import copy
import unittest

from validate_atomic_schema import AtomicSchemaValidator


def valid_document() -> dict:
    root_path = "category.route"
    detail_path = "details.conditional-detail"
    root_signature = {
        "observed_key": root_path,
        "label": "研究路线",
        "widget": "radio",
        "required": True,
        "enabled": True,
        "options": ["a", "b"],
    }
    detail_signature = {
        "observed_key": detail_path,
        "label": "A路线详情",
        "widget": "text",
        "required": True,
        "enabled": True,
    }
    return {
        "schema_version": "0.3-draft",
        "workflow": {
            "pages": [
                {
                    "id": "category",
                    "label": "研究类别",
                    "order": 0,
                    "visible_if": True,
                    "nodes": [
                        {
                            "kind": "control",
                            "id": "route",
                            "label": "研究路线",
                            "widget": "radio",
                            "order": 0,
                            "required": True,
                            "visible_if": True,
                            "options": [
                                {"id": "a", "label": "路线A"},
                                {"id": "b", "label": "路线B"},
                            ],
                        },
                        {
                            "kind": "action",
                            "id": "next",
                            "label": "下一步",
                            "order": 1,
                            "visible_if": True,
                        },
                        {
                            "kind": "control",
                            "id": "internal-cache",
                            "label": "内部缓存",
                            "widget": "hidden",
                            "order": 2,
                            "required": False,
                            "visible_if": False,
                        },
                    ],
                },
                {
                    "id": "details",
                    "label": "详情",
                    "order": 1,
                    "visible_if": {"control": root_path, "equals": "a"},
                    "nodes": [
                        {
                            "kind": "group",
                            "id": "main",
                            "label": "主要信息",
                            "order": 0,
                            "visible_if": True,
                            "children": [
                                {
                                    "kind": "control",
                                    "id": "conditional-detail",
                                    "path": detail_path,
                                    "label": "A路线详情",
                                    "widget": "text",
                                    "order": 0,
                                    "required": True,
                                    "visible_if": True,
                                }
                            ],
                        }
                    ],
                },
            ]
        },
        "verification": {
            "scenarios": [
                {
                    "id": "route-a",
                    "selections": {root_path: "a"},
                    "page_sequence": ["category", "details"],
                    "observed_pages": [
                        {"page_id": "category", "observed_signature": [root_signature]},
                        {"page_id": "details", "observed_signature": [detail_signature]},
                    ],
                },
                {
                    "id": "route-b",
                    "selections": {root_path: "b"},
                    "page_sequence": ["category"],
                    "observed_pages": [
                        {"page_id": "category", "observed_signature": [root_signature]},
                    ],
                },
            ]
        },
    }


class AtomicValidatorTests(unittest.TestCase):
    def test_valid_document_passes(self) -> None:
        self.assertEqual(AtomicSchemaValidator(valid_document()).validate(), [])

    def test_zero_based_order_and_draft_version_are_supported(self) -> None:
        data = valid_document()
        self.assertEqual(data["schema_version"], "0.3-draft")
        self.assertEqual(data["workflow"]["pages"][0]["order"], 0)
        self.assertEqual(data["workflow"]["pages"][0]["nodes"][0]["order"], 0)
        self.assertEqual(AtomicSchemaValidator(data).validate(), [])

    def test_hidden_system_control_is_not_in_observed_signature_or_coverage(self) -> None:
        data = valid_document()
        issues = AtomicSchemaValidator(data).validate()
        self.assertEqual(issues, [])

    def test_string_subfield_shorthand_fails(self) -> None:
        data = valid_document()
        data["notes"] = {"dynamic_subfields": ["字段甲", "字段乙"]}
        issues = AtomicSchemaValidator(data).validate()
        self.assertTrue(any("field shorthand contains string leaves" in issue for issue in issues))

    def test_unknown_condition_option_fails(self) -> None:
        data = copy.deepcopy(valid_document())
        data["workflow"]["pages"][1]["visible_if"]["equals"] = "missing"
        issues = AtomicSchemaValidator(data).validate()
        self.assertTrue(any("unknown option 'missing'" in issue for issue in issues))

    def test_strict_signature_difference_fails(self) -> None:
        data = copy.deepcopy(valid_document())
        data["verification"]["scenarios"][0]["observed_pages"][1]["observed_signature"][0][
            "required"
        ] = False
        issues = AtomicSchemaValidator(data).validate()
        self.assertTrue(any("strict signature mismatch" in issue for issue in issues))


if __name__ == "__main__":
    unittest.main()
