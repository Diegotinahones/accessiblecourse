from __future__ import annotations

import logging
from datetime import UTC, datetime
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, Body, Depends, File, Request, UploadFile, status
from fastapi.responses import FileResponse
from sqlmodel import Session

from app.api.deps import get_engine, get_rate_limiter, get_session, get_settings
from app.core.config import Settings
from app.core.errors import AppError
from app.core.rate_limit import MemoryRateLimiter, get_client_ip
from app.models.entities import ChecklistValue, Resource, ReviewSession
from app.schemas import (
    ChecklistDetailRead,
    ChecklistItemRead,
    ChecklistSaveRequest,
    ChecklistSaveResult,
    JobCreatedResponse,
    JobReportRead,
    JobStatusResponse,
    ReportGenerateRequest,
    ResourceDetailPayload,
    ResourceListItemRead,
    ResourceListPayload,
    ReviewFailItemRead,
    ReviewFailResourceRead,
    ReviewSessionRead,
    ReviewSummaryPayload,
)
from app.services.jobs import (
    create_job_record,
    prepare_retry_job,
    process_job,
    serialize_job,
)
from app.services.jobs import (
    get_job_or_404 as get_processing_job_or_404,
)
from app.services.reports import generate_job_report, get_report_file_info, load_job_report
from app.services.review_service import (
    build_summary_payload,
    ensure_job_inventory,
    ensure_review_rollups,
    get_checklist_snapshot,
    get_resource_or_404,
    load_inventory_index,
    list_resources_with_fail_counts,
    upsert_checklist,
)
from app.services.storage import (
    get_upload_path,
    sanitize_filename,
    save_upload_file,
    validate_extension,
)

router = APIRouter(prefix="/jobs", tags=["jobs"])
logger = logging.getLogger("accessiblecourse.review")


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _review_session_read(review_session: ReviewSession) -> ReviewSessionRead:
    return ReviewSessionRead(
        jobId=review_session.job_id,
        status=review_session.status,
        startedAt=review_session.started_at,
        updatedAt=review_session.updated_at,
    )


def _resource_read(
    resource: Resource,
    fail_count: int,
    inventory_item=None,
) -> ResourceListItemRead:
    source_url = inventory_item.source_url if inventory_item is not None else resource.url
    file_path = inventory_item.file_path if inventory_item is not None else resource.path
    module_path = inventory_item.course_path if inventory_item is not None else resource.course_path
    return ResourceListItemRead(
        id=resource.id,
        jobId=resource.job_id,
        title=resource.title,
        type=resource.type,
        origin=resource.origin,
        url=source_url,
        sourceUrl=source_url,
        path=file_path,
        localPath=file_path,
        filePath=file_path,
        coursePath=module_path,
        modulePath=module_path,
        status=resource.status,
        urlStatus=inventory_item.url_status if inventory_item is not None else None,
        finalUrl=inventory_item.final_url if inventory_item is not None else source_url,
        checkedAt=inventory_item.checked_at if inventory_item is not None else None,
        notes=resource.notes,
        reviewState=resource.review_state,
        failCount=fail_count,
        updatedAt=resource.updated_at,
    )


def _is_broken_inventory_resource(resource: Resource, inventory_item) -> bool:
    url_status = inventory_item.url_status if inventory_item is not None else None
    if isinstance(url_status, str):
        normalized = url_status.strip().lower()
        if normalized == "timeout":
            return True
        if normalized.isdigit():
            return int(normalized) >= 400
        if normalized in {"4xx", "5xx"}:
            return True

    return resource.status.value == "ERROR"


def _ensure_review_inventory(session: Session, settings: Settings, job_id: str) -> None:
    try:
        ensure_job_inventory(session, settings, job_id)
    except FileNotFoundError as exc:
        raise AppError(
            code="inventory_not_found",
            message="No hemos encontrado el inventario del curso para este job.",
            status_code=status.HTTP_404_NOT_FOUND,
            details={"reason": str(exc)},
            job_id=job_id,
        ) from exc
    except ValueError as exc:
        raise AppError(
            code="invalid_inventory",
            message="El inventario del curso no tiene un formato valido.",
            status_code=status.HTTP_409_CONFLICT,
            details={"reason": str(exc)},
            job_id=job_id,
        ) from exc


def _get_review_resource(session: Session, job_id: str, resource_id: str) -> Resource:
    try:
        return get_resource_or_404(session, job_id, resource_id)
    except LookupError as exc:
        raise AppError(
            code="resource_not_found",
            message="No hemos encontrado ese recurso.",
            status_code=status.HTTP_404_NOT_FOUND,
            details={"reason": str(exc)},
            job_id=job_id,
        ) from exc


