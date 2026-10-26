"""领域数据结构。

P0 先固定核心枚举与 Pydantic 模型，后续 LangGraph 节点直接复用，
避免在节点里临时拼 dict 导致字段漂移。
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class SourceType(str, Enum):
    LITERATURE = "literature"
    PATENT = "patent"
    ELN = "eln"
    REPORT = "report"
    OMICS = "omics"
    TRIAL = "trial"
    DATABASE = "database"


class Stance(str, Enum):
    SUPPORT = "support"
    CONTRADICT = "contradict"
    NEUTRAL = "neutral"
    UNKNOWN = "unknown"


class EvidenceLevel(str, Enum):
    A = "A"
    B = "B"
    C = "C"
    D = "D"
    UNKNOWN = "unknown"


class TaskStatus(str, Enum):
    PLANNED = "planned"
    RUNNING = "running"
    PENDING_REVIEW = "pending_review"
    COMPLETED = "completed"
    FAILED = "failed"
    REJECTED = "rejected"


class ReviewAction(str, Enum):
    ACCEPT = "accept"
    ACCEPT_WITH_REVISION = "accept_with_revision"
    REJECT = "reject"


class EntityRef(BaseModel):
    canonical_id: str
    entity_type: Literal[
        "target", "gene", "protein", "disease", "cell", "compound", "pathway"
    ]
    name: str
    aliases: list[str] = Field(default_factory=list)
    cross_ids: dict[str, str] = Field(default_factory=dict)
    species: str | None = None
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)


class SubQuestion(BaseModel):
    id: str
    text: str
    intent: str = "evidence_lookup"
    sources: list[SourceType] = Field(default_factory=list)
    queries: list[str] = Field(default_factory=list)
    filters: dict[str, Any] = Field(default_factory=dict)
    status: Literal["pending", "running", "done", "failed"] = "pending"


class Locator(BaseModel):
    page: int | None = None
    section: str | None = None
    figure: str | None = None
    table: str | None = None
    doi: str | None = None
    patent_no: str | None = None
    experiment_id: str | None = None
    url: str | None = None


class ScoreSet(BaseModel):
    dense: float | None = None
    sparse: float | None = None
    rrf: float | None = None
    rerank: float | None = None


class Evidence(BaseModel):
    evidence_id: str
    source_type: SourceType
    source_id: str
    title: str
    chunk_id: str
    quote: str
    locator: Locator = Field(default_factory=Locator)
    entity_ids: list[str] = Field(default_factory=list)
    species: str | None = None
    sample: str | None = None
    method: str | None = None
    stance: Stance = Stance.UNKNOWN
    level: EvidenceLevel = EvidenceLevel.UNKNOWN
    acl_scope: str = "public"
    scores: ScoreSet = Field(default_factory=ScoreSet)
    retrieved_at: datetime = Field(default_factory=utcnow)
    tool_call_id: str | None = None


class Claim(BaseModel):
    claim_id: str
    text: str
    stance: Stance
    level: EvidenceLevel = EvidenceLevel.UNKNOWN
    support_ids: list[str] = Field(default_factory=list)
    contradict_ids: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    caveats: list[str] = Field(default_factory=list)
    verified: bool = False


class Conflict(BaseModel):
    topic: str
    support_ids: list[str] = Field(default_factory=list)
    contradict_ids: list[str] = Field(default_factory=list)
    explanation: str


class ReviewDecision(BaseModel):
    reviewer_id: str
    claim_id: str | None = None
    action: ReviewAction
    comment: str = ""


class ResearchTaskRequest(BaseModel):
    project_id: str = Field(min_length=1, max_length=100)
    question: str = Field(min_length=1, max_length=2000)
    sources: list[SourceType] = Field(
        default_factory=lambda: [
            SourceType.LITERATURE,
            SourceType.PATENT,
            SourceType.ELN,
            SourceType.OMICS,
            SourceType.TRIAL,
        ]
    )
    require_human_review: bool = True


class ResearchTaskResponse(BaseModel):
    task_id: str
    status: TaskStatus
    subquestions: list[str] = Field(default_factory=list)
    estimated_minutes: float = 0.0
    requires_human_review: bool = True
    trace_id: str


class ResearchResult(BaseModel):
    task_id: str
    status: TaskStatus
    assessment: str = ""
    claims: list[Claim] = Field(default_factory=list)
    internal_evidence: list[Evidence] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)
    suggested_next_steps: list[str] = Field(default_factory=list)
    trace_id: str = ""


class KnowledgeStats(BaseModel):
    document_count: int = 0
    chunk_count: int = 0
    last_rebuilt_at: datetime | None = None
    embedding_model: str
    embedding_dim: int
    collection: str = "default"


class HealthResponse(BaseModel):
    app: str
    version: str
    status: Literal["ok", "degraded"]
    database: Literal["ok", "error"]
    llm_configured: bool
    embedding_configured: bool
    index_available: bool
    timestamp: datetime = Field(default_factory=utcnow)
