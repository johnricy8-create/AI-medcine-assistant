"""健康检查接口。

不在这里调用外部模型：健康检查应快速、稳定、无成本。
真实 Key 连通性由 scripts/check_services.py 手动验证。
"""

from __future__ import annotations

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


@router.get("/health", response_model=HealthResponse, summary="应用健康检查")
def health(request: Request) -> HealthResponse:
    settings: Settings = request.app.state.settings
    database_ok = check_db(settings.sqlite_path)
    return HealthResponse(
        app=settings.app_name,
        version=settings.app_version,
        status="ok" if database_ok else "degraded",
        database="ok" if database_ok else "error",
        llm_configured=settings.llm_configured(),
        embedding_configured=settings.embedding_configured(),
        index_available=_index_available(settings),
    )
