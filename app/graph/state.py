"""LangGraph 状态、预算、事件与 reducers。"""

from __future__ import annotations

import operator
import time
from datetime import datetime, timezone
from typing import Annotated, Any, TypedDict

from pydantic import BaseModel, Field

from app.schemas import Claim, Conflict, EntityRef, Evidence, SubQuestion
from app.tools.models import ToolResult


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class BudgetState(BaseModel):
    max_plan_rounds: int = 2
    max_subquestions: int = 5
    max_retrievals: int = 12
    max_tool_calls: int = 4
    max_llm_calls: int = 12
    max_task_seconds: int = 180
    max_evidence: int = 40

    started_at: float = Field(default_factory=time.time)
    plan_rounds: int = 0
    retrievals: int = 0
    tool_calls: int = 0
    llm_calls: int = 0

    def elapsed(self) -> float:
        return time.time() - self.started_at

    def timed_out(self) -> bool:
        return self.elapsed() > self.max_task_seconds

    def can_plan(self) -> bool:
        return self.plan_rounds < self.max_plan_rounds and not self.timed_out()

    def can_retrieve(self, count: int = 1) -> bool:
        return self.retrievals + count <= self.max_retrievals and not self.timed_out()

    def can_call_tool(self, count: int = 1) -> bool:
        return self.tool_calls + count <= self.max_tool_calls and not self.timed_out()

    def consume_plan(self) -> None:
        self.plan_rounds += 1

    def consume_retrievals(self, count: int) -> None:
        self.retrievals += count

    def consume_tool_calls(self, count: int) -> None:
        self.tool_calls += count

    def consume_llm(self) -> None:
        self.llm_calls += 1


class Event(BaseModel):
    node: str
    event_type: str = "info"
    message: str = ""
    payload: dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=utcnow)


class NodeError(BaseModel):
    node: str
    error_type: str
    message: str
    timestamp: datetime = Field(default_factory=utcnow)


def merge_evidence(
    existing: list[Evidence] | None,
    incoming: list[Evidence] | None,
) -> list[Evidence]:
    merged: dict[str, Evidence] = {}
    for item in (existing or []) + (incoming or []):
        key = item.evidence_id or item.chunk_id
        if key not in merged:
            merged[key] = item
    return list(merged.values())


class ResearchState(TypedDict, total=False):
    task_id: str
    trace_id: str
    user_id: str
    project_id: str
    question: str
    allowed_scopes: list[str]
    allowed_sources: list[Any]
    entities: list[EntityRef]
    subquestions: list[SubQuestion]
    evidence: Annotated[list[Evidence], merge_evidence]
    # normalize 的排序结果单独存放，避免 evidence reducer 保留 fan-out 旧顺序。
    final_evidence: list[Evidence]
    counter_evidence: list[Evidence]
    claims: list[Claim]
    assessment: str
    conflicts: list[Conflict]
    gaps: list[str]
    next_steps: list[str]
    verify_notes: list[str]
    llm_used: bool
    tool_results: Annotated[list[ToolResult], operator.add]
    events: Annotated[list[Event], operator.add]
    errors: Annotated[list[NodeError], operator.add]
    budget: BudgetState
    round: int
    status: str
    report_md: str
    review: dict[str, Any] | None
    metadata: dict[str, Any]
