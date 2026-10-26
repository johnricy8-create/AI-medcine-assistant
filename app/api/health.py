"""健康检查接口。

不在这里调用外部模型：健康检查应快速、稳定、无成本。
真实 Key 连通性由 scripts/check_services.py 手动验证。
"""

from __future__ import annotations

import json

from fastapi import APIRouter, Request

from app.config import Settings
from app.schemas import HealthResponse
from app.storage.db import check_db

router = APIRouter(prefix="/api", tags=["health"])


def _index_available(settings: Settings) -> bool:
    try:
        if not settings.chroma_dir.exists():
            return False
        return any(child.name != ".gitkeep" for child in settings.chroma_dir.iterdir())
    except OSError:
        return False


def _index_manifest(settings: Settings) -> dict:
    path = settings.data_dir / "processed" / "index_manifest.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


@router.get("/health", response_model=HealthResponse, summary="应用健康检查")
def health(request: Request) -> HealthResponse:
    settings: Settings = request.app.state.settings
    database_ok = check_db(settings.sqlite_path)
    manifest = _index_manifest(settings)
    services_ready = getattr(request.app.state, "task_service", None) is not None
    return HealthResponse(
        app=settings.app_name,
        version=settings.app_version,
        status="ok" if database_ok else "degraded",
        database="ok" if database_ok else "error",
        llm_configured=settings.llm_configured(),
        embedding_configured=settings.embedding_configured(),
        index_available=_index_available(settings) or bool(manifest),
        services_ready=services_ready,
        llm_model=settings.llm_model,
        embedding_model=settings.embedding_model,
        rerank_enabled=settings.rerank_enabled,
        index_chunk_count=int(manifest.get("chunk_count", 0)),
    )
