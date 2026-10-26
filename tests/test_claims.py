"""Claims 综合测试（Fake LLM，不访问网络）。"""

from __future__ import annotations

import unittest

from app.evidence.claims import (
    ClaimDraft,
    ClaimSynthesizer,
    ConflictDraft,
    SynthesisBundle,
)
from app.schemas import Evidence, EvidenceLevel, SourceType, Stance


def _evidence(
    evidence_id: str,
    *,
    quote: str,
    polarity: str = "unknown",
    level: EvidenceLevel = EvidenceLevel.B,
    source_type: SourceType = SourceType.LITERATURE,
) -> Evidence:
    return Evidence(
        evidence_id=evidence_id,
        source_type=source_type,
        source_id=f"doc:{evidence_id}",
        title=f"Title {evidence_id}",
        chunk_id=f"chunk:{evidence_id}",
        quote=quote,
        level=level,
        metadata={"result_polarity": polarity},
    )


class _FakeLLM:
    def __init__(self, bundle: SynthesisBundle | None = None, fail: bool = False):
        self.bundle = bundle
        self.fail = fail

    def generate_json(self, system_prompt, user_prompt, schema, max_tokens=None):
        if self.fail or self.bundle is None:
            raise RuntimeError("fake llm failure")
        return self.bundle, "fake-model"


class TestClaimSynthesizer(unittest.TestCase):
    def setUp(self) -> None:
        self.synthesizer = ClaimSynthesizer()
        self.evidence = [
            _evidence(
                "ev-support",
                quote="IL23R increased in inflamed biopsies.",
                polarity="positive",
                level=EvidenceLevel.A,
            ),
            _evidence(
                "ev-counter",
                quote="IL23R protein was not changed in mouse colitis.",
                polarity="negative",
                level=EvidenceLevel.B,
                source_type=SourceType.ELN,
            ),
        ]

    def test_llm_claims_are_sanitized_and_graded(self) -> None:
        bundle = SynthesisBundle(
            assessment="存在支持与反例证据。",
            claims=[
                ClaimDraft(
                    text="IL23R 在炎症黏膜升高，但小鼠蛋白阴性。",
                    stance=Stance.SUPPORT,
                    level=EvidenceLevel.D,
                    support_ids=["ev-support"],
                    contradict_ids=["ev-counter"],
                    confidence=0.8,
                ),
                ClaimDraft(
                    text="无效引用",
                    stance=Stance.SUPPORT,
                    support_ids=["ev-missing"],
                ),
                ClaimDraft(
                    text="无引用",
                    stance=Stance.NEUTRAL,
                ),
            ],
            conflicts=[
                ConflictDraft(
                    topic="IL23R 蛋白",
                    support_ids=["ev-support"],
                    contradict_ids=["ev-counter"],
                    explanation="人体 RNA 与小鼠蛋白不一致。",
                )
            ],
            gaps=["缺少蛋白验证"],
            next_steps=["补充蛋白验证"],
        )
        result = self.synthesizer.synthesize(
            "IL23R 是否有表达？",
            self.evidence,
            llm=_FakeLLM(bundle),
        )
        self.assertTrue(result.llm_used)
        self.assertEqual(len(result.claims), 1)
        claim = result.claims[0]
        self.assertEqual(claim.support_ids, ["ev-support"])
        self.assertEqual(claim.contradict_ids, ["ev-counter"])
        self.assertEqual(claim.level, EvidenceLevel.A)
        self.assertEqual(len(result.conflicts), 1)
        self.assertEqual(result.gaps, ["缺少蛋白验证"])

    def test_llm_failure_falls_back(self) -> None:
        result = self.synthesizer.synthesize(
            "IL23R 是否有表达？",
            self.evidence,
            llm=_FakeLLM(fail=True),
        )
        self.assertFalse(result.llm_used)
        self.assertTrue(result.claims)
        self.assertTrue(result.conflicts)

    def test_internal_eln_is_added_if_llm_ignores_it(self) -> None:
        bundle = SynthesisBundle(
            assessment="仅依据文献。",
            claims=[
                ClaimDraft(
                    text="IL23R 在炎症中升高。",
                    stance=Stance.SUPPORT,
                    support_ids=["ev-support"],
                )
            ],
        )
        result = self.synthesizer.synthesize(
            "公司是否做过 IL23R 的体内验证？",
            self.evidence,
            llm=_FakeLLM(bundle),
        )
        cited = {
            item
            for claim in result.claims
            for item in claim.support_ids + claim.contradict_ids
        }
        self.assertIn("ev-counter", cited)
        internal_claims = [
            claim for claim in result.claims if claim.contradict_ids == ["ev-counter"]
        ]
        self.assertTrue(internal_claims)

    def test_no_llm_fallback_is_extractive(self) -> None:
        result = self.synthesizer.synthesize(
            "IL23R 是否有表达？",
            self.evidence,
        )
        self.assertFalse(result.llm_used)
        self.assertTrue(result.claims)
        self.assertTrue(all(claim.claim_id.startswith("claim-") for claim in result.claims))

    def test_no_evidence(self) -> None:
        result = self.synthesizer.synthesize("IL23R？", [])
        self.assertEqual(result.claims, [])
        self.assertIn("没有可用证据", result.assessment)


if __name__ == "__main__":
    unittest.main()
