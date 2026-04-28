from __future__ import annotations

from typing import Any
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, Depends, Request, status
from sqlmodel import Session

from app.api.deps import get_engine, get_rate_limiter, get_session, get_settings
from app.core.config import Settings
from app.core.errors import AppError
from app.core.rate_limit import MemoryRateLimiter, get_client_ip
from app.schemas import JobCreatedResponse, OnlineJobCreateRequest
from app.services.canvas_api import CanvasAPIClient, CanvasAPIError
from app.services.canvas_client import CanvasClient, CanvasCredentials, OnlineJobContext
from app.services.jobs import create_online_job_record, process_online_job
from app.services.url_check import URLCheckService

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


@router.post("/jobs", response_model=JobCreatedResponse, status_code=status.HTTP_201_CREATED)
def create_canvas_job(
    payload: OnlineJobCreateRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
    rate_limiter: MemoryRateLimiter = Depends(get_rate_limiter),
    engine=Depends(get_engine),
) -> JobCreatedResponse:
    rate_limiter.hit(
        bucket="canvas:jobs:create",
        key=get_client_ip(request),
        limit=settings.online_rate_limit_per_minute,
    )
    credentials = _canvas_credentials_from_settings(settings)
    client = _build_canvas_client(credentials, settings)
    course = client.get_course(payload.courseId)

    job_id = str(uuid4())
    response = create_online_job_record(
        session,
        settings,
        job_id=job_id,
        course_id=course.id,
        course_name=course.name,
    )
    request.app.state.online_job_contexts.put(
        response.jobId,
        OnlineJobContext(credentials=credentials, course_id=course.id, course_name=course.name),
    )
    background_tasks.add_task(
        process_online_job,
        engine,
        settings,
        request.app.state.online_job_contexts,
        response.jobId,
        _build_canvas_client,
        _build_url_checker,
    )
    return response


def _raise_canvas_error(exc: CanvasAPIError) -> None:
    raise AppError(
        code="canvas_api_error",
        message=exc.message,
        status_code=exc.status or status.HTTP_503_SERVICE_UNAVAILABLE,
        details=exc.as_debug_payload(),
    ) from exc


def _canvas_credentials_from_settings(settings: Settings) -> CanvasCredentials:
    try:
        return CanvasCredentials.create(
            base_url=settings.canvas_base_url or "",
            token=settings.canvas_token or "",
        )
    except AppError as exc:
        raise AppError(
            code=exc.code,
            message=exc.message,
            status_code=exc.status_code,
            details=exc.details,
        ) from exc


def _build_canvas_client(credentials: CanvasCredentials, settings: Settings) -> CanvasClient:
    return CanvasClient(credentials, timeout_seconds=settings.canvas_timeout_seconds)


def _build_url_checker(settings: Settings) -> URLCheckService:
    return URLCheckService(
        timeout_seconds=settings.url_check_timeout_seconds,
        max_urls=settings.url_check_max_urls,
    )
