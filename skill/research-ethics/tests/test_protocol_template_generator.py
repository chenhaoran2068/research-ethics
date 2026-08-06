"""Regression tests for the deterministic research-protocol skeleton generator."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from render_protocol_template import render, selected_module_ids  # noqa: E402
from validate_protocol_template_assets import validate  # noqa: E402


class ProtocolTemplateGeneratorTest(unittest.TestCase):
    def setUp(self) -> None:
        self.matrix = yaml.safe_load((ROOT / "references" / "protocol-coverage-matrix.yaml").read_text(encoding="utf-8"))
        self.sources = yaml.safe_load((ROOT / "references" / "protocol-template-sources.yaml").read_text(encoding="utf-8"))
        self.canonical = yaml.safe_load((ROOT / "references" / "registration-tree.yaml").read_text(encoding="utf-8"))

    def test_assets_are_self_consistent(self) -> None:
        self.assertEqual([], validate(self.matrix, self.sources, self.canonical))

    def test_diagnostic_route_includes_diagnostic_module(self) -> None:
        content = render(
            self.matrix,
            self.sources,
            self.canonical,
            route="investigator-observational",
            diagnostic_trial="yes",
            conditions={"biospecimen", "public-on-chictr"},
        )
        self.assertIn("诊断试验模块", content)
        self.assertIn("生物样本与人类遗传资源条件模块", content)
        self.assertIn("ChiCTR 公开信息与英文术语核对", content)
        self.assertIn("医院补充层", content)

    def test_non_diagnostic_route_omits_diagnostic_module(self) -> None:
        module_ids = selected_module_ids(
            self.matrix,
            route="investigator-observational",
            diagnostic_trial="no",
            conditions=set(),
        )
        self.assertNotIn("diagnostic-methods", module_ids)

    def test_deferred_route_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "V2"):
            selected_module_ids(
                self.matrix,
                route="investigator-interventional",
                diagnostic_trial="no",
                conditions=set(),
            )


if __name__ == "__main__":
    unittest.main()
