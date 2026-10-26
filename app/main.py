"""FastAPI 应用入口：研究任务 API、SSE 与研究工作台。"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.api.health import router as health_router
from app.api.knowledge import router as knowledge_router
from app.api.tasks import router as tasks_router
from app.config import PROJECT_ROOT, Settings, get_settings
from app.graph.services import build_services
from app.services.task_service import TaskService
from app.storage.db import init_db

logger = logging.getLogger(__name__)
TEMPLATES_DIR = PROJECT_ROOT / "app" / "templates"
STATIC_DIR = PROJECT_ROOT / "app" / "static"


def create_app(
    settings: Settings | None = None,
    task_service: TaskService | None = None,
) -> FastAPI:
    app_settings = settings or get_settings()
    owns_service = task_service is None

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app_settings.ensure_directories()
        init_db(app_settings.sqlite_path)
        if task_service is not None:
            app.state.task_service = task_service
            app.state.services = getattr(task_service, "services", None)
        else:
            try:
                services = build_services(app_settings)
                app.state.services = services
                app.state.task_service = TaskService(app_settings, services)
            except Exception as exc:  # noqa: BLE001
                logger.exception("研究服务初始化失败: %s", exc)
                app.state.services = None
                app.state.task_service = None
        yield
        if owns_service and app.state.task_service is not None:
            app.state.task_service.close()

    app = FastAPI(
        title=app_settings.app_name,
        version=app_settings.app_version,
        description="基于 LangChain + LangGraph 的医药研发知识助手",
        lifespan=lifespan,
    )
    app.state.settings = app_settings
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
    templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
    app.state.templates = templates

    app.include_router(health_router)
    app.include_router(tasks_router)
    app.include_router(knowledge_router)

    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    def index(request: Request):
        return templates.TemplateResponse(
            request=request,
            name="index.html",
            context={"app_name": app_settings.app_name},
        )

    @app.get("/api/version", include_in_schema=False)
    def version() -> dict[str, str]:
        return {
            "app": app_settings.app_name,
            "version": app_settings.app_version,
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
