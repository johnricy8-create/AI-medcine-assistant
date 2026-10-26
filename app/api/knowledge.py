"""知识库统计与重建 API。"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request

from app.config import Settings
from app.graph.services import build_services
from app.retrieval.index_builder import build_index
from app.schemas import KnowledgeStats
from app.services.task_service import TaskService

router = APIRouter(prefix="/api/knowledge", tags=["knowledge"])


def _manifest_path(settings: Settings) -> Path:
    return settings.data_dir / "processed" / "index_manifest.json"


def _stats(settings: Settings) -> KnowledgeStats:
    manifest: dict = {}
    path = _manifest_path(settings)
    if path.exists():
        try:
            manifest = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            manifest = {}
    last = None
    value = manifest.get("built_at")
    if value:
        try:
            last = datetime.fromisoformat(value)
        except ValueError:
            last = None
    return KnowledgeStats(
        document_count=int(manifest.get("document_count", 0)),
        chunk_count=int(manifest.get("chunk_count", 0)),
        last_rebuilt_at=last,
        embedding_model=str(manifest.get("embedding_model", settings.embedding_model)),
        embedding_dim=int(manifest.get("embedding_dim", settings.embedding_dim)),
        collection=str(manifest.get("collection", settings.chroma_collection)),
    )


@router.get("/stats", response_model=KnowledgeStats)
def stats(request: Request) -> KnowledgeStats:
    return _stats(request.app.state.settings)


@router.post("/rebuild")
async def rebuild(request: Request) -> dict:
    settings: Settings = request.app.state.settings
    if not settings.embedding_configured():
        raise HTTPException(status_code=503, detail="未配置 EMBEDDING_API_KEY")
    service: TaskService | None = getattr(request.app.state, "task_service", None)
    user_id = request.headers.get(settings.demo_user_header) or settings.default_demo_user
    if service is not None:
        service.services.close()
    try:
        result = await asyncio.to_thread(build_index, settings)
        if service is not None:
            new_services = await asyncio.to_thread(build_services, settings)
            service.reload_services(new_services)
            service.store.log_audit(
                user_id=user_id,
                project_id=None,
                action="rebuild_index",
                resource=result.collection,
                allowed=True,
                reason=f"documents={result.document_count}, chunks={result.chunk_count}",
            )
    except Exception as exc:  # noqa: BLE001
        if service is not None:
            service.store.log_audit(
                user_id=user_id,
                project_id=None,
                action="rebuild_index",
                resource="knowledge",
                allowed=False,
                reason=str(exc)[:300],
            )
            try:
                service.reload_services(await asyncio.to_thread(build_services, settings))
            except Exception:
                pass
        raise HTTPException(status_code=500, detail=f"重建失败: {exc}") from exc
    return result.model_dump(mode="json")
