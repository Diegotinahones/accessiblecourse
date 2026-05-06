from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response

from app.api.deps import get_settings
from app.core.config import Settings
from app.services.token_session import (
    activate_demo_canvas_token,
    deactivate_demo_canvas_token,
    get_canvas_token_session_status,
)

router = APIRouter(prefix="/token", tags=["token"])


@router.get("/status")
def get_token_status(request: Request, settings: Settings = Depends(get_settings)) -> dict[str, bool | str]:
    return get_canvas_token_session_status(request, settings).as_payload()


@router.post("/activate-demo")
def activate_demo_token(response: Response, settings: Settings = Depends(get_settings)) -> dict[str, bool]:
    activate_demo_canvas_token(response, settings)
    return {"ok": True, "tokenActive": True}


@router.post("/deactivate")
def deactivate_token(response: Response, settings: Settings = Depends(get_settings)) -> dict[str, bool]:
    deactivate_demo_canvas_token(response, settings)
    return {"ok": True, "tokenActive": False}
