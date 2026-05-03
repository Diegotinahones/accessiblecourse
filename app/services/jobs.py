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
from app.models.entities import (
    ChecklistResponse,
    Job as ReviewJob,
    Resource as ReviewResource,
    ReviewSession,
    ReviewSummary,
)
from app.schemas import (
    ChecklistDecision,
    ChecklistStateResponse,
    ChecklistUpdateRequest,
    JobCreatedResponse,
    JobLifecycleStatus,
    JobPhase,
    JobStatusResponse,
    ResourceResponse,
)
from app.services.access_analysis import OfflineAccessAdapter, OnlineAccessAdapter, analyze_access
from app.services.canvas_client import CanvasClient, CanvasCredentials, OnlineJobContextStore
from app.services.canvas_inventory import build_canvas_inventory
from app.services.catalog import get_checklist_template
from app.services.course_structure import build_fallback_course_structure
from app.services.imscc import build_resources_from_extracted
from app.services.imscc_parser import IMSCCParser, ParserError
from app.services.review_service import sync_job_inventory_from_payload
from app.services.storage import (
    get_extracted_dir,
    get_job_dir,
    get_job_log_path,
    get_reports_dir,
    get_upload_path,
)
from app.services.url_check import URLCheckService

logger = logging.getLogger("accessiblecourse.jobs")
DEFAULT_GENERIC_MODULE_TITLE = "Módulo general"

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


SENSITIVE_DETAIL_KEYS = {"authorization", "password", "secret", "token", "api_key", "apikey"}


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
    safe_details = _redact_log_details(details or {})
    session.add(
        JobEvent(
            job_id=job_id,
            event=event,
            message=message,
            progress=progress,
            details=safe_details,
        )
    )
    append_job_log(get_job_log_path(settings, job_id), event=event, message=message, details=safe_details)
    with job_logging_context(job_id):
        logger.log(level, message, extra={"event": event, "job_id": job_id, "details": safe_details})


def serialize_job(job: Job) -> JobStatusResponse:
    return JobStatusResponse(
        jobId=job.id,
        status=JobLifecycleStatus(job.status),
        phase=_coerce_job_phase(job.phase),
        progress=job.progress,
        message=job.message,
        currentStep=job.current_step,
        totalSteps=job.total_steps,
        errorCode=job.error_code,
    )


def _coerce_job_phase(value: str | None) -> JobPhase:
    if value in {phase.value for phase in JobPhase}:
        return JobPhase(str(value))
    return JobPhase.ERROR


def _redact_log_details(value: Any) -> Any:
    if isinstance(value, dict):
        redacted: dict[str, Any] = {}
        for key, item in value.items():
            normalized_key = str(key).replace("-", "_").lower()
            if any(secret_key in normalized_key for secret_key in SENSITIVE_DETAIL_KEYS):
                redacted[str(key)] = "[redacted]"
            else:
                redacted[str(key)] = _redact_log_details(item)
        return redacted
    if isinstance(value, list):
        return [_redact_log_details(item) for item in value]
    return value


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


def _normalized_excluded_extensions(settings: Settings) -> set[str]:
    return {extension.lower() for extension in settings.offline_excluded_extensions}


def _build_review_inventory(
    resources,
    *,
    excluded_extensions: set[str],
) -> list[dict[str, str | None]]:
    inventory: list[dict[str, str | None]] = []
    for parsed_resource in resources:
        href = parsed_resource.href or parsed_resource.extracted_path
        is_external = bool(href and href.startswith(("http://", "https://")))
        file_path = parsed_resource.extracted_path or (None if is_external else href)
        source_url = href if is_external else None
        if _should_skip_metadata_resource(
            file_path=file_path,
            source_url=source_url,
            excluded_extensions=excluded_extensions,
        ):
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


