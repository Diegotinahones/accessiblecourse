from __future__ import annotations

import json
import logging
import shutil
from pathlib import Path, PurePosixPath

from sqlmodel import Session, delete, select

from app.core.config import Settings
from app.core.errors import AppError
from app.core.logging import append_job_log, job_logging_context
from app.models import ChecklistEntry, Job, JobEvent, ReportRecord, ResourceRecord, utcnow
from app.schemas import (
    ChecklistDecision,
    ChecklistStateResponse,
    ChecklistUpdateRequest,
    JobCreatedResponse,
    JobLifecycleStatus,
    JobStatusResponse,
    ResourceResponse,
)
from app.services.catalog import get_checklist_template
from app.services.imscc import build_resources_from_extracted
from app.services.storage import (
    get_extracted_dir,
    get_job_dir,
    get_job_log_path,
    get_reports_dir,
    get_upload_path,
)

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
        path = parsed_resource.extracted_path or (None if is_external else href)
        inventory.append(
            {
                "id": parsed_resource.resource_id,
                "title": parsed_resource.title,
                "type": RESOURCE_TYPE_TO_REVIEW_TYPE.get(parsed_resource.resource_type, "OTHER"),
                "origin": parsed_resource.origin,
                "url": href if is_external else None,
                "path": path,
                "course_path": _derive_course_path(path or href),
                "status": RESOURCE_STATUS_TO_REVIEW_STATUS.get(parsed_resource.status, "WARN"),
                "notes": None,
            }
        )
    return inventory


def _write_review_inventory(settings: Settings, job_id: str, resources) -> None:
    inventory_path = get_job_dir(settings, job_id) / "resources.json"
    inventory_path.parent.mkdir(parents=True, exist_ok=True)
    inventory_path.write_text(
        json.dumps(_build_review_inventory(resources), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def create_job_record(
    session: Session,
    settings: Settings,
    *,
    job_id: str,
    original_filename: str,
    stored_filename: str,
    size_bytes: int,
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
        total_steps=4,
        message="Analisis en cola.",
    )
    session.add(job)
    record_job_event(
        session,
        settings,
        job_id=job_id,
        event="created",
        message="Job creado y pendiente de procesamiento.",
        progress=0,
        details={"filename": original_filename, "sizeBytes": size_bytes},
    )
    session.commit()
    return JobCreatedResponse(jobId=job_id)


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
            resources = build_resources_from_extracted(extracted_dir)
            if not resources:
                raise AppError(
                    code="no_resources_found",
                    message="No se han encontrado recursos procesables dentro del paquete.",
                    job_id=job_id,
                )
            _write_review_inventory(settings, job_id, resources)

            for parsed_resource in resources:
                resource_record = ResourceRecord(
                    id=parsed_resource.resource_id,
                    job_id=job_id,
                    title=parsed_resource.title,
                    type=parsed_resource.resource_type,
                    origin=parsed_resource.origin,
                    status=parsed_resource.status,
                    href=parsed_resource.href,
                    extracted_path=parsed_resource.extracted_path,
                )
                session.add(resource_record)
                for item in get_checklist_template(resource_record.type):
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
                details={"resourceCount": len(resources)},
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
