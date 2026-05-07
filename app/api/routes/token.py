from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response, status
from pydantic import BaseModel, ConfigDict

from app.api.deps import get_settings
from app.core.config import Settings
from app.core.errors import AppError
from app.services.canvas_api import CanvasAPIClient, CanvasAPIError
from app.services.token_session import (
    activate_demo_canvas_token,
    configure_user_canvas_token,
    deactivate_canvas_token,
    get_canvas_token_session_status,
)

router = APIRouter(prefix="/token", tags=["token"])


class TokenConfigureRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    token: str


@router.get("/status")
def get_token_status(request: Request, settings: Settings = Depends(get_settings)) -> dict[str, bool | str]:
    return get_canvas_token_session_status(request, settings).as_payload()


@router.post("/configure")
def configure_token(
    payload: TokenConfigureRequest,
    request: Request,
    response: Response,
    settings: Settings = Depends(get_settings),
) -> dict[str, bool | str]:
    token = payload.token.strip()
    if not token:
        raise AppError(
            code="canvas_token_required",
            message="Introduce un token de Canvas válido.",
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    _validate_canvas_token(settings, token)
    configure_user_canvas_token(request, response, settings, token)
    return {"ok": True, "tokenConfigured": True, "mode": "user"}


@router.post("/activate-demo")
def activate_demo_token(
    request: Request,
    response: Response,
    settings: Settings = Depends(get_settings),
) -> dict[str, bool | str]:
    activate_demo_canvas_token(request, response, settings)
    return {"ok": True, "tokenConfigured": True, "mode": "demo"}


@router.post("/deactivate")
def deactivate_token(
    request: Request,
    response: Response,
    settings: Settings = Depends(get_settings),
) -> dict[str, bool | str]:
    deactivate_canvas_token(request, response, settings)
    return {"ok": True, "tokenConfigured": False, "mode": "none"}


def _validate_canvas_token(settings: Settings, token: str) -> None:
    try:
        client = CanvasAPIClient(settings.model_copy(update={"canvas_token": token}))
        client.get_json("/users/self/profile")
    except CanvasAPIError as exc:
        raise AppError(
            code="invalid_canvas_token",
            message="No hemos podido validar el token con Canvas/UOC.",
            status_code=status.HTTP_401_UNAUTHORIZED,
        ) from exc
