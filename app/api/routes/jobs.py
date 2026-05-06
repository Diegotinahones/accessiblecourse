from __future__ import annotations

import logging
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, Body, Depends, File, Request, UploadFile, status
from fastapi.responses import FileResponse, HTMLResponse, Response
from sqlmodel import Session, select

from app.api.deps import get_engine, get_rate_limiter, get_session, get_settings
from app.core.config import Settings
from app.core.errors import AppError
from app.core.rate_limit import MemoryRateLimiter, get_client_ip
from app.models.entities import ChecklistValue, Resource, ReviewSession
from app.schemas import (
    AccessibilityReportRead,
    AccessSummaryRead,
    ChecklistDetailRead,
    ChecklistItemRead,
    ChecklistSaveRequest,
    ChecklistSaveResult,
    AccessModuleRead,
    ExecutiveSummaryRead,
    JobCreatedResponse,
    JobAccessRead,
    JobPhase,
    JobReportRead,
    JobStatusResponse,
    ReportGenerateRequest,
    ResourceContentCheckRead,
    ResourceDetailPayload,
    ResourceListItemRead,
    ResourceListPayload,
    ReviewFailItemRead,
    ReviewFailResourceRead,
    ReviewSessionRead,
    ReviewSummaryPayload,
)
from app.services.access_analysis import build_access_summary
from app.services.canvas_client import CanvasClient, CanvasCredentials
from app.services.course_structure import (
    augment_course_structure,
    build_fallback_course_structure,
    filter_course_structure,
    load_course_structure,
)
from app.services.docx_accessibility import ensure_docx_accessibility_report
from app.services.executive_summary import build_executive_summary
from app.services.html_accessibility import ensure_accessibility_report
from app.services.jobs import (
    create_job_record,
    load_inventory_breakdown,
    prepare_access_analysis_retry,
    prepare_retry_job,
    process_job,
    rerun_access_analysis,
    serialize_job,
)
from app.services.pdf_accessibility import ensure_pdf_accessibility_report
from app.services.jobs import (
    get_job_or_404 as get_processing_job_or_404,
)
from app.services.reports import generate_job_report, get_report_file_info, load_job_report
from app.services.resource_core import ResourceContentResult, get_resource_content, normalize_resource
from app.services.token_session import get_active_canvas_token, require_active_canvas_token
from app.services.video_accessibility import ensure_video_accessibility_report
from app.services.review_service import (
    build_summary_payload,
    ensure_job_inventory,
    ensure_review_rollups,
    get_checklist_snapshot,
    load_inventory_file,
    get_resource_or_404,
    list_resources_with_fail_counts,
    upsert_checklist,
)
from app.services.storage import (
    get_extracted_dir,
    get_upload_path,
    resolve_job_resource_path,
    sanitize_filename,
    save_upload_file,
    validate_extension,
)
from app.services.url_check import URLCheckService

router = APIRouter(prefix="/jobs", tags=["jobs"])
logger = logging.getLogger("accessiblecourse.review")


def _canvas_client_factory(credentials: CanvasCredentials, settings: Settings) -> CanvasClient:
    return CanvasClient(credentials, timeout_seconds=settings.canvas_timeout_seconds)


def _url_check_factory(settings: Settings) -> URLCheckService:
    return URLCheckService(timeout_seconds=settings.url_check_timeout_seconds, max_urls=settings.url_check_max_urls)


def _no_store_headers() -> dict[str, str]:
    return {
        "Cache-Control": "no-store, max-age=0",
        "Pragma": "no-cache",
        "Expires": "0",
    }


def _load_resource_content(
    *,
    request: Request,
    settings: Settings,
    job_id: str,
    resource_id: str,
) -> ResourceContentResult:
    content_settings = _settings_for_request_canvas_token(request, settings)
    canvas_client, canvas_credentials, course_id = _load_online_context(
        request=request,
        settings=settings,
        job_id=job_id,
    )
    return get_resource_content(
        job_id,
        resource_id,
        settings=content_settings,
        canvas_client=canvas_client,
        canvas_credentials=canvas_credentials,
        course_id=course_id,
    )


