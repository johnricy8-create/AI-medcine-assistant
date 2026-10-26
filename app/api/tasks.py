"""研究任务 API 与 SSE。"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from app.api.schemas import (
    ProjectInfo,
    ReviewRequest,
    TaskCreateResponse,
    TaskResultResponse,
    TaskStatusResponse,
)
from app.schemas import ResearchTaskRequest
from app.services.task_service import TERMINAL_STATUSES, TaskService

router = APIRouter(prefix="/api", tags=["research"])


def _service(request: Request) -> TaskService:
    service: TaskService | None = getattr(request.app.state, "task_service", None)
    if service is None:
        raise HTTPException(
            status_code=503,
            detail="研究服务尚未就绪；请检查索引、模型 Key 与服务日志",
        )
    return service


def _user_id(request: Request) -> str:
    settings = request.app.state.settings
    return request.headers.get(settings.demo_user_header) or settings.default_demo_user


@router.get("/projects", response_model=list[ProjectInfo])
def list_projects(request: Request) -> list[ProjectInfo]:
    service = _service(request)
    return [ProjectInfo.model_validate(item) for item in service.store.list_projects()]


@router.post("/research/tasks", response_model=TaskCreateResponse)
def create_task(payload: ResearchTaskRequest, request: Request) -> TaskCreateResponse:
    service = _service(request)
    projects = {item["project_id"] for item in service.store.list_projects()}
    user_id = _user_id(request)
    if payload.project_id not in projects:
        service.store.log_audit(
            user_id=user_id,
            project_id=payload.project_id,
            action="create_task",
            resource="research_tasks",
            allowed=False,
            reason="project_not_found",
        )
        raise HTTPException(status_code=400, detail="项目不存在")
    try:
        record = service.create_task(
            user_id=user_id,
            project_id=payload.project_id,
            question=payload.question.strip(),
            sources=payload.sources,
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"任务创建失败: {exc}") from exc
    service.store.log_audit(
        user_id=user_id,
        project_id=payload.project_id,
        action="create_task",
        resource=record.task_id,
        allowed=True,
    )
    return TaskCreateResponse(
        task_id=record.task_id,
        status=record.status,
        trace_id=record.trace_id,
        requires_human_review=payload.require_human_review,
    )


@router.get("/research/tasks/{task_id}", response_model=TaskStatusResponse)
def get_task(task_id: str, request: Request) -> TaskStatusResponse:
    service = _service(request)
    record = service.get_task(task_id)
    if record is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    error = None
    if record.result:
        error = record.result.get("error")
    return TaskStatusResponse(
        task_id=record.task_id,
        status=record.status,
        user_id=record.user_id,
        project_id=record.project_id,
        question=record.question,
        trace_id=record.trace_id,
        event_count=record.event_count,
        created_at=record.created_at,
        updated_at=record.updated_at,
        version=record.version,
        error=error,
    )


@router.get("/research/tasks/{task_id}/result", response_model=TaskResultResponse)
def get_result(task_id: str, request: Request) -> TaskResultResponse:
    service = _service(request)
    record = service.get_task(task_id)
    if record is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    result = service.get_result(task_id)
    if result is None:
        raise HTTPException(status_code=202, detail="任务尚未完成")
    evidence = result.get("final_evidence") or result.get("evidence") or []
    claims = result.get("claims", [])
    internal = [
        item for item in evidence if item.get("source_type") == "eln"
    ]
    return TaskResultResponse(
        task_id=task_id,
        status=record.status,
        assessment=result.get("assessment", ""),
        claims=claims,
        internal_evidence=internal,
        gaps=result.get("gaps", []),
        suggested_next_steps=result.get("next_steps", []),
        evidence=evidence,
        conflicts=result.get("conflicts", []),
        report_md=result.get("report_md", ""),
        trace_id=result.get("trace_id") or record.trace_id,
        entities=result.get("entities", []),
        subquestions=result.get("subquestions", []),
        verify_notes=result.get("verify_notes", []),
        llm_used=bool(result.get("llm_used")),
        version=int(result.get("version", record.version)),
        error=result.get("error"),
    )


@router.get("/research/tasks/{task_id}/events")
async def stream_events(
    task_id: str,
    request: Request,
    after: int = Query(default=0, ge=0),
) -> StreamingResponse:
    service = _service(request)
    record = service.get_task(task_id)
    if record is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    header_last = request.headers.get("Last-Event-ID")
    try:
        last_id = int(header_last) if header_last else after
    except ValueError:
        last_id = after

    async def generator():
        nonlocal last_id
        idle = 0
        while True:
            if await request.is_disconnected():
                break
            events = service.store.list_events(task_id, last_id)
            for event in events:
                last_id = event.id
                payload = event.model_dump(mode="json")
                yield (
                    f"id: {event.id}\n"
                    f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
                )
            current = service.get_task(task_id)
            if current is None:
                break
            if current.status in TERMINAL_STATUSES and not events:
                yield 'event: done\ndata: {"status": "%s"}\n\n' % current.status
                break
            await asyncio.sleep(0.4)
            idle += 1
            if idle % 38 == 0:
                yield ": ping\n\n"

    return StreamingResponse(
        generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/research/tasks/{task_id}/review")
def review_task(
    task_id: str,
    payload: ReviewRequest,
    request: Request,
) -> dict[str, Any]:
    service = _service(request)
    reviewer = payload.reviewer_id or _user_id(request)
    try:
        return service.review_task(
            task_id,
            reviewer_id=reviewer,
            action=payload.action.value,
            claim_id=payload.claim_id,
            comment=payload.comment,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/research/tasks/{task_id}/reviews")
def list_reviews(task_id: str, request: Request) -> list[dict[str, Any]]:
    service = _service(request)
    if service.get_task(task_id) is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    return service.store.list_reviews(task_id)


@router.get("/research/tasks/{task_id}/snapshot")
def get_snapshot(task_id: str, request: Request) -> dict[str, Any]:
    service = _service(request)
    if service.get_task(task_id) is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    snapshot = service.store.get_snapshot(task_id)
    if snapshot is None:
        raise HTTPException(status_code=404, detail="快照不存在")
    return snapshot


@router.get("/audit")
def audit(request: Request, limit: int = Query(default=100, ge=1, le=500)) -> list[dict[str, Any]]:
    service = _service(request)
    return service.store.list_audit(limit=limit)


@router.get("/evidence/{evidence_id}")
def get_evidence(evidence_id: str, request: Request) -> dict[str, Any]:
    service = _service(request)
    evidence = service.store.get_evidence(evidence_id)
    if evidence is None:
        raise HTTPException(status_code=404, detail="证据不存在")
    user_id = _user_id(request)
    user = service.services.acl.users.get(user_id)
    allowed = set(user.allowed_scopes if user else ["public"])
    if evidence.get("acl_scope") not in allowed:
        service.store.log_audit(
            user_id=user_id,
            project_id=evidence.get("project_id"),
            action="read_evidence",
            resource=evidence_id,
            allowed=False,
            reason="acl_scope_denied",
        )
        raise HTTPException(status_code=404, detail="证据不存在")
    service.store.log_audit(
        user_id=user_id,
        project_id=evidence.get("project_id"),
        action="read_evidence",
        resource=evidence_id,
        allowed=True,
    )
    return evidence
