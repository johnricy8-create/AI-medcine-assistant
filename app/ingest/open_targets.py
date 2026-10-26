"""Open Targets Platform 靶点—疾病关联抓取。

同时产出：
1. 可检索的靶点关联摘要文档；
2. 供 NetworkX 使用的 nodes.jsonl / edges.jsonl。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx

from app.ingest.manifest import write_json, write_jsonl
from app.ingest.models import DocumentSection, FetchedDocument, NormalizedDocument
from app.schemas import SourceType

GRAPHQL_URL = "https://api.platform.opentargets.org/api/v4/graphql"
TARGETS = {
    "IL23R": "ENSG00000162594",
    "NOD2": "ENSG00000167207",
}

TARGET_QUERY = """
query TargetAssociations($id: String!, $size: Int!) {
  target(ensemblId: $id) {
    id
    approvedSymbol
    approvedName
    associatedDiseases(page: {index: 0, size: $size}) {
      count
      rows {
        disease { id name }
        score
        datatypeScores { id score }
      }
    }
  }
}
"""


def fetch_open_targets(
    data_dir: Path,
    *,
    targets: dict[str, str] | None = None,
    size: int = 25,
) -> list[FetchedDocument]:
    targets = targets or TARGETS
    raw_dir = data_dir / "raw" / "open_targets"
    raw_dir.mkdir(parents=True, exist_ok=True)

    fetched: list[FetchedDocument] = []
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []

    with httpx.Client(
        timeout=60,
        follow_redirects=True,
        headers={"User-Agent": "pharma-research-agent/0.1 (teaching demo)"},
    ) as client:
        for symbol, ensembl_id in targets.items():
            response = client.post(
                GRAPHQL_URL,
                json={
                    "query": TARGET_QUERY,
                    "variables": {"id": ensembl_id, "size": size},
                },
            )
            response.raise_for_status()
            payload = response.json()
            if payload.get("errors"):
                raise RuntimeError(f"Open Targets GraphQL 错误: {payload['errors']}")
            target = payload["data"]["target"]
            raw_path = raw_dir / f"{symbol}.json"
            raw_path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

            nodes.append(
                {
                    "id": f"target:{ensembl_id}",
                    "node_type": "target",
                    "label": target.get("approvedSymbol") or symbol,
                    "properties": {
                        "ensembl_id": ensembl_id,
                        "approved_name": target.get("approvedName"),
                    },
                }
            )
            for row in target.get("associatedDiseases", {}).get("rows", []):
                disease = row.get("disease", {})
                disease_id = disease.get("id")
                if not disease_id:
                    continue
                nodes.append(
                    {
                        "id": f"disease:{disease_id}",
                        "node_type": "disease",
                        "label": disease.get("name") or disease_id,
                        "properties": {"disease_id": disease_id},
                    }
                )
                edges.append(
                    {
                        "source": f"target:{ensembl_id}",
                        "target": f"disease:{disease_id}",
                        "relation": "associated_with",
                        "weight": row.get("score"),
                        "properties": {
                            "datatype_scores": {
                                item.get("id"): item.get("score")
                                for item in row.get("datatypeScores", [])
                            }
                        },
                    }
                )

            fetched.append(
                FetchedDocument(
                    document=_build_document(symbol, target),
                    source="Open Targets Platform",
                    raw_path=str(raw_path),
                    parse_status="ok",
                )
            )

    write_jsonl(data_dir / "processed" / "graph" / "nodes.jsonl", _dedupe_nodes(nodes))
    write_jsonl(data_dir / "processed" / "graph" / "edges.jsonl", _dedupe_edges(edges))
    write_json(
        data_dir / "processed" / "graph" / "summary.json",
        {
            "targets": list(targets.keys()),
            "node_count": len(_dedupe_nodes(nodes)),
            "edge_count": len(_dedupe_edges(edges)),
        },
    )
    return fetched


def _build_document(symbol: str, target: dict[str, Any]) -> NormalizedDocument:
    rows = target.get("associatedDiseases", {}).get("rows", [])
    lines = []
    for row in rows:
        disease = row.get("disease", {})
        datatype = ", ".join(
            f"{item.get('id')}={item.get('score'):.3f}"
            for item in row.get("datatypeScores", [])
            if item.get("score") is not None
        )
        lines.append(
            f"{disease.get('name')} ({disease.get('id')}): "
            f"overall={row.get('score'):.3f}; {datatype}"
        )
    text = "\n".join(lines)
    title = f"[Open Targets] {symbol} target-disease associations"
    document = NormalizedDocument(
        doc_id=f"database:opentargets:{symbol}",
        source_type=SourceType.DATABASE,
        source_id=f"OpenTargets:{symbol}",
        title=title,
        text=f"{title}\n\n{text}",
        sections=[
            DocumentSection(
                heading="Target-disease associations",
                text=text,
                kind="database",
            )
        ],
        abstract=text[:500],
        url=f"https://platform.opentargets.org/target/{target.get('id')}",
        license="CC BY 4.0 (Open Targets Platform)",
        acl_scope="public",
        species="Homo sapiens",
        method="integrated evidence (genetic, literature, expression, animal model)",
        entity_ids=[target.get("id")],
        metadata={
            "symbol": symbol,
            "ensembl_id": target.get("id"),
            "approved_name": target.get("approvedName"),
            "association_count": target.get("associatedDiseases", {}).get("count"),
            "top_associations": rows,
        },
    )
    return document.finalize()


def _dedupe_nodes(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: dict[str, dict[str, Any]] = {}
    for node in nodes:
        seen[node["id"]] = node
    return sorted(seen.values(), key=lambda item: item["id"])


def _dedupe_edges(edges: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: dict[tuple[str, str, str], dict[str, Any]] = {}
    for edge in edges:
        key = (edge["source"], edge["target"], edge["relation"])
        seen[key] = edge
    return sorted(seen.values(), key=lambda item: (item["source"], item["target"]))
