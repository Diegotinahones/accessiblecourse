from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, File, Request, UploadFile, status
from sqlalchemy import func
from sqlmodel import Session, select

from app.api.deps import get_rate_limiter, get_session, get_settings
from app.core.config import ALLOWED_ARCHIVE_EXTENSIONS, Settings
from app.core.errors import AppError
from app.core.rate_limit import MemoryRateLimiter, get_client_ip
from app.models import ChecklistResponse, ChecklistValue
from app.schemas import (
    ChecklistDecision,
    ChecklistDetailResponse,
    ChecklistItemRead,
    ChecklistSaveRequest,
    ChecklistSaveResult,
    ChecklistStateResponse,
    ChecklistUpdateRequest,
    JobCreatedResponse,
    JobStatusResponse,
    ResourceListItemRead,
    ResourceListResponse,
    ReviewFailItemRead,
    ReviewFailResourceRead,
    ReviewSessionRead,
    ReviewSummaryRead,
)
from app.services.job_store import JobStore
from app.services.review_service import (
    build_summary_payload,
    ensure_job_inventory,
    ensure_review_rollups,
    get_checklist_snapshot,
    get_resource_or_404,
    list_resources_with_fail_counts,
    upsert_checklist,
)
from app.services.worker import JobProcessor

router = APIRouter(prefix="/jobs", tags=["jobs"])


def _job_store(request: Request) -> JobStore:
    return request.app.state.job_store


def _job_processor(request: Request) -> JobProcessor:
    return request.app.state.job_processor


def _serialize_job_status(store: JobStore, job_id: str) -> JobStatusResponse:
    job = store.get_job(job_id)
    return JobStatusResponse(
        jobId=job.id,
        status=job.status,
        progress=job.progress,
        message=job.message,
        errorDetail=job.error_detail,
    )


def _serialize_review_session(review_session) -> ReviewSessionRead:
    return ReviewSessionRead(
        jobId=review_session.job_id,
        status=review_session.status,
        startedAt=review_session.started_at,
        updatedAt=review_session.updated_at,
    )


def _serialize_resource_row(resource, fail_count: int) -> ResourceListItemRead:
    return ResourceListItemRead(
        id=resource.id,
        jobId=resource.job_id,
        title=resource.title,
        type=resource.type,
        origin=resource.origin,
        url=resource.url,
        path=resource.path,
        coursePath=resource.course_path,
        status=resource.status,
        notes=resource.notes,
        reviewState=resource.review_state,
        failCount=fail_count,
        updatedAt=resource.updated_at,
    )


def _ensure_inventory_or_raise(
    session: Session,
    settings: Settings,
    store: JobStore,
    job_id: str,
) -> None:
    try:
        ensure_job_inventory(session, settings, job_id)
    except FileNotFoundError as exc:
        if store.has_job(job_id):
            job = store.get_job(job_id)
            if job.status != "done":
                raise AppError(
                    code="job_not_ready",
                    message="Los recursos todavía no están disponibles porque el job sigue en proceso.",
                    status_code=status.HTTP_409_CONFLICT,
                    job_id=job_id,
                ) from exc
        raise AppError(
            code="job_not_found",
            message="No hemos encontrado ese análisis.",
            status_code=status.HTTP_404_NOT_FOUND,
            job_id=job_id,
        ) from exc


