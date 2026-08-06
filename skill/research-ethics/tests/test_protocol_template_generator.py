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
        self.language_pairs = yaml.safe_load(
            (ROOT / "references" / "protocol-template-language-pairs.yaml").read_text(encoding="utf-8")
        )

    def test_assets_are_self_consistent(self) -> None:
        self.assertEqual([], validate(self.matrix, self.sources, self.canonical, self.language_pairs))

    def test_diagnostic_route_includes_diagnostic_module(self) -> None:
        content = render(
            self.matrix,
            self.sources,
            self.canonical,
            route="investigator-observational",
            diagnostic_trial="yes",
            conditions={"biospecimen", "public-on-chictr"},
            language_pairs=self.language_pairs,
        )
        self.assertIn("诊断试验模块", content)
        self.assertIn("生物样本与人类遗传资源条件模块", content)
        self.assertIn("ChiCTR 公开信息与英文术语核对", content)
        self.assertIn("医院补充层（可选的私有适配）", content)
        self.assertIn("中国通用骨架不以该层为前置条件", content)

    def test_china_generic_language_and_hospital_contract(self) -> None:
        scope = self.matrix["scope"]
        self.assertEqual("zh-CN", scope["language_policy"]["canonical_language"])
        self.assertEqual(["zh-CN", "en"], scope["language_policy"]["supported_output_languages"])
        self.assertTrue(scope["language_policy"]["chictr_public_requires_platform_english_pairing"])
        self.assertFalse(scope["hospital_policy"]["generic_generation_requires_hospital_template"])

    def test_bilingual_render_keeps_one_chapter_id_for_two_languages(self) -> None:
        content = render(
            self.matrix,
            self.sources,
            self.canonical,
            route="investigator-observational",
            diagnostic_trial="yes",
            conditions={"public-on-chictr"},
            language="bilingual",
            language_pairs=self.language_pairs,
        )
        self.assertIn("研究题目、版本与修订记录 | Study Title, Version, and Amendment Record (`P-01`)", content)
        self.assertIn("同源事实组 | Shared fact group: `P-01`", content)
        self.assertIn("English paired fact: `[To be completed after researcher/user confirmation]`", content)
        self.assertIn("ChiCTR 公开信息与英文术语核对 | ChiCTR Public Information and English Terminology Check", content)

    def test_english_render_uses_controlled_pair_catalog(self) -> None:
        content = render(
            self.matrix,
            self.sources,
            self.canonical,
            route="investigator-observational",
            diagnostic_trial="no",
            conditions=set(),
            language="en",
            language_pairs=self.language_pairs,
        )
        self.assertIn("China-General Research Protocol Skeleton", content)
        self.assertIn("Core Study Information and Governance", content)
        self.assertIn("Observational-Study Methods Module", content)
        self.assertNotIn("Diagnostic-Study Module", content)

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
