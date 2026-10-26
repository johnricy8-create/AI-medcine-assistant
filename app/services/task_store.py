"""研究任务 SQLite 持久化。

P6 只负责任务、事件、证据、claims 的落库与查询；人工评审/快照在 P7。
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, Field

from app.storage.db import db_session


class TaskRecord(BaseModel):
    task_id: str
    user_id: str
    project_id: str
    question: str
    status: str
    trace_id: str
    created_at: str = ""
    updated_at: str = ""
    event_count: int = 0
    version: int = 1
    report_md: str = ""
    result: dict[str, Any] | None = None


class StoredEvent(BaseModel):
    id: int
    task_id: str
    node: str
    event_type: str
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: str


class TaskStore:
    def __init__(
        self,
        db_path: Path,
        data_dir: Path,
        snapshot_dir: Path | None = None,
    ) -> None:
        self.db_path = db_path
        self.data_dir = data_dir
        self.snapshot_dir = snapshot_dir or (data_dir.parent / "storage" / "snapshots")

    def ensure_projects_from_acl(self, acl_dir: Path) -> None:
        path = acl_dir / "projects.yaml"
        if not path.exists():
            return
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        with db_session(self.db_path) as conn:
            for item in data.get("projects", []):
                conn.execute(
                    "INSERT OR IGNORE INTO projects(project_id, name, description) "
                    "VALUES (?, ?, ?)",
                    (
                        item.get("project_id", ""),
                        item.get("name", ""),
                        item.get("description", ""),
                    ),
                )

    def create_task(
        self,
        *,
        task_id: str,
        user_id: str,
        project_id: str,
        question: str,
        trace_id: str,
    ) -> TaskRecord:
        with db_session(self.db_path) as conn:
            conn.execute(
                "INSERT INTO research_tasks"
                "(task_id, user_id, project_id, question, status, trace_id) "
                "VALUES (?, ?, ?, ?, 'planned', ?)",
                (task_id, user_id, project_id, question, trace_id),
            )
        record = self.get_task(task_id)
        if record is None:
            raise RuntimeError(f"任务创建失败: {task_id}")
        return record

    def update_status(self, task_id: str, status: str) -> None:
        with db_session(self.db_path) as conn:
            conn.execute(
                "UPDATE research_tasks SET status = ?, updated_at = CURRENT_TIMESTAMP "
                "WHERE task_id = ?",
                (status, task_id),
            )

    def append_events(self, task_id: str, events: list[Any]) -> int:
        if not events:
            return 0
        inserted = 0
        with db_session(self.db_path) as conn:
            for event in events:
                payload = event.payload if hasattr(event, "payload") else {}
                conn.execute(
                    "INSERT INTO task_events"
                    "(task_id, node, event_type, payload_json, created_at) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (
                        task_id,
                        getattr(event, "node", "unknown"),
                        getattr(event, "event_type", "info"),
                        json.dumps(
                            jsonable_encoder(payload),
                            ensure_ascii=False,
                        ),
                        getattr(event, "timestamp", datetime.now(timezone.utc)).isoformat(),
                    ),
                )
                inserted += 1
        return inserted

    def save_result(self, task_id: str, state: dict[str, Any]) -> None:
        encoded = jsonable_encoder(state)
        current = self.get_task(task_id)
        encoded.setdefault("version", current.version if current else 1)
        encoded.setdefault("task_id", task_id)
        status = encoded.get("status", "completed")
        evidence = encoded.get("final_evidence") or encoded.get("evidence") or []
        claims = encoded.get("claims", [])
        events = encoded.get("events", [])
        plan = {
            "entities": encoded.get("entities", []),
            "subquestions": encoded.get("subquestions", []),
            "budget": encoded.get("budget", {}),
        }
        with db_session(self.db_path) as conn:
            conn.execute(
                "UPDATE research_tasks SET status = ?, result_json = ?, "
                "plan_json = ?, report_md = ?, updated_at = CURRENT_TIMESTAMP "
                "WHERE task_id = ?",
                (
                    status,
                    json.dumps(encoded, ensure_ascii=False),
                    json.dumps(plan, ensure_ascii=False),
                    encoded.get("report_md", ""),
                    task_id,
                ),
            )
            conn.execute("DELETE FROM evidence WHERE task_id = ?", (task_id,))
            for item in evidence:
                conn.execute(
                    "INSERT OR REPLACE INTO evidence"
                    "(evidence_id, task_id, source_type, source_id, title, chunk_id, "
                    " quote, locator_json, entity_ids_json, species, sample, method, "
                    " stance, level, acl_scope, scores_json, retrieved_at, tool_call_id) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        item.get("evidence_id"),
                        task_id,
                        item.get("source_type"),
                        item.get("source_id"),
                        item.get("title", ""),
                        item.get("chunk_id", ""),
                        item.get("quote", ""),
                        json.dumps(item.get("locator", {}), ensure_ascii=False),
                        json.dumps(item.get("entity_ids", []), ensure_ascii=False),
                        item.get("species"),
                        item.get("sample"),
                        item.get("method"),
                        item.get("stance", "unknown"),
                        item.get("level", "unknown"),
                        item.get("acl_scope", "public"),
                        json.dumps(item.get("scores", {}), ensure_ascii=False),
                        item.get("retrieved_at"),
                        item.get("tool_call_id"),
                    ),
                )
            conn.execute("DELETE FROM claims WHERE task_id = ?", (task_id,))
            for item in claims:
                conn.execute(
                    "INSERT OR REPLACE INTO claims"
                    "(claim_id, task_id, text, stance, level, support_ids_json, "
                    " contradict_ids_json, confidence, caveats_json, verified, "
                    " verify_detail_json) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        item.get("claim_id"),
                        task_id,
                        item.get("text", ""),
                        item.get("stance", "unknown"),
                        item.get("level", "unknown"),
                        json.dumps(item.get("support_ids", []), ensure_ascii=False),
                        json.dumps(item.get("contradict_ids", []), ensure_ascii=False),
                        item.get("confidence", 0),
                        json.dumps(item.get("caveats", []), ensure_ascii=False),
                        1 if item.get("verified") else 0,
                        json.dumps(
                            item.get("verify_notes", []),
                            ensure_ascii=False,
                        ),
                    ),
                )
    def get_task(self, task_id: str) -> TaskRecord | None:
        with db_session(self.db_path) as conn:
            row = conn.execute(
                "SELECT * FROM research_tasks WHERE task_id = ?",
                (task_id,),
            ).fetchone()
            if row is None:
                return None
            count = conn.execute(
                "SELECT COUNT(*) AS n FROM task_events WHERE task_id = ?",
                (task_id,),
            ).fetchone()["n"]
        result = None
        try:
            result = json.loads(row["result_json"] or "{}") or None
        except json.JSONDecodeError:
            result = None
        return TaskRecord(
            task_id=row["task_id"],
            user_id=row["user_id"],
            project_id=row["project_id"],
            question=row["question"],
            status=row["status"],
            trace_id=row["trace_id"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            event_count=int(count),
            version=int(row["version"]),
            report_md=row["report_md"] or "",
            result=result,
        )

    def get_result(self, task_id: str) -> dict[str, Any] | None:
        record = self.get_task(task_id)
        if record is None or not record.result:
            return None
        result = dict(record.result)
        result.setdefault("task_id", task_id)
        result.setdefault("status", record.status)
        result["report_md"] = record.report_md or result.get("report_md", "")
        result["version"] = record.version
        return result

    def list_projects(self) -> list[dict[str, str]]:
        with db_session(self.db_path) as conn:
            rows = conn.execute(
                "SELECT project_id, name, description FROM projects ORDER BY project_id"
            ).fetchall()
        return [dict(row) for row in rows]

    def get_evidence(self, evidence_id: str) -> dict[str, Any] | None:
        with db_session(self.db_path) as conn:
            row = conn.execute(
                "SELECT * FROM evidence WHERE evidence_id = ?",
                (evidence_id,),
            ).fetchone()
        if row is None:
            return None
        data = dict(row)
        for key in ("locator_json", "entity_ids_json", "scores_json"):
            try:
                data[key] = json.loads(data.get(key) or "{}")
            except json.JSONDecodeError:
                data[key] = {}
        return data

    def update_result_for_review(
        self,
        task_id: str,
        result: dict[str, Any],
        *,
        status: str,
        report_md: str,
        version: int,
    ) -> None:
        encoded = jsonable_encoder(result)
        claims = encoded.get("claims", [])
        with db_session(self.db_path) as conn:
            conn.execute(
                "UPDATE research_tasks SET result_json = ?, report_md = ?, "
                "status = ?, version = ?, updated_at = CURRENT_TIMESTAMP "
                "WHERE task_id = ?",
                (
                    json.dumps(encoded, ensure_ascii=False),
                    report_md,
                    status,
                    version,
                    task_id,
                ),
            )
            conn.execute("DELETE FROM claims WHERE task_id = ?", (task_id,))
            for item in claims:
                conn.execute(
                    "INSERT OR REPLACE INTO claims"
                    "(claim_id, task_id, text, stance, level, support_ids_json, "
                    " contradict_ids_json, confidence, caveats_json, verified, "
                    " verify_detail_json) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        item.get("claim_id"),
                        task_id,
                        item.get("text", ""),
                        item.get("stance", "unknown"),
                        item.get("level", "unknown"),
                        json.dumps(item.get("support_ids", []), ensure_ascii=False),
                        json.dumps(item.get("contradict_ids", []), ensure_ascii=False),
                        item.get("confidence", 0),
                        json.dumps(item.get("caveats", []), ensure_ascii=False),
                        1 if item.get("verified") else 0,
                        json.dumps(item.get("verify_notes", []), ensure_ascii=False),
                    ),
                )

    def add_review(
        self,
        task_id: str,
        *,
        reviewer_id: str,
        action: str,
        claim_id: str | None,
        comment: str,
    ) -> dict[str, Any]:
        review_id = f"rev-{uuid.uuid4().hex[:10]}"
        with db_session(self.db_path) as conn:
            conn.execute(
                "INSERT INTO reviews"
                "(review_id, task_id, reviewer_id, claim_id, action, comment, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    review_id,
                    task_id,
                    reviewer_id,
                    claim_id,
                    action,
                    comment,
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
        return {
            "review_id": review_id,
            "task_id": task_id,
            "reviewer_id": reviewer_id,
            "claim_id": claim_id,
            "action": action,
            "comment": comment,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }

    def list_reviews(self, task_id: str) -> list[dict[str, Any]]:
        with db_session(self.db_path) as conn:
            rows = conn.execute(
                "SELECT * FROM reviews WHERE task_id = ? ORDER BY created_at ASC",
                (task_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def save_snapshot(
        self,
        task_id: str,
        *,
        state: dict[str, Any],
        version: int,
    ) -> dict[str, Any]:
        snapshot_id = f"snap-{uuid.uuid4().hex[:10]}"
        index_manifest = {}
        manifest_path = self.data_dir / "processed" / "index_manifest.json"
        if manifest_path.exists():
            try:
                index_manifest = json.loads(
                    manifest_path.read_text(encoding="utf-8")
                )
            except json.JSONDecodeError:
                index_manifest = {}
        evidence = state.get("final_evidence") or state.get("evidence") or []
        evidence_ids = [
            item.get("evidence_id")
            for item in evidence
            if isinstance(item, dict) and item.get("evidence_id")
        ]
        manifest = {
            "task_id": task_id,
            "version": version,
            "index": index_manifest,
            "evidence_ids": evidence_ids,
            "model_versions": {
                "llm": state.get("llm_model", ""),
                "embedding": index_manifest.get("embedding_model", ""),
                "rerank": state.get("rerank_model", ""),
            },
            "prompt_version": "p5-claims-v1",
            "graph_version": "p7-v1",
            "tool_calls": state.get("tool_results", []),
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        content = json.dumps(
            {
                "manifest": manifest,
                "result": state,
            },
            ensure_ascii=False,
            default=str,
        )
        import hashlib

        content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
        self.snapshot_dir.mkdir(parents=True, exist_ok=True)
        file_path = self.snapshot_dir / f"{snapshot_id}.json"
        file_path.write_text(content, encoding="utf-8")
        with db_session(self.db_path) as conn:
            conn.execute(
                "INSERT INTO snapshots"
                "(snapshot_id, task_id, version, manifest_json, model_versions_json, "
                " prompt_version, graph_version, tool_calls_json, evidence_ids_json, "
                " content_hash, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    snapshot_id,
                    task_id,
                    version,
                    json.dumps(manifest, ensure_ascii=False, default=str),
                    json.dumps(manifest["model_versions"], ensure_ascii=False),
                    manifest["prompt_version"],
                    manifest["graph_version"],
                    json.dumps(manifest["tool_calls"], ensure_ascii=False, default=str),
                    json.dumps(evidence_ids, ensure_ascii=False),
                    content_hash,
                    manifest["created_at"],
                ),
            )
            conn.execute(
                "UPDATE research_tasks SET snapshot_id = ? WHERE task_id = ?",
                (snapshot_id, task_id),
            )
        return {
            "snapshot_id": snapshot_id,
            "task_id": task_id,
            "version": version,
            "content_hash": content_hash,
            "path": str(file_path),
            "manifest": manifest,
        }

    def get_snapshot(self, task_id: str) -> dict[str, Any] | None:
        with db_session(self.db_path) as conn:
            row = conn.execute(
                "SELECT * FROM snapshots WHERE task_id = ? "
                "ORDER BY created_at DESC LIMIT 1",
                (task_id,),
            ).fetchone()
        if row is None:
            return None
        data = dict(row)
        for key in (
            "manifest_json",
            "model_versions_json",
            "tool_calls_json",
            "evidence_ids_json",
        ):
            try:
                data[key] = json.loads(data.get(key) or "{}")
            except json.JSONDecodeError:
                data[key] = {}
        return data

    def log_audit(
        self,
        *,
        user_id: str | None,
        project_id: str | None,
        action: str,
        resource: str,
        allowed: bool,
        reason: str = "",
    ) -> None:
        with db_session(self.db_path) as conn:
            conn.execute(
                "INSERT INTO audit_log"
                "(user_id, project_id, action, resource, allowed, reason, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    user_id,
                    project_id,
                    action,
                    resource,
                    1 if allowed else 0,
                    reason,
                    datetime.now(timezone.utc).isoformat(),
                ),
            )

    def list_audit(self, limit: int = 100) -> list[dict[str, Any]]:
        with db_session(self.db_path) as conn:
            rows = conn.execute(
                "SELECT * FROM audit_log ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def list_events(self, task_id: str, after_id: int = 0) -> list[StoredEvent]:
        with db_session(self.db_path) as conn:
            rows = conn.execute(
                "SELECT * FROM task_events WHERE task_id = ? AND id > ? "
                "ORDER BY id ASC",
                (task_id, after_id),
            ).fetchall()
        events: list[StoredEvent] = []
        for row in rows:
            try:
                payload = json.loads(row["payload_json"] or "{}")
            except json.JSONDecodeError:
                payload = {}
            events.append(
                StoredEvent(
                    id=int(row["id"]),
                    task_id=row["task_id"],
                    node=row["node"],
                    event_type=row["event_type"],
                    payload=payload,
                    created_at=row["created_at"],
                )
            )
        return events
