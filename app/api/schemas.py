"""P6 API 响应模型。"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app.schemas import ReviewAction


class TaskCreateResponse(BaseModel):
    task_id: str
    status: str
    trace_id: str
    requires_human_review: bool = True


class TaskStatusResponse(BaseModel):
    task_id: str
    status: str
    user_id: str
    project_id: str
    question: str
    trace_id: str
    event_count: int = 0
    created_at: str = ""
    updated_at: str = ""
    version: int = 1
    error: str | None = None


class TaskResultResponse(BaseModel):
    task_id: str
    status: str
    assessment: str = ""
    claims: list[dict[str, Any]] = Field(default_factory=list)
    internal_evidence: list[dict[str, Any]] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)
    suggested_next_steps: list[str] = Field(default_factory=list)
    evidence: list[dict[str, Any]] = Field(default_factory=list)
    conflicts: list[dict[str, Any]] = Field(default_factory=list)
    report_md: str = ""
    trace_id: str = ""
    entities: list[dict[str, Any]] = Field(default_factory=list)
    subquestions: list[dict[str, Any]] = Field(default_factory=list)
    verify_notes: list[str] = Field(default_factory=list)
    llm_used: bool = False
    version: int = 1
    error: str | None = None


class ReviewRequest(BaseModel):
    reviewer_id: str | None = None
    claim_id: str | None = None
    action: ReviewAction
    comment: str = Field(default="", max_length=2000)


class ProjectInfo(BaseModel):
    project_id: str
    name: str = ""
    description: str = ""
