from __future__ import annotations

from typing import Any
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, Depends, Request, status
from fastapi.responses import StreamingResponse
from sqlmodel import Session

from app.api.deps import get_engine, get_rate_limiter, get_session, get_settings
from app.core.config import Settings
from app.core.errors import AppError
from app.core.rate_limit import MemoryRateLimiter, get_client_ip
from app.schemas import JobCreatedResponse, OnlineJobCreateRequest
from app.services.canvas_api import CanvasAPIClient, CanvasAPIError
from app.services.canvas_client import CanvasClient, CanvasCredentials, OnlineJobContext
from app.services.canvas_inventory import build_canvas_inventory
from app.services.access_analysis import OnlineAccessAdapter, analyze_access
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


@router.get("/courses/{course_id}/access-summary")
def get_canvas_course_access_summary(
    course_id: str,
    request: Request,
    settings: Settings = Depends(get_settings),
    rate_limiter: MemoryRateLimiter = Depends(get_rate_limiter),
) -> dict[str, Any]:
    rate_limiter.hit(
        bucket="canvas:courses:access-summary",
        key=get_client_ip(request),
        limit=settings.online_rate_limit_per_minute,
    )
    credentials = _canvas_credentials_from_settings(settings)
    client = _build_canvas_client(credentials, settings)
    url_checker = _build_url_checker(settings)

    course = client.get_course(course_id)
    modules = client.list_modules(course.id)
    if not modules:
        raise AppError(
            code="canvas_no_modules",
            message="El curso no tiene modulos visibles para comprobar los recursos online.",
            status_code=status.HTTP_409_CONFLICT,
        )

    inventory = build_canvas_inventory(
        client,
        course_id=course.id,
        modules=modules,
        url_checker=None,
        credentials=credentials,
        verify_access=False,
    )
    analysis = analyze_access(
        job_id=f"canvas-course-{course.id}",
        resources=inventory.resources,
        adapter=OnlineAccessAdapter(
            client=client,
            credentials=credentials,
            course_id=course.id,
            url_checker=url_checker,
            max_depth=settings.canvas_crawl_depth if settings.online_deep_scan_enabled else 0,
            max_pages=settings.online_deep_scan_max_pages,
            max_discovered=settings.canvas_max_discovered,
        ),
    )
    summary = analysis.summary

    return {
        "courseId": course.id,
        "courseName": course.name,
        "summary": {
            "total": summary["total"],
            "ok_count": summary["ok_count"],
            "no_accede_count": summary["no_accede_count"],
            "requiere_interaccion_count": summary["requiere_interaccion_count"],
            "requiere_sso_count": summary["requiere_sso_count"],
            "downloadables_total": summary["downloadables_total"],
            "downloadables_ok": summary["downloadables_ok"],
            "byStatus": summary["byStatus"],
        },
        "total": summary["total"],
        "accessible": summary["accessible"],
        "downloadable": summary["downloadable"],
        "downloadableAccessible": summary["downloadableAccessible"],
        "ok_count": summary["ok_count"],
        "no_accede_count": summary["no_accede_count"],
        "requiere_interaccion_count": summary["requiere_interaccion_count"],
        "requiere_sso_count": summary["requiere_sso_count"],
        "downloadables_total": summary["downloadables_total"],
        "downloadables_ok": summary["downloadables_ok"],
        "byStatus": summary["byStatus"],
        "deepScan": summary.get("deepScan"),
        "modules": [
            {
                "moduleId": group["modulePath"],
                "moduleName": group["modulePath"],
                "total": group["total"],
                "accessible": group["accessible"],
                "downloadable": group["downloadable"],
                "downloadableAccessible": group["downloadableAccessible"],
                "ok_count": group["ok_count"],
                "no_accede_count": group["no_accede_count"],
                "requiere_interaccion_count": group["requiere_interaccion_count"],
                "requiere_sso_count": group["requiere_sso_count"],
                "downloadables_total": group["downloadables_total"],
                "downloadables_ok": group["downloadables_ok"],
                "byStatus": group["byStatus"],
                "resources": group["resources"],
            }
            for group in summary["groups"]
        ],
    }


@router.get("/courses/{course_id}/resources/{resource_id}/download")
def download_canvas_course_resource(
    course_id: str,
    resource_id: str,
    request: Request,
    settings: Settings = Depends(get_settings),
    rate_limiter: MemoryRateLimiter = Depends(get_rate_limiter),
):
    rate_limiter.hit(
        bucket="canvas:courses:resource-download",
        key=get_client_ip(request),
        limit=settings.online_rate_limit_per_minute,
    )
    credentials = _canvas_credentials_from_settings(settings)
    client = _build_canvas_client(credentials, settings)
    modules = client.list_modules(course_id)
    if not modules:
        raise AppError(
            code="canvas_no_modules",
            message="El curso no tiene modulos visibles para localizar el recurso.",
            status_code=status.HTTP_409_CONFLICT,
        )

    inventory = build_canvas_inventory(
        client,
        course_id=course_id,
        modules=modules,
        url_checker=None,
        credentials=credentials,
        verify_access=False,
    )
    analysis = analyze_access(
        job_id=f"canvas-course-{course_id}",
        resources=inventory.resources,
        adapter=OnlineAccessAdapter(
            client=client,
            credentials=credentials,
            course_id=course_id,
            url_checker=_build_url_checker(settings),
            max_depth=settings.canvas_crawl_depth if settings.online_deep_scan_enabled else 0,
            max_pages=settings.online_deep_scan_max_pages,
            max_discovered=settings.canvas_max_discovered,
        ),
    )
    resource = next((item for item in analysis.resources if str(item.get("id")) == resource_id), None)
    if resource is None:
        raise AppError(
            code="resource_not_found",
            message="No hemos encontrado ese recurso en Canvas.",
            status_code=status.HTTP_404_NOT_FOUND,
        )

    download_url = resource.get("downloadUrl")
    if not isinstance(download_url, str) or not download_url:
        raise AppError(
            code="resource_not_downloadable",
            message="Este recurso no tiene un fichero descargable asociado en Canvas.",
            status_code=status.HTTP_409_CONFLICT,
        )

    filename = None
    details = resource.get("details")
    if isinstance(details, dict):
        raw_filename = details.get("filename") or details.get("displayName")
        if isinstance(raw_filename, str) and raw_filename.strip():
            filename = raw_filename.strip()
    if not filename:
        filename = str(resource.get("title") or "canvas-resource")

    handle = client.stream_download(download_url, filename=filename)
    response_headers: dict[str, str] = {}
    if handle.content_length is not None:
        response_headers["Content-Length"] = str(handle.content_length)
    response_headers["Content-Disposition"] = f'attachment; filename="{filename}"'

    return StreamingResponse(
        handle.iter_bytes(),
        media_type=handle.content_type or "application/octet-stream",
        headers=response_headers,
    )


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
