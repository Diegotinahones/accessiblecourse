from __future__ import annotations

import base64
import hashlib
import hmac
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal
from uuid import UUID, uuid4

from cryptography.fernet import Fernet, InvalidToken
from fastapi import Request, Response, status

from app.core.config import Settings
from app.core.errors import AppError

CANVAS_SESSION_COOKIE = "accessiblecourse_session"
CANVAS_DEMO_TOKEN_COOKIE = "accessiblecourse_canvas_demo_token"
CANVAS_TOKEN_REQUIRED_MESSAGE = "Configura tu token de acceso para consultar tus cursos de Canvas."
TOKEN_COOKIE_MAX_AGE_SECONDS = 60 * 60 * 8
TokenMode = Literal["user", "demo", "none"]


@dataclass(slots=True, frozen=True)
class CanvasTokenSessionStatus:
    tokenConfigured: bool
    demoTokenAvailable: bool
    mode: TokenMode

    def as_payload(self) -> dict[str, bool | str]:
        return {
            "tokenConfigured": self.tokenConfigured,
            "demoTokenAvailable": self.demoTokenAvailable,
            "mode": self.mode,
        }


def get_canvas_token_session_status(request: Request, settings: Settings) -> CanvasTokenSessionStatus:
    demo_token_available = _has_canvas_token(settings)
    session_id = _read_session_id(request, settings)
    session = _load_session(settings, session_id) if session_id else None
    mode = _resolved_mode(settings, session)
    return CanvasTokenSessionStatus(
        tokenConfigured=mode in {"user", "demo"},
        demoTokenAvailable=demo_token_available,
        mode=mode,
    )


def get_active_canvas_token(request: Request, settings: Settings) -> str | None:
    session_id = _read_session_id(request, settings)
    session = _load_session(settings, session_id) if session_id else None
    mode = _resolved_mode(settings, session)
    if mode == "demo":
        return _normalize_canvas_token(settings.canvas_token)
    if mode != "user" or not session:
        return None
    encrypted_token = _string(session, "encryptedToken")
    if not encrypted_token:
        return None
    try:
        token = _fernet(settings).decrypt(encrypted_token.encode("utf-8")).decode("utf-8")
    except (InvalidToken, ValueError):
        return None
    return _normalize_canvas_token(token)


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