def _build_summary_response(session: Session, settings: Settings, job_id: str) -> ReviewSummaryPayload:
    _ensure_review_inventory(session, settings, job_id)
    try:
        review_session, review_summary, rows = build_summary_payload(session, job_id)
    except LookupError as exc:
        raise AppError(
            code="checklist_template_not_found",
            message="No hay plantillas de checklist disponibles para construir el informe.",
            status_code=status.HTTP_409_CONFLICT,
            details={"reason": str(exc)},
            job_id=job_id,
        ) from exc

    return ReviewSummaryPayload(
        jobId=job_id,
        totalResources=review_summary.total_resources,
        totalFailItems=review_summary.total_fail_items,
        lastUpdated=review_summary.last_updated,
        reviewSession=_review_session_read(review_session),
        resources=[
            ReviewFailResourceRead(
                resourceId=str(row["resourceId"]),
                title=str(row["title"]),
                resourceType=row["resourceType"],
                reviewState=row["reviewState"],
                failCount=int(row["failCount"]),
                recommendations=[
                    ReviewFailItemRead(
                        itemKey=str(recommendation["itemKey"]),
                        label=str(recommendation["label"]),
                        recommendation=recommendation["recommendation"],
                        comment=recommendation["comment"],
                    )
                    for recommendation in row["recommendations"]
                ],
            )
            for row in rows
        ],
    )


def _load_inventory_index_or_empty(settings: Settings, job_id: str):
    try:
        return load_inventory_index(settings, job_id)
    except (FileNotFoundError, ValueError):
        return {}


@router.post("", response_model=JobCreatedResponse, status_code=status.HTTP_201_CREATED)
async def create_job(
    request: Request,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
    rate_limiter: MemoryRateLimiter = Depends(get_rate_limiter),
) -> JobCreatedResponse:
    rate_limiter.hit(
        bucket="jobs:create",
        key=get_client_ip(request),
        limit=settings.jobs_rate_limit_per_minute,
    )
    validate_extension(file.filename or "")
    job_id = str(uuid4())
    upload_path = get_upload_path(settings, job_id, file.filename or "course.imscc")
    uploaded_size = await save_upload_file(
        upload=file,
        destination=upload_path,
        max_size_bytes=settings.max_upload_bytes,
        job_id=job_id,
    )
    # The Job is persisted only after the upload passes size and archive validation.
    response = create_job_record(
        session,
        settings,
        job_id=job_id,
        original_filename=file.filename or "course.imscc",
        stored_filename=sanitize_filename(file.filename or "course.imscc"),
        size_bytes=uploaded_size,
    )
    background_tasks.add_task(process_job, request.app.state.engine, settings, response.jobId)
    return response


@router.get("/{job_id}", response_model=JobStatusResponse)
def get_job_status(job_id: str, session: Session = Depends(get_session)) -> JobStatusResponse:
    return serialize_job(get_processing_job_or_404(session, job_id))


@router.post("/{job_id}/retry", response_model=JobStatusResponse)
def retry_existing_job(
    job_id: str,
    background_tasks: BackgroundTasks,
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
    engine=Depends(get_engine),
) -> JobStatusResponse:
    response = prepare_retry_job(session, settings, job_id)
    background_tasks.add_task(process_job, engine, settings, job_id)
    return response