def _persist_analyzed_inventory(
    session: Session,
    settings: Settings,
    *,
    job_id: str,
    inventory: list[dict[str, Any]],
    course_structure: dict[str, Any] | None,
) -> None:
    _write_review_inventory_payload(settings, job_id, inventory)
    _write_course_structure_payload(settings, job_id, course_structure)
    job = session.get(Job, job_id)
    if job is not None:
        job.course_structure = course_structure
        job.updated_at = utcnow()
        session.add(job)
    _persist_legacy_inventory(session, job_id, inventory)
    sync_job_inventory_from_payload(session, job_id, inventory)


def _write_course_structure_payload(settings: Settings, job_id: str, structure: dict[str, Any] | None) -> None:
    structure_path = get_job_dir(settings, job_id) / "course_structure.json"
    if structure is None:
        structure_path.unlink(missing_ok=True)
        return

    structure_path.parent.mkdir(parents=True, exist_ok=True)
    structure_path.write_text(
        json.dumps(structure, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _load_course_structure_payload(settings: Settings, job_id: str) -> dict[str, Any] | None:
    structure_path = get_job_dir(settings, job_id) / "course_structure.json"
    if not structure_path.exists():
        return None
    payload = json.loads(structure_path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else None


def _write_review_inventory(
    settings: Settings,
    job_id: str,
    resources,
    *,
    excluded_extensions: set[str],
) -> None:
    _write_review_inventory_payload(
        settings,
        job_id,
        _build_review_inventory(resources, excluded_extensions=excluded_extensions),
    )


def build_url_checker(settings: Settings) -> URLCheckService:
    return URLCheckService(
        timeout_seconds=settings.url_check_timeout_seconds,
        max_urls=settings.url_check_max_urls,
    )


def _should_skip_metadata_resource(
    *,
    file_path: str | None,
    source_url: str | None,
    excluded_extensions: set[str],
) -> bool:
    if source_url:
        return False
    if not file_path:
        return False
    normalized_name = Path(file_path.split("#", 1)[0].split("?", 1)[0]).name.lower()
    if normalized_name == "imsmanifest.xml":
        return True
    return Path(normalized_name).suffix.lower() in excluded_extensions


def _normalize_origin(origin: str | None, *, source_url: str | None) -> str:
    normalized = (origin or "").strip().lower()
    if normalized in {"external", "externo"} or source_url:
        return "externo"
    return "interno"


def _normalize_offline_inventory(
    inventory: list[dict[str, Any]],
    *,
    preserve_unmapped_paths: bool = False,
    excluded_extensions: set[str],
) -> list[dict[str, Any]]:
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

        if _should_skip_metadata_resource(
            file_path=file_path,
            source_url=source_url,
            excluded_extensions=excluded_extensions,
        ):
            continue

        module_path = resource.get("modulePath") or resource.get("module_path") or resource.get("coursePath")
        if not isinstance(module_path, str) or not module_path.strip():
            module_path = None if preserve_unmapped_paths else _derive_course_path(file_path or source_url)
        else:
            module_path = module_path.strip()

        title = str(resource.get("title") or "Recurso sin titulo")
        item_path = resource.get("itemPath") or resource.get("item_path")
        if isinstance(item_path, str):
            item_path = item_path.strip() or None
        else:
            item_path = None
        if not item_path and module_path:
            item_path = f"{module_path} > {title}"

        module_title = resource.get("moduleTitle") or resource.get("module_title")
        if isinstance(module_title, str):
            module_title = module_title.strip() or None
        else:
            module_title = None
        if not module_title and module_path:
            module_title = module_path.split(">", 1)[0].strip()

        section_title = resource.get("sectionTitle") or resource.get("section_title")
        if isinstance(section_title, str):
            section_title = section_title.strip() or None
        else:
            section_title = None
        if not section_title:
            if item_path and ">" in item_path:
                section_title = item_path.rsplit(">", 2)[-2].strip()
            else:
                section_title = module_path.rsplit(">", 1)[-1].strip() if module_path else title

        downloadable = resource.get("downloadable")
        if not isinstance(downloadable, bool):
            downloadable = bool(
                not source_url
                and file_path
                and Path(file_path).suffix.lower() not in {".html", ".htm", ".xhtml"}
            )

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
        normalized["item_path"] = item_path
        normalized["itemPath"] = item_path
        normalized["module_title"] = module_title
        normalized["moduleTitle"] = module_title
        normalized["section_title"] = section_title
        normalized["sectionTitle"] = section_title
        normalized["downloadable"] = downloadable
        normalized.setdefault("details", {})
        normalized_resources.append(normalized)

    return normalized_resources


def _assign_generic_module_paths(resources: list[dict[str, Any]], module_title: str = DEFAULT_GENERIC_MODULE_TITLE) -> None:
    for resource in resources:
        title = str(resource.get("title") or "Recurso")
        if not isinstance(resource.get("modulePath"), str) or not str(resource.get("modulePath")).strip():
            resource["modulePath"] = module_title
            resource["module_path"] = module_title
        if not isinstance(resource.get("coursePath"), str) or not str(resource.get("coursePath")).strip():
            resource["coursePath"] = module_title
            resource["course_path"] = module_title
        if not isinstance(resource.get("itemPath"), str) or not str(resource.get("itemPath")).strip():
            resource["itemPath"] = f"{module_title} > {title}"
            resource["item_path"] = f"{module_title} > {title}"
        if not isinstance(resource.get("moduleTitle"), str) or not str(resource.get("moduleTitle")).strip():
            resource["moduleTitle"] = module_title
            resource["module_title"] = module_title
        if not isinstance(resource.get("sectionTitle"), str) or not str(resource.get("sectionTitle")).strip():
            resource["sectionTitle"] = module_title
            resource["section_title"] = module_title


def _build_manifest_review_inventory(
    extracted_dir: Path,
    settings: Settings,
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    parser = IMSCCParser()
    manifest_path = parser.find_manifest(extracted_dir)
    parsed_manifest = parser.parse_manifest(manifest_path, extracted_dir)
    excluded_extensions = _normalized_excluded_extensions(settings)
    inventory = parser.build_resource_inventory(
        parsed_manifest,
        manifest_path,
        extracted_dir,
        excluded_extensions=excluded_extensions,
    )
    discovered_inventory = parser.discover_html_linked_resources(
        inventory,
        extracted_dir,
        excluded_extensions=excluded_extensions,
    )
    inventory = _merge_discovered_inventory(inventory, discovered_inventory)
    normalized_inventory = _normalize_offline_inventory(
        inventory,
        preserve_unmapped_paths=True,
        excluded_extensions=excluded_extensions,
    )
    visible_resource_ids = {
        str(resource.get("id"))
        for resource in normalized_inventory
        if isinstance(resource.get("id"), str) and resource.get("id")
    }
    course_structure = {
        **parsed_manifest.structure,
        "unplacedResourceIds": [
            resource.identifier
            for resource in parsed_manifest.resources
            if resource.identifier
            and resource.identifier in visible_resource_ids
            and resource.identifier not in parsed_manifest.item_map
        ],
    }
    return (
        normalized_inventory,
        course_structure,
    )


def _merge_discovered_inventory(
    inventory: list[dict[str, Any]],
    discovered_inventory: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    discovered_by_parent: dict[str, list[dict[str, Any]]] = {}
    unparented: list[dict[str, Any]] = []

    for resource in discovered_inventory:
        details = resource.get("details")
        html_discovery = details.get("htmlDiscovery") if isinstance(details, dict) else None
        parent_id = html_discovery.get("parentResourceId") if isinstance(html_discovery, dict) else None
        if isinstance(parent_id, str) and parent_id:
            discovered_by_parent.setdefault(parent_id, []).append(resource)
        else:
            unparented.append(resource)

    merged: list[dict[str, Any]] = []
    for resource in inventory:
        merged.append(resource)
        resource_id = resource.get("id")
        if isinstance(resource_id, str) and resource_id in discovered_by_parent:
            merged.extend(discovered_by_parent.pop(resource_id))

    for remaining in discovered_by_parent.values():
        unparented.extend(remaining)

    merged.extend(unparented)
    return merged


def _build_offline_review_inventory(
    extracted_dir: Path,
    settings: Settings,
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    try:
        manifest_inventory, course_structure = _build_manifest_review_inventory(extracted_dir, settings)
        if manifest_inventory:
            return manifest_inventory, course_structure
    except ParserError:
        logger.info(
            "manifest_inventory_fallback",
            extra={"event": "manifest_inventory_fallback", "details": {"reason": "parser_error"}},
        )

    excluded_extensions = _normalized_excluded_extensions(settings)
    fallback_inventory = _build_review_inventory(
        build_resources_from_extracted(extracted_dir),
        excluded_extensions=excluded_extensions,
    )
    fallback_discovered = IMSCCParser().discover_html_linked_resources(
        fallback_inventory,
        extracted_dir,
        excluded_extensions=excluded_extensions,
    )
    fallback_inventory = _normalize_offline_inventory(
        _merge_discovered_inventory(fallback_inventory, fallback_discovered),
        preserve_unmapped_paths=True,
        excluded_extensions=excluded_extensions,
    )
    _assign_generic_module_paths(fallback_inventory)
    return fallback_inventory, build_fallback_course_structure(fallback_inventory)


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
    total_steps: int = 5,
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
        phase=JobPhase.UPLOAD.value,
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
    phase: JobPhase | None = None,
    error_code: str | None = None,
    error_message: str | None = None,
) -> None:
    job.status = status.value
    if phase is not None:
        job.phase = phase.value
    elif status == JobLifecycleStatus.DONE:
        job.phase = JobPhase.DONE.value
    elif status == JobLifecycleStatus.ERROR:
        job.phase = JobPhase.ERROR.value
    job.progress = progress
    job.current_step = current_step
    job.message = message
    job.error_code = error_code
    job.error_message = error_message
    job.updated_at = utcnow()
    if status in {JobLifecycleStatus.DONE, JobLifecycleStatus.ERROR}:
        job.finished_at = utcnow()
    else:
        job.finished_at = None
    session.add(job)


def _reset_job_related_data(session: Session, settings: Settings, job_id: str) -> None:
    session.exec(delete(ChecklistEntry).where(ChecklistEntry.job_id == job_id))
    session.exec(delete(ResourceRecord).where(ResourceRecord.job_id == job_id))
    session.exec(delete(ChecklistResponse).where(ChecklistResponse.job_id == job_id))
    session.exec(delete(ReviewResource).where(ReviewResource.job_id == job_id))
    session.exec(delete(ReviewSummary).where(ReviewSummary.job_id == job_id))
    session.exec(delete(ReviewSession).where(ReviewSession.job_id == job_id))
    existing_report = session.exec(select(ReportRecord).where(ReportRecord.job_id == job_id)).first()
    if existing_report:
        Path(existing_report.pdf_path).unlink(missing_ok=True)
        Path(existing_report.docx_path).unlink(missing_ok=True)
        session.delete(existing_report)

    (get_job_dir(settings, job_id) / "resources.json").unlink(missing_ok=True)
    (get_job_dir(settings, job_id) / "course_structure.json").unlink(missing_ok=True)
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
    phase: JobPhase | None = None,
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
        phase=phase,
    )
    event_details = dict(details or {})
    event_details.setdefault("phase", job.phase)
    record_job_event(
        session,
        settings,
        job_id=job.id,
        event=event,
        message=message,
        progress=progress,
        details=event_details,
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
                phase=JobPhase.UPLOAD,
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
                phase=JobPhase.INVENTORY,
                progress=30,
                current_step=2,
                message="Extrayendo recursos del curso.",
            )
            record_job_event(
                session,
                settings,
                job_id=job_id,
                event="progress",
                message="Extrayendo el paquete de curso.",
                progress=30,
            )
            session.commit()

            from app.services.storage import extract_archive

            extract_archive(source=upload_path, destination=extracted_dir, settings=settings)

            _update_job(
                session,
                job,
                status=JobLifecycleStatus.PROCESSING,
                phase=JobPhase.INVENTORY,
                progress=55,
                current_step=3,
                message="Reconstruyendo estructura e inventario.",
            )
            record_job_event(
                session,
                settings,
                job_id=job_id,
                event="progress",
                message="Catalogando recursos y estructura del curso.",
                progress=55,
            )
            session.commit()

            session.exec(delete(ChecklistEntry).where(ChecklistEntry.job_id == job_id))
            session.exec(delete(ResourceRecord).where(ResourceRecord.job_id == job_id))
            inventory, course_structure = _build_offline_review_inventory(extracted_dir, settings)
            if not inventory:
                raise AppError(
                    code="no_resources_found",
                    message="No se han encontrado recursos procesables dentro del paquete.",
                    job_id=job_id,
                )

            _update_job_progress(
                session,
                settings,
                job,
                current_step=4,
                progress=80,
                message="Ejecutando Access + Deep Scan.",
                phase=JobPhase.ACCESS_SCAN,
            )
            access_analysis = analyze_access(
                job_id=job_id,
                resources=inventory,
                adapter=OfflineAccessAdapter(
                    settings=settings,
                    job_id=job_id,
                    url_checker=build_url_checker(settings),
                ),
                progress=95,
            )
            inventory = access_analysis.resources
            access_summary = access_analysis.summary

            _update_job_progress(
                session,
                settings,
                job,
                current_step=5,
                progress=95,
                message="Guardando inventario analizado.",
                phase=JobPhase.ACCESS_SCAN,
                details=access_summary,
            )

            _persist_analyzed_inventory(
                session,
                settings,
                job_id=job_id,
                inventory=inventory,
                course_structure=course_structure,
            )

            _update_job(
                session,
                job,
                status=JobLifecycleStatus.DONE,
                phase=JobPhase.DONE,
                progress=100,
                current_step=5,
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
                    "accessibleCount": access_summary["accessible"],
                    "downloadableCount": access_summary["downloadable"],
                    "discoveredCount": access_analysis.discovered_count,
                    "byStatus": access_summary["byStatus"],
                },
            )
            session.commit()
        except AppError as exc:
            session.rollback()
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
            session.rollback()
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
        context = job_contexts.get(job_id)
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
                phase=JobPhase.UPLOAD,
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
                phase=JobPhase.UPLOAD,
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
                phase=JobPhase.INVENTORY,
                details={"moduleCount": len(modules)},
            )

            inventory_build = build_canvas_inventory(
                client,
                course_id=course.id,
                modules=modules,
                url_checker=None,
                credentials=context.credentials,
                verify_access=False,
            )
            _update_job_progress(
                session,
                settings,
                job,
                current_step=4,
                progress=65,
                message=f"Inventario inicial construido: {inventory_build.items_read} items leidos.",
                phase=JobPhase.INVENTORY,
                details={"itemsRead": inventory_build.items_read, "resourceCount": len(inventory_build.resources)},
            )

            _update_job_progress(
                session,
                settings,
                job,
                current_step=5,
                progress=82,
                message="Ejecutando Access + Deep Scan.",
                phase=JobPhase.ACCESS_SCAN,
            )
            access_analysis = analyze_access(
                job_id=job_id,
                resources=inventory_build.resources,
                adapter=OnlineAccessAdapter(
                    client=client,
                    credentials=context.credentials,
                    course_id=course.id,
                    url_checker=url_checker,
                    max_depth=settings.canvas_crawl_depth if settings.online_deep_scan_enabled else 0,
                    max_pages=settings.online_deep_scan_max_pages,
                    max_discovered=settings.canvas_max_discovered,
                ),
                progress=95,
            )
            inventory = access_analysis.resources
            access_summary = access_analysis.summary

            _update_job_progress(
                session,
                settings,
                job,
                current_step=6,
                progress=95,
                message="Guardando inventario online analizado.",
                phase=JobPhase.ACCESS_SCAN,
                details=access_summary,
            )

            _persist_analyzed_inventory(
                session,
                settings,
                job_id=job_id,
                inventory=inventory,
                course_structure=build_fallback_course_structure(inventory, title=course.name),
            )

            _update_job(
                session,
                job,
                status=JobLifecycleStatus.DONE,
                phase=JobPhase.DONE,
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
                    "resourceCount": len(inventory),
                    "accessible": access_summary["accessible"],
                    "downloadable": access_summary["downloadable"],
                    "discoveredCount": access_analysis.discovered_count,
                    "byStatus": access_summary["byStatus"],
                },
            )
            session.commit()
        except AppError as exc:
            session.rollback()
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
            session.rollback()
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


def prepare_access_analysis_retry(session: Session, settings: Settings, job_id: str) -> JobStatusResponse:
    job = get_job_or_404(session, job_id)
    inventory_path = get_job_dir(settings, job_id) / "resources.json"
    if not inventory_path.exists():
        raise AppError(
            code="inventory_not_found",
            message="No hemos encontrado inventario previo para reanalizar el acceso.",
            status_code=404,
            job_id=job_id,
        )
    if job.status == JobLifecycleStatus.PROCESSING.value:
        raise AppError(
            code="job_processing",
            message="El analisis ya esta en curso.",
            status_code=409,
            job_id=job_id,
        )

    _update_job(
        session,
        job,
        status=JobLifecycleStatus.PROCESSING,
        phase=JobPhase.ACCESS_SCAN,
        progress=min(job.progress or 0, 80),
        current_step=min(max(job.current_step, 1), job.total_steps),
        message="Reanalisis de acceso en cola.",
        error_code=None,
        error_message=None,
    )
    record_job_event(
        session,
        settings,
        job_id=job_id,
        event="access_retry_queued",
        message="Reanalisis Access + Deep Scan en cola.",
        progress=job.progress,
    )
    session.commit()
    session.refresh(job)
    return serialize_job(job)


def rerun_access_analysis(
    engine,
    settings: Settings,
    job_contexts: OnlineJobContextStore,
    job_id: str,
    canvas_client_factory: Callable[[Any, Settings], CanvasClient],
    url_check_factory: Callable[[Settings], URLCheckService],
) -> None:
    with Session(engine) as session:
        job = get_job_or_404(session, job_id)
        try:
            inventory_path = get_job_dir(settings, job_id) / "resources.json"
            resources_payload = json.loads(inventory_path.read_text(encoding="utf-8"))
            if not isinstance(resources_payload, list):
                raise AppError(
                    code="invalid_inventory",
                    message="El inventario del curso no tiene un formato valido.",
                    status_code=409,
                    job_id=job_id,
                )

            _update_job_progress(
                session,
                settings,
                job,
                current_step=min(max(job.current_step, 1), job.total_steps),
                progress=82,
                message="Reejecutando Access + Deep Scan.",
                phase=JobPhase.ACCESS_SCAN,
                event="access_retry_started",
            )

            adapter = _build_retry_access_adapter(
                settings=settings,
                job_contexts=job_contexts,
                job_id=job_id,
                resources=resources_payload,
                canvas_client_factory=canvas_client_factory,
                url_check_factory=url_check_factory,
            )
            analysis = analyze_access(
                job_id=job_id,
                resources=resources_payload,
                adapter=adapter,
                progress=95,
                clean_discovered=True,
            )
            course_structure = _load_course_structure_payload(settings, job_id)
            if course_structure is None:
                course_structure = build_fallback_course_structure(analysis.resources, title=job.original_filename)

            _persist_analyzed_inventory(
                session,
                settings,
                job_id=job_id,
                inventory=analysis.resources,
                course_structure=course_structure,
            )
            _update_job(
                session,
                job,
                status=JobLifecycleStatus.DONE,
                phase=JobPhase.DONE,
                progress=100,
                current_step=job.total_steps,
                message="Reanalisis de acceso completado.",
            )
            record_job_event(
                session,
                settings,
                job_id=job_id,
                event="access_retry_finished",
                message="Access + Deep Scan recalculado correctamente.",
                progress=100,
                details={
                    "resourceCount": len(analysis.resources),
                    "accessible": analysis.summary["accessible"],
                    "downloadable": analysis.summary["downloadable"],
                    "discoveredCount": analysis.discovered_count,
                    "byStatus": analysis.summary["byStatus"],
                },
            )
            session.commit()
        except AppError as exc:
            session.rollback()
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
            record_job_event(
                session,
                settings,
                job_id=job_id,
                event="access_retry_error",
                message=exc.message,
                progress=job.progress,
                details=exc.details if isinstance(exc.details, dict) else {"details": exc.details},
                level=logging.ERROR,
            )
            session.commit()
        except Exception as exc:  # pragma: no cover
            session.rollback()
            _update_job(
                session,
                job,
                status=JobLifecycleStatus.ERROR,
                progress=job.progress or 0,
                current_step=min(job.current_step, job.total_steps),
                message="No hemos podido reanalizar el acceso del curso.",
                error_code="unexpected_access_retry_error",
                error_message=str(exc),
            )
            record_job_event(
                session,
                settings,
                job_id=job_id,
                event="access_retry_error",
                message="Error no controlado durante el reanalisis de acceso.",
                progress=job.progress,
                details={"exception": exc.__class__.__name__},
                level=logging.ERROR,
            )
            logger.exception("Unhandled access retry error", extra={"event": "access_retry_error", "job_id": job_id})
            session.commit()


def _build_retry_access_adapter(
    *,
    settings: Settings,
    job_contexts: OnlineJobContextStore,
    job_id: str,
    resources: list[dict[str, Any]],
    canvas_client_factory: Callable[[Any, Settings], CanvasClient],
    url_check_factory: Callable[[Settings], URLCheckService],
):
    context = job_contexts.get(job_id)
    if context is not None:
        return OnlineAccessAdapter(
            client=canvas_client_factory(context.credentials, settings),
            credentials=context.credentials,
            course_id=context.course_id,
            url_checker=url_check_factory(settings),
            max_depth=settings.canvas_crawl_depth if settings.online_deep_scan_enabled else 0,
            max_pages=settings.online_deep_scan_max_pages,
            max_discovered=settings.canvas_max_discovered,
        )

    course_id = _course_id_from_resources(resources)
    if course_id and settings.canvas_base_url and settings.canvas_token:
        credentials = CanvasCredentials.create(base_url=settings.canvas_base_url, token=settings.canvas_token)
        return OnlineAccessAdapter(
            client=canvas_client_factory(credentials, settings),
            credentials=credentials,
            course_id=course_id,
            url_checker=url_check_factory(settings),
            max_depth=settings.canvas_crawl_depth if settings.online_deep_scan_enabled else 0,
            max_pages=settings.online_deep_scan_max_pages,
            max_discovered=settings.canvas_max_discovered,
        )

    if get_extracted_dir(settings, job_id).exists():
        return OfflineAccessAdapter(settings=settings, job_id=job_id, url_checker=url_check_factory(settings))

    raise AppError(
        code="access_retry_not_available",
        message="No hay contexto suficiente para reanalizar este job.",
        status_code=409,
        job_id=job_id,
    )


def _course_id_from_resources(resources: list[dict[str, Any]]) -> str | None:
    for resource in resources:
        value = resource.get("courseId")
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


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
        phase=JobPhase.UPLOAD,
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
