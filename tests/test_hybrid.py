"""RRF 融合与混合检索测试。"""

from __future__ import annotations

import unittest

from app.config import Settings
from app.retrieval.hybrid import (
    HybridHit,
    HybridRetriever,
    dedupe_parents,
    rrf_fuse,
)
from app.retrieval.query_expansion import ExpandedQuery
from app.retrieval.rerank import RerankError
from app.retrieval.vector_store import SearchHit


def _hit(chunk_id: str, text: str, score: float, parent_id: str = "") -> SearchHit:
    return SearchHit(
        chunk_id=chunk_id,
        doc_id=f"doc:{chunk_id}",
        text=text,
        score=score,
        metadata={
            "chunk_id": chunk_id,
            "doc_id": f"doc:{chunk_id}",
            "parent_id": parent_id or f"parent:{chunk_id}",
            "acl_scope": "public",
            "text": text,
            "source_type": "literature",
        },
    )


class _FakeExpander:
    def expand(self, query: str) -> ExpandedQuery:
        return ExpandedQuery(
            original=query,
            dense_query=query,
            sparse_query=query,
            entities=[],
            terms=[],
        )


class _FakeVectorStore:
    def __init__(self, hits: list[SearchHit]) -> None:
        self.hits = hits
        self.calls = []

    def search(self, query, *, k=8, allowed_scopes=None, source_types=None):
        self.calls.append((query, k, allowed_scopes, source_types))
        return self.hits[:k]


class _FakeBM25:
    def __init__(self, hits: list[SearchHit]) -> None:
        self.hits = hits
        self.calls = []

    def search(self, query, *, k=8, allowed_scopes=None, source_types=None):
        self.calls.append((query, k, allowed_scopes, source_types))
        return self.hits[:k]


class _FakeReranker:
    def __init__(self, scores: dict[int, float] | None = None, fail: bool = False):
        self.scores = scores or {}
        self.fail = fail

    def rerank(self, query, documents, *, top_n=None):
        if self.fail:
            raise RerankError("fake failure")
        return sorted(
            [(index, score) for index, score in self.scores.items()],
            key=lambda item: item[1],
            reverse=True,
        )


class TestRRF(unittest.TestCase):
    def test_fusion_order(self) -> None:
        dense = [_hit("c1", "a", 0.1), _hit("c2", "b", 0.2), _hit("c3", "c", 0.3)]
        sparse = [_hit("c2", "b", 10.0), _hit("c1", "a", 9.0), _hit("c4", "d", 8.0)]
        fused = rrf_fuse(dense, sparse, k=60)
        self.assertEqual([hit.chunk_id for hit in fused[:2]], ["c1", "c2"])
        self.assertIn("c4", [hit.chunk_id for hit in fused])
        self.assertGreater(fused[0].rrf_score, fused[2].rrf_score)
        self.assertEqual(fused[0].dense_rank, 1)
        self.assertEqual(fused[0].sparse_rank, 2)

    def test_parent_dedupe(self) -> None:
        hits = [
            HybridHit(
                chunk_id="c1",
                doc_id="d1",
                parent_id="p1",
                text="a",
                score=0.03,
            ),
            HybridHit(
                chunk_id="c2",
                doc_id="d1",
                parent_id="p1",
                text="b",
                score=0.02,
            ),
            HybridHit(
                chunk_id="c3",
                doc_id="d2",
                parent_id="p2",
                text="c",
                score=0.01,
            ),
        ]
        deduped = dedupe_parents(hits)
        self.assertEqual([hit.chunk_id for hit in deduped], ["c1", "c3"])


class TestHybridRetriever(unittest.TestCase):
    def setUp(self) -> None:
        self.settings = Settings(
            _env_file=None,
            retrieval_k=10,
            rrf_k=60,
            rerank_top_n=10,
            rerank_enabled=False,
        )
        self.dense = [_hit("c1", "IL23R paper", 0.2), _hit("c2", "NOD2 paper", 0.3)]
        self.sparse = [_hit("c2", "NOD2 paper", 8.0), _hit("c3", "negative ELN", 7.0)]
        self.vector = _FakeVectorStore(self.dense)
        self.bm25 = _FakeBM25(self.sparse)

    def _retriever(self, reranker=None) -> HybridRetriever:
        return HybridRetriever(
            self.settings,
            vector_store=self.vector,
            bm25=self.bm25,
            expander=_FakeExpander(),
            reranker=reranker,
        )

    def test_retrieve_and_acl_passthrough(self) -> None:
        result = self._retriever().retrieve(
            "IL23R", k=3, allowed_scopes=["public"]
        )
        self.assertTrue(result.hits)
        self.assertEqual(result.dense_count, 2)
        self.assertEqual(result.sparse_count, 2)
        self.assertEqual(self.vector.calls[0][2], ["public"])
        self.assertEqual(self.bm25.calls[0][2], ["public"])
        self.assertIsNone(self.vector.calls[0][3])

    def test_rerank_success(self) -> None:
        result = self._retriever(_FakeReranker({0: 0.9, 1: 0.1})).retrieve(
            "IL23R", k=2, use_rerank=True
        )
        self.assertTrue(result.reranked)
        self.assertEqual(result.hits[0].chunk_id, "c2")
        self.assertIsNotNone(result.hits[0].rerank_score)

    def test_rerank_failure_falls_back(self) -> None:
        result = self._retriever(_FakeReranker(fail=True)).retrieve(
            "IL23R", k=2, use_rerank=True
        )
        self.assertFalse(result.reranked)
        self.assertTrue(result.hits)


if __name__ == "__main__":
    unittest.main()
