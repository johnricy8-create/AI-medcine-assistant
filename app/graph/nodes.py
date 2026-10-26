"""LangGraph 节点实现。

P4 只负责：准入、实体、规划、并行检索、证据归一化、最小研究底稿。
证据分级、claims、反例、引用校验在 P5。
"""

from __future__ import annotations

import json
import re
import uuid
from typing import Any

from langgraph.types import Send

from app.graph.services import GraphServices
from app.graph.state import BudgetState, Event, NodeError, ResearchState
from app.ingest.manifest import sha256_text
from app.schemas import (
    EntityRef,
    Evidence,
    EvidenceLevel,
    Locator,
    ScoreSet,
    SourceType,
    Stance,
    SubQuestion,
    TaskStatus,
)
from app.tools.models import ToolResult

INJECTION_PATTERNS = (
    "ignore previous",
    "ignore all previous",
    "system prompt",
    "developer message",
    "忽略之前",
    "忽略以上",
    "忽略前面",
    "输出所有未公开",
    "输出所有项目",
)
PROJECT_PATTERN = re.compile(
    r"\b(?:[A-Z]{2,}-\d{2,}|[A-Z]{2,}-[A-Z]{2,}-\d{2,})\b"
)


def _event(
    node: str,
    message: str,
    event_type: str = "info",
    **payload: Any,
) -> Event:
    return Event(node=node, event_type=event_type, message=message, payload=payload)


def _error(node: str, exc: Exception) -> NodeError:
    return NodeError(
        node=node,
        error_type=type(exc).__name__,
        message=str(exc)[:500],
    )


def _as_budget(value: Any, services: GraphServices) -> BudgetState:
    if isinstance(value, BudgetState):
        return value
    if isinstance(value, dict):
        return BudgetState.model_validate(value)
    settings = services.settings
    return BudgetState(
        max_plan_rounds=settings.max_plan_rounds,
        max_subquestions=settings.max_subquestions,
        max_retrievals=settings.max_retrievals,
        max_tool_calls=settings.max_tool_calls,
        max_llm_calls=settings.max_llm_calls,
        max_task_seconds=settings.max_task_seconds,
        max_evidence=settings.max_evidence,
    )


def intake_node(state: ResearchState, services: GraphServices) -> dict[str, Any]:
    question = (state.get("question") or "").strip()
    task_id = state.get("task_id") or f"rt-{uuid.uuid4().hex[:10]}"
    trace_id = state.get("trace_id") or f"rr-{uuid.uuid4().hex[:10]}"
    user_id = state.get("user_id") or services.settings.default_demo_user
    project_id = state.get("project_id") or ""
    access = services.acl.context(user_id, project_id)
    budget = _as_budget(state.get("budget"), services)
    events = [
        _event(
            "intake",
            "任务准入完成",
            user_id=user_id,
            project_id=project_id,
            allowed_scopes=access.allowed_scopes,
        )
    ]

    blocked_reason = ""
    if not question:
        blocked_reason = "empty_question"
    elif len(question) > 2000:
        blocked_reason = "question_too_long"
    elif any(pattern.casefold() in question.casefold() for pattern in INJECTION_PATTERNS):
        blocked_reason = "unsafe_instruction"
    else:
        mentioned = set(PROJECT_PATTERN.findall(question))
        unauthorized = [
            project
            for project in mentioned
            if project in services.acl.project_ids()
            and project not in access.project_ids
        ]
        if unauthorized:
            blocked_reason = "unauthorized_project"

    if blocked_reason:
        events.append(
            _event(
                "intake",
                "请求被安全策略拦截",
                "blocked",
                reason=blocked_reason,
            )
        )
        return {
            "task_id": task_id,
            "trace_id": trace_id,
            "user_id": user_id,
            "project_id": project_id,
            "question": question,
            "allowed_scopes": access.allowed_scopes,
            "budget": budget,
            "events": events,
            "status": TaskStatus.BLOCKED.value,
            "report_md": "请求被安全策略拦截，或无权访问该内容。",
            "metadata": {
                "project_allowed": access.project_allowed,
                "user_known": access.user_known,
                "blocked_reason": blocked_reason,
            },
        }

    if not access.project_allowed:
        events.append(
            _event(
                "intake",
                "用户不属于当前项目，仅检索 public 证据",
                "warning",
                project_id=project_id,
            )
        )

    return {
        "task_id": task_id,
        "trace_id": trace_id,
        "user_id": user_id,
        "project_id": project_id,
        "question": question,
        "allowed_scopes": access.allowed_scopes,
        "budget": budget,
        "events": events,
        "status": TaskStatus.RUNNING.value,
        "report_md": "",
        "metadata": {
            "project_allowed": access.project_allowed,
            "user_known": access.user_known,
        },
    }


