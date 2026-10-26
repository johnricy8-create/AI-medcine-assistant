"""规则规划器测试。"""

from __future__ import annotations

import unittest

from app.config import PROJECT_ROOT
from app.graph.planner import RuleBasedPlanner
from app.ingest.entity_linker import EntityLinker
from app.schemas import SourceType


class TestPlanner(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.linker = EntityLinker.from_yaml(
            PROJECT_ROOT / "data" / "ontology" / "entities.yaml"
        )
        cls.planner = RuleBasedPlanner()

    def test_il23r_internal_question(self) -> None:
        question = "公司是否做过 IL23R 的体内验证？"
        entities = self.linker.link(question)
        subquestions = self.planner.plan(
            question,
            entities,
            max_subquestions=5,
            max_retrievals=12,
        )
        sources = [
            source
            for subquestion in subquestions
            for source in subquestion.sources
        ]
        self.assertIn(SourceType.LITERATURE, sources)
        self.assertIn(SourceType.OMICS, sources)
        self.assertIn(SourceType.ELN, sources)
        self.assertIn(SourceType.REPORT, sources)
        self.assertIn(SourceType.PATENT, sources)

    def test_no_gene_skips_omics(self) -> None:
        question = "公司的请假制度是什么？"
        subquestions = self.planner.plan(
            question,
            [],
            max_subquestions=5,
            max_retrievals=12,
        )
        sources = [
            source
            for subquestion in subquestions
            for source in subquestion.sources
        ]
        self.assertNotIn(SourceType.OMICS, sources)

    def test_retrieval_budget_trims_sources(self) -> None:
        question = "IL23R 在 IBD 中如何表达？"
        entities = self.linker.link(question)
        subquestions = self.planner.plan(
            question,
            entities,
            max_subquestions=5,
            max_retrievals=2,
        )
        count = sum(len(subquestion.sources) for subquestion in subquestions)
        self.assertLessEqual(count, 2)

    def test_clinical_keyword_adds_trial(self) -> None:
        question = "IL23R 的临床试验入组标准是什么？"
        entities = self.linker.link(question)
        subquestions = self.planner.plan(
            question,
            entities,
            max_subquestions=6,
            max_retrievals=12,
        )
        sources = [
            source
            for subquestion in subquestions
            for source in subquestion.sources
        ]
        self.assertIn(SourceType.TRIAL, sources)


if __name__ == "__main__":
    unittest.main()