def _load_online_context(
    *,
    request: Request,
    settings: Settings,
    job_id: str,
) -> tuple[CanvasClient | None, CanvasCredentials | None, str | None]:
    context_store = getattr(request.app.state, "online_job_contexts", None)
    context = context_store.get(job_id) if context_store is not None else None
    active_token = get_active_canvas_token(request, settings)
    if context is None and active_token is None:
        return None, None, None
    if context is not None and getattr(context, "auth_source", "header") == "demo" and active_token is None:
        return None, None, None
    canvas_client = _canvas_client_factory(context.credentials, settings) if context is not None else None
    canvas_credentials = context.credentials if context is not None else None
    course_id = context.course_id if context is not None else None
    return canvas_client, canvas_credentials, course_id


def _settings_for_request_canvas_token(request: Request, settings: Settings) -> Settings:
    if get_active_canvas_token(request, settings) is not None:
        return settings
    return settings.model_copy(update={"canvas_token": None})


def _accessibility_resource_payload(resource, analysis_type: str) -> dict:
    payload = resource.model_dump(mode="python")
    payload["analysisType"] = analysis_type
    return payload


def _resource_analysis_type(resource) -> str:
    analysis_type = getattr(resource, "analysisType", None)
    if analysis_type in {"HTML", "PDF", "DOCX", "VIDEO"}:
        return analysis_type
    if getattr(resource, "type", None) == "VIDEO":
        return "VIDEO"
    if getattr(resource, "type", None) == "DOCX":
        return "DOCX"
    return "PDF" if getattr(resource, "type", None) == "PDF" else "HTML"


def _accessibility_modules_payload(report, analysis_type: str) -> list[dict]:
    modules = []
    for module in report.modules:
        resources = [
            resource
            for resource in module.resources
            if _resource_analysis_type(resource) == analysis_type
        ]
        if not resources:
            continue
        payload = module.model_dump(mode="python")
        payload["resources"] = [
            _accessibility_resource_payload(resource, analysis_type)
            for resource in resources
        ]
        modules.append(payload)
    return modules


def _accessibility_type_summary(summary, *, prefix: str) -> dict[str, int]:
    analysis_type = prefix.upper()
    type_summary = summary.byType.get(analysis_type)
    total_key = f"{prefix}ResourcesTotal"
    analyzed_key = f"{prefix}ResourcesAnalyzed"
    return {
        "resourcesTotal": int(getattr(summary, total_key)),
        "resourcesAnalyzed": int(getattr(summary, analyzed_key)),
        "passCount": type_summary.passCount if type_summary else summary.passCount,
        "failCount": type_summary.failCount if type_summary else summary.failCount,
        "warningCount": type_summary.warningCount if type_summary else summary.warningCount,
        "notApplicableCount": type_summary.notApplicableCount if type_summary else summary.notApplicableCount,
        "errorCount": type_summary.errorCount if type_summary else summary.errorCount,
    }


def _accessibility_report_read(report) -> AccessibilityReportRead:
    payload = report.model_dump(mode="python")
    payload["resources"] = [
        resource.model_dump(mode="python")
        for module in report.modules
        for resource in module.resources
    ]
    return AccessibilityReportRead.model_validate(payload)