def link_entities_node(state: ResearchState, services: GraphServices) -> dict[str, Any]:
    question = state.get("question", "")
    entities = services.linker.link(question)
    return {
        "entities": entities,
        "events": [
            _event(
                "link_entities",
                f"识别实体 {len(entities)} 个",
                entities=[
                    {
                        "id": entity.canonical_id,
                        "name": entity.name,
                        "type": entity.entity_type,
                        "confidence": entity.confidence,
                    }
                    for entity in entities
                ],
            )
        ],
        "status": TaskStatus.RUNNING.value,
    }


def plan_node(state: ResearchState, services: GraphServices) -> dict[str, Any]:
    budget = _as_budget(state.get("budget"), services)
    if not budget.can_plan():
        return {
            "budget": budget,
            "status": TaskStatus.BUDGET_EXHAUSTED.value,
            "report_md": "任务预算已耗尽，未能继续规划。",
            "events": [
                _event("plan", "规划预算耗尽", "warning", elapsed=budget.elapsed())
            ],
        }
    budget.consume_plan()
    remaining_retrievals = max(0, budget.max_retrievals - budget.retrievals)
    remaining_tools = max(0, budget.max_tool_calls - budget.tool_calls)
    subquestions = services.planner.plan(
        state.get("question", ""),
        state.get("entities", []),
        max_subquestions=budget.max_subquestions,
        max_retrievals=remaining_retrievals,
    )
    subquestions, retrieval_count, tool_count = _fit_source_budget(
        subquestions,
        remaining_retrievals,
        remaining_tools,
    )
    budget.consume_retrievals(retrieval_count)
    budget.consume_tool_calls(tool_count)

    status = TaskStatus.RUNNING.value if subquestions else TaskStatus.BUDGET_EXHAUSTED.value
    return {
        "subquestions": subquestions,
        "budget": budget,
        "status": status,
        "report_md": "" if subquestions else "没有可执行的检索子问题（预算或数据源限制）。",
        "events": [
            _event(
                "plan",
                f"规划 {len(subquestions)} 个子问题，{retrieval_count} 次检索",
                subquestions=[
                    {
                        "id": item.id,
                        "intent": item.intent,
                        "sources": [source.value for source in item.sources],
                    }
                    for item in subquestions
                ],
                retrieval_count=retrieval_count,
                tool_count=tool_count,
            )
        ],
    }


def _fit_source_budget(
    subquestions: list[SubQuestion],
    max_retrievals: int,
    max_tools: int,
) -> tuple[list[SubQuestion], int, int]:
    fitted: list[SubQuestion] = []
    retrievals = 0
    tools = 0
    for subquestion in subquestions:
        sources: list[SourceType] = []
        for source in subquestion.sources:
            if retrievals >= max_retrievals:
                break
            if source == SourceType.OMICS and tools >= max_tools:
                continue
            sources.append(source)
            retrievals += 1
            if source == SourceType.OMICS:
                tools += 1
        if sources:
            fitted.append(subquestion.model_copy(update={"sources": sources}))
    return fitted, retrievals, tools


def fan_out(state: ResearchState) -> list[Send] | str:
    if state.get("status") in {
        TaskStatus.BLOCKED.value,
        TaskStatus.BUDGET_EXHAUSTED.value,
    }:
        return "finalize"
    subquestions = state.get("subquestions", [])
    if not subquestions:
        return "finalize"
    sends: list[Send] = []
    for subquestion in subquestions:
        for source in subquestion.sources:
            sends.append(
                Send(
                    "retrieve_source",
                    {
                        "task_id": state.get("task_id"),
                        "question": state.get("question"),
                        "subquestion": subquestion.model_dump(mode="json"),
                        "source": source.value,
                        "allowed_scopes": state.get("allowed_scopes", []),
                        "entities": [
                            entity.model_dump(mode="json")
                            for entity in state.get("entities", [])
                        ],
                    },
                )
            )
    return sends


