#!/usr/bin/env python3
"""Structural checks for the source-free governed-Study bridge."""

from __future__ import annotations

import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]


class GovernedStudyBridgeTests(unittest.TestCase):
    def setUp(self) -> None:
        with (ROOT / "MODULE_MANIFEST.yaml").open(encoding="utf-8") as handle:
            self.manifest = yaml.safe_load(handle)

    def test_manifest_declares_only_the_supported_bridge_scope(self) -> None:
        self.assertEqual("research-ethics", self.manifest["module_id"])
        self.assertEqual("1.1.1", self.manifest["module_version"])
        self.assertEqual("1.0.0", self.manifest["bridge_interface_version"])
        self.assertEqual(
            "GRW-CAP-200-01",
            self.manifest["governed_system_compatibility"]["required_capability_id"],
        )
        self.assertEqual(
            ["china-mainland"], self.manifest["supported_scope"]["jurisdictions"]
        )
        self.assertIn(
            "researcher-initiated-observational",
            self.manifest["supported_scope"]["research_routes"],
        )

    def test_manifest_refuses_discovery_and_automatic_invocation(self) -> None:
        requirements = self.manifest["governed_study_requirements"]
        self.assertEqual("required", requirements["explicit_user_request"])
        self.assertEqual("required", requirements["exact_study_root"])
        self.assertEqual("required", requirements["explicit_input_allowlist"])
        self.assertEqual("forbidden", requirements["source_discovery"])
        self.assertEqual("forbidden", requirements["automatic_invocation"])

    def test_skill_and_reference_preserve_authority_boundaries(self) -> None:
        skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        bridge = (ROOT / "references" / "governed-study-bridge.md").read_text(
            encoding="utf-8"
        )
        for text in (skill, bridge):
            self.assertIn("governed_study", text)
            self.assertIn("actual_submission", text)
            self.assertIn("test_public", text)
        self.assertIn("must never replace the current protocol", bridge)
        self.assertIn("must never replace the current protocol or prove an ethics", bridge)
        self.assertIn("prospective researcher-assigned", bridge)

    def test_synthetic_fixture_remains_source_free(self) -> None:
        with (ROOT / "tests" / "fixtures" / "governed-study-module-manifest.yaml").open(
            encoding="utf-8"
        ) as handle:
            fixture = yaml.safe_load(handle)
        self.assertEqual("research-ethics", fixture["module_id"])
        self.assertNotIn("project_id", fixture)
        self.assertNotIn("study_root", fixture)
        self.assertNotIn("actual_compliance_evidence", fixture)

    def test_maintenance_cadence_and_escalation_are_documented(self) -> None:
        bridge = (ROOT / "references" / "governed-study-bridge.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("every 90 days", bridge)
        self.assertIn("separate Charter", bridge)
        maintenance = self.manifest["maintenance"]
        self.assertEqual(90, maintenance["routine_public_source_review_interval_days"])
        self.assertIn(
            "bridge-contract-or-system-authority-change",
            maintenance["immediate_review_triggers"],
        )


if __name__ == "__main__":
    unittest.main()
