"""BM25 稀疏检索（中文 jieba 分词）。

BM25 与向量检索互补：精确匹配靶点名、基因别名、专利号、ELN 编号。
"""

from __future__ import annotations

import re
from typing import Iterable

import jieba
from rank_bm25 import BM25Okapi

from app.ingest.chunker import Chunk
from app.retrieval.vector_store import SearchHit

CUSTOM_WORDS = [
    "IL23R",
    "IL-23R",
    "NOD2",
    "CARD15",
    "IL23A",
    "IL-23",
    "IL12B",
    "IBD",
    "Crohn",
    "ulcerative colitis",
    "Treg",
    "ILC3",
    "Paneth",
    "CD4",
    "ELN",
    "DOI",
]

STOPWORDS = {
    "the",
    "a",
    "an",
    "and",
    "or",
    "of",
    "in",
    "to",
    "with",
    "for",
    "was",
    "were",
    "is",
    "are",
    "we",
    "this",
    "that",
    "by",
    "on",
    "as",
    "from",
    "at",
    "be",
    "been",
    "has",
    "have",
    "had",
    "的",
    "了",
    "在",
    "是",
    "和",
    "与",
    "对",
    "中",
    "有",
    "为",
    "及",
    "或",
    "等",
    "被",
    "由",
    "后",
    "前",
}

_INITIALIZED = False


def _ensure_jieba() -> None:
    global _INITIALIZED
    if _INITIALIZED:
        return
    for word in CUSTOM_WORDS:
        jieba.add_word(word)
    _INITIALIZED = True


def tokenize(text: str) -> list[str]:
    _ensure_jieba()
    tokens: list[str] = []
    for raw in jieba.lcut(text.lower()):
        token = raw.strip()
        if not token or token in STOPWORDS:
            continue
        if re.fullmatch(r"[\W_]+", token):
            continue
        tokens.append(token)
    return tokens


class BM25Index:
    def __init__(self, chunks: Iterable[Chunk]) -> None:
        self.chunks: list[Chunk] = list(chunks)
        self._by_id = {chunk.chunk_id: chunk for chunk in self.chunks}
        self._corpus = [tokenize(chunk.embed_text) for chunk in self.chunks]
        self._bm25 = BM25Okapi(self._corpus) if self._corpus else None

    def search(
        self,
        query: str,
        *,
        k: int = 8,
        allowed_scopes: list[str] | None = None,
        source_types: list[str] | None = None,
    ) -> list[SearchHit]:
        if not self._bm25 or not query.strip():
            return []
        scores = self._bm25.get_scores(tokenize(query))
        allowed = set(allowed_scopes) if allowed_scopes else None
        sources = set(source_types) if source_types else None
        ranked: list[tuple[float, Chunk]] = []
        for score, chunk in zip(scores, self.chunks):
            if score <= 0:
                continue
            if allowed is not None and chunk.acl_scope not in allowed:
                continue
            if sources is not None and chunk.source_type.value not in sources:
                continue
            ranked.append((float(score), chunk))
        ranked.sort(key=lambda item: item[0], reverse=True)
        hits: list[SearchHit] = []
        for score, chunk in ranked[:k]:
            hits.append(
                SearchHit(
                    chunk_id=chunk.chunk_id,
                    doc_id=chunk.doc_id,
                    text=chunk.text,
                    score=score,
                    metadata=chunk.to_chroma_metadata(),
                )
            )
        return hits

    def count(self) -> int:
        return len(self.chunks)