def retrieve_source_node(payload: dict[str, Any], services: GraphServices) -> dict[str, Any]:
    subquestion = SubQuestion.model_validate(payload["subquestion"])
    source = SourceType(payload["source"])
    allowed = set(payload.get("allowed_scopes", []))
    node_name = f"retrieve_source:{source.value}"
    events: list[Event] = []
    errors: list[NodeError] = []
    evidence: list[Evidence] = []
    tool_results: list[ToolResult] = []

    try:
        if source == SourceType.OMICS:
            entities = [
                EntityRef.model_validate(item)
                for item in payload.get("entities", [])
            ]
            genes = [
                entity.name
                for entity in entities
                if entity.entity_type in {"gene", "target", "protein"}
            ]
            if not genes:
                events.append(
                    _event(node_name, "未识别到可查询的基因，跳过组学工具", "warning")
                )
                return {"events": events}
            for gene in dict.fromkeys(genes):
                result = services.omics_tool.expression(gene, top_n=8)
                tool_results.append(result)
                if not result.ok:
                    errors.append(
                        NodeError(
                            node=node_name,
                            error_type="ToolError",
                            message=result.error or "组学工具返回失败",
                        )
                    )
                    continue
                data = result.data
                quote = json.dumps(data, ensure_ascii=False)[:1200]
                evidence.append(
                    Evidence(
                        evidence_id=f"ev-tool-{sha256_text(gene + payload['task_id'])[:12]}",
                        source_type=SourceType.OMICS,
                        source_id=f"HPA:{gene}",
                        title=f"[HPA] {gene} expression profile",
                        chunk_id=f"tool:{gene}",
                        quote=quote,
                        locator=Locator(url=data.get("source_url")),
                        entity_ids=[
                            item
                            for item in [data.get("ensembl")]
                            if item
                        ],
                        species="Homo sapiens",
                        sample="tissue / single cell / blood",
                        method="RNA expression profiling",
                        stance=Stance.UNKNOWN,
                        level=EvidenceLevel.UNKNOWN,
                        acl_scope="public",
                        scores=ScoreSet(),
                        tool_call_id=f"tool-omics-{gene}",
                    )
                )
                events.append(
                    _event(node_name, f"组学工具返回 {gene}", gene=gene)
                )
            return {
                "evidence": evidence,
                "tool_results": tool_results,
                "events": events,
                "errors": errors,
            }

        result = services.retriever.retrieve(
            subquestion.queries[0] if subquestion.queries else payload["question"],
            k=6,
            allowed_scopes=list(allowed),
            source_types=[source.value],
            use_rerank=None,
        )
        for hit in result.hits:
            metadata = hit.metadata or {}
            acl_scope = str(metadata.get("acl_scope") or "public")
            if acl_scope not in allowed:
                continue
            document = services.document(str(metadata.get("doc_id") or hit.doc_id))
            quote = hit.text.strip()
            if not quote:
                continue
            page = metadata.get("page_number")
            page_number = int(page) if isinstance(page, int) and page > 0 else None
            evidence.append(
                Evidence(
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
                            document.metadata.get("patent_no")
                            if document
                            else None
                        ),
                        experiment_id=(
                            document.metadata.get("experiment_id")
                            if document
                            else None
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
                )
            )
        events.append(
            _event(
                node_name,
                f"检索到 {len(evidence)} 条证据",
                subquestion=subquestion.id,
                top_doc_ids=[item.source_id for item in evidence[:5]],
                dense=result.dense_count,
                sparse=result.sparse_count,
                reranked=result.reranked,
            )
        )
    except Exception as exc:  # noqa: BLE001
        errors.append(_error(node_name, exc))
        events.append(
            _event(node_name, f"检索失败: {type(exc).__name__}", "error")
        )
    return {
        "evidence": evidence,
        "tool_results": tool_results,
        "events": events,
        "errors": errors,
    }