@router.get("/{job_id}/resources", response_model=ResourceListPayload)
def get_resources(
    job_id: str,
    onlyBroken: bool = False,
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> ResourceListPayload:
    _ensure_review_inventory(session, settings, job_id)
    review_session, _ = ensure_review_rollups(session, job_id)
    inventory_index = _load_inventory_index_or_empty(settings, job_id)
    resources = []
    for resource, fail_count in list_resources_with_fail_counts(session, job_id):
        inventory_item = inventory_index.get(resource.id)
        if onlyBroken and not _is_broken_inventory_resource(resource, inventory_item):
            continue
        resources.append(_resource_read(resource, fail_count, inventory_item))
    logger.info("Inventario de revision cargado", extra={"job_id": job_id, "resource_count": len(resources)})
    return ResourceListPayload(
        jobId=job_id,
        resources=resources,
        reviewSession=_review_session_read(review_session),
    )


@router.get("/{job_id}/resources/{resource_id}", response_model=ResourceDetailPayload)
def get_resource_detail(
    job_id: str,
    resource_id: str,
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> ResourceDetailPayload:
    _ensure_review_inventory(session, settings, job_id)
    resource = _get_review_resource(session, job_id, resource_id)
    inventory_item = _load_inventory_index_or_empty(settings, job_id).get(resource_id)
    try:
        template_bundle, responses = get_checklist_snapshot(session, resource)
    except LookupError as exc:
        raise AppError(
            code="checklist_template_not_found",
            message="No hay una plantilla de checklist disponible para este tipo de recurso.",
            status_code=status.HTTP_409_CONFLICT,
            details={"reason": str(exc)},
            job_id=job_id,
        ) from exc

    fail_count = sum(1 for response in responses.values() if response.value == ChecklistValue.FAIL)
    review_session, _ = ensure_review_rollups(session, job_id)

    return ResourceDetailPayload(
        resource=_resource_read(resource, fail_count, inventory_item),
        checklist=ChecklistDetailRead(
            templateId=template_bundle.template.id,
            resourceType=template_bundle.template.resource_type,
            items=[
                ChecklistItemRead(
                    itemKey=item.key,
                    label=item.label,
                    description=item.description,
                    recommendation=item.recommendation,
                    value=responses[item.key].value if item.key in responses else ChecklistValue.PENDING,
                    comment=responses[item.key].comment if item.key in responses else None,
                )
                for item in template_bundle.items
            ],
        ),
        reviewSession=_review_session_read(review_session),
    )


@router.put("/{job_id}/resources/{resource_id}/checklist", response_model=ChecklistSaveResult)
def put_resource_checklist(
    job_id: str,
    resource_id: str,
    payload: ChecklistSaveRequest,
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> ChecklistSaveResult:
    _ensure_review_inventory(session, settings, job_id)
    resource = _get_review_resource(session, job_id, resource_id)
    try:
        review_state, fail_count, updated_at = upsert_checklist(
            session,
            job_id,
            resource,
            [item.model_dump(mode="python") for item in payload.responses],
        )
    except LookupError as exc:
        raise AppError(
            code="checklist_template_not_found",
            message="No hay una plantilla de checklist disponible para este tipo de recurso.",
            status_code=status.HTTP_409_CONFLICT,
            details={"reason": str(exc)},
            job_id=job_id,
        ) from exc
    except RuntimeError as exc:
        raise AppError(
            code="invalid_checklist_payload",
            message="El checklist no se ha podido guardar con los datos recibidos.",
            status_code=status.HTTP_409_CONFLICT,
            details={"reason": str(exc)},
            job_id=job_id,
        ) from exc

    logger.info(
        "Checklist persistido",
        extra={
            "job_id": job_id,
            "resource_id": resource_id,
            "review_state": review_state.value,
            "fail_count": fail_count,
        },
    )
    return ChecklistSaveResult(
        resourceId=resource_id,
        reviewState=review_state,
        failCount=fail_count,
        updatedAt=updated_at,
    )


@router.get("/{job_id}/summary", response_model=ReviewSummaryPayload)
def get_review_summary(
    job_id: str,
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> ReviewSummaryPayload:
    return _build_summary_response(session, settings, job_id)


@router.post("/{job_id}/report", response_model=JobReportRead)
def create_job_report(
    job_id: str,
    request: Request,
    payload: ReportGenerateRequest | None = Body(default=None),
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
    rate_limiter: MemoryRateLimiter = Depends(get_rate_limiter),
) -> dict:
    rate_limiter.hit(
        bucket="reports:create",
        key=get_client_ip(request),
        limit=settings.reports_rate_limit_per_minute,
    )
    report_payload = generate_job_report(
        session,
        settings,
        job_id,
        include_pending=payload.includePending if payload else True,
        only_fails=payload.onlyFails if payload else False,
    )
    logger.info(
        "Informe generado",
        extra={
            "job_id": job_id,
            "failed_item_count": report_payload["stats"]["fails"],
            "pending_count": report_payload["stats"]["pending"],
            "resource_count": report_payload["stats"]["resources"],
        },
    )
    return report_payload


@router.get("/{job_id}/report", response_model=JobReportRead)
def get_job_report(job_id: str, session: Session = Depends(get_session)) -> dict:
    return load_job_report(session, job_id)


@router.get("/{job_id}/report/download")
def download_job_report(
    job_id: str,
    format: str,
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> FileResponse:
    file_path, media_type, filename = get_report_file_info(session, settings, job_id, format)
    return FileResponse(
        path=file_path,
        media_type=media_type,
        filename=filename,
        headers={
            "Cache-Control": "no-store, max-age=0",
            "Pragma": "no-cache",
            "Expires": "0",
        },
    )
