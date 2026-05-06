from __future__ import annotations

import base64
import hashlib
import hmac
from dataclasses import dataclass
from typing import Literal

from fastapi import Request, Response, status

from app.core.config import Settings
from app.core.errors import AppError

CANVAS_DEMO_TOKEN_COOKIE = "accessiblecourse_canvas_demo_token"
CANVAS_TOKEN_REQUIRED_MESSAGE = "Configura tu token de acceso para consultar tus cursos de Canvas."
TOKEN_COOKIE_MAX_AGE_SECONDS = 60 * 60 * 8
TokenMode = Literal["demo", "none"]


@dataclass(slots=True, frozen=True)
class CanvasTokenSessionStatus:
    demoTokenAvailable: bool
    tokenActive: bool
    mode: TokenMode

    def as_payload(self) -> dict[str, bool | str]:
        return {
            "demoTokenAvailable": self.demoTokenAvailable,
            "tokenActive": self.tokenActive,
            "mode": self.mode,
        }


def get_canvas_token_session_status(request: Request, settings: Settings) -> CanvasTokenSessionStatus:
    demo_token_available = _has_canvas_token(settings)
    cookie_state = _read_cookie_state(request, settings)
    token_active = bool(cookie_state is True and demo_token_available)
    return CanvasTokenSessionStatus(
        demoTokenAvailable=demo_token_available,
        tokenActive=token_active,
        mode="demo" if token_active else "none",
    )


def get_active_canvas_token(request: Request, settings: Settings) -> str | None:
    status_payload = get_canvas_token_session_status(request, settings)
    if not status_payload.tokenActive:
        return None
    return _normalize_canvas_token(settings.canvas_token)


def require_active_canvas_token(request: Request, settings: Settings) -> str:
    token = get_active_canvas_token(request, settings)
    if token:
        return token
    raise AppError(
        code="canvas_token_required",
        message=CANVAS_TOKEN_REQUIRED_MESSAGE,
        status_code=status.HTTP_428_PRECONDITION_REQUIRED,
        details=get_canvas_token_session_status(request, settings).as_payload(),
    )


def activate_demo_canvas_token(response: Response, settings: Settings) -> None:
    if not _has_canvas_token(settings):
        raise AppError(
            code="token_not_configured",
            message="No hay un token demo configurado en el backend.",
            status_code=status.HTTP_409_CONFLICT,
        )
    _set_cookie_state(response, settings, active=True)


def deactivate_demo_canvas_token(response: Response, settings: Settings) -> None:
    _set_cookie_state(response, settings, active=False)


def _has_canvas_token(settings: Settings) -> bool:
    return bool(_normalize_canvas_token(settings.canvas_token))


def _normalize_canvas_token(value: str | None) -> str | None:
    if not value:
        return None
    token = value.strip()
    if token.lower().startswith("bearer "):
        token = token[7:].strip()
    return token or None


def _read_cookie_state(request: Request, settings: Settings) -> bool | None:
    raw_cookie = request.cookies.get(CANVAS_DEMO_TOKEN_COOKIE)
    if not raw_cookie:
        return None
    try:
        state, signature = raw_cookie.split(".", 1)
    except ValueError:
        return None
    if state not in {"active", "inactive"}:
        return None
    expected = _signature(settings, state)
    if not hmac.compare_digest(signature, expected):
        return None
    return state == "active"


def _set_cookie_state(response: Response, settings: Settings, *, active: bool) -> None:
    state = "active" if active else "inactive"
    response.set_cookie(
        CANVAS_DEMO_TOKEN_COOKIE,
        f"{state}.{_signature(settings, state)}",
        max_age=TOKEN_COOKIE_MAX_AGE_SECONDS,
        httponly=True,
        secure=settings.token_cookie_secure,
        samesite=settings.token_cookie_samesite,
    )


def _signature(settings: Settings, state: str) -> str:
    digest = hmac.new(_signing_secret(settings), state.encode("utf-8"), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def _signing_secret(settings: Settings) -> bytes:
    secret = settings.token_session_secret
    if not secret:
        secret = f"{settings.app_name}:{settings.environment}:canvas-demo-token-session"
    return secret.encode("utf-8")
