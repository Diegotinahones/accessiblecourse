from __future__ import annotations

import json
import logging
import shutil
from collections.abc import Callable
from pathlib import Path, PurePosixPath
from typing import Any

from sqlmodel import Session, delete, select

from app.core.config import Settings
from app.core.errors import AppError
from app.core.logging import append_job_log, job_logging_context
from app.models import ChecklistEntry, Job, JobEvent, ReportRecord, ResourceRecord, utcnow
from app.models.entities import Job as ReviewJob
from app.schemas import (
    ChecklistDecision,
    ChecklistStateResponse,
    ChecklistUpdateRequest,
    JobCreatedResponse,
    JobLifecycleStatus,
    JobStatusResponse,
    ResourceResponse,
)
from app.services.canvas_client import CanvasClient, OnlineJobContextStore
from app.services.canvas_inventory import build_canvas_inventory
from app.services.catalog import get_checklist_template
from app.services.imscc import build_resources_from_extracted
from app.services.imscc_parser import IMSCCParser, ParserError
from app.services.storage import (
    get_extracted_dir,
    get_job_dir,
    get_job_log_path,
    get_reports_dir,
    get_upload_path,
)
from app.services.url_check import URLCheckService

logger = logging.getLogger("accessiblecourse.jobs")

RESOURCE_TYPE_TO_REVIEW_TYPE = {
    "PDF": "PDF",
    "Web": "WEB",
    "Video": "VIDEO",
    "Notebook": "NOTEBOOK",
    "Other": "OTHER",
}

RESOURCE_STATUS_TO_REVIEW_STATUS = {
    "OK": "OK",
    "AVISO": "WARN",
    "ERROR": "ERROR",
}

REVIEW_TYPE_TO_LEGACY_TYPE = {
    "WEB": "Web",
    "PDF": "PDF",
    "VIDEO": "Video",
    "NOTEBOOK": "Notebook",
    "IMAGE": "Other",
    "OTHER": "Other",
}

REVIEW_STATUS_TO_LEGACY_STATUS = {
    "OK": "OK",
    "WARN": "AVISO",
    "ERROR": "ERROR",
}

EXCLUDED_METADATA_EXTENSIONS = {
    ".xml",
    ".xsd",
    ".dtd",
    ".qti",
    ".imsmanifest",
}


def get_job_or_404(session: Session, job_id: str) -> Job:
    job = session.get(Job, job_id)
    if not job:
        raise AppError(code="job_not_found", message="No hemos encontrado ese analisis.", status_code=404)
    return job


def get_resource_or_404(session: Session, job_id: str, resource_id: str) -> ResourceRecord:
    statement = select(ResourceRecord).where(ResourceRecord.job_id == job_id, ResourceRecord.id == resource_id)
    resource = session.exec(statement).first()
    if not resource:
        raise AppError(code="resource_not_found", message="No hemos encontrado ese recurso.", status_code=404)
    return resource


def record_job_event(
    session: Session,
    settings: Settings,
    *,
    job_id: str,
    event: str,
    message: str,
    progress: int | None = None,
    details: dict | None = None,
    level: int = logging.INFO,
) -> None:
    session.add(
        JobEvent(
            job_id=job_id,
            event=event,
            message=message,
            progress=progress,
            details=details or {},
        )
    )
    append_job_log(get_job_log_path(settings, job_id), event=event, message=message, details=details)
    with job_logging_context(job_id):
        logger.log(level, message, extra={"event": event, "job_id": job_id, "details": details or {}})


def serialize_job(job: Job) -> JobStatusResponse:
    return JobStatusResponse(
        jobId=job.id,
        status=JobLifecycleStatus(job.status),
        progress=job.progress,
        message=job.message,
        currentStep=job.current_step,
        totalSteps=job.total_steps,
        errorCode=job.error_code,
    )


def serialize_resource(resource: ResourceRecord) -> ResourceResponse:
    return ResourceResponse(
        id=resource.id,
        title=resource.title,
        type=resource.type,
        origin=resource.origin,
        status=resource.status,
        href=resource.href,
    )


def _derive_course_path(source: str | None) -> str:
    if not source:
        return "Raiz del curso"

    if source.startswith(("http://", "https://")):
        return "Enlaces externos"

    parent = PurePosixPath(source).parent.as_posix().strip(".")
    return parent or "Raiz del curso"


