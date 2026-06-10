from contextlib import asynccontextmanager
import logging
from pathlib import Path
from threading import Thread

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api.routes import router as api_router
from app.core.config import Settings
from app.core.container import AppContainer


"""
应用入口模块。
负责创建 FastAPI 实例、配置 CORS 中间件、挂载静态文件，
以及在应用启动时异步预热检索服务。
"""


logger = logging.getLogger(__name__)


def _start_background_initialize(container: AppContainer) -> None:
    """Run document loading and retriever warmup in the background."""

    def runner() -> None:
        try:
            container.warmup_status_service.start(
                selected_only=True,
                message="loading_documents",
            )
            container.document_ingestion_service.load_document()
            container.warmup_status_service.start(
                selected_only=True,
                message="selected_documents",
            )
            container.prepare_retrieval(selected_only=False)
            container.warmup_status_service.succeed("ready")
        except Exception as exc:
            container.warmup_status_service.fail(
                "initialization_failed",
                "Document loading or retriever warmup failed in background.",
            )
            logger.warning(
                "Application initialization failed in background.",
                exc_info=True,
            )

    Thread(target=runner, daemon=True).start()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理：启动时构建依赖容器，并在后台初始化文档与检索器。"""
    container = AppContainer.build()
    app.state.container = container
    _start_background_initialize(container)
    yield


def create_app() -> FastAPI:
    """创建并配置 FastAPI 应用实例（CORS、静态文件、路由）。"""
    app = FastAPI(title=Settings().app_name, lifespan=lifespan)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    static_dir = Path(__file__).parent / "static"
    app.mount("/static", StaticFiles(directory=static_dir), name="static")
    app.include_router(api_router)

    @app.get("/", include_in_schema=False)
    async def index():
        return FileResponse(
            static_dir / "index.html",
            headers={"Cache-Control": "no-store"},
        )

    @app.get("/kb", include_in_schema=False)
    async def kb_page():
        return FileResponse(
            static_dir / "kb.html",
            headers={"Cache-Control": "no-store"},
        )

    return app


app = create_app()
