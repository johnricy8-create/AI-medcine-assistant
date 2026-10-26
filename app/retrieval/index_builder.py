"""索引构建：文档 → chunks → 实体链接 → Chroma + BM25 → manifest。"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from pydantic import BaseModel, Field

from app.config import Settings
from app.ingest.chunker import chunk_documents
from app.ingest.entity_linker import EntityLinker
from app.ingest.manifest import read_jsonl, sha256_text, write_json, write_jsonl
from app.ingest.models import NormalizedDocument
from app.retrieval.bm25 import BM25Index
from app.retrieval.vector_store import VectorStore
from app.storage.db import db_session, init_db


class IndexBuildResult(BaseModel):
    built_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    document_count: int
    chunk_count: int
    collection: str
    embedding_model: str
    embedding_dim: int
    chroma_count: int = 0
    bm25_count: int = 0
    chunks_path: str
    manifest_path: str
    source_counts: dict[str, int] = Field(default_factory=dict)
    acl_counts: dict[str, int] = Field(default_factory=dict)


def load_documents(settings: Settings) -> list[NormalizedDocument]:
    path = settings.data_dir / "processed" / "documents.jsonl"
    if not path.exists():
        raise FileNotFoundError(
            f"未找到标准化文档 {path}；请先运行 scripts/fetch_data.py"
        )
    return [
        NormalizedDocument.model_validate(row)
        for row in read_jsonl(path)
    ]


def build_index(
    settings: Settings,
    *,
    documents: list[NormalizedDocument] | None = None,
    limit: int | None = None,
    embeddings: object | None = None,
    expected_dim: int | None = None,
    chunks_only: bool = False,
    progress: Callable[[int, int], None] | None = None,
) -> IndexBuildResult:
    docs = documents if documents is not None else load_documents(settings)
    if limit is not None:
        docs = docs[:limit]
    if not docs:
        raise ValueError("没有可索引的文档")

    chunks = chunk_documents(docs, settings)
    if not chunks:
        raise ValueError("没有生成任何 chunk")

    if settings.enable_entity_linker:
        ontology_path = settings.data_dir / "ontology" / "entities.yaml"
        if ontology_path.exists():
            linker = EntityLinker.from_yaml(ontology_path)
            for chunk in chunks:
                linked = linker.canonical_ids(chunk.embed_text)
                if linked:
                    chunk.entity_ids = sorted(set(chunk.entity_ids) | set(linked))

    chunks_path = settings.data_dir / "processed" / "chunks.jsonl"
    write_jsonl(chunks_path, [chunk.model_dump(mode="json") for chunk in chunks])

    bm25 = BM25Index(chunks)
    chroma_count = 0
    if not chunks_only:
        store = VectorStore(
            settings,
            embeddings=embeddings,
            expected_dim=expected_dim,
        )
        store.reset()
        try:
            store.add_chunks(chunks, progress=progress)
            chroma_count = store.count()
        except Exception:
            store.delete()
            raise
        finally:
            store.close()

    source_counts: dict[str, int] = {}
    for doc in docs:
        key = doc.source_type.value
        source_counts[key] = source_counts.get(key, 0) + 1
    acl_counts: dict[str, int] = {}
    for doc in docs:
        acl_counts[doc.acl_scope] = acl_counts.get(doc.acl_scope, 0) + 1

    built_at = datetime.now(timezone.utc)
    manifest = {
        "version": settings.chunker_version,
        "built_at": built_at.isoformat(),
        "document_count": len(docs),
        "chunk_count": len(chunks),
        "collection": settings.chroma_collection,
        "embedding_model": settings.embedding_model,
        "embedding_dim": settings.embedding_dim,
        "chunk_size": settings.chunk_size,
        "chunk_overlap": settings.chunk_overlap,
        "table_chunk_size": settings.table_chunk_size,
        "entity_linker": settings.enable_entity_linker,
        "source_counts": source_counts,
        "acl_counts": acl_counts,
        "bm25_count": bm25.count(),
        "chroma_count": chroma_count,
        "chunks_hash": sha256_text(
            "\n".join(chunk.chunk_id for chunk in chunks)
        ),
    }
    manifest_path = settings.data_dir / "processed" / "index_manifest.json"
    write_json(manifest_path, manifest)

    init_db(settings.sqlite_path)
    with db_session(settings.sqlite_path) as conn:
        conn.execute(
            "INSERT INTO index_manifest"
            "(collection, embedding_model, embedding_dim, chunker_version, "
            " document_count, chunk_count, manifest_json, built_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                settings.chroma_collection,
                settings.embedding_model,
                settings.embedding_dim,
                settings.chunker_version,
                len(docs),
                len(chunks),
                json.dumps(manifest, ensure_ascii=False),
                built_at.isoformat(),
            ),
        )

    return IndexBuildResult(
        built_at=built_at,
        document_count=len(docs),
        chunk_count=len(chunks),
        collection=settings.chroma_collection,
        embedding_model=settings.embedding_model,
        embedding_dim=settings.embedding_dim,
        chroma_count=chroma_count,
        bm25_count=bm25.count(),
        chunks_path=str(chunks_path),
        manifest_path=str(manifest_path),
        source_counts=source_counts,
        acl_counts=acl_counts,
    )
