from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.api.routes import api_router
from app.core.config import Settings, get_settings
from app.core.errors import AppError, app_error_handler, unhandled_error_handler, validation_error_handler
from app.core.logging import configure_logging
from app.core.rate_limit import MemoryRateLimiter
from app.core.security import SecurityHeadersMiddleware
from app.db import build_engine, init_db
from app.services.storage import ensure_storage_layout


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved_settings = settings or get_settings()
    configure_logging(resolved_settings)
    ensure_storage_layout(resolved_settings)
    engine = build_engine(resolved_settings)
    init_db(engine)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.settings = resolved_settings
        app.state.engine = engine
        app.state.rate_limiter = MemoryRateLimiter()
        yield

    app = FastAPI(
        title=resolved_settings.app_name,
        version=__version__,
        lifespan=lifespan,
    )
    app.state.settings = resolved_settings
    app.state.engine = engine
    app.state.rate_limiter = MemoryRateLimiter()

    app.add_exception_handler(AppError, app_error_handler)
    app.add_exception_handler(RequestValidationError, validation_error_handler)
    app.add_exception_handler(Exception, unhandled_error_handler)
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=resolved_settings.cors_origins,
        allow_credentials=False,
        allow_methods=['GET', 'POST', 'PUT', 'OPTIONS'],
        allow_headers=['*'],
    )
    app.include_router(api_router, prefix=resolved_settings.api_prefix)
    return app


app = create_app()