def _raise_content_error(content: ResourceContentResult, *, job_id: str) -> None:
    error_code = content.error_code or "UNKNOWN"
    status_code = status.HTTP_404_NOT_FOUND if error_code == "NOT_FOUND" else status.HTTP_409_CONFLICT
    code = {
        "REQUIERE_SSO": "resource_requires_sso",
        "NO_ANALIZABLE": "resource_not_analyzable",
        "AUTH_REQUIRED": "resource_auth_required",
        "NOT_FOUND": "resource_content_not_found",
    }.get(error_code, "resource_content_unavailable")
    message = content.error_detail or "No hay contenido reutilizable para este recurso."
    raise AppError(
        code=code,
        message=message,
        status_code=status_code,
        details={"resourceId": content.resource_id, "reason": error_code},
        job_id=job_id,
    )


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
    module_title = inventory_item.module_title if inventory_item is not None else None
    section_title = inventory_item.section_title if inventory_item is not None else None
    section_key = inventory_item.section_key if inventory_item is not None else None
    section_type = inventory_item.section_type if inventory_item is not None else None
    item_path = inventory_item.item_path if inventory_item is not None else None
    parent_resource_id = inventory_item.parent_resource_id if inventory_item is not None else resource.parent_resource_id
    can_download = inventory_item.can_download if inventory_item is not None else resource.can_download
    download_url = f"/api/jobs/{resource.job_id}/resources/{resource.id}/download" if can_download else None
    core = normalize_resource(resource, inventory_item)
    content_available = core.contentAvailable
    return ResourceListItemRead(
        id=resource.id,
        jobId=resource.job_id,
        title=resource.title,
        type=resource.type,
        origin=core.origin,
        analysisCategory=inventory_item.analysis_category if inventory_item is not None else "MAIN_ANALYZABLE",
        url=source_url,
        sourceUrl=source_url,
        downloadUrl=download_url,
        path=file_path,
        htmlPath=file_path if core.origin == "INTERNAL_PAGE" else None,
        localPath=file_path if core.origin != "EXTERNAL_URL" else None,
        filePath=file_path,
        coursePath=module_path,
        modulePath=module_path,
        moduleTitle=module_title,
        sectionTitle=section_title,
        sectionKey=section_key,
        sectionType=section_type,
        itemPath=item_path,
        status=resource.status,
        urlStatus=inventory_item.url_status if inventory_item is not None else None,
        finalUrl=core.finalUrl,
        checkedAt=inventory_item.checked_at if inventory_item is not None else None,
        canAccess=inventory_item.can_access if inventory_item is not None else resource.can_access,
        accessStatus=inventory_item.access_status if inventory_item is not None else resource.access_status,
        httpStatus=inventory_item.http_status if inventory_item is not None else resource.http_status,
        accessStatusCode=(
            inventory_item.access_status_code if inventory_item is not None else resource.access_status_code
        ),
        canDownload=can_download,
        downloadStatus=inventory_item.download_status if inventory_item is not None else resource.download_status,
        downloadStatusCode=(
            inventory_item.download_status_code if inventory_item is not None else resource.download_status_code
        ),
        contentAvailable=content_available,
        discoveredChildrenCount=(
            inventory_item.discovered_children_count
            if inventory_item is not None
            else resource.discovered_children_count
        ),
        parentResourceId=core.parentId or parent_resource_id,
        parentId=core.parentId or parent_resource_id,
        discovered=inventory_item.discovered if inventory_item is not None else resource.discovered,
        accessNote=inventory_item.access_note if inventory_item is not None else resource.access_note,
        errorMessage=inventory_item.error_message if inventory_item is not None else resource.error_message,
        reasonCode=core.reasonCode,
        reasonDetail=core.reasonDetail,
        notes=resource.notes,
        reviewState=resource.review_state,
        failCount=fail_count,
        updatedAt=resource.updated_at,
        core=core,
    )


def _is_broken_inventory_resource(resource: Resource, inventory_item) -> bool:
    access_status = inventory_item.access_status if inventory_item is not None else resource.access_status
    normalized_access_status = access_status.value if hasattr(access_status, "value") else str(access_status or "")
    if normalized_access_status.upper() in {"NO_ACCEDE", "NOT_FOUND", "FORBIDDEN", "TIMEOUT", "ERROR"}:
        return True

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


