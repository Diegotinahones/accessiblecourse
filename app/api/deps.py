from __future__ import annotations

from fastapi import Request
from sqlmodel import Session

from app.core.config import Settings
from app.core.rate_limit import MemoryRateLimiter


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_rate_limiter(request: Request) -> MemoryRateLimiter:
    return request.app.state.rate_limiter


def get_engine(request: Request):
    return request.app.state.engine


def get_session(request: Request):
    with Session(request.app.state.engine) as session:
        yield session
