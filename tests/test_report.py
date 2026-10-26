"""研究底稿渲染测试。"""

from __future__ import annotations

import unittest

from app.evidence.report import render_research_brief
from app.schemas import (
    Claim,
    Conflict,
    EntityRef,
    Evidence,
    EvidenceLevel,
    SourceType,
    Stance,
)


class TestReport(unittest.TestCase):
    def test_render_sections_and_citations(self) -> None:
        evidence = [
            Evidence(
                evidence_id="ev-1",
                source_type=SourceType.LITERATURE,
                source_id="paper:PMC1",
                title="IL23R in IBD",
                chunk_id="chunk-1",
                quote="IL23R mRNA was increased in inflamed biopsies.",
                entity_ids=["ENSG00000162594"],
                species="Homo sapiens",
                method="RNA-seq",
                level=EvidenceLevel.B,
                metadata={
                    "grade": {
                        "rationale": "directness=28, species=20 → B"
                    }
                },
            ),
            Evidence(
                evidence_id="ev-2",
                source_type=SourceType.ELN,
                source_id="eln:ELN-1",
                title="Negative in vivo experiment",
                chunk_id="chunk-2",
                quote="IL23R protein was not changed in mouse colitis.",
                locator={"experiment_id": "ELN-1"},
                species="Mus musculus",
                method="Western blot",
                level=EvidenceLevel.B,
                metadata={"result_polarity": "negative"},
            ),
        ]
        claims = [
            Claim(
                claim_id="claim-1",
                text="IL23R 在人体炎症黏膜中升高，但小鼠蛋白阴性。",
                stance=Stance.SUPPORT,
                level=EvidenceLevel.B,
                support_ids=["ev-1"],
                contradict_ids=["ev-2"],
                confidence=0.7,
                verified=True,
            )
        ]
        report = render_research_brief(
            question="IL23R 是否升高？",
            user_id="scientist_031",
            project_id="IBD-TX-07",
            allowed_scopes=["public", "project:IBD-TX-07"],
            entities=[EntityRef(canonical_id="ENSG00000162594", entity_type="gene", name="IL23R")],
            assessment="人体 RNA 支持，但蛋白/动物证据不一致。",
            claims=claims,
            conflicts=[
                Conflict(
                    topic="IL23R 蛋白",
                    support_ids=["ev-1"],
                    contradict_ids=["ev-2"],
                    explanation="物种和方法差异。",
                )
            ],
            gaps=["缺少统一蛋白验证"],
            next_steps=["补充 Western blot"],
            evidence=evidence,
            llm_used=False,
        )
        for section in (
            "## 一句话判断",
            "## 支持证据",
            "## 反例与冲突",
            "## 内部实验",
            "## 证据等级",
            "## 数据缺口",
            "## 建议的下一步实验",
            "## 引用与定位",
            "## 校验与边界",
        ):
            self.assertIn(section, report)
        self.assertIn("ev-1", report)
        self.assertIn("ELN-1", report)
        self.assertIn("DEMO / SYNTHETIC", report)
        self.assertIn("通过引用/ACL 校验 1 条", report)


if __name__ == "__main__":
    unittest.main()