def normalize_node(state: ResearchState, services: GraphServices) -> dict[str, Any]:
    allowed = set(state.get("allowed_scopes", []))
    budget = _as_budget(state.get("budget"), services)
    deduped: dict[str, Evidence] = {}
    for item in state.get("evidence", []):
        if allowed and item.acl_scope not in allowed:
            continue
        document = services.document(item.source_id)
        if document:
            item.title = item.title or document.title
            item.locator.doi = item.locator.doi or document.doi
            item.locator.url = item.locator.url or document.url
            item.locator.patent_no = (
                item.locator.patent_no
                or document.metadata.get("patent_no")
            )
            item.locator.experiment_id = (
                item.locator.experiment_id
                or document.metadata.get("experiment_id")
            )
            item.species = item.species if item.species != "unknown" else document.species
            item.sample = item.sample or document.sample
            item.method = item.method or document.method
            item.entity_ids = sorted(set(item.entity_ids) | set(document.entity_ids))
        existing = deduped.get(item.chunk_id)
        if existing is None or _evidence_score(item) > _evidence_score(existing):
            deduped[item.chunk_id] = item
    evidence = sorted(
        deduped.values(),
        key=_evidence_score,
        reverse=True,
    )[: budget.max_evidence]
    subquestions = [
        item.model_copy(update={"status": "done"})
        for item in state.get("subquestions", [])
    ]
    return {
        "final_evidence": evidence,
        "subquestions": subquestions,
        "events": [
            _event(
                "normalize",
                f"归一化后保留 {len(evidence)} 条证据",
                acl_scopes=sorted({item.acl_scope for item in evidence}),
            )
        ],
        "status": TaskStatus.RUNNING.value,
    }


def finalize_node(state: ResearchState, services: GraphServices) -> dict[str, Any]:
    status = state.get("status", TaskStatus.RUNNING.value)
    events = [_event("finalize", "生成研究底稿", status=status)]
    if status == TaskStatus.BLOCKED.value:
        return {
            "status": status,
            "report_md": state.get("report_md") or "请求被安全策略拦截。",
            "events": events,
        }
    if status == TaskStatus.BUDGET_EXHAUSTED.value:
        return {
            "status": status,
            "report_md": state.get("report_md") or "任务预算已耗尽。",
            "events": events,
        }

    allowed = set(state.get("allowed_scopes", []))
    final_evidence = state.get("final_evidence")
    if final_evidence is None:
        final_evidence = state.get("evidence", [])
    evidence = [
        item
        for item in final_evidence
        if not allowed or item.acl_scope in allowed
    ]
    if not evidence:
        return {
            "status": TaskStatus.NO_EVIDENCE.value,
            "report_md": "知识库中没有找到足够依据，请补充文档或转研发专家。",
            "events": [_event("finalize", "没有合格证据，拒答", "no_evidence")],
        }

    question = state.get("question", "")
    entities = state.get("entities", [])
    lines = [
        "# 研究证据底稿（P4 检索阶段）",
        "",
        f"**问题**：{question}",
        f"**用户/项目**：{state.get('user_id')} / {state.get('project_id')}",
        f"**实体**：{', '.join(entity.name for entity in entities) or '未识别'}",
        f"**可见范围**：{', '.join(state.get('allowed_scopes', []))}",
        "",
        "## 子问题",
    ]
    for item in state.get("subquestions", []):
        lines.append(
            f"- `{item.id}` {item.intent}: "
            f"{', '.join(source.value for source in item.sources)}"
        )
    lines.extend(["", "## 检索证据"])
    for index, item in enumerate(evidence[:20], start=1):
        scores = item.scores
        score_parts = []
        for name in ("dense", "sparse", "rrf", "rerank"):
            value = getattr(scores, name)
            if value is not None:
                score_parts.append(f"{name}={value:.4f}")
        lines.extend(
            [
                f"### {index}. [{item.source_type.value}] {item.title}",
                f"- 来源：`{item.source_id}`",
                f"- 定位：{item.locator.section or item.locator.url or 'N/A'}",
                f"- 分数：{', '.join(score_parts)}",
                f"- 片段：{item.quote[:400]}",
                "",
            ]
        )
    lines.extend(
        [
            "## 说明",
            "本文件是 P4 检索编排结果；证据分级、claims、反例、引用校验将在 P5 实现。",
            "内部 ELN/项目/专利为 `DEMO / SYNTHETIC`，不得作为真实科学结论。",
        ]
    )
    source_counts: dict[str, int] = {}
    for item in evidence:
        key = item.source_type.value
        source_counts[key] = source_counts.get(key, 0) + 1
    events.append(
        _event(
            "finalize",
            "研究底稿完成",
            evidence_count=len(evidence),
            source_counts=source_counts,
        )
    )
    return {
        "status": TaskStatus.COMPLETED.value,
        "report_md": "\n".join(lines),
        "events": events,
    }


def _evidence_score(item: Evidence) -> float:
    scores = item.scores
    if scores.rerank is not None:
        return float(scores.rerank)
    if scores.rrf is not None:
        return float(scores.rrf)
    if scores.dense is not None:
        return -float(scores.dense)
    return 0.0
