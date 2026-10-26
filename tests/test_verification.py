"""引用校验测试。"""

from __future__ import annotations

import unittest

from app.evidence.verification import CitationVerifier
from app.ingest.chunker import Chunk
from app.schemas import Claim, Evidence, SourceType, Stance


def _chunk() -> Chunk:
    return Chunk(
        chunk_id="chunk-1",
        parent_id="parent-1",
        doc_id="doc:1",
        source_type=SourceType.LITERATURE,
        title="IL23R paper",
        text="IL23R mRNA was increased in inflamed biopsies from IBD patients.",
        embed_text="IL23R paper IL23R mRNA was increased in inflamed biopsies from IBD patients.",
        parent_text="IL23R mRNA was increased in inflamed biopsies from IBD patients.",
        acl_scope="public",
    )


def _evidence(quote: str, acl_scope: str = "public", chunk_id: str = "chunk-1") -> Evidence:
    return Evidence(
        evidence_id="ev-1",
        source_type=SourceType.LITERATURE,
        source_id="doc:1",
        title="IL23R paper",
        chunk_id=chunk_id,
        quote=quote,
        acl_scope=acl_scope,
    )


def _claim(**kwargs) -> Claim:
    data = {
        "claim_id": "claim-1",
        "text": "IL23R increased in IBD.",
        "stance": Stance.SUPPORT,
        "support_ids": ["ev-1"],
        "level": "B",
    }
    data.update(kwargs)
    return Claim(**data)


class TestCitationVerifier(unittest.TestCase):
    def setUp(self) -> None:
        self.verifier = CitationVerifier({"chunk-1": _chunk()})

    def test_valid_quote(self) -> None:
        claims, notes = self.verifier.verify(
            [_claim()],
            [_evidence("IL23R mRNA was increased in inflamed biopsies")],
            ["public"],
        )
        self.assertEqual(len(claims), 1)
        self.assertTrue(claims[0].verified)
        self.assertEqual(notes, [])

    def test_quote_mismatch_drops_claim(self) -> None:
        claims, notes = self.verifier.verify(
            [_claim()],
            [_evidence("completely different quote")],
            ["public"],
        )
        self.assertEqual(claims, [])
        self.assertTrue(notes)

    def test_acl_mismatch_drops_claim(self) -> None:
        claims, notes = self.verifier.verify(
            [_claim()],
            [_evidence("IL23R mRNA was increased", acl_scope="project:ONCO-02")],
            ["public"],
        )
        self.assertEqual(claims, [])
        self.assertTrue(any("ACL" in note for note in notes))

    def test_missing_evidence_id_drops_claim(self) -> None:
        claims, notes = self.verifier.verify(
            [_claim(support_ids=["missing"])],
            [_evidence("IL23R mRNA was increased")],
            ["public"],
        )
        self.assertEqual(claims, [])
        self.assertTrue(any("不存在" in note for note in notes))

    def test_tool_evidence_without_chunk_is_kept(self) -> None:
        tool = Evidence(
            evidence_id="ev-tool",
            source_type=SourceType.OMICS,
            source_id="HPA:IL23R",
            title="HPA IL23R",
            chunk_id="tool:IL23R",
            quote="IL23R expression: tissue={}",
            acl_scope="public",
        )
        claims, notes = self.verifier.verify(
            [_claim(support_ids=["ev-tool"])],
            [tool],
            ["public"],
        )
        self.assertEqual(len(claims), 1)
        self.assertTrue(claims[0].verified)


if __name__ == "__main__":
    unittest.main()
