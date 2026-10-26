"""BM25 检索测试。"""

from __future__ import annotations

import unittest

from app.ingest.chunker import Chunk
from app.retrieval.bm25 import BM25Index
from app.schemas import SourceType


def _chunk(
    chunk_id: str,
    text: str,
    *,
    acl_scope: str = "public",
    doc_id: str = "doc:1",
) -> Chunk:
    return Chunk(
        chunk_id=chunk_id,
        parent_id=f"parent:{chunk_id}",
        doc_id=doc_id,
        source_type=SourceType.LITERATURE,
        title="Test document",
        text=text,
        embed_text=text,
        parent_text=text,
        acl_scope=acl_scope,
    )


class TestBM25(unittest.TestCase):
    def setUp(self) -> None:
        self.chunks = [
            _chunk(
                "c1",
                "IL23R mRNA was increased in inflamed intestinal biopsies.",
            ),
            _chunk(
                "c2",
                "NOD2 knockdown did not change IL23R expression in organoids.",
            ),
            _chunk(
                "c3",
                "IL23R expression in tumor infiltrating lymphocytes.",
                acl_scope="project:ONCO-02",
                doc_id="doc:onco",
            ),
        ]
        self.index = BM25Index(self.chunks)

    def test_exact_target_search(self) -> None:
        hits = self.index.search("IL23R inflamed biopsies", k=3)
        self.assertEqual(hits[0].chunk_id, "c1")
        self.assertTrue(any(hit.chunk_id == "c2" for hit in hits))

    def test_nod2_search(self) -> None:
        hits = self.index.search("NOD2 organoid", k=3)
        self.assertTrue(hits)
        self.assertEqual(hits[0].chunk_id, "c2")

    def test_acl_filter(self) -> None:
        public_hits = self.index.search(
            "IL23R", k=5, allowed_scopes=["public"]
        )
        self.assertTrue(public_hits)
        self.assertTrue(all(hit.metadata["acl_scope"] == "public" for hit in public_hits))
        self.assertNotIn("c3", {hit.chunk_id for hit in public_hits})

        onco_hits = self.index.search(
            "IL23R", k=5, allowed_scopes=["project:ONCO-02"]
        )
        self.assertEqual([hit.chunk_id for hit in onco_hits], ["c3"])

    def test_count(self) -> None:
        self.assertEqual(self.index.count(), 3)


if __name__ == "__main__":
    unittest.main()
