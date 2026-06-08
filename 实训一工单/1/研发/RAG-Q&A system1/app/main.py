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


def _start_background_prepare(container: AppContainer, *, selected_only: bool) -> None:
    """在后台守护线程中预热检索器，避免阻塞主进程。"""
    def runner() -> None:
        try:
            container.prepare_retrieval(selected_only=selected_only)
        except Exception:
            logger.warning("Retriever warmup failed in background.", exc_info=True)

    Thread(target=runner, daemon=True).start()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理：启动时构建依赖容器、加载文档并异步预热检索。"""
    container = AppContainer.build()
    app.state.container = container
    container.document_ingestion_service.load_document()
    _start_background_prepare(container, selected_only=True)
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
        return FileResponse(static_dir / "index.html")

    @app.get("/kb", include_in_schema=False)
    async def kb_page():
        return FileResponse(static_dir / "kb.html")

    return app


app = create_app()