def _build_access_summary(session: Session, settings: Settings, job_id: str) -> AccessSummaryRead:
    resources = session.exec(select(Resource).where(Resource.job_id == job_id)).all()
    job = get_processing_job_or_404(session, job_id)
    breakdown = load_inventory_breakdown(settings, job_id)
    resource_payload = [
        {
            "id": resource.id,
            "title": resource.title,
            "type": resource.type.value if hasattr(resource.type, "value") else str(resource.type),
            "modulePath": resource.course_path,
            "coursePath": resource.course_path,
            "canAccess": resource.can_access,
            "accessStatus": resource.access_status.value
            if hasattr(resource.access_status, "value")
            else str(resource.access_status),
            "canDownload": resource.can_download,
            "downloadStatus": resource.download_status,
            "accessStatusCode": resource.access_status_code,
            "downloadStatusCode": resource.download_status_code,
            "accessNote": resource.access_note or resource.error_message,
        }
        for resource in resources
    ]
    summary = build_access_summary(
        job_id=job_id,
        resources=resource_payload,
        progress=job.progress,
        status=job.status,
    )
    summary["downloadableAccessible"] = sum(1 for resource in resources if resource.can_access and resource.can_download)
    summary["discovered"] = sum(resource.discovered_children_count for resource in resources)
    summary["totalAnalizables"] = summary["total"]
    summary["noAnalizablesExternos"] = breakdown["noAnalizablesExternos"]
    summary["tecnicosIgnorados"] = breakdown["tecnicosIgnorados"]
    summary["globalUnplacedCount"] = breakdown["globalUnplacedCount"]
    summary["noAccessCount"] = breakdown["noAccessCount"]
    summary["noAccessByReason"] = breakdown["noAccessByReason"]
    return AccessSummaryRead.model_validate(summary)


def _coerce_job_phase(value: str | None) -> JobPhase:
    if value in {phase.value for phase in JobPhase}:
        return JobPhase(str(value))
    return JobPhase.ERROR


def _build_access_response(session: Session, settings: Settings, job_id: str) -> JobAccessRead:
    _ensure_review_inventory(session, settings, job_id)
    job = get_processing_job_or_404(session, job_id)
    summary = _build_access_summary(session, settings, job_id)
    breakdown = load_inventory_breakdown(settings, job_id)
    inventory_items = _load_inventory_items_or_empty(settings, job_id)
    inventory_index = {item.id: item for item in inventory_items}
    inventory_order = {item.id: index for index, item in enumerate(inventory_items)}

    resources = []
    for resource in session.exec(select(Resource).where(Resource.job_id == job_id)).all():
        inventory_item = inventory_index.get(resource.id)
        resources.append(_resource_read(resource, 0, inventory_item))
    resources.sort(
        key=lambda resource: (
            inventory_order.get(resource.id, len(inventory_order)),
            (resource.modulePath or resource.coursePath or "").lower(),
            resource.title.lower(),
            resource.id,
        )
    )

    resources_by_module: dict[str, list[ResourceListItemRead]] = {}
    for resource in resources:
        module_path = resource.modulePath or resource.coursePath or "Modulo general"
        resources_by_module.setdefault(module_path, []).append(resource)

    modules = [
        AccessModuleRead(
            modulePath=group.modulePath,
            total=group.total,
            accessible=group.accessible,
            downloadable=group.downloadable,
            downloadableAccessible=group.downloadableAccessible,
            ok_count=group.ok_count,
            no_accede_count=group.no_accede_count,
            requires_interaction_count=group.requires_interaction_count,
            requires_sso_count=group.requires_sso_count,
            requiere_interaccion_count=group.requiere_interaccion_count,
            requiere_sso_count=group.requiere_sso_count,
            downloadables_total=group.downloadables_total,
            downloadables_ok=group.downloadables_ok,
            byStatus=group.byStatus,
            resources=resources_by_module.get(group.modulePath, []),
        )
        for group in summary.groups
    ]
    return JobAccessRead(
        jobId=job_id,
        status=job.status,
        phase=_coerce_job_phase(job.phase),
        progress=job.progress,
        summary=summary,
        modules=modules,
        nonAnalyzableExternalResources=breakdown["auxiliaryResources"],
    )


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
    breakdown = load_inventory_breakdown(settings, job_id)
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
        totalAnalizables=review_summary.total_resources,
        totalFailItems=review_summary.total_fail_items,
        accessibleResources=review_summary.accessible_resources,
        downloadableResources=review_summary.downloadable_resources,
        noAnalizablesExternos=breakdown["noAnalizablesExternos"],
        tecnicosIgnorados=breakdown["tecnicosIgnorados"],
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
        return {item.id: item for item in load_inventory_file(settings, job_id)}
    except (FileNotFoundError, ValueError):
        return {}


