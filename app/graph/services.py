"""图运行时依赖容器。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.config import Settings
from app.graph.planner import RuleBasedPlanner
from app.ingest.entity_linker import EntityLinker
from app.ingest.manifest import read_jsonl
from app.ingest.models import NormalizedDocument
from app.retrieval.hybrid import HybridRetriever, build_hybrid_retriever
from app.services.acl import AccessService
from app.tools.omics import OmicsTool


@dataclass
class GraphServices:
    settings: Settings
    retriever: HybridRetriever
    omics_tool: OmicsTool
    linker: EntityLinker
    acl: AccessService
    documents: dict[str, NormalizedDocument]
    planner: RuleBasedPlanner

    def close(self) -> None:
        self.retriever.vector_store.close()

    def document(self, doc_id: str) -> NormalizedDocument | None:
        return self.documents.get(doc_id)


def build_services(
    settings: Settings,
    *,
    use_rerank: bool | None = None,
) -> GraphServices:
    data_dir = settings.data_dir
    documents_path = data_dir / "processed" / "documents.jsonl"
    if not documents_path.exists():
        raise FileNotFoundError(
            f"未找到文档 {documents_path}；请先运行 scripts/fetch_data.py"
        )
    documents = {
        row["doc_id"]: NormalizedDocument.model_validate(row)
        for row in read_jsonl(documents_path)
    }
    retriever = build_hybrid_retriever(settings, use_rerank=use_rerank)
    omics_path = data_dir / "processed" / "omics" / "hpa_expression.json"
    acl_dir = data_dir / "internal_demo" / "acl"
    return GraphServices(
        settings=settings,
        retriever=retriever,
        omics_tool=OmicsTool(omics_path),
        linker=EntityLinker.from_yaml(data_dir / "ontology" / "entities.yaml"),
        acl=AccessService.from_files(
            acl_dir / "users.yaml",
            acl_dir / "projects.yaml",
        ),
        documents=documents,
        planner=RuleBasedPlanner(),
    )
