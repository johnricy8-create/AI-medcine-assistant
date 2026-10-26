"""Human Protein Atlas 表达数据抓取。

保存两类产物：
1. data/processed/omics/hpa_expression.json：结构化表达数据，供组学工具查询；
2. 一个用于检索的 NormalizedDocument 摘要，便于 RAG 找到表达证据。
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
from pydantic import BaseModel, Field

from app.ingest.manifest import sha256_text, write_json
from app.ingest.models import DocumentSection, FetchedDocument, NormalizedDocument
from app.schemas import SourceType

HPA_URL = "https://www.proteinatlas.org/{ensembl}.json"
GENE_ENSEMBL = {
    "IL23R": "ENSG00000162594",
    "NOD2": "ENSG00000167207",
}


class ExpressionDataset(BaseModel):
    gene: str
    ensembl: str
    uniprot: list[str] = Field(default_factory=list)
    synonyms: list[str] = Field(default_factory=list)
    description: str | None = None
    tissue_specific_ntpm: dict[str, float] = Field(default_factory=dict)
    single_cell_type_specific_ncpm: dict[str, float] = Field(default_factory=dict)
    single_cell_group_specific_ncpm: dict[str, float] = Field(default_factory=dict)
    blood_cell_specific_ntpm: dict[str, float] = Field(default_factory=dict)
    source_url: str
    license: str = "CC BY 4.0 (Human Protein Atlas)"
    retrieved_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


def fetch_expression(
    data_dir: Path,
    *,
    genes: dict[str, str] | None = None,
) -> list[FetchedDocument]:
    genes = genes or GENE_ENSEMBL
    raw_dir = data_dir / "raw" / "hpa"
    raw_dir.mkdir(parents=True, exist_ok=True)
    datasets: list[ExpressionDataset] = []
    fetched: list[FetchedDocument] = []

    with httpx.Client(
        timeout=60,
        follow_redirects=True,
        headers={"User-Agent": "pharma-research-agent/0.1 (teaching demo)"},
    ) as client:
        for gene, ensembl in genes.items():
            response = client.get(HPA_URL.format(ensembl=ensembl))
            response.raise_for_status()
            payload = response.json()
            (raw_dir / f"{ensembl}_{gene}.json").write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            dataset = _build_dataset(gene, ensembl, payload)
            datasets.append(dataset)
            fetched.append(
                FetchedDocument(
                    document=_build_document(dataset),
                    source="Human Protein Atlas",
                    raw_path=str(raw_dir / f"{ensembl}_{gene}.json"),
                    parse_status="ok",
                )
            )

    write_json(
        data_dir / "processed" / "omics" / "hpa_expression.json",
        [dataset.model_dump(mode="json") for dataset in datasets],
    )
    return fetched


def _build_dataset(gene: str, ensembl: str, payload: dict[str, Any]) -> ExpressionDataset:
    return ExpressionDataset(
        gene=gene,
        ensembl=ensembl,
        uniprot=payload.get("Uniprot") or [],
        synonyms=payload.get("Gene synonym") or [],
        description=payload.get("Gene description"),
        tissue_specific_ntpm=_float_map(payload.get("RNA tissue specific nTPM")),
        single_cell_type_specific_ncpm=_float_map(
            payload.get("RNA single cell type specific nCPM")
        ),
        single_cell_group_specific_ncpm=_float_map(
            payload.get("RNA single cell type group specific nCPM")
        ),
        blood_cell_specific_ntpm=_float_map(
            payload.get("RNA blood cell specific nTPM")
        ),
        source_url=f"https://www.proteinatlas.org/{ensembl}-{gene}",
    )


def _build_document(dataset: ExpressionDataset) -> NormalizedDocument:
    tissue_top = _top_items(dataset.tissue_specific_ntpm, limit=8)
    cell_top = _top_items(dataset.single_cell_type_specific_ncpm, limit=8)
    group_top = _top_items(dataset.single_cell_group_specific_ncpm, limit=8)
    blood_top = _top_items(dataset.blood_cell_specific_ntpm, limit=8)

    sections = [
        DocumentSection(
            heading="Tissue RNA expression (nTPM)",
            text=_format_items(tissue_top),
            kind="expression",
        ),
        DocumentSection(
            heading="Single-cell type RNA expression (nCPM)",
            text=_format_items(cell_top),
            kind="expression",
        ),
        DocumentSection(
            heading="Single-cell group RNA expression (nCPM)",
            text=_format_items(group_top),
            kind="expression",
        ),
        DocumentSection(
            heading="Blood cell RNA expression (nTPM)",
            text=_format_items(blood_top),
            kind="expression",
        ),
    ]
    sections = [section for section in sections if section.text]
    text = "\n\n".join(
        f"{section.heading}\n{section.text}" for section in sections
    )
    title = f"[HPA] {dataset.gene} expression profile"
    metadata = {
        "gene": dataset.gene,
        "ensembl": dataset.ensembl,
        "uniprot": dataset.uniprot,
        "synonyms": dataset.synonyms,
        "description": dataset.description,
        "source": "Human Protein Atlas",
        "tissue_specific_ntpm": dataset.tissue_specific_ntpm,
        "single_cell_type_specific_ncpm": dataset.single_cell_type_specific_ncpm,
        "single_cell_group_specific_ncpm": dataset.single_cell_group_specific_ncpm,
        "blood_cell_specific_ntpm": dataset.blood_cell_specific_ntpm,
    }
    document = NormalizedDocument(
        doc_id=f"omics:hpa:{dataset.gene}",
        source_type=SourceType.OMICS,
        source_id=f"HPA:{dataset.gene}",
        title=title,
        text=f"{title}\n\n{text}",
        sections=sections,
        abstract=text[:500],
        url=dataset.source_url,
        license=dataset.license,
        acl_scope="public",
        species="Homo sapiens",
        sample="tissue / single cell / blood",
        method="RNA expression profiling",
        entity_ids=[dataset.ensembl],
        metadata=metadata,
        content_hash=sha256_text(json.dumps(metadata, ensure_ascii=False, sort_keys=True)),
    )
    return document.finalize()


def _float_map(value: Any) -> dict[str, float]:
    if not isinstance(value, dict):
        return {}
    result: dict[str, float] = {}
    for key, raw in value.items():
        try:
            result[str(key)] = float(raw)
        except (TypeError, ValueError):
            continue
    return result


def _top_items(values: dict[str, float], limit: int) -> list[tuple[str, float]]:
    return sorted(values.items(), key=lambda item: item[1], reverse=True)[:limit]


def _format_items(items: list[tuple[str, float]]) -> str:
    if not items:
        return ""
    return "; ".join(f"{name}: {value:g}" for name, value in items)
