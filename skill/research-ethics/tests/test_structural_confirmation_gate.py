"""Regression tests for the mandatory user-confirmation gate."""

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
from render_copyable_checklist import render  # noqa: E402
from render_structural_confirmation import render as render_confirmation  # noqa: E402
from validate_v1_intake import validate  # noqa: E402


class StructuralConfirmationGateTest(unittest.TestCase):
    def setUp(self) -> None:
        with (ROOT / "references" / "registration-tree.yaml").open(encoding="utf-8") as handle:
            self.canonical = yaml.safe_load(handle)

    def test_valid_intake_needs_explicit_confirmation_of_every_active_driver(self) -> None:
        intake = confirmed_intake(self.canonical)
        self.assertEqual([], validate(self.canonical, intake))

        missing = copy.deepcopy(intake)
        del missing["metadata"]["structural_confirmation"]["confirmed_selections"]["research-design.random-group"]
        issues = validate(self.canonical, missing)
        self.assertTrue(any("research-design.random-group" in issue for issue in issues))

    def test_renderer_cannot_bypass_pending_confirmation(self) -> None:
        intake = confirmed_intake(self.canonical)
        intake["metadata"]["structural_confirmation"]["status"] = "pending"
        with self.assertRaisesRegex(ValueError, "结构性确认门槛"):
            render(self.canonical, intake, {})

    def test_confirmation_sheet_lists_current_drivers_without_marking_them_confirmed(self) -> None:
        proposed = {
            "metadata": {"operating_mode": "test_public", "structural_confirmation": {"status": "pending"}},
            "selections": {
                "research-category.route-leaf": "investigator-observational",
                "research-category.diagnostic-trial": "no",
                "basic-information.sync-platform": "private",
            },
        }
        sheet = render_confirmation(self.canonical, proposed)
        self.assertIn("是否为多中心试验/研究", sheet)
        self.assertIn("是否随机分组", sheet)
        self.assertIn("待用户明确确认", sheet)
        self.assertNotIn("已记录；仍须核对本轮回复", sheet)


if __name__ == "__main__":
    unittest.main()
