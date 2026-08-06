from __future__ import annotations

import sys
import unittest
from copy import deepcopy
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

from render_semantic_protocol import (  # noqa: E402
    DEFAULT_COMPOSITION,
    render,
    validate_composition,
    validate_fact_model,
)
from validate_protocol_template_assets import (  # noqa: E402
    DEFAULT_CANONICAL,
    DEFAULT_LANGUAGE_PAIRS,
    DEFAULT_MATRIX,
    DEFAULT_SOURCES,
    load_yaml,
)


def pending(statement_id: str, zh: str, en: str) -> dict:
    return {"id": statement_id, "status": "pending", "prompt_zh": zh, "prompt_en": en}


def confirmed(statement_id: str, zh: str, en: str) -> dict:
    return {"id": statement_id, "status": "confirmed", "zh": zh, "en": en}


class SemanticProtocolRendererTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.matrix = load_yaml(DEFAULT_MATRIX)
        cls.sources = load_yaml(DEFAULT_SOURCES)
        cls.canonical = load_yaml(DEFAULT_CANONICAL)
        cls.language_pairs = load_yaml(DEFAULT_LANGUAGE_PAIRS)
        cls.composition = load_yaml(DEFAULT_COMPOSITION)

    def synthetic_facts(self) -> dict:
        return {
            "metadata": {
                "route": "investigator-observational",
                "diagnostic_trial": "no",
                "conditions": [],
                "fact_confirmation": "synthetic_test_only",
            },
            "chapters": {
                "P-04": {
                    "units": [{
                        "id": "background-and-gap",
                        "statements": [
                            confirmed("p04.synthetic.problem", "合成队列中该临床问题具有明确的长期管理需求。", "In the synthetic cohort, this clinical problem has a clear long-term management need."),
                            confirmed("p04.synthetic.evidence", "现有证据主要来自不同场景，直接外推仍有局限。", "Existing evidence comes mainly from different settings, and direct extrapolation remains limited."),
                            confirmed("p04.synthetic.gap", "本研究拟在预先规定的真实世界数据框架中评估该关联。", "This study will assess the association in a prespecified real-world data framework."),
                        ],
                    }],
                },
                "P-18": {
                    "units": [
                        {"id": "results-publication", "statements": [
                            confirmed("p18.synthetic.results.1", "合成结果将按预先规定的分析计划完整报告。", "Synthetic results will be reported in accordance with the prespecified analysis plan."),
                            confirmed("p18.synthetic.results.2", "不因结果方向选择性省略主要分析。", "Primary analyses will not be selectively omitted according to result direction."),
                        ]},
                        {"id": "data-sharing", "statements": [
                            confirmed("p18.synthetic.share.1", "去标识化数据仅向获得批准的研究者提供。", "De-identified data will be available only to approved researchers."),
                            confirmed("p18.synthetic.share.2", "访问须符合最小必要原则与数据使用协议。", "Access will be subject to data-use agreements and the minimum-necessary principle."),
                        ]},
                        {"id": "data-reuse", "statements": [
                            confirmed("p18.synthetic.reuse.1", "再利用仅限于经批准的相关研究目的。", "Reuse will be limited to approved related research purposes."),
                            confirmed("p18.synthetic.reuse.2", "超出原目的的使用须重新完成必要审查。", "Uses beyond the original purpose will undergo the required renewed review."),
                        ]},
                    ],
                },
            },
        }

    def test_composition_asset_is_valid(self) -> None:
        self.assertEqual(validate_composition(self.composition, self.matrix), [])

    def test_bilingual_output_uses_same_semantic_paragraph(self) -> None:
        facts = self.synthetic_facts()
        self.assertEqual(validate_fact_model(facts, self.composition, self.matrix), [])
        output = render(
            self.matrix, self.sources, self.canonical, self.language_pairs, self.composition, facts, language="bilingual",
        )
        self.assertEqual(sum(1 for line in output.splitlines() if line.startswith("# ")), 1)
        self.assertIn("Presentation status", output)
        self.assertIn("content-and-structure working draft", output)
        self.assertIn(
            "合成队列中该临床问题具有明确的长期管理需求。 现有证据主要来自不同场景，直接外推仍有局限。 本研究拟在预先规定的真实世界数据框架中评估该关联。",
            output,
        )
        self.assertIn(
            "In the synthetic cohort, this clinical problem has a clear long-term management need. Existing evidence comes mainly from different settings, and direct extrapolation remains limited. This study will assess the association in a prespecified real-world data framework.",
            output,
        )
        self.assertIn("#### 研究结果发布", output)
        self.assertIn("#### Results Publication", output)
        self.assertIn("#### 数据共享", output)
        self.assertIn("#### Data Sharing", output)
        self.assertIn("#### 数据再利用边界", output)
        self.assertIn("#### Data Reuse Boundaries", output)

    def test_rejects_single_sentence_narrative(self) -> None:
        facts = self.synthetic_facts()
        facts["chapters"]["P-04"]["units"][0]["statements"] = facts["chapters"]["P-04"]["units"][0]["statements"][:1]
        issues = validate_fact_model(facts, self.composition, self.matrix)
        self.assertTrue(any("sentence-by-sentence" in issue for issue in issues))

    def test_private_template_has_no_confirmed_content(self) -> None:
        template = yaml.safe_load((ROOT / "references" / "protocol-semantic-fact-template.yaml").read_text(encoding="utf-8"))
        for chapter in template["chapters"].values():
            for unit in chapter["units"]:
                for statement in unit["statements"]:
                    self.assertEqual(statement["status"], "pending")
        self.assertEqual(validate_fact_model(template, self.composition, self.matrix), [])


if __name__ == "__main__":
    unittest.main()
