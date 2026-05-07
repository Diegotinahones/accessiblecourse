from __future__ import annotations

from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, Depends, Request, status
from sqlmodel import Session

from app.api.deps import get_engine, get_rate_limiter, get_session, get_settings
from app.core.config import Settings
from app.core.errors import AppError
from app.core.rate_limit import MemoryRateLimiter, get_client_ip
from app.schemas import JobCreatedResponse, OnlineCourseRead, OnlineJobCreateRequest
from app.services.canvas_client import CanvasClient, CanvasCredentials, OnlineJobContext
from app.services.jobs import create_online_job_record, process_online_job
from app.services.token_session import get_canvas_token_session_status, require_active_canvas_token
from app.services.url_check import URLCheckService

router = APIRouter(prefix="/online", tags=["online"])


def get_canvas_auth(
    request: Request,
    settings: Settings = Depends(get_settings),
) -> CanvasCredentials:
    token = require_active_canvas_token(request, settings)
    try:
        return CanvasCredentials.create(base_url=settings.canvas_base_url or "", token=token)
    except AppError:
        raise


def build_canvas_client(credentials: CanvasCredentials, settings: Settings) -> CanvasClient:
    return CanvasClient(credentials, timeout_seconds=settings.url_check_timeout_seconds)


def build_url_checker(settings: Settings) -> URLCheckService:
    return URLCheckService(
        timeout_seconds=settings.url_check_timeout_seconds,
        max_urls=settings.url_check_max_urls,
    )


@router.get("/courses", response_model=list[OnlineCourseRead])
def list_online_courses(
    request: Request,
    auth: CanvasCredentials = Depends(get_canvas_auth),
    settings: Settings = Depends(get_settings),
    rate_limiter: MemoryRateLimiter = Depends(get_rate_limiter),
) -> list[OnlineCourseRead]:
    rate_limiter.hit(
        bucket="online:courses",
        key=get_client_ip(request),
        limit=settings.online_rate_limit_per_minute,
    )
    client = build_canvas_client(auth, settings)
    courses = client.list_courses()

    return [
        OnlineCourseRead(
            id=course.id,
            name=course.name,
            term=course.term,
            start_at=course.start_at,
            end_at=course.end_at,
        )
        for course in courses
    ]


@router.post("/jobs", response_model=JobCreatedResponse, status_code=status.HTTP_201_CREATED)
def create_online_job(
    payload: OnlineJobCreateRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    auth: CanvasCredentials = Depends(get_canvas_auth),
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
    rate_limiter: MemoryRateLimiter = Depends(get_rate_limiter),
    engine=Depends(get_engine),
) -> JobCreatedResponse:
    rate_limiter.hit(
        bucket="online:jobs:create",
        key=get_client_ip(request),
        limit=settings.online_rate_limit_per_minute,
    )

    client = build_canvas_client(auth, settings)
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
        OnlineJobContext(
            credentials=auth,
            course_id=course.id,
            course_name=course.name,
            auth_source=get_canvas_token_session_status(request, settings).mode,
        ),
    )
    background_tasks.add_task(
        process_online_job,
        engine,
        settings,
        request.app.state.online_job_contexts,
        response.jobId,
        build_canvas_client,
        build_url_checker,
    )
    return response
