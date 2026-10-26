"""FastAPI 应用入口。

P0 只做：
- 配置加载
- 目录初始化
- SQLite 初始化
- 健康检查
不自动建索引、不自动调用模型。
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.health import router as health_router
from app.config import Settings, get_settings
from app.storage.db import init_db


def create_app(settings: Settings | None = None) -> FastAPI:
    app_settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        app_settings.ensure_directories()
        init_db(app_settings.sqlite_path)
        yield

    app = FastAPI(
        title=app_settings.app_name,
        version=app_settings.app_version,
        description="基于 LangChain + LangGraph 的医药研发知识助手",
        lifespan=lifespan,
    )
    app.state.settings = app_settings
    app.include_router(health_router)

    @app.get("/", include_in_schema=False)
    def root() -> dict[str, str]:
        return {
            "app": app_settings.app_name,
            "version": app_settings.app_version,
            "health": "/api/health",
            "docs": "/docs",
        }

    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn

    settings = get_settings()
    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
    )
