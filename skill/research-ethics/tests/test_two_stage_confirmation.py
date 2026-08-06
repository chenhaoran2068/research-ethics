"""Regression tests for the ordered two-stage confirmation workflow."""

from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

from confirmation_support import confirmed_intake  # noqa: E402
from confirmation_workflow import pending_completion_items  # noqa: E402
from render_confirmation_batches import render_framework, render_gaps  # noqa: E402
from render_copyable_checklist import render  # noqa: E402
from validate_v1_intake import validate  # noqa: E402


class TwoStageConfirmationTest(unittest.TestCase):
    def setUp(self) -> None:
        with (ROOT / "references" / "registration-tree.yaml").open(encoding="utf-8") as handle:
            self.canonical = yaml.safe_load(handle)

    def test_plan_derived_value_requires_matching_stage_one_confirmation(self) -> None:
        intake = confirmed_intake(self.canonical)
        intake["values"]["basic-information.research-title"] = {
            "value": "合成研究题目",
            "source": "研究计划书第 1 节",
        }
        issues = validate(self.canonical, intake)
        self.assertTrue(any("basic-information.research-title" in issue for issue in issues))

        intake["metadata"]["proposal_confirmation"]["confirmed_values"] = {
            "basic-information.research-title": "合成研究题目"
        }
        self.assertEqual([], validate(self.canonical, intake))

    def test_gap_stage_is_blocked_until_framework_is_confirmed(self) -> None:
        intake = confirmed_intake(self.canonical)
        pending = copy.deepcopy(intake)
        pending["metadata"]["proposal_confirmation"]["status"] = "pending"
        with self.assertRaisesRegex(ValueError, "第一阶段尚未完成"):
            render_gaps(self.canonical, pending)
        self.assertIn("第一阶段：总体框架", render_framework(self.canonical, pending))
        self.assertIn("第二阶段：按平台顺序补全缺失内容", render_gaps(self.canonical, intake))

    def test_renderer_blocks_unfinished_second_stage(self) -> None:
        intake = confirmed_intake(self.canonical)
        intake["metadata"]["completion_confirmation"]["status"] = "pending"
        with self.assertRaisesRegex(ValueError, "填写稿生成被结构性确认门槛"):
            render(self.canonical, intake, {})

    def test_explicit_not_applicable_is_not_rendered_as_generic_pending(self) -> None:
        intake = confirmed_intake(self.canonical)
        optional = next(
            item
            for item in pending_completion_items(self.canonical, intake)
            if not item["required"] and item["kind"] == "field"
        )
        intake["metadata"]["completion_confirmation"]["resolutions"][optional["key"]] = "not_applicable"
        self.assertEqual([], validate(self.canonical, intake))
        markdown = render(self.canonical, intake, {})
        start = markdown.index(optional["label"])
        section = markdown[start : start + 600]
        self.assertIn("不适用／不填写", section)


if __name__ == "__main__":
    unittest.main()
