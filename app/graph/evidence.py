"""把检索命中/工具结果转换为统一 Evidence。"""

from __future__ import annotations

from typing import Any

from app.graph.services import GraphServices
from app.ingest.manifest import sha256_text
from app.retrieval.hybrid import HybridHit
from app.schemas import (
    Evidence,
    EvidenceLevel,
    Locator,
    ScoreSet,
    SourceType,
    Stance,
)
from app.tools.models import ToolResult

META_KEYS = (
    "pub_types",
    "mesh_terms",
    "study_type",
    "result_polarity",
    "has_embodiments",
    "patent_no",
    "experiment_id",
    "conditions",
    "result",
    "enrollment",
    "phases",
    "journal",
    "year",
    "synthetic",
    "demo_notice",
    "description",
)


def evidence_from_hit(
    hit: HybridHit,
    source: SourceType,
    services: GraphServices,
    allowed_scopes: set[str],
) -> Evidence | None:
    metadata = hit.metadata or {}
    acl_scope = str(metadata.get("acl_scope") or "public")
    if allowed_scopes and acl_scope not in allowed_scopes:
        return None
    quote = hit.text.strip()
    if not quote:
        return None
    document = services.document(str(metadata.get("doc_id") or hit.doc_id))
    page = metadata.get("page_number")
    page_number = int(page) if isinstance(page, int) and page > 0 else None
    evidence_meta: dict[str, Any] = {
        "chunk_id": hit.chunk_id,
        "parent_id": metadata.get("parent_id"),
        "section_path": metadata.get("section_path"),
        "source_type": source.value,
        "result_polarity": metadata.get("result_polarity", "unknown"),
    }
    if document:
        for key in META_KEYS:
            if key in document.metadata and document.metadata[key] is not None:
                evidence_meta[key] = document.metadata[key]
    return Evidence(
        evidence_id=f"ev-{hit.chunk_id}",
        source_type=source,
        source_id=str(metadata.get("doc_id") or hit.doc_id),
        title=str(
            metadata.get("title")
            or (document.title if document else source.value)
        ),
        chunk_id=hit.chunk_id,
        quote=quote[:1200],
        locator=Locator(
            page=page_number,
            section=metadata.get("section_path") or None,
            figure=metadata.get("figure") or None,
            table=metadata.get("table_ref") or None,
            doi=document.doi if document else None,
            patent_no=(
                document.metadata.get("patent_no") if document else None
            ),
            experiment_id=(
                document.metadata.get("experiment_id") if document else None
            ),
            url=document.url if document else None,
        ),
        entity_ids=(
            list(document.entity_ids)
            if document
            else [
                item
                for item in str(metadata.get("entity_ids_json", "")).split(",")
                if item
            ]
        ),
        species=str(metadata.get("species") or "unknown"),
        sample=str(metadata.get("sample") or "") or None,
        method=str(metadata.get("method") or "") or None,
        stance=Stance.UNKNOWN,
        level=EvidenceLevel.UNKNOWN,
        acl_scope=acl_scope,
        scores=ScoreSet(
            dense=hit.dense_score,
            sparse=hit.sparse_score,
            rrf=hit.rrf_score,
            rerank=hit.rerank_score,
        ),
        metadata=evidence_meta,
    )


def evidence_from_tool(
    result: ToolResult,
    gene: str,
    task_id: str,
) -> Evidence:
    data = result.data
    quote = (
        f"{gene} expression: "
        f"tissue={data.get('tissue_specific_ntpm')}; "
        f"single_cell={data.get('single_cell_type_specific_ncpm')}; "
        f"blood={data.get('blood_cell_specific_ntpm')}"
    )
    return Evidence(
        evidence_id=f"ev-tool-{sha256_text(gene + task_id)[:12]}",
        source_type=SourceType.OMICS,
        source_id=f"HPA:{gene}",
        title=f"[HPA] {gene} expression profile",
        chunk_id=f"tool:{gene}",
        quote=quote[:1200],
        locator=Locator(url=data.get("source_url")),
        entity_ids=[item for item in [data.get("ensembl")] if item],
        species="Homo sapiens",
        sample="tissue / single cell / blood",
        method="RNA expression profiling",
        stance=Stance.UNKNOWN,
        level=EvidenceLevel.UNKNOWN,
        acl_scope="public",
        scores=ScoreSet(),
        tool_call_id=f"tool-omics-{gene}",
        metadata={
            "result_polarity": "unknown",
            "study_type": "RNA expression profiling",
            "data": data,
            "license": result.license,
            "dataset_version": result.dataset_version,
        },
    )
