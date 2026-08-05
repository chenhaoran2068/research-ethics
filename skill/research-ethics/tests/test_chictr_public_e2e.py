#!/usr/bin/env python3
"""Regression test for the de-identified ChiCTR-public V1 delivery path."""

from __future__ import annotations

import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from render_copyable_checklist import read_yaml, render  # noqa: E402
from render_copyable_docx import build  # noqa: E402
from validate_dfs_ledger import validate_ledger  # noqa: E402


class ChictrPublicEndToEndTest(unittest.TestCase):
    def test_public_route_has_english_pairs_and_operator_guidance(self) -> None:
        canonical_path = ROOT / "references" / "registration-tree.yaml"
        ledger_path = ROOT / "references" / "dfs-exploration-ledger.yaml"
        intake_path = ROOT / "tests" / "fixtures" / "observational-diagnostic-yes-chictr.yaml"
        validated = validate_ledger(canonical_path, ledger_path)
        markdown = render(read_yaml(canonical_path), read_yaml(intake_path), validated["ledger"])

        self.assertIn("Scientific title", markdown)
        self.assertIn("Public title", markdown)
        self.assertIn("附件准备清单（不上传）", markdown)
        self.assertIn("实时字典使用说明", markdown)
        self.assertNotIn("5.1｜研究设计｜暂不自动生成", markdown)
        self.assertIn("平台规则说明：In the observational route", markdown)

        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "chictr-public.docx"
            build(markdown, output)
            with zipfile.ZipFile(output) as archive:
                document_xml = archive.read("word/document.xml").decode("utf-8")
                core_xml = archive.read("docProps/core.xml").decode("utf-8")
            self.assertIn("Scientific title", document_xml)
            self.assertIn("附件准备清单", document_xml)
            self.assertNotIn("Synthetic Diagnostic Observational Study", core_xml)


if __name__ == "__main__":
    unittest.main()