def _load_inventory_items_or_empty(settings: Settings, job_id: str):
    try:
        return load_inventory_file(settings, job_id)
    except (FileNotFoundError, ValueError):
        return []


def _load_course_structure_or_empty(settings: Settings, job_id: str):
    try:
        return load_course_structure(settings, job_id)
    except (FileNotFoundError, ValueError):
        return None


def _build_visible_course_structure(
    settings: Settings,
    job_id: str,
    resources: list[ResourceListItemRead],
):
    resource_payload = [resource.model_dump(mode="python") for resource in resources]
    raw_structure = _load_course_structure_or_empty(settings, job_id)
    if raw_structure is None:
        raw_structure = build_fallback_course_structure(resource_payload)

    visible_resource_ids = {resource.id for resource in resources}
    augmented_structure = augment_course_structure(raw_structure, resource_payload) or raw_structure
    filtered_structure = filter_course_structure(augmented_structure, visible_resource_ids=visible_resource_ids)
    return filtered_structure or build_fallback_course_structure(resource_payload)


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
    review_session, review_summary = ensure_review_rollups(session, job_id)
    breakdown = load_inventory_breakdown(settings, job_id)
    inventory_items = _load_inventory_items_or_empty(settings, job_id)
    inventory_index = {item.id: item for item in inventory_items}
    inventory_order = {item.id: index for index, item in enumerate(inventory_items)}
    resources = []
    for resource, fail_count in list_resources_with_fail_counts(session, job_id):
        inventory_item = inventory_index.get(resource.id)
        if onlyBroken and not _is_broken_inventory_resource(resource, inventory_item):
            continue
        resources.append(_resource_read(resource, fail_count, inventory_item))
    resources.sort(
        key=lambda resource: (
            inventory_order.get(resource.id, len(inventory_order)),
            resource.title.lower(),
            resource.id,
        )
    )
    logger.info("Inventario de revision cargado", extra={"job_id": job_id, "resource_count": len(resources)})
    return ResourceListPayload(
        jobId=job_id,
        resources=resources,
        totalAnalizables=review_summary.total_resources,
        noAnalizablesExternos=breakdown["noAnalizablesExternos"],
        tecnicosIgnorados=breakdown["tecnicosIgnorados"],
        globalUnplacedCount=breakdown["globalUnplacedCount"],
        noAccessCount=breakdown["noAccessCount"],
        noAccessByReason=breakdown["noAccessByReason"],
        nonAnalyzableExternalResources=breakdown["auxiliaryResources"],
        reviewSession=_review_session_read(review_session),
        structure=_build_visible_course_structure(settings, job_id, resources),
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


@router.get("/{job_id}/access-summary", response_model=AccessSummaryRead)
def get_access_summary(
    job_id: str,
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> AccessSummaryRead:
    _ensure_review_inventory(session, settings, job_id)
    return _build_access_summary(session, settings, job_id)


@router.get("/{job_id}/access", response_model=JobAccessRead)
def get_job_access(
    job_id: str,
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> JobAccessRead:
    return _build_access_response(session, settings, job_id)


@router.get("/{job_id}/accessibility", response_model=AccessibilityReportRead)
def get_job_accessibility(
    job_id: str,
    request: Request,
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> AccessibilityReportRead:
    get_processing_job_or_404(session, job_id)
    _ensure_review_inventory(session, settings, job_id)
    report_settings = _settings_for_request_canvas_token(request, settings)
    canvas_client, canvas_credentials, course_id = _load_online_context(
        request=request,
        settings=settings,
        job_id=job_id,
    )
    inventory = [item.model_dump(mode="python") for item in load_inventory_file(report_settings, job_id)]
    ensure_accessibility_report(
        settings=report_settings,
        job_id=job_id,
        resources=inventory,
        canvas_client=canvas_client,
        canvas_credentials=canvas_credentials,
        course_id=course_id,
    )
    report = ensure_pdf_accessibility_report(
        settings=report_settings,
        job_id=job_id,
        resources=inventory,
        canvas_client=canvas_client,
        canvas_credentials=canvas_credentials,
        course_id=course_id,
    )
    report = ensure_docx_accessibility_report(
        settings=report_settings,
        job_id=job_id,
        resources=inventory,
        canvas_client=canvas_client,
        canvas_credentials=canvas_credentials,
        course_id=course_id,
    )
    report = ensure_video_accessibility_report(
        settings=report_settings,
        job_id=job_id,
        resources=inventory,
        canvas_client=canvas_client,
        canvas_credentials=canvas_credentials,
        course_id=course_id,
    )
    return _accessibility_report_read(report)


@router.get("/{job_id}/executive-summary", response_model=ExecutiveSummaryRead)
def get_job_executive_summary(
    job_id: str,
    request: Request,
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> dict:
    job = get_processing_job_or_404(session, job_id)
    _ensure_review_inventory(session, settings, job_id)
    report_settings = _settings_for_request_canvas_token(request, settings)
    canvas_client, canvas_credentials, course_id = _load_online_context(
        request=request,
        settings=settings,
        job_id=job_id,
    )
    inventory = [item.model_dump(mode="python") for item in load_inventory_file(report_settings, job_id)]
    ensure_accessibility_report(
        settings=report_settings,
        job_id=job_id,
        resources=inventory,
        canvas_client=canvas_client,
        canvas_credentials=canvas_credentials,
        course_id=course_id,
    )
    report = ensure_pdf_accessibility_report(
        settings=report_settings,
        job_id=job_id,
        resources=inventory,
        canvas_client=canvas_client,
        canvas_credentials=canvas_credentials,
        course_id=course_id,
    )
    report = ensure_docx_accessibility_report(
        settings=report_settings,
        job_id=job_id,
        resources=inventory,
        canvas_client=canvas_client,
        canvas_credentials=canvas_credentials,
        course_id=course_id,
    )
    report = ensure_video_accessibility_report(
        settings=report_settings,
        job_id=job_id,
        resources=inventory,
        canvas_client=canvas_client,
        canvas_credentials=canvas_credentials,
        course_id=course_id,
    )
    return build_executive_summary(
        job_id=job_id,
        mode=_job_mode(report_settings, job_id),
        course_title=job.original_filename,
        inventory_items=inventory,
        accessibility_report=report,
    )


def _job_mode(settings: Settings, job_id: str) -> str:
    return "OFFLINE_IMSCC" if get_extracted_dir(settings, job_id).exists() else "ONLINE_CANVAS"


@router.post("/{job_id}/access-analysis/retry", response_model=JobStatusResponse, status_code=status.HTTP_202_ACCEPTED)
def retry_access_analysis(
    job_id: str,
    background_tasks: BackgroundTasks,
    request: Request,
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
    engine=Depends(get_engine),
) -> JobStatusResponse:
    if not get_extracted_dir(settings, job_id).exists():
        require_active_canvas_token(request, settings)
    response = prepare_access_analysis_retry(session, settings, job_id)
    background_tasks.add_task(
        rerun_access_analysis,
        engine,
        settings,
        request.app.state.online_job_contexts,
        job_id,
        _canvas_client_factory,
        _url_check_factory,
    )
    return response


@router.get("/{job_id}/resources/{resource_id}/download")
def download_resource_file(
    job_id: str,
    resource_id: str,
    request: Request,
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
):
    _ensure_review_inventory(session, settings, job_id)
    resource = _get_review_resource(session, job_id, resource_id)
    inventory_item = _load_inventory_index_or_empty(settings, job_id).get(resource_id)
    can_download = inventory_item.can_download if inventory_item is not None else resource.can_download

    if not can_download:
        raise AppError(
            code="resource_not_downloadable",
            message="Este recurso no tiene un archivo descargable asociado en el backend.",
            status_code=status.HTTP_409_CONFLICT,
            job_id=job_id,
        )

    file_path = inventory_item.file_path if inventory_item is not None else resource.path
    if file_path:
        try:
            resolved_path = resolve_job_resource_path(settings, job_id, file_path)
        except AppError:
            resolved_path = None
        if resolved_path is not None and resolved_path.exists() and resolved_path.is_file():
            return FileResponse(
                path=resolved_path,
                filename=resolved_path.name,
                headers=_no_store_headers(),
            )

    content = _load_resource_content(
        request=request,
        settings=settings,
        job_id=job_id,
        resource_id=resource_id,
    )
    if content.ok and content.binaryPath:
        return FileResponse(
            path=content.binaryPath,
            filename=content.filename,
            media_type=content.mimeType or "application/octet-stream",
            headers=_no_store_headers(),
        )

    _raise_content_error(content, job_id=job_id)


@router.get("/{job_id}/resources/{resource_id}/content")
def get_resource_content_endpoint(
    job_id: str,
    resource_id: str,
    request: Request,
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
):
    _ensure_review_inventory(session, settings, job_id)
    _get_review_resource(session, job_id, resource_id)
    content = _load_resource_content(
        request=request,
        settings=settings,
        job_id=job_id,
        resource_id=resource_id,
    )
    if not content.ok:
        _raise_content_error(content, job_id=job_id)

    if content.htmlContent is not None:
        return HTMLResponse(
            content=content.htmlContent,
            media_type=content.mimeType or "text/html",
            headers=_no_store_headers(),
        )
    if content.textContent is not None:
        return Response(
            content=content.textContent,
            media_type=content.mimeType or "text/plain",
            headers=_no_store_headers(),
        )
    if content.binaryPath:
        return FileResponse(
            path=content.binaryPath,
            filename=content.filename,
            media_type=content.mimeType or "application/octet-stream",
            headers=_no_store_headers(),
        )

    raise AppError(
        code="resource_content_unavailable",
        message="No hay contenido reutilizable para este recurso.",
        status_code=status.HTTP_409_CONFLICT,
        job_id=job_id,
    )


@router.get("/{job_id}/resources/{resource_id}/content-check", response_model=ResourceContentCheckRead)
def check_resource_content(
    job_id: str,
    resource_id: str,
    request: Request,
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> ResourceContentCheckRead:
    _ensure_review_inventory(session, settings, job_id)
    inventory_item = _load_inventory_index_or_empty(settings, job_id).get(resource_id)
    resource = session.get(Resource, resource_id)
    if resource is not None and resource.job_id != job_id:
        resource = None
    if resource is None and inventory_item is None:
        raise AppError(
            code="resource_not_found",
            message="No hemos encontrado ese recurso.",
            status_code=status.HTTP_404_NOT_FOUND,
            details={"reason": f"El recurso '{resource_id}' no existe."},
            job_id=job_id,
        )
    core = normalize_resource(resource or inventory_item, inventory_item if resource is not None else None)
    content = _load_resource_content(
        request=request,
        settings=settings,
        job_id=job_id,
        resource_id=resource_id,
    )
    return ResourceContentCheckRead(
        ok=content.ok,
        resourceId=content.resourceId,
        title=content.title,
        type=content.type,
        origin=content.origin,
        contentKind=content.contentKind,
        contentAvailable=content.ok and content.contentKind in {"HTML", "TEXT", "PDF", "BINARY"},
        downloadable=core.downloadable and content.contentKind in {"TEXT", "PDF", "BINARY"},
        mimeType=content.mimeType,
        filename=content.filename,
        errorCode=content.errorCode,
        errorDetail=content.errorDetail,
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
    report_settings = _settings_for_request_canvas_token(request, settings)
    canvas_client, canvas_credentials, course_id = _load_online_context(
        request=request,
        settings=settings,
        job_id=job_id,
    )
    report_payload = generate_job_report(
        session,
        report_settings,
        job_id,
        include_pending=payload.includePending if payload else True,
        only_fails=payload.onlyFails if payload else False,
        canvas_client=canvas_client,
        canvas_credentials=canvas_credentials,
        course_id=course_id,
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