def configure_user_canvas_token(request: Request, response: Response, settings: Settings, token: str) -> None:
    cleaned_token = _normalize_canvas_token(token)
    if not cleaned_token:
        raise AppError(
            code="canvas_token_required",
            message="Introduce un token de Canvas válido.",
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    session_id = _ensure_session_id(request, response, settings)
    now = _now_iso()
    existing = _load_session(settings, session_id) or {}
    created_at = _string(existing, "createdAt") or now
    encrypted_token = _fernet(settings).encrypt(cleaned_token.encode("utf-8")).decode("utf-8")
    _save_session(
        settings,
        session_id,
        {
            "sessionId": session_id,
            "mode": "user",
            "encryptedToken": encrypted_token,
            "createdAt": created_at,
            "updatedAt": now,
        },
    )


def activate_demo_canvas_token(request: Request, response: Response, settings: Settings) -> None:
    if not _has_canvas_token(settings):
        raise AppError(
            code="token_not_configured",
            message="No hay un token demo configurado en el backend.",
            status_code=status.HTTP_409_CONFLICT,
        )
    session_id = _ensure_session_id(request, response, settings)
    now = _now_iso()
    existing = _load_session(settings, session_id) or {}
    _save_session(
        settings,
        session_id,
        {
            "sessionId": session_id,
            "mode": "demo",
            "encryptedToken": None,
            "createdAt": _string(existing, "createdAt") or now,
            "updatedAt": now,
        },
    )


def deactivate_canvas_token(request: Request, response: Response, settings: Settings) -> None:
    session_id = _read_session_id(request, settings)
    if session_id:
        _delete_session(settings, session_id)
    _delete_session_cookie(response, settings)


def _resolved_mode(settings: Settings, session: dict[str, Any] | None) -> TokenMode:
    if not session:
        return "none"
    mode = _string(session, "mode")
    if mode == "demo":
        return "demo" if _has_canvas_token(settings) else "none"
    if mode == "user" and _string(session, "encryptedToken") and _can_decrypt_user_token(settings, session):
        return "user"
    return "none"


def _can_decrypt_user_token(settings: Settings, session: dict[str, Any]) -> bool:
    encrypted_token = _string(session, "encryptedToken")
    if not encrypted_token:
        return False
    try:
        token = _fernet(settings).decrypt(encrypted_token.encode("utf-8")).decode("utf-8")
    except (InvalidToken, ValueError):
        return False
    return bool(_normalize_canvas_token(token))


def _has_canvas_token(settings: Settings) -> bool:
    return bool(_normalize_canvas_token(settings.canvas_token))


def _normalize_canvas_token(value: str | None) -> str | None:
    if not value:
        return None
    token = value.strip()
    if token.lower().startswith("bearer "):
        token = token[7:].strip()
    return token or None


def _ensure_session_id(request: Request, response: Response, settings: Settings) -> str:
    session_id = _read_session_id(request, settings)
    if session_id is None:
        session_id = str(uuid4())
    _set_session_cookie(response, settings, session_id)
    return session_id


def _read_session_id(request: Request, settings: Settings) -> str | None:
    raw_cookie = request.cookies.get(CANVAS_SESSION_COOKIE)
    if not raw_cookie:
        return None
    try:
        session_id, signature = raw_cookie.split(".", 1)
        UUID(session_id)
    except ValueError:
        return None
    expected = _signature(settings, session_id)
    if not hmac.compare_digest(signature, expected):
        return None
    return session_id


def _set_session_cookie(response: Response, settings: Settings, session_id: str) -> None:
    response.set_cookie(
        CANVAS_SESSION_COOKIE,
        f"{session_id}.{_signature(settings, session_id)}",
        max_age=TOKEN_COOKIE_MAX_AGE_SECONDS,
        httponly=True,
        secure=_cookie_secure(settings),
        samesite=settings.token_cookie_samesite,
    )
    response.delete_cookie(CANVAS_DEMO_TOKEN_COOKIE)


def _delete_session_cookie(response: Response, settings: Settings) -> None:
    response.delete_cookie(
        CANVAS_SESSION_COOKIE,
        httponly=True,
        secure=_cookie_secure(settings),
        samesite=settings.token_cookie_samesite,
    )
    response.delete_cookie(CANVAS_DEMO_TOKEN_COOKIE)


def _cookie_secure(settings: Settings) -> bool:
    return bool(settings.token_cookie_secure or settings.environment == "production")


def _signature(settings: Settings, value: str) -> str:
    digest = hmac.new(_signing_secret(settings), value.encode("utf-8"), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def _signing_secret(settings: Settings) -> bytes:
    secret = settings.session_secret or settings.token_session_secret
    if not secret:
        secret = f"{settings.app_name}:{settings.environment}:canvas-session"
    return secret.encode("utf-8")


def _fernet(settings: Settings) -> Fernet:
    key = (settings.token_encryption_key or "").strip()
    if not key:
        raise AppError(
            code="token_encryption_not_configured",
            message="No hay clave de cifrado configurada para guardar tokens de usuario.",
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )
    raw_key = key.encode("utf-8")
    try:
        return Fernet(raw_key)
    except ValueError:
        derived = base64.urlsafe_b64encode(hashlib.sha256(raw_key).digest())
        return Fernet(derived)


def _sessions_dir(settings: Settings) -> Path:
    return settings.storage_root / "sessions"


def _session_path(settings: Settings, session_id: str) -> Path:
    UUID(session_id)
    return _sessions_dir(settings) / f"{session_id}.json"


def _load_session(settings: Settings, session_id: str | None) -> dict[str, Any] | None:
    if not session_id:
        return None
    try:
        path = _session_path(settings, session_id)
    except ValueError:
        return None
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _save_session(settings: Settings, session_id: str, payload: dict[str, Any]) -> None:
    directory = _sessions_dir(settings)
    directory.mkdir(parents=True, exist_ok=True)
    path = _session_path(settings, session_id)
    temporary_path = path.with_suffix(".tmp")
    temporary_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        temporary_path.chmod(0o600)
    except OSError:
        pass
    temporary_path.replace(path)


def _delete_session(settings: Settings, session_id: str) -> None:
    try:
        _session_path(settings, session_id).unlink(missing_ok=True)
    except (OSError, ValueError):
        return


def _string(payload: dict[str, Any], key: str) -> str | None:
    value = payload.get(key)
    if value is None:
        return None
    cleaned = str(value).strip()
    return cleaned or None


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()