@router.post("", response_model=JobCreatedResponse, status_code=status.HTTP_201_CREATED)
async def create_job(
    request: Request,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    settings: Settings = Depends(get_settings),
    rate_limiter: MemoryRateLimiter = Depends(get_rate_limiter),
) -> JobCreatedResponse:
    rate_limiter.hit(
        bucket="jobs:create",
        key=get_client_ip(request),
        limit=settings.jobs_rate_limit_per_minute,
    )

    filename = file.filename or "package.imscc"
    suffix = Path(filename).suffix.lower()
    if suffix not in ALLOWED_ARCHIVE_EXTENSIONS:
        raise AppError(
            code="invalid_extension",
            message="Solo se admiten archivos .imscc o .zip.",
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    store = _job_store(request)
    processor = _job_processor(request)
    job = store.create_job(filename=filename)
    upload_path = store.upload_path(job.id, suffix)

    size = 0
    with upload_path.open("wb") as target:
        while chunk := await file.read(1024 * 1024):
            size += len(chunk)
            if size > settings.max_upload_bytes:
                upload_path.unlink(missing_ok=True)
                raise AppError(
                    code="upload_too_large",
                    message="El archivo excede el tamaño máximo permitido.",
                    status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                )
            target.write(chunk)

    store.update_job(
        job.id,
        archive_path=str(upload_path),
        message="Archivo recibido. El procesamiento comenzará en breve.",
    )
    store.append_log(job.id, event="created", message="Job creado y pendiente de procesamiento.", details={"filename": filename, "sizeBytes": size})
    background_tasks.add_task(processor.process, job.id)
    return JobCreatedResponse(jobId=job.id)


@router.get("/{job_id}", response_model=JobStatusResponse)
def get_job_status(job_id: str, request: Request) -> JobStatusResponse:
    store = _job_store(request)
    try:
        return _serialize_job_status(store, job_id)
    except FileNotFoundError as exc:
        raise AppError(
            code="job_not_found",
            message="No hemos encontrado ese análisis.",
            status_code=status.HTTP_404_NOT_FOUND,
            job_id=job_id,
        ) from exc


@router.get("/{job_id}/resources")
def get_resources(
    job_id: str,
    request: Request,
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> ResourceListResponse:
    store = _job_store(request)
    _ensure_inventory_or_raise(session, settings, store, job_id)
    review_session, _ = ensure_review_rollups(session, job_id)
    resources = [
        _serialize_resource_row(resource, fail_count)
        for resource, fail_count in list_resources_with_fail_counts(session, job_id)
    ]
    if store.has_job(job_id):
        return [resource.model_dump(by_alias=True) for resource in resources]

    return ResourceListResponse(
        jobId=job_id,
        resources=resources,
        reviewSession=_serialize_review_session(review_session),
    ).model_dump(by_alias=True)


@router.get("/{job_id}/resources/{resource_id}", response_model=ChecklistDetailResponse)
def get_resource_detail(
    job_id: str,
    resource_id: str,
    request: Request,
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> ChecklistDetailResponse:
    store = _job_store(request)
    _ensure_inventory_or_raise(session, settings, store, job_id)
    resource = get_resource_or_404(session, job_id, resource_id)
    template_bundle, responses_by_key = get_checklist_snapshot(session, resource)
    fail_count = session.exec(
        select(func.count())
        .select_from(ChecklistResponse)
        .where(
            ChecklistResponse.job_id == job_id,
            ChecklistResponse.resource_id == resource_id,
            ChecklistResponse.value == ChecklistValue.FAIL,
        )
    ).one()
    review_session, _ = ensure_review_rollups(session, job_id)
    checklist_items = [
        ChecklistItemRead(
            itemKey=item.key,
            label=item.label,
            description=item.description,
            recommendation=item.recommendation,
            value=(responses_by_key.get(item.key).value if item.key in responses_by_key else ChecklistValue.PENDING),
            comment=(responses_by_key.get(item.key).comment if item.key in responses_by_key else None),
        )
        for item in template_bundle.items
    ]

    return ChecklistDetailResponse(
        resource=_serialize_resource_row(resource, int(fail_count)),
        checklist={
            "templateId": template_bundle.template.id,
            "resourceType": resource.type,
            "items": checklist_items,
        },
        reviewSession=_serialize_review_session(review_session),
    )


@router.put("/{job_id}/resources/{resource_id}/checklist", response_model=ChecklistSaveResult)
def save_resource_checklist(
    job_id: str,
    resource_id: str,
    payload: ChecklistSaveRequest,
    request: Request,
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> ChecklistSaveResult:
    store = _job_store(request)
    _ensure_inventory_or_raise(session, settings, store, job_id)
    resource = get_resource_or_404(session, job_id, resource_id)
    review_state, fail_count, updated_at = upsert_checklist(
        session,
        job_id,
        resource,
        [
            {
                "itemKey": item.item_key,
                "value": item.value,
                "comment": item.comment,
            }
            for item in payload.responses
        ],
    )
    return ChecklistSaveResult(
        resourceId=resource_id,
        reviewState=review_state,
        failCount=fail_count,
        updatedAt=updated_at,
    )


@router.get("/{job_id}/checklist", response_model=ChecklistStateResponse)
def get_checklist_state(
    job_id: str,
    request: Request,
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> ChecklistStateResponse:
    store = _job_store(request)
    _ensure_inventory_or_raise(session, settings, store, job_id)
    rows = session.exec(
        select(ChecklistResponse).where(ChecklistResponse.job_id == job_id).order_by(ChecklistResponse.resource_id, ChecklistResponse.item_key)
    ).all()
    state: dict[str, dict[str, ChecklistDecision]] = {}
    for row in rows:
        state.setdefault(row.resource_id, {})[row.item_key] = ChecklistDecision(row.value.lower())
    return ChecklistStateResponse(jobId=job_id, state=state)


@router.put("/{job_id}/checklist/{resource_id}", response_model=ChecklistStateResponse)
def update_checklist_state(
    job_id: str,
    resource_id: str,
    payload: ChecklistUpdateRequest,
    request: Request,
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> ChecklistStateResponse:
    store = _job_store(request)
    _ensure_inventory_or_raise(session, settings, store, job_id)
    resource = get_resource_or_404(session, job_id, resource_id)
    upsert_checklist(
        session,
        job_id,
        resource,
        [
            {
                "itemKey": item_key,
                "value": item.value.upper(),
                "comment": None,
            }
            for item_key, item in payload.items.items()
        ],
    )
    return get_checklist_state(job_id, request=request, session=session, settings=settings)


@router.get("/{job_id}/summary", response_model=ReviewSummaryRead)
def get_review_summary(
    job_id: str,
    request: Request,
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> ReviewSummaryRead:
    store = _job_store(request)
    _ensure_inventory_or_raise(session, settings, store, job_id)
    review_session, review_summary, resources = build_summary_payload(session, job_id)
    return ReviewSummaryRead(
        jobId=job_id,
        totalResources=review_summary.total_resources,
        totalFailItems=review_summary.total_fail_items,
        lastUpdated=review_summary.last_updated,
        reviewSession=_serialize_review_session(review_session),
        resources=[
            ReviewFailResourceRead(
                resourceId=item["resourceId"],
                title=item["title"],
                resourceType=item["resourceType"],
                reviewState=item["reviewState"],
                failCount=item["failCount"],
                recommendations=[
                    ReviewFailItemRead(
                        itemKey=recommendation["itemKey"],
                        label=recommendation["label"],
                        recommendation=recommendation["recommendation"],
                        comment=recommendation["comment"],
                    )
                    for recommendation in item["recommendations"]
                ],
            )
            for item in resources
        ],
    )


@router.get("/{job_id}/structure")
def get_job_structure(job_id: str, request: Request):
    store = _job_store(request)
    try:
        store.get_job(job_id)
    except FileNotFoundError as exc:
        raise AppError(
            code="job_not_found",
            message="No hemos encontrado ese análisis.",
            status_code=status.HTTP_404_NOT_FOUND,
            job_id=job_id,
        ) from exc

    structure = store.load_structure(job_id)
    if structure is None:
        raise AppError(
            code="structure_not_ready",
            message="La estructura del curso todavía no está disponible.",
            status_code=status.HTTP_404_NOT_FOUND,
            job_id=job_id,
        )
    return structure