def _build_review_inventory(resources) -> list[dict[str, str | None]]:
    inventory: list[dict[str, str | None]] = []
    for parsed_resource in resources:
        href = parsed_resource.href or parsed_resource.extracted_path
        is_external = bool(href and href.startswith(("http://", "https://")))
        file_path = parsed_resource.extracted_path or (None if is_external else href)
        source_url = href if is_external else None
        if _should_skip_metadata_resource(file_path=file_path, source_url=source_url):
            continue

        module_path = _derive_course_path(file_path or source_url)
        inventory.append(
            {
                "id": parsed_resource.resource_id,
                "title": parsed_resource.title,
                "type": RESOURCE_TYPE_TO_REVIEW_TYPE.get(parsed_resource.resource_type, "OTHER"),
                "origin": _normalize_origin(parsed_resource.origin, source_url=source_url),
                "url": source_url,
                "sourceUrl": source_url,
                "path": file_path,
                "filePath": file_path,
                "localPath": file_path,
                "course_path": module_path,
                "coursePath": module_path,
                "module_path": module_path,
                "modulePath": module_path,
                "status": RESOURCE_STATUS_TO_REVIEW_STATUS.get(parsed_resource.status, "WARN"),
                "notes": None,
            }
        )
    return inventory


def _write_review_inventory_payload(settings: Settings, job_id: str, inventory: list[dict]) -> None:
    inventory_path = get_job_dir(settings, job_id) / "resources.json"
    inventory_path.parent.mkdir(parents=True, exist_ok=True)
    inventory_path.write_text(
        json.dumps(inventory, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _write_review_inventory(settings: Settings, job_id: str, resources) -> None:
    _write_review_inventory_payload(settings, job_id, _build_review_inventory(resources))


def build_url_checker(settings: Settings) -> URLCheckService:
    return URLCheckService(
        timeout_seconds=settings.url_check_timeout_seconds,
        max_urls=settings.url_check_max_urls,
    )


def _should_skip_metadata_resource(*, file_path: str | None, source_url: str | None) -> bool:
    if source_url:
        return False
    if not file_path:
        return False
    normalized_name = Path(file_path.split("#", 1)[0].split("?", 1)[0]).name.lower()
    if normalized_name == "imsmanifest.xml":
        return True
    return Path(normalized_name).suffix.lower() in EXCLUDED_METADATA_EXTENSIONS


def _normalize_origin(origin: str | None, *, source_url: str | None) -> str:
    normalized = (origin or "").strip().lower()
    if normalized in {"external", "externo"} or source_url:
        return "externo"
    return "interno"


def _normalize_offline_inventory(inventory: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized_resources: list[dict[str, Any]] = []
    for resource in inventory:
        source_url = resource.get("sourceUrl") or resource.get("url")
        file_path = resource.get("filePath") or resource.get("localPath") or resource.get("path")
        if isinstance(source_url, str):
            source_url = source_url.strip() or None
        else:
            source_url = None
        if isinstance(file_path, str):
            file_path = file_path.strip() or None
        else:
            file_path = None

        if _should_skip_metadata_resource(file_path=file_path, source_url=source_url):
            continue

        module_path = resource.get("modulePath") or resource.get("module_path") or resource.get("coursePath")
        if not isinstance(module_path, str) or not module_path.strip():
            module_path = _derive_course_path(file_path or source_url)
        else:
            module_path = module_path.strip()

        normalized = dict(resource)
        normalized["origin"] = _normalize_origin(
            resource.get("origin") if isinstance(resource.get("origin"), str) else None,
            source_url=source_url,
        )
        normalized["url"] = source_url
        normalized["sourceUrl"] = source_url
        normalized["path"] = file_path
        normalized["filePath"] = file_path
        normalized["localPath"] = file_path
        normalized["course_path"] = module_path
        normalized["coursePath"] = module_path
        normalized["module_path"] = module_path
        normalized["modulePath"] = module_path
        normalized.setdefault("details", {})
        normalized_resources.append(normalized)

    return normalized_resources


def _build_manifest_review_inventory(extracted_dir: Path) -> list[dict[str, Any]]:
    parser = IMSCCParser()
    manifest_path = parser.find_manifest(extracted_dir)
    parsed_manifest = parser.parse_manifest(manifest_path, extracted_dir)
    inventory = parser.build_resource_inventory(parsed_manifest, manifest_path, extracted_dir)
    return _normalize_offline_inventory(inventory)


def _build_offline_review_inventory(extracted_dir: Path) -> list[dict[str, Any]]:
    try:
        manifest_inventory = _build_manifest_review_inventory(extracted_dir)
        if manifest_inventory:
            return manifest_inventory
    except ParserError:
        logger.info(
            "manifest_inventory_fallback",
            extra={"event": "manifest_inventory_fallback", "details": {"reason": "parser_error"}},
        )

    return _normalize_offline_inventory(_build_review_inventory(build_resources_from_extracted(extracted_dir)))


def _persist_legacy_inventory(session: Session, job_id: str, inventory: list[dict]) -> None:
    session.exec(delete(ChecklistEntry).where(ChecklistEntry.job_id == job_id))
    session.exec(delete(ResourceRecord).where(ResourceRecord.job_id == job_id))

    for resource in inventory:
        legacy_type = REVIEW_TYPE_TO_LEGACY_TYPE.get(str(resource.get("type")), "Other")
        resource_record = ResourceRecord(
            id=str(resource["id"]),
            job_id=job_id,
            title=str(resource.get("title") or "Recurso sin titulo"),
            type=legacy_type,
            origin=str(resource.get("origin") or "interno"),
            status=REVIEW_STATUS_TO_LEGACY_STATUS.get(str(resource.get("status") or "WARN"), "AVISO"),
            href=resource.get("url"),
            extracted_path=resource.get("path"),
        )
        session.add(resource_record)
        for item in get_checklist_template(legacy_type):
            session.add(
                ChecklistEntry(
                    job_id=job_id,
                    resource_id=resource_record.id,
                    item_id=str(item["id"]),
                    label=str(item["label"]),
                    recommendation=str(item["recommendation"]),
                    decision=ChecklistDecision.PENDING.value,
                )
            )


def create_job_record(
    session: Session,
    settings: Settings,
    *,
    job_id: str,
    original_filename: str,
    stored_filename: str,
    size_bytes: int,
    total_steps: int = 4,
    initial_message: str = "Analisis en cola.",
    event_details: dict | None = None,
) -> JobCreatedResponse:
    job_dir = get_job_dir(settings, job_id)
    job_dir.mkdir(parents=True, exist_ok=True)

    job = Job(
        id=job_id,
        original_filename=original_filename,
        stored_filename=stored_filename,
        size_bytes=size_bytes,
        storage_dir=str(job_dir),
        status=JobLifecycleStatus.CREATED.value,
        progress=0,
        current_step=1,
        total_steps=total_steps,
        message=initial_message,
    )
    session.add(job)
    details = {"filename": original_filename, "sizeBytes": size_bytes}
    if event_details:
        details.update(event_details)
    record_job_event(
        session,
        settings,
        job_id=job_id,
        event="created",
        message="Job creado y pendiente de procesamiento.",
        progress=0,
        details=details,
    )
    session.commit()
    return JobCreatedResponse(jobId=job_id)


def create_online_job_record(
    session: Session,
    settings: Settings,
    *,
    job_id: str,
    course_id: str,
    course_name: str | None,
) -> JobCreatedResponse:
    resolved_course_name = course_name or f"Canvas course {course_id}"
    review_job = session.get(ReviewJob, job_id)
    if review_job is None:
        session.add(ReviewJob(id=job_id, name=resolved_course_name))
    else:
        review_job.name = resolved_course_name
        review_job.updated_at = utcnow()
        session.add(review_job)
    session.flush()

    return create_job_record(
        session,
        settings,
        job_id=job_id,
        original_filename=resolved_course_name,
        stored_filename=resolved_course_name,
        size_bytes=0,
        total_steps=6,
        initial_message="Analisis online en cola.",
        event_details={"source": "canvas", "courseId": course_id},
    )


def _update_job(
    session: Session,
    job: Job,
    *,
    status: JobLifecycleStatus,
    progress: int,
    current_step: int,
    message: str,
    error_code: str | None = None,
    error_message: str | None = None,
) -> None:
    job.status = status.value
    job.progress = progress
    job.current_step = current_step
    job.message = message
    job.error_code = error_code
    job.error_message = error_message
    job.updated_at = utcnow()
    if status in {JobLifecycleStatus.DONE, JobLifecycleStatus.ERROR}:
        job.finished_at = utcnow()
    session.add(job)


def _reset_job_related_data(session: Session, settings: Settings, job_id: str) -> None:
    session.exec(delete(ChecklistEntry).where(ChecklistEntry.job_id == job_id))
    session.exec(delete(ResourceRecord).where(ResourceRecord.job_id == job_id))
    existing_report = session.exec(select(ReportRecord).where(ReportRecord.job_id == job_id)).first()
    if existing_report:
        Path(existing_report.pdf_path).unlink(missing_ok=True)
        Path(existing_report.docx_path).unlink(missing_ok=True)
        session.delete(existing_report)

    shutil.rmtree(get_extracted_dir(settings, job_id), ignore_errors=True)
    shutil.rmtree(get_reports_dir(settings, job_id), ignore_errors=True)
    session.commit()


def _update_job_progress(
    session: Session,
    settings: Settings,
    job: Job,
    *,
    current_step: int,
    progress: int,
    message: str,
    event: str = "progress",
    details: dict[str, Any] | None = None,
) -> None:
    _update_job(
        session,
        job,
        status=JobLifecycleStatus.PROCESSING,
        progress=progress,
        current_step=current_step,
        message=message,
    )
    record_job_event(
        session,
        settings,
        job_id=job.id,
        event=event,
        message=message,
        progress=progress,
        details=details,
    )
    session.commit()


def _append_note(resource: dict[str, Any], note: str) -> None:
    existing = resource.get("notes")
    if existing is None:
        resource["notes"] = [note]
        return
    if isinstance(existing, list):
        if note not in existing:
            existing.append(note)
        return
    if isinstance(existing, str):
        cleaned = existing.strip()
        resource["notes"] = [cleaned, note] if cleaned and cleaned != note else [note]


def _apply_url_validation(
    resources: list[dict[str, Any]],
    url_results: dict[str, Any],
) -> dict[str, Any]:
    broken_links: list[dict[str, Any]] = []
    checked_urls = 0
    skipped_urls = 0

    for resource in resources:
        resource_id = str(resource["id"])
        result = url_results.get(resource_id)
        if result is None:
            continue

        details = dict(resource.get("details") or {})
        if not result.checked:
            skipped_urls += 1
            details["urlCheck"] = {"checked": False, "reason": result.reason}
            resource["details"] = details
            continue

        checked_urls += 1
        url_check_details = {"checked": True}
        if result.status_code is not None:
            url_check_details["statusCode"] = result.status_code
        if result.url_status is not None:
            url_check_details["urlStatus"] = result.url_status
            resource["urlStatus"] = result.url_status
        if result.final_url:
            url_check_details["finalUrl"] = result.final_url
            resource["finalUrl"] = result.final_url
        if result.checked_at is not None:
            checked_at_iso = result.checked_at.isoformat()
            url_check_details["checkedAt"] = checked_at_iso
            resource["checkedAt"] = checked_at_iso
        if result.reason:
            url_check_details["reason"] = result.reason
        details["urlCheck"] = url_check_details

        if result.broken_link:
            resource["status"] = "ERROR"
            details["broken_link"] = {
                "url": resource.get("url"),
                "reason": result.reason,
                "statusCode": result.status_code,
            }
            if result.reason == "404_not_found":
                _append_note(resource, "broken_link: URL devuelve 404.")
            elif result.reason == "timeout":
                _append_note(resource, "broken_link: la URL ha excedido el tiempo de espera.")
            elif result.status_code is not None and result.status_code >= 400:
                _append_note(resource, f"broken_link: URL devuelve {result.status_code}.")
            broken_links.append(
                {
                    "resourceId": resource_id,
                    "title": resource.get("title"),
                    "url": resource.get("sourceUrl") or resource.get("url"),
                    "reason": result.reason,
                    "statusCode": result.status_code,
                    "urlStatus": result.url_status,
                }
            )

        resource["details"] = details

    return {
        "brokenLinks": broken_links,
        "checkedUrls": checked_urls,
        "skippedUrls": skipped_urls,
    }


def load_checklist_state(session: Session, job_id: str) -> ChecklistStateResponse:
    get_job_or_404(session, job_id)
    entries = session.exec(
        select(ChecklistEntry)
        .where(ChecklistEntry.job_id == job_id)
        .order_by(ChecklistEntry.resource_id, ChecklistEntry.id)
    ).all()
    state: dict[str, dict[str, ChecklistDecision]] = {}
    for entry in entries:
        state.setdefault(entry.resource_id, {})[entry.item_id] = ChecklistDecision(entry.decision)
    return ChecklistStateResponse(jobId=job_id, state=state)


def save_resource_checklist(
    session: Session,
    job_id: str,
    resource_id: str,
    payload: ChecklistUpdateRequest,
) -> dict[str, ChecklistDecision]:
    job = get_job_or_404(session, job_id)
    if job.status != JobLifecycleStatus.DONE.value:
        raise AppError(
            code="job_not_ready",
            message="El checklist solo se puede guardar cuando el analisis ha terminado.",
            status_code=409,
            job_id=job_id,
        )

    resource = get_resource_or_404(session, job_id, resource_id)
    existing_entries = session.exec(
        select(ChecklistEntry).where(ChecklistEntry.job_id == job_id, ChecklistEntry.resource_id == resource_id)
    ).all()
    existing_by_id = {entry.item_id: entry for entry in existing_entries}

    for item in get_checklist_template(resource.type):
        decision = payload.items.get(
            item.id,
            ChecklistDecision(
                existing_by_id[item.id].decision if item.id in existing_by_id else ChecklistDecision.PENDING.value
            ),
        )
        if item.id in existing_by_id:
            existing_by_id[item.id].decision = decision.value
            session.add(existing_by_id[item.id])
        else:
            session.add(
                ChecklistEntry(
                    job_id=job_id,
                    resource_id=resource_id,
                    item_id=item.id,
                    label=item.label,
                    recommendation=item.recommendation,
                    decision=decision.value,
                )
            )

    session.commit()
    persisted_entries = session.exec(
        select(ChecklistEntry).where(ChecklistEntry.job_id == job_id, ChecklistEntry.resource_id == resource_id)
    ).all()
    return {entry.item_id: ChecklistDecision(entry.decision) for entry in persisted_entries}


def list_resources(session: Session, job_id: str) -> list[ResourceResponse]:
    job = get_job_or_404(session, job_id)
    if job.status != JobLifecycleStatus.DONE.value:
        raise AppError(
            code="job_not_ready",
            message="Los recursos solo estan disponibles cuando el analisis ha terminado.",
            status_code=409,
            job_id=job_id,
        )

    resources = session.exec(
        select(ResourceRecord).where(ResourceRecord.job_id == job_id).order_by(ResourceRecord.title)
    ).all()
    return [serialize_resource(resource) for resource in resources]


def process_job(engine, settings: Settings, job_id: str) -> None:
    with Session(engine) as session:
        job = get_job_or_404(session, job_id)
        upload_path = get_upload_path(settings, job_id, job.original_filename)
        extracted_dir = get_extracted_dir(settings, job_id)
        try:
            _update_job(
                session,
                job,
                status=JobLifecycleStatus.PROCESSING,
                progress=10,
                current_step=1,
                message="Validando archivo del curso.",
            )
            record_job_event(
                session,
                settings,
                job_id=job_id,
                event="started",
                message="Procesamiento del job iniciado.",
                progress=10,
            )
            session.commit()

            extracted_dir.mkdir(parents=True, exist_ok=True)
            _update_job(
                session,
                job,
                status=JobLifecycleStatus.PROCESSING,
                progress=35,
                current_step=2,
                message="Extrayendo recursos del curso.",
            )
            record_job_event(
                session,
                settings,
                job_id=job_id,
                event="progress",
                message="Extrayendo el paquete de curso.",
                progress=35,
            )
            session.commit()

            from app.services.storage import extract_archive

            extract_archive(source=upload_path, destination=extracted_dir, settings=settings)

            _update_job(
                session,
                job,
                status=JobLifecycleStatus.PROCESSING,
                progress=70,
                current_step=3,
                message="Preparando checklist de recursos.",
            )
            record_job_event(
                session,
                settings,
                job_id=job_id,
                event="progress",
                message="Catalogando recursos y checklist base.",
                progress=70,
            )
            session.commit()

            session.exec(delete(ChecklistEntry).where(ChecklistEntry.job_id == job_id))
            session.exec(delete(ResourceRecord).where(ResourceRecord.job_id == job_id))
            inventory = _build_offline_review_inventory(extracted_dir)
            if not inventory:
                raise AppError(
                    code="no_resources_found",
                    message="No se han encontrado recursos procesables dentro del paquete.",
                    job_id=job_id,
                )
            url_checker = build_url_checker(settings)
            url_validation_summary = _apply_url_validation(inventory, url_checker.check(inventory))

            _write_review_inventory_payload(settings, job_id, inventory)
            _persist_legacy_inventory(session, job_id, inventory)

            _update_job(
                session,
                job,
                status=JobLifecycleStatus.DONE,
                progress=100,
                current_step=4,
                message="Analisis completado.",
            )
            record_job_event(
                session,
                settings,
                job_id=job_id,
                event="finished",
                message="Analisis completado correctamente.",
                progress=100,
                details={
                    "resourceCount": len(inventory),
                    "brokenLinkCount": len(url_validation_summary["brokenLinks"]),
                },
            )
            session.commit()
        except AppError as exc:
            _update_job(
                session,
                job,
                status=JobLifecycleStatus.ERROR,
                progress=job.progress or 0,
                current_step=min(job.current_step, job.total_steps),
                message=exc.message,
                error_code=exc.code,
                error_message=exc.message,
            )
            details = exc.details if isinstance(exc.details, dict) else {"details": exc.details}
            record_job_event(
                session,
                settings,
                job_id=job_id,
                event="error",
                message=exc.message,
                progress=job.progress,
                details=details,
                level=logging.ERROR,
            )
            session.commit()
        except Exception as exc:  # pragma: no cover
            _update_job(
                session,
                job,
                status=JobLifecycleStatus.ERROR,
                progress=job.progress or 0,
                current_step=min(job.current_step, job.total_steps),
                message="No hemos podido procesar el archivo. Revisa el formato e intentalo de nuevo.",
                error_code="unexpected_processing_error",
                error_message=str(exc),
            )
            record_job_event(
                session,
                settings,
                job_id=job_id,
                event="error",
                message="Error no controlado durante el procesamiento del job.",
                progress=job.progress,
                details={"exception": exc.__class__.__name__},
                level=logging.ERROR,
            )
            logger.exception("Unhandled job processing error", extra={"event": "error", "job_id": job_id})
            session.commit()


def process_online_job(
    engine,
    settings: Settings,
    job_contexts: OnlineJobContextStore,
    job_id: str,
    canvas_client_factory: Callable[[Any, Settings], CanvasClient],
    url_check_factory: Callable[[Settings], URLCheckService],
) -> None:
    with Session(engine) as session:
        job = get_job_or_404(session, job_id)
        context = job_contexts.pop(job_id)
        if context is None:
            _update_job(
                session,
                job,
                status=JobLifecycleStatus.ERROR,
                progress=job.progress or 0,
                current_step=min(job.current_step, job.total_steps),
                message="La sesion temporal de Canvas ha caducado antes de empezar el analisis.",
                error_code="canvas_session_missing",
                error_message="Missing online job context",
            )
            record_job_event(
                session,
                settings,
                job_id=job_id,
                event="error",
                message="La sesion temporal de Canvas ha caducado antes de empezar el analisis.",
                progress=job.progress,
                details={"reason": "missing_online_job_context"},
                level=logging.ERROR,
            )
            session.commit()
            return

        client = canvas_client_factory(context.credentials, settings)
        url_checker = url_check_factory(settings)
        try:
            client.verify_auth()
            _update_job_progress(
                session,
                settings,
                job,
                current_step=1,
                progress=10,
                message="Autenticacion Canvas validada.",
                event="started",
                details={"source": "canvas", "courseId": context.course_id},
            )

            course = client.get_course(context.course_id)
            job.original_filename = course.name
            job.stored_filename = course.name
            review_job = session.get(ReviewJob, job_id)
            if review_job is None:
                review_job = ReviewJob(id=job_id, name=course.name)
            else:
                review_job.name = course.name
                review_job.updated_at = utcnow()
            session.add(review_job)
            session.add(job)
            session.commit()
            _update_job_progress(
                session,
                settings,
                job,
                current_step=2,
                progress=25,
                message=f"Curso cargado: {course.name}",
                details={"courseId": course.id, "courseName": course.name},
            )

            modules = client.list_modules(course.id)
            if not modules:
                raise AppError(
                    code="canvas_no_modules",
                    message="El curso no tiene modulos visibles para construir el inventario online.",
                    status_code=409,
                    job_id=job_id,
                )
            _update_job_progress(
                session,
                settings,
                job,
                current_step=3,
                progress=45,
                message=f"Modulos leidos: {len(modules)}",
                details={"moduleCount": len(modules)},
            )

            inventory_build = build_canvas_inventory(client, course_id=course.id, modules=modules)
            _update_job_progress(
                session,
                settings,
                job,
                current_step=4,
                progress=65,
                message=f"Items leidos: {inventory_build.items_read}",
                details={"itemsRead": inventory_build.items_read, "resourceCount": len(inventory_build.resources)},
            )

            url_results = url_checker.check(inventory_build.resources, credentials=context.credentials)
            url_validation_summary = _apply_url_validation(inventory_build.resources, url_results)
            _update_job_progress(
                session,
                settings,
                job,
                current_step=5,
                progress=82,
                message="Validacion de URLs completada.",
                details=url_validation_summary,
            )

            _write_review_inventory_payload(settings, job_id, inventory_build.resources)
            _persist_legacy_inventory(session, job_id, inventory_build.resources)

            _update_job(
                session,
                job,
                status=JobLifecycleStatus.DONE,
                progress=100,
                current_step=6,
                message="Analisis online completado.",
            )
            record_job_event(
                session,
                settings,
                job_id=job_id,
                event="finished",
                message="Inventario online persistido correctamente.",
                progress=100,
                details={
                    "courseId": course.id,
                    "courseName": course.name,
                    "resourceCount": len(inventory_build.resources),
                    "brokenLinkCount": len(url_validation_summary["brokenLinks"]),
                },
            )
            session.commit()
        except AppError as exc:
            _update_job(
                session,
                job,
                status=JobLifecycleStatus.ERROR,
                progress=job.progress or 0,
                current_step=min(job.current_step, job.total_steps),
                message=exc.message,
                error_code=exc.code,
                error_message=exc.message,
            )
            details = exc.details if isinstance(exc.details, dict) else {"details": exc.details}
            record_job_event(
                session,
                settings,
                job_id=job_id,
                event="error",
                message=exc.message,
                progress=job.progress,
                details=details,
                level=logging.ERROR,
            )
            session.commit()
        except Exception as exc:  # pragma: no cover
            _update_job(
                session,
                job,
                status=JobLifecycleStatus.ERROR,
                progress=job.progress or 0,
                current_step=min(job.current_step, job.total_steps),
                message="No hemos podido procesar el curso online. Intentalo de nuevo en unos instantes.",
                error_code="unexpected_online_processing_error",
                error_message=str(exc),
            )
            record_job_event(
                session,
                settings,
                job_id=job_id,
                event="error",
                message="Error no controlado durante el procesamiento online.",
                progress=job.progress,
                details={"exception": exc.__class__.__name__},
                level=logging.ERROR,
            )
            logger.exception("Unhandled online job processing error", extra={"event": "error", "job_id": job_id})
            session.commit()


def prepare_retry_job(session: Session, settings: Settings, job_id: str) -> JobStatusResponse:
    job = get_job_or_404(session, job_id)
    upload_path = get_upload_path(settings, job_id, job.original_filename)
    if not upload_path.exists():
        raise AppError(
            code="upload_missing",
            message="No se encuentra el fichero original del analisis para reintentarlo.",
            status_code=409,
            job_id=job_id,
        )

    _reset_job_related_data(session, settings, job_id)
    _update_job(
        session,
        job,
        status=JobLifecycleStatus.CREATED,
        progress=0,
        current_step=1,
        message="Reintento en cola.",
        error_code=None,
        error_message=None,
    )
    record_job_event(
        session,
        settings,
        job_id=job_id,
        event="created",
        message="Reintento del job programado.",
        progress=0,
    )
    session.commit()
    return serialize_job(job)
