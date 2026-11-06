from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from nawa.core.config import get_settings
from nawa.core.db import get_sessionmaker
from nawa.core.errors import install_error_handlers
from nawa.core.health import router as health_router
from nawa.core.logging import RequestIdMiddleware, configure_logging
from nawa.workspace.router import router as workspace_router
from nawa.workspace.setup_service import ensure_setup_token


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    await ensure_setup_token(get_sessionmaker(get_settings()))
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)
    app = FastAPI(title="NAWA.AI API", version="0.1.0", lifespan=lifespan)
    app.add_middleware(RequestIdMiddleware)
    install_error_handlers(app)
    app.include_router(health_router)
    app.include_router(workspace_router)
    return app
