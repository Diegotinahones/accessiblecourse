from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Request

from app.schemas import HealthResponse

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
def get_health(request: Request) -> HealthResponse:
    settings = request.app.state.settings
    return HealthResponse(status="ok", version=settings.version, time=datetime.now(tz=UTC))
