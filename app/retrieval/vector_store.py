"""Chroma 向量库封装。

- 使用余弦距离（hnsw:space=cosine）；
- ACL / source_type 在检索时通过 metadata filter 生效；
- 建库时直接 upsert 预计算向量，避免重复调用 Embedding；
- 不把 distance 转成伪百分比。

Chroma 1.x 的 client 对线程归属敏感：LangGraph Send 并行调用时，
即使加锁，跨线程使用同一 client 仍可能报 tenant 错误。这里把所有
Chroma 操作固定到一个单线程 executor，保证 client 只在创建它的线程使用。
"""

from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable

from langchain_chroma import Chroma
from pydantic import BaseModel, Field

from app.config import Settings
from app.ingest.chunker import Chunk
from app.retrieval.embeddings import build_embeddings, validate_vectors

logger = logging.getLogger(__name__)


class SearchHit(BaseModel):
    chunk_id: str
    doc_id: str
    text: str
    score: float
    metadata: dict[str, Any] = Field(default_factory=dict)


class VectorStore:
    def __init__(
        self,
        settings: Settings,
        embeddings: Any | None = None,
        *,
        expected_dim: int | None = None,
    ) -> None:
        self.settings = settings
        self.embeddings = embeddings or build_embeddings(settings)
        self.expected_dim = expected_dim or settings.embedding_dim
        self.persist_directory = settings.chroma_dir
        self.collection_name = settings.chroma_collection
        self._store: Chroma | None = None
        self._executor: ThreadPoolExecutor | None = ThreadPoolExecutor(
            max_workers=1,
            thread_name_prefix="chroma",
        )

    # ---------- 单线程执行器 ----------
    def _run(self, fn: Callable[[], Any]) -> Any:
        if self._executor is None:
            raise RuntimeError("VectorStore 已关闭")
        return self._executor.submit(fn).result()

    def _open(self) -> Chroma:
        """只能在 executor 线程中调用。"""
        if self._store is None:
            self.persist_directory.mkdir(parents=True, exist_ok=True)
            self._store = Chroma(
                collection_name=self.collection_name,
                embedding_function=self.embeddings,
                persist_directory=str(self.persist_directory),
                collection_metadata={
                    "hnsw:space": "cosine",
                    "hnsw:batch_size": self.settings.hnsw_batch_size,
                    "hnsw:sync_threshold": self.settings.hnsw_sync_threshold,
                },
            )
        return self._store

    # ---------- 生命周期 ----------
    def reset(self) -> None:
        """删除当前 collection，但保留 executor 供后续重建使用。"""
        self._run(self._reset_sync)

    def _reset_sync(self) -> None:
        try:
            store = self._open()
            store.delete_collection()
        except Exception:  # noqa: BLE001 - 空目录/不存在时忽略
            pass
        finally:
            self._stop_sync()

    def delete(self) -> None:
        if self._executor is None:
            return
        try:
            self._run(self._delete_sync)
        finally:
            self._executor.shutdown(wait=True)
            self._executor = None

    def _delete_sync(self) -> None:
        try:
            self._open().delete_collection()
        except Exception:  # noqa: BLE001
            pass
        finally:
            self._stop_sync()

    def close(self) -> None:
        """停止 Chroma 后台 system，确保 HNSW 索引落盘。"""
        if self._executor is None:
            return
        try:
            self._run(self._stop_sync)
        finally:
            self._executor.shutdown(wait=True)
            self._executor = None

    def _stop_sync(self) -> None:
        if self._store is None:
            return
        # 给 Chroma 后台 compactor 一点时间完成最后一批写入。
        time.sleep(1.0)
        client = getattr(self._store, "_client", None)
        system = getattr(client, "_system", None)
        if system is not None:
            try:
                system.stop()
            except Exception:  # noqa: BLE001
                pass
        if client is not None:
            try:
                client.clear_system_cache()
            except Exception:  # noqa: BLE001
                pass
        self._store = None

    # ---------- 写入 ----------
    def add_chunks(
        self,
        chunks: list[Chunk],
        *,
        batch_size: int | None = None,
        progress: Callable[[int, int], None] | None = None,
    ) -> int:
        if not chunks:
            return 0
        return self._run(
            lambda: self._add_chunks_sync(
                chunks,
                batch_size=batch_size,
                progress=progress,
            )
        )

    def _add_chunks_sync(
        self,
        chunks: list[Chunk],
        *,
        batch_size: int | None,
        progress: Callable[[int, int], None] | None,
    ) -> int:
        store = self._open()
        batch_size = batch_size or self.settings.index_batch_size
        total = len(chunks)
        done = 0
        for start in range(0, total, batch_size):
            batch = chunks[start : start + batch_size]
            texts = [chunk.embed_text for chunk in batch]
            metadatas = [chunk.to_chroma_metadata() for chunk in batch]
            ids = [chunk.chunk_id for chunk in batch]
            vectors = self._embed_batch(texts)
            store._collection.upsert(
                ids=ids,
                embeddings=vectors,
                documents=texts,
                metadatas=metadatas,
            )
            done += len(batch)
            if progress:
                progress(done, total)
        return done

    def _embed_batch(self, texts: list[str]) -> list[list[float]]:
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                vectors = self.embeddings.embed_documents(texts)
                if len(vectors) != len(texts):
                    raise RuntimeError(
                        f"Embedding 返回数量 {len(vectors)} != 输入数量 {len(texts)}"
                    )
                validate_vectors(vectors, self.expected_dim, label="embedding")
                return vectors
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                if attempt < 2:
                    time.sleep(2 * (attempt + 1))
        raise RuntimeError(f"Embedding 批次失败: {last_error}") from last_error

    # ---------- 检索 ----------
    def search(
        self,
        query: str,
        *,
        k: int = 8,
        allowed_scopes: list[str] | None = None,
        source_types: list[str] | None = None,
    ) -> list[SearchHit]:
        if not query.strip():
            return []
        where = build_filter(allowed_scopes, source_types)
        return self._run(lambda: self._search_sync(query, k, where))

    def _search_sync(
        self,
        query: str,
        k: int,
        where: dict[str, Any] | None,
    ) -> list[SearchHit]:
        store = self._open()
        try:
            results = store.similarity_search_with_score(
                query,
                k=k,
                filter=where,
            )
        except Exception as exc:  # noqa: BLE001
            count = store._collection.count()
            if count == 0:
                return []
            logger.error("Chroma 检索失败: %s", exc)
            raise
        hits: list[SearchHit] = []
        for document, score in results:
            metadata = dict(document.metadata or {})
            hits.append(
                SearchHit(
                    chunk_id=str(metadata.get("chunk_id", "")),
                    doc_id=str(metadata.get("doc_id", "")),
                    text=str(metadata.get("text") or document.page_content),
                    score=float(score),
                    metadata=metadata,
                )
            )
        return hits

    def count(self) -> int:
        return int(self._run(self._count_sync))

    def _count_sync(self) -> int:
        return int(self._open()._collection.count())

    def exists(self) -> bool:
        return self.count() > 0


def build_acl_filter(allowed_scopes: list[str] | None) -> dict[str, Any] | None:
    if not allowed_scopes:
        return None
    return {"acl_scope": {"$in": list(dict.fromkeys(allowed_scopes))}}


def build_filter(
    allowed_scopes: list[str] | None,
    source_types: list[str] | None = None,
) -> dict[str, Any] | None:
    conditions: list[dict[str, Any]] = []
    if allowed_scopes:
        conditions.append(
            {"acl_scope": {"$in": list(dict.fromkeys(allowed_scopes))}}
        )
    if source_types:
        conditions.append(
            {"source_type": {"$in": list(dict.fromkeys(source_types))}}
        )
    if not conditions:
        return None
    if len(conditions) == 1:
        return conditions[0]
    return {"$and": conditions}
