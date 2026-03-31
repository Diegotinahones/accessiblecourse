from __future__ import annotations

from datetime import UTC, datetime

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router
from app.core.config import Settings, ensure_runtime_directories
from app.core.db import create_sqlalchemy_engine, init_database
from app.core.errors import AppError, app_error_handler, unhandled_error_handler, validation_error_handler
from app.core.rate_limit import MemoryRateLimiter
from app.schemas import HealthResponse
from app.services.job_store import JobStore
from app.services.worker import JobProcessor


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved_settings = ensure_runtime_directories(settings)
    engine = create_sqlalchemy_engine(resolved_settings)
    init_database(engine)
    job_store = JobStore(
        jobs_dir=resolved_settings.data_dir / "jobs",
        uploads_dir=resolved_settings.data_dir / "uploads",
    )
    application = FastAPI(
        title="AccessibleCourse Backend",
        version=resolved_settings.version,
        description="FastAPI backend for AccessibleCourse reports and checklist persistence.",
    )
    application.state.settings = resolved_settings
    application.state.engine = engine
    application.state.rate_limiter = MemoryRateLimiter()
    application.state.job_store = job_store
    application.state.job_processor = JobProcessor(job_store)
    application.add_middleware(
        CORSMiddleware,
        allow_origins=resolved_settings.cors_origins or ["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    application.add_exception_handler(AppError, app_error_handler)
    application.add_exception_handler(RequestValidationError, validation_error_handler)
    application.add_exception_handler(Exception, unhandled_error_handler)

    @application.get("/health", response_model=HealthResponse)
    def healthcheck() -> HealthResponse:
        return HealthResponse(status="ok", version=resolved_settings.version, time=datetime.now(tz=UTC))

    application.include_router(api_router)
    return application


app = create_app()
