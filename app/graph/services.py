"""图运行时依赖容器。"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from app.config import Settings
from app.evidence.claims import ClaimSynthesizer
from app.evidence.grading import EvidenceGrader
from app.evidence.verification import CitationVerifier
from app.graph.planner import RuleBasedPlanner
from app.ingest.chunker import Chunk
from app.ingest.entity_linker import EntityLinker
from app.ingest.manifest import read_jsonl
from app.ingest.models import NormalizedDocument
from app.llm.client import LLMClient
from app.retrieval.hybrid import HybridRetriever, build_hybrid_retriever
from app.services.acl import AccessService
from app.tools.omics import OmicsTool

logger = logging.getLogger(__name__)


@dataclass
class GraphServices:
    settings: Settings
    retriever: HybridRetriever
    omics_tool: OmicsTool
    linker: EntityLinker
    acl: AccessService
    documents: dict[str, NormalizedDocument]
    planner: RuleBasedPlanner
    chunks: dict[str, Chunk] = field(default_factory=dict)
    llm: LLMClient | None = None
    grader: EvidenceGrader = field(default_factory=EvidenceGrader)
    synthesizer: ClaimSynthesizer = field(default_factory=ClaimSynthesizer)
    verifier: CitationVerifier | None = None

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
    chunks_path = data_dir / "processed" / "chunks.jsonl"
    chunks = {
        row["chunk_id"]: Chunk.model_validate(row)
        for row in read_jsonl(chunks_path)
    } if chunks_path.exists() else {}
    omics_path = data_dir / "processed" / "omics" / "hpa_expression.json"
    acl_dir = data_dir / "internal_demo" / "acl"
    llm = None
    if settings.llm_configured():
        try:
            llm = LLMClient(settings)
        except Exception as exc:  # noqa: BLE001
            logger.warning("LLM 初始化失败，将使用规则兜底: %s", exc)
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
        chunks=chunks,
        llm=llm,
        verifier=CitationVerifier(chunks),
    )
