"""Regression test for the reusable Word filling-draft color semantics."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

from docx import Document


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
from render_copyable_docx import PENDING_RED, SUGGESTION_BLUE, build  # noqa: E402


class CopyableDocxStylesTest(unittest.TestCase):
    def test_suggestion_value_blue_pending_red_and_options_black(self) -> None:
        markdown = """# 测试填写稿

- 建议填写／选择：已确认文本；可选：是、否
- 建议填写／选择：待用户确认；可选：是、否
"""
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "draft.docx"
            build(markdown, output)
            paragraphs = Document(output).paragraphs

        confirmed = next(paragraph for paragraph in paragraphs if paragraph.text.startswith("建议填写／选择：已确认文本"))
        pending = next(paragraph for paragraph in paragraphs if paragraph.text.startswith("建议填写／选择：待用户确认"))
        self.assertEqual(str(confirmed.runs[0].font.color.rgb), "000000")
        self.assertEqual(str(confirmed.runs[1].font.color.rgb), str(SUGGESTION_BLUE))
        self.assertEqual(str(confirmed.runs[2].font.color.rgb), "000000")
        self.assertEqual(str(pending.runs[0].font.color.rgb), "000000")
        self.assertEqual(str(pending.runs[1].font.color.rgb), str(PENDING_RED))
        self.assertEqual(str(pending.runs[2].font.color.rgb), "000000")


if __name__ == "__main__":
    unittest.main()
