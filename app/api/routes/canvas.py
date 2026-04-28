from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, status

from app.api.deps import get_settings
from app.core.config import Settings
from app.core.errors import AppError
from app.services.canvas_api import CanvasAPIClient, CanvasAPIError

router = APIRouter(prefix="/canvas", tags=["canvas"])


@router.get("/health")
def canvas_health(settings: Settings = Depends(get_settings)) -> dict[str, Any]:
    try:
        client = CanvasAPIClient(settings)
        client.get_json("/users/self/profile")
    except CanvasAPIError as exc:
        return {
            "ok": False,
            "status": exc.status,
            "detail": exc.detail or exc.message,
        }
    return {"ok": True}


@router.get("/profile")
def canvas_profile(settings: Settings = Depends(get_settings)) -> Any:
    try:
        client = CanvasAPIClient(settings)
        return client.get_json("/users/self/profile")
    except CanvasAPIError as exc:
        _raise_canvas_error(exc)


@router.get("/courses")
def canvas_courses(
    settings: Settings = Depends(get_settings),
) -> list[dict[str, Any]]:
    try:
        client = CanvasAPIClient(settings)
        courses = client.get_paginated_json(
            "/courses",
            params={
                "enrollment_state": "active",
                "per_page": settings.canvas_per_page,
            },
            max_pages=3,
        )
    except CanvasAPIError as exc:
        _raise_canvas_error(exc)

    return [
        {
            "id": course.get("id"),
            "name": course.get("name"),
            "course_code": course.get("course_code"),
            "workflow_state": course.get("workflow_state"),
        }
        for course in courses
        if isinstance(course, dict)
    ]


def _raise_canvas_error(exc: CanvasAPIError) -> None:
    raise AppError(
        code="canvas_api_error",
        message=exc.message,
        status_code=exc.status or status.HTTP_503_SERVICE_UNAVAILABLE,
        details=exc.as_debug_payload(),
    ) from exc
