"""研究任务执行服务：后台运行 LangGraph、持久化事件与结果。"""

from __future__ import annotations

import logging
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from fastapi.encoders import jsonable_encoder

from app.config import Settings
from app.evidence.report import render_research_brief
from app.graph.builder import build_graph
from app.graph.services import GraphServices
from app.graph.state import Event
from app.schemas import Claim, Conflict, EntityRef, Evidence, ReviewAction, SourceType
from app.services.task_store import TaskRecord, TaskStore
from app.storage.db import init_db

logger = logging.getLogger(__name__)

TERMINAL_STATUSES = {
    "completed",
    "no_evidence",
    "blocked",
    "budget_exhausted",
    "failed",
    "rejected",
}


class TaskService:
    def __init__(
        self,
        settings: Settings,
        services: GraphServices,
        *,
        max_workers: int = 2,
        store: TaskStore | None = None,
    ) -> None:
        self.settings = settings
        self.services = services
        init_db(settings.sqlite_path)
        self.store = store or TaskStore(
            settings.sqlite_path,
            settings.data_dir,
            settings.snapshot_dir,
        )
        self.store.ensure_projects_from_acl(
            settings.data_dir / "internal_demo" / "acl"
        )
        self._executor = ThreadPoolExecutor(
            max_workers=max_workers,
            thread_name_prefix="research-task",
        )

    def create_task(
        self,
        *,
        user_id: str,
        project_id: str,
        question: str,
        sources: list[SourceType] | None = None,
    ) -> TaskRecord:
        task_id = f"rt-{uuid.uuid4().hex[:10]}"
        trace_id = f"rr-{uuid.uuid4().hex[:10]}"
        record = self.store.create_task(
            task_id=task_id,
            user_id=user_id,
            project_id=project_id,
            question=question,
            trace_id=trace_id,
        )
        self._executor.submit(
            self._execute,
            task_id,
            user_id,
            project_id,
            question,
            trace_id,
            list(sources) if sources else list(SourceType),
        )
        return record

    def _execute(
        self,
        task_id: str,
        user_id: str,
        project_id: str,
        question: str,
        trace_id: str,
        sources: list[SourceType],
    ) -> None:
        self.store.update_status(task_id, "running")
        self.store.append_events(
            task_id,
            [
                Event(
                    node="task",
                    event_type="started",
                    message="研究任务开始",
                    payload={"task_id": task_id},
                )
            ],
        )
        final_state: dict[str, Any] = {}
        seen_events = 0
        try:
            graph = build_graph(self.services)
            initial = {
                "task_id": task_id,
                "trace_id": trace_id,
                "user_id": user_id,
                "project_id": project_id,
                "question": question,
                "allowed_sources": sources,
            }
            for snapshot in graph.stream(
                initial,
                config={"configurable": {"thread_id": task_id}},
                stream_mode="values",
            ):
                if not isinstance(snapshot, dict):
                    continue
                final_state = snapshot
                events = snapshot.get("events", [])
                if len(events) > seen_events:
                    self.store.append_events(task_id, events[seen_events:])
                    seen_events = len(events)
                # 终态要等结果和快照落库后再写，避免 wait() 提前返回空结果。
                status = snapshot.get("status")
                if status and status not in TERMINAL_STATUSES:
                    self.store.update_status(task_id, status)

            if not final_state:
                raise RuntimeError("图执行没有返回状态")
            status = str(final_state.get("status") or "completed")
            self.store.save_result(task_id, final_state)
            record = self.store.get_task(task_id)
            snapshot_state = jsonable_encoder(final_state)
            snapshot_state["llm_model"] = self.settings.llm_model
            snapshot_state["rerank_model"] = (
                self.settings.rerank_model if self.settings.rerank_enabled else None
            )
            self.store.save_snapshot(
                task_id,
                state=snapshot_state,
                version=record.version if record else 1,
            )
            self.store.append_events(
                task_id,
                [
                    Event(
                        node="task",
                        event_type="finished",
                        message="研究任务结束",
                        payload={"status": status},
                    )
                ],
            )
            self.store.update_status(task_id, status)
        except Exception as exc:  # noqa: BLE001
            logger.exception("任务执行失败 %s", task_id)
            self.store.update_status(task_id, "failed")
            self.store.append_events(
                task_id,
                [
                    Event(
                        node="task",
                        event_type="failed",
                        message=f"任务失败: {type(exc).__name__}",
                        payload={"error": str(exc)[:500]},
                    )
                ],
            )
            self.store.save_result(
                task_id,
                {
                    "task_id": task_id,
                    "status": "failed",
                    "report_md": "研究任务执行失败，请检查日志或重试。",
                    "error": str(exc)[:500],
                    "events": [],
                },
            )

    def review_task(
        self,
        task_id: str,
        *,
        reviewer_id: str,
        action: str,
        claim_id: str | None = None,
        comment: str = "",
    ) -> dict[str, Any]:
        record = self.store.get_task(task_id)
        if record is None:
            raise KeyError("任务不存在")
        access = self.services.acl.context(reviewer_id, record.project_id)
        if not access.project_allowed:
            self.store.log_audit(
                user_id=reviewer_id,
                project_id=record.project_id,
                action="review",
                resource=task_id,
                allowed=False,
                reason="project_access_denied",
            )
            raise PermissionError("无权评审该项目")
        result = self.store.get_result(task_id)
        if result is None:
            raise ValueError("任务尚未生成结果")
        action_value = action.value if isinstance(action, ReviewAction) else str(action)
        if action_value not in {"accept", "accept_with_revision", "reject"}:
            raise ValueError("无效评审动作")
        claims = [
            Claim.model_validate(item) for item in result.get("claims", [])
        ]
        evidence = [
            Evidence.model_validate(item)
            for item in result.get("final_evidence", [])
        ]
        conflicts = [
            Conflict.model_validate(item)
            for item in result.get("conflicts", [])
        ]
        entities = [
            EntityRef.model_validate(item) for item in result.get("entities", [])
        ]
        gaps = list(result.get("gaps", []))
        assessment = result.get("assessment", "")
        status = result.get("status", record.status)

        if claim_id:
            target = next((item for item in claims if item.claim_id == claim_id), None)
            if target is None:
                raise KeyError("claim 不存在")
            if action_value == "reject":
                claims = [item for item in claims if item.claim_id != claim_id]
                gaps.append(f"评审驳回 {claim_id}：{comment or '未给出理由'}")
            else:
                target.verified = True
                if action_value == "accept_with_revision":
                    target.caveats.append(f"评审修订：{comment or '已修订'}")
                else:
                    target.caveats.append("评审接受")
        elif action_value == "reject":
            status = "rejected"
            assessment = f"任务被评审驳回：{comment or '未给出理由'}"
        else:
            status = "completed"

        version = record.version + 1
        report = render_research_brief(
            question=record.question,
            user_id=record.user_id,
            project_id=record.project_id,
            allowed_scopes=access.allowed_scopes,
            entities=entities,
            assessment=assessment,
            claims=claims,
            conflicts=conflicts,
            gaps=gaps,
            next_steps=result.get("next_steps", []),
            evidence=evidence,
            llm_used=bool(result.get("llm_used")),
            verify_notes=result.get("verify_notes", []),
        )
        payload = dict(result)
        payload.update(
            {
                "claims": [item.model_dump(mode="json") for item in claims],
                "gaps": gaps,
                "assessment": assessment,
                "status": status,
                "report_md": report,
                "version": version,
            }
        )
        self.store.update_result_for_review(
            task_id,
            payload,
            status=status,
            report_md=report,
            version=version,
        )
        review = self.store.add_review(
            task_id,
            reviewer_id=reviewer_id,
            action=action_value,
            claim_id=claim_id,
            comment=comment,
        )
        snapshot_state = jsonable_encoder(payload)
        snapshot_state["llm_model"] = self.settings.llm_model
        snapshot_state["rerank_model"] = (
            self.settings.rerank_model if self.settings.rerank_enabled else None
        )
        snapshot = self.store.save_snapshot(
            task_id,
            state=snapshot_state,
            version=version,
        )
        self.store.append_events(
            task_id,
            [
                Event(
                    node="review",
                    event_type="info",
                    message=f"人工评审：{action_value}",
                    payload={
                        "review_id": review["review_id"],
                        "reviewer_id": reviewer_id,
                        "claim_id": claim_id,
                        "comment": comment,
                    },
                )
            ],
        )
        self.store.log_audit(
            user_id=reviewer_id,
            project_id=record.project_id,
            action="review",
            resource=task_id,
            allowed=True,
            reason=action_value,
        )
        return {
            "review": review,
            "result_version": version,
            "status": status,
            "claims": payload["claims"],
            "snapshot": snapshot,
        }

    def get_task(self, task_id: str) -> TaskRecord | None:
        return self.store.get_task(task_id)

    def get_result(self, task_id: str) -> dict[str, Any] | None:
        return self.store.get_result(task_id)

    def reload_services(self, services: GraphServices) -> None:
        old = self.services
        self.services = services
        old.close()

    def wait(self, task_id: str, timeout: float = 180.0) -> TaskRecord | None:
        deadline = time.time() + timeout
        while time.time() < deadline:
            record = self.store.get_task(task_id)
            if record is None:
                return None
            if record.status in TERMINAL_STATUSES:
                return record
            time.sleep(0.2)
        return self.store.get_task(task_id)

    def close(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)
        self.services.close()
