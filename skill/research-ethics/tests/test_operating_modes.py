#!/usr/bin/env python3
"""Regression checks for private actual-submission versus public-test modes."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from validate_v1_intake import validate  # noqa: E402


class OperatingModeTest(unittest.TestCase):
    def setUp(self) -> None:
        with (ROOT / "references" / "registration-tree.yaml").open(encoding="utf-8") as handle:
            self.canonical = yaml.safe_load(handle)

    def test_actual_submission_is_an_explicit_valid_mode(self) -> None:
        intake = {
            "metadata": {"operating_mode": "actual_submission"},
            "selections": {
                "research-category.route-leaf": "investigator-observational",
                "research-category.diagnostic-trial": "no",
                "basic-information.sync-platform": "private",
            },
            "values": {},
            "repeat_groups": {},
        }
        self.assertEqual([], validate(self.canonical, intake))

    def test_unknown_mode_is_rejected(self) -> None:
        intake = {
            "metadata": {"operating_mode": "automatic-redaction"},
            "selections": {
                "research-category.route-leaf": "investigator-observational",
                "research-category.diagnostic-trial": "no",
                "basic-information.sync-platform": "private",
            },
        }
        issues = validate(self.canonical, intake)
        self.assertTrue(any("metadata.operating_mode" in issue for issue in issues))

    def test_skill_instructions_distinguish_the_two_modes(self) -> None:
        skill_text = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("actual_submission", skill_text)
        self.assertIn("test_public", skill_text)
        self.assertIn("不要自动脱敏", skill_text)


if __name__ == "__main__":
    unittest.main()
