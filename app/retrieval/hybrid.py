"""RRF 混合检索：Chroma 稠密 + BM25 稀疏 + 可选 rerank。"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Iterable

from pydantic import BaseModel, Field

from app.config import Settings
from app.ingest.chunker import Chunk
from app.ingest.entity_linker import EntityLinker
from app.ingest.manifest import read_jsonl
from app.retrieval.bm25 import BM25Index
from app.retrieval.query_expansion import ExpandedQuery, QueryExpander
from app.retrieval.rerank import RerankError, SiliconFlowReranker
from app.retrieval.vector_store import SearchHit, VectorStore

logger = logging.getLogger(__name__)


class HybridHit(BaseModel):
    chunk_id: str
    doc_id: str
    parent_id: str = ""
    text: str
    score: float
    rrf_score: float = 0.0
    dense_score: float | None = None
    sparse_score: float | None = None
    rerank_score: float | None = None
    dense_rank: int | None = None
    sparse_rank: int | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class HybridResult(BaseModel):
    query: str
    dense_query: str
    entities: list[str] = Field(default_factory=list)
    terms: list[str] = Field(default_factory=list)
    dense_count: int = 0
    sparse_count: int = 0
    hits: list[HybridHit] = Field(default_factory=list)
    reranked: bool = False
    dense_top_distance: float | None = None


def rrf_fuse(
    dense_hits: Iterable[SearchHit],
    sparse_hits: Iterable[SearchHit],
    *,
    k: int = 60,
    dense_weight: float = 1.0,
    sparse_weight: float = 1.0,
) -> list[HybridHit]:
    merged: dict[str, HybridHit] = {}

    def _entry(hit: SearchHit) -> HybridHit:
        if hit.chunk_id not in merged:
            metadata = dict(hit.metadata or {})
            merged[hit.chunk_id] = HybridHit(
                chunk_id=hit.chunk_id,
                doc_id=hit.doc_id,
                parent_id=str(metadata.get("parent_id") or hit.chunk_id),
                text=hit.text,
                score=0.0,
                metadata=metadata,
            )
        return merged[hit.chunk_id]

    for rank, hit in enumerate(dense_hits, start=1):
        entry = _entry(hit)
        entry.dense_score = hit.score
        entry.dense_rank = rank
        entry.rrf_score += dense_weight / (k + rank)

    for rank, hit in enumerate(sparse_hits, start=1):
        entry = _entry(hit)
        entry.sparse_score = hit.score
        entry.sparse_rank = rank
        entry.rrf_score += sparse_weight / (k + rank)

    for entry in merged.values():
        entry.score = entry.rrf_score

    return sorted(
        merged.values(),
        key=lambda item: (
            item.rrf_score,
            -(item.dense_rank or 10**6),
            -(item.sparse_rank or 10**6),
        ),
        reverse=True,
    )


def dedupe_parents(hits: Iterable[HybridHit], max_per_parent: int = 1) -> list[HybridHit]:
    counts: dict[str, int] = {}
    result: list[HybridHit] = []
    for hit in hits:
        key = hit.parent_id or hit.chunk_id
        if counts.get(key, 0) >= max_per_parent:
            continue
        counts[key] = counts.get(key, 0) + 1
        result.append(hit)
    return result


class HybridRetriever:
    def __init__(
        self,
        settings: Settings,
        *,
        vector_store: VectorStore,
        bm25: BM25Index,
        expander: QueryExpander,
        reranker: SiliconFlowReranker | None = None,
    ) -> None:
        self.settings = settings
        self.vector_store = vector_store
        self.bm25 = bm25
        self.expander = expander
        self.reranker = reranker

    def retrieve(
        self,
        query: str,
        *,
        k: int = 8,
        allowed_scopes: list[str] | None = None,
        use_rerank: bool | None = None,
    ) -> HybridResult:
        expanded = self.expander.expand(query)
        dense_hits = self.vector_store.search(
            expanded.dense_query,
            k=self.settings.retrieval_k,
            allowed_scopes=allowed_scopes,
        )
        sparse_hits = self.bm25.search(
            expanded.sparse_query,
            k=self.settings.retrieval_k,
            allowed_scopes=allowed_scopes,
        )
        fused = rrf_fuse(
            dense_hits,
            sparse_hits,
            k=self.settings.rrf_k,
        )
        candidates = dedupe_parents(fused)
        use_rerank = (
            self.settings.rerank_enabled if use_rerank is None else use_rerank
        )
        reranked = False
        if use_rerank and self.reranker is not None:
            candidates, reranked = self._rerank(query, candidates)
        return HybridResult(
            query=query,
            dense_query=expanded.dense_query,
            entities=expanded.canonical_ids,
            terms=expanded.terms,
            dense_count=len(dense_hits),
            sparse_count=len(sparse_hits),
            hits=candidates[:k],
            reranked=reranked,
            dense_top_distance=dense_hits[0].score if dense_hits else None,
        )

    def _rerank(
        self,
        query: str,
        candidates: list[HybridHit],
    ) -> tuple[list[HybridHit], bool]:
        assert self.reranker is not None
        top_candidates = candidates[: self.settings.rerank_top_n]
        try:
            score_pairs = self.reranker.rerank(
                query,
                [hit.text for hit in top_candidates],
                top_n=self.settings.rerank_top_n,
            )
        except RerankError as exc:
            logger.warning("Rerank 失败，回退 RRF: %s", exc)
            return candidates, False

        score_map = dict(score_pairs)
        for index, hit in enumerate(top_candidates):
            hit.rerank_score = score_map.get(index, 0.0)
            hit.score = hit.rerank_score
        top_candidates.sort(
            key=lambda item: (item.rerank_score or 0.0, item.rrf_score),
            reverse=True,
        )
        # rerank 未覆盖的候选保留在尾部，避免丢证据。
        rest = candidates[self.settings.rerank_top_n :]
        return top_candidates + rest, True

    def counter_evidence_queries(self, query: str) -> list[str]:
        return self.expander.counter_evidence_queries(query)


def build_hybrid_retriever(
    settings: Settings,
    *,
    chunks_path: Path | None = None,
    use_rerank: bool | None = None,
) -> HybridRetriever:
    chunks_path = chunks_path or settings.data_dir / "processed" / "chunks.jsonl"
    if not chunks_path.exists():
        raise FileNotFoundError(
            f"未找到 chunks: {chunks_path}；请先运行 scripts/rebuild_index.py"
        )
    chunks = [Chunk.model_validate(row) for row in read_jsonl(chunks_path)]
    linker = EntityLinker.from_yaml(
        settings.data_dir / "ontology" / "entities.yaml"
    )
    reranker = None
    enabled = settings.rerank_enabled if use_rerank is None else use_rerank
    if enabled:
        try:
            reranker = SiliconFlowReranker(settings)
        except RerankError as exc:
            logger.warning("未启用 rerank: %s", exc)
    return HybridRetriever(
        settings,
        vector_store=VectorStore(settings),
        bm25=BM25Index(chunks),
        expander=QueryExpander(linker),
        reranker=reranker,
    )
