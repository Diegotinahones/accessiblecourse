from __future__ import annotations

from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import urlparse

from app.services.url_check import URLCheckService, UrlCheckResult

ACCESS_STATUS_OK = "OK"
ACCESS_STATUS_NO_ACCEDE = "NO_ACCEDE"
ACCESS_STATUS_REQUIRES_INTERACTION = "REQUIERE_INTERACCION"
ACCESS_STATUS_REQUIRES_SSO = "REQUIERE_SSO"
ACCESS_STATUS_VALUES = (
    ACCESS_STATUS_OK,
    ACCESS_STATUS_NO_ACCEDE,
    ACCESS_STATUS_REQUIRES_INTERACTION,
    ACCESS_STATUS_REQUIRES_SSO,
)

DOWNLOADABLE_EXTENSIONS = {
    ".pdf",
    ".doc",
    ".docx",
    ".ppt",
    ".pptx",
    ".xls",
    ".xlsx",
    ".csv",
    ".zip",
    ".txt",
    ".rtf",
    ".md",
    ".ipynb",
    ".mp4",
    ".webm",
    ".mov",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".svg",
}

DOWNLOADABLE_CONTENT_PREFIXES = (
    "application/",
    "audio/",
    "image/",
    "video/",
)


def build_access_status_counts() -> dict[str, int]:
    return {status: 0 for status in ACCESS_STATUS_VALUES}


def verify_offline_resource_access(
    resources: list[dict[str, Any]],
    *,
    extracted_dir: Path,
    url_checker: URLCheckService,
) -> dict[str, Any]:
    url_results = url_checker.check(resources)
    summary = {
        "total": 0,
        "accessible": 0,
        "downloadable": 0,
        "byStatus": build_access_status_counts(),
    }

    for resource in resources:
        source_url = _resource_source_url(resource)
        if source_url:
            access_payload = _external_access_payload(resource, url_results.get(str(resource.get("id"))))
        else:
            access_payload = _internal_access_payload(resource, extracted_dir)

        _merge_access_payload(resource, access_payload)

        summary["total"] += 1
        summary["accessible"] += int(access_payload["canAccess"])
        summary["downloadable"] += int(access_payload["canDownload"])
        summary["byStatus"][str(access_payload["accessStatus"])] += 1

    return summary


def _resource_source_url(resource: dict[str, Any]) -> str | None:
    for key in ("sourceUrl", "url"):
        value = resource.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _resource_file_path(resource: dict[str, Any]) -> str | None:
    for key in ("filePath", "localPath", "path"):
        value = resource.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _internal_access_payload(resource: dict[str, Any], extracted_dir: Path) -> dict[str, Any]:
    relative_path = _resource_file_path(resource)
    resolved_path = _resolve_internal_path(extracted_dir, relative_path)
    if relative_path is None:
        return _build_access_payload(
            can_access=False,
            access_status=ACCESS_STATUS_NO_ACCEDE,
            http_status=None,
            can_download=False,
            reason_code="UNKNOWN",
            reason_detail="El recurso no tiene un fichero asociado dentro del paquete.",
            error_message="El recurso no tiene un fichero asociado dentro del paquete.",
        )
    if resolved_path is None:
        return _build_access_payload(
            can_access=False,
            access_status=ACCESS_STATUS_NO_ACCEDE,
            http_status=None,
            can_download=False,
            reason_code="UNKNOWN",
            reason_detail="La ruta del recurso no es válida dentro del paquete extraído.",
            error_message="La ruta del recurso no es válida dentro del paquete extraído.",
        )
    if not resolved_path.exists() or not resolved_path.is_file():
        return _build_access_payload(
            can_access=False,
            access_status=ACCESS_STATUS_NO_ACCEDE,
            http_status=None,
            can_download=False,
            reason_code="NOT_FOUND",
            reason_detail="No se ha encontrado el fichero extraído para este recurso.",
            error_message="No se ha encontrado el fichero extraído para este recurso.",
        )
    return _build_access_payload(
        can_access=True,
        access_status=ACCESS_STATUS_OK,
        http_status=200,
        can_download=not _is_html_reference(relative_path),
        reason_code="OK",
        reason_detail="Recurso incluido dentro del paquete.",
        error_message=None,
    )


def _external_access_payload(resource: dict[str, Any], result: UrlCheckResult | None) -> dict[str, Any]:
    if result is None:
        return _build_access_payload(
            can_access=False,
            access_status=ACCESS_STATUS_NO_ACCEDE,
            http_status=None,
            can_download=False,
            reason_code="UNKNOWN",
            reason_detail="No se ha podido verificar la URL externa.",
            error_message="No se ha podido verificar la URL externa.",
        )

    checked_at = result.checked_at.isoformat() if result.checked_at else None

    reason_code = getattr(result, "reason_code", None) or _reason_code_from_legacy_result(result)

    if reason_code == "TIMEOUT":
        return _build_access_payload(
            can_access=False,
            access_status=ACCESS_STATUS_NO_ACCEDE,
            http_status=result.status_code,
            can_download=False,
            reason_code=reason_code,
            reason_detail=getattr(result, "reason_detail", None),
            error_message=result.error_message or "La URL ha excedido el tiempo de espera.",
            url_status=result.url_status,
            final_url=result.final_url,
            checked_at=checked_at,
        )

    if reason_code == "NOT_FOUND":
        return _build_access_payload(
            can_access=False,
            access_status=ACCESS_STATUS_NO_ACCEDE,
            http_status=result.status_code,
            can_download=False,
            reason_code=reason_code,
            reason_detail=getattr(result, "reason_detail", None),
            error_message=result.error_message or "La URL devolvió 404.",
            url_status=result.url_status,
            final_url=result.final_url,
            checked_at=checked_at,
        )

    if reason_code in {"AUTH_REQUIRED", "FORBIDDEN"}:
        return _build_access_payload(
            can_access=False,
            access_status=ACCESS_STATUS_NO_ACCEDE,
            http_status=result.status_code,
            can_download=False,
            reason_code=reason_code,
            reason_detail=getattr(result, "reason_detail", None),
            error_message=result.error_message or "La URL no permite acceso directo.",
            url_status=result.url_status,
            final_url=result.final_url,
            checked_at=checked_at,
        )

    if result.broken_link or not result.checked:
        return _build_access_payload(
            can_access=False,
            access_status=ACCESS_STATUS_NO_ACCEDE,
            http_status=result.status_code,
            can_download=False,
            reason_code=reason_code,
            reason_detail=getattr(result, "reason_detail", None),
            error_message=result.error_message or "No se ha podido acceder a la URL.",
            url_status=result.url_status,
            final_url=result.final_url,
            checked_at=checked_at,
        )

    final_reference = result.final_url or _resource_source_url(resource)
    return _build_access_payload(
        can_access=True,
        access_status=ACCESS_STATUS_OK,
        http_status=result.status_code,
        can_download=bool(getattr(result, "downloadable_guess", False)) or _looks_downloadable_url(
            final_reference=final_reference,
            content_type=result.content_type,
            content_disposition=result.content_disposition,
        ),
        reason_code="OK",
        reason_detail=getattr(result, "reason_detail", None),
        error_message=None,
        url_status=result.url_status,
        final_url=result.final_url,
        checked_at=checked_at,
    )


def _build_access_payload(
    *,
    can_access: bool,
    access_status: str,
    http_status: int | None,
    can_download: bool,
    reason_code: str,
    reason_detail: str | None,
    error_message: str | None,
    url_status: str | None = None,
    final_url: str | None = None,
    checked_at: str | None = None,
) -> dict[str, Any]:
    return {
        "canAccess": can_access,
        "accessStatus": access_status,
        "httpStatus": http_status,
        "reasonCode": reason_code,
        "reasonDetail": reason_detail,
        "canDownload": can_download,
        "errorMessage": error_message,
        "urlStatus": url_status,
        "finalUrl": final_url,
        "checkedAt": checked_at,
    }


def _merge_access_payload(resource: dict[str, Any], access_payload: dict[str, Any]) -> None:
    resource["canAccess"] = access_payload["canAccess"]
    resource["can_access"] = access_payload["canAccess"]
    resource["accessStatus"] = access_payload["accessStatus"]
    resource["access_status"] = access_payload["accessStatus"]
    resource["httpStatus"] = access_payload["httpStatus"]
    resource["http_status"] = access_payload["httpStatus"]
    resource["accessStatusCode"] = access_payload["httpStatus"]
    resource["access_status_code"] = access_payload["httpStatus"]
    resource["reasonCode"] = access_payload["reasonCode"]
    resource["reason_code"] = access_payload["reasonCode"]
    resource["reasonDetail"] = access_payload["reasonDetail"]
    resource["reason_detail"] = access_payload["reasonDetail"]
    resource["canDownload"] = access_payload["canDownload"]
    resource["can_download"] = access_payload["canDownload"]
    resource["downloadStatus"] = "OK" if access_payload["canDownload"] else "NO_DESCARGABLE"
    resource["download_status"] = resource["downloadStatus"]
    resource["downloadStatusCode"] = access_payload["httpStatus"] if access_payload["canDownload"] else None
    resource["download_status_code"] = resource["downloadStatusCode"]
    resource["errorMessage"] = access_payload["errorMessage"]
    resource["error_message"] = access_payload["errorMessage"]
    resource["accessNote"] = access_payload["errorMessage"]
    resource["access_note"] = access_payload["errorMessage"]

    if access_payload.get("urlStatus") is not None:
        resource["urlStatus"] = access_payload["urlStatus"]
    if access_payload.get("finalUrl") is not None:
        resource["finalUrl"] = access_payload["finalUrl"]
    if access_payload.get("checkedAt") is not None:
        resource["checkedAt"] = access_payload["checkedAt"]

    details = dict(resource.get("details") or {})
    details["accessCheck"] = {
        "canAccess": access_payload["canAccess"],
        "accessStatus": access_payload["accessStatus"],
        "reasonCode": access_payload["reasonCode"],
        "reasonDetail": access_payload["reasonDetail"],
        "httpStatus": access_payload["httpStatus"],
        "canDownload": access_payload["canDownload"],
        "errorMessage": access_payload["errorMessage"],
    }
    if access_payload.get("finalUrl") is not None:
        details["accessCheck"]["finalUrl"] = access_payload["finalUrl"]
    if access_payload.get("checkedAt") is not None:
        details["accessCheck"]["checkedAt"] = access_payload["checkedAt"]
    resource["details"] = details

    if access_payload["accessStatus"] == ACCESS_STATUS_NO_ACCEDE:
        resource["status"] = "ERROR"
        note = _broken_link_note(access_payload)
        if note:
            _append_note(resource, note)


def _resolve_internal_path(extracted_dir: Path, relative_path: str | None) -> Path | None:
    if not relative_path:
        return None
    normalized = relative_path.split("#", 1)[0].split("?", 1)[0].strip().replace("\\", "/")
    if not normalized:
        return None
    pure_path = PurePosixPath(normalized)
    if pure_path.is_absolute() or any(part == ".." for part in pure_path.parts):
        return None
    root = extracted_dir.resolve()
    candidate = (root / Path(*pure_path.parts)).resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        return None
    return candidate


def _looks_downloadable_url(
    *,
    final_reference: str | None,
    content_type: str | None,
    content_disposition: str | None,
) -> bool:
    if content_disposition and "attachment" in content_disposition.lower():
        return True

    if final_reference:
        suffix = Path(urlparse(final_reference).path).suffix.lower()
        if suffix in DOWNLOADABLE_EXTENSIONS:
            return True

    normalized_content_type = (content_type or "").split(";", 1)[0].strip().lower()
    if normalized_content_type.startswith("text/html"):
        return False
    return normalized_content_type.startswith(DOWNLOADABLE_CONTENT_PREFIXES)


def _is_html_reference(reference: str | None) -> bool:
    if not reference:
        return False
    return Path(urlparse(reference).path or reference).suffix.lower() in {".html", ".htm", ".xhtml"}


def _reason_code_from_legacy_result(result: UrlCheckResult) -> str:
    if result.reason == "404_not_found" or result.status_code == 404:
        return "NOT_FOUND"
    if result.reason in {"auth_required", "canvas_auth_required"} or result.status_code == 401:
        return "AUTH_REQUIRED"
    if result.reason == "forbidden" or result.status_code == 403:
        return "FORBIDDEN"
    if result.reason == "timeout":
        return "TIMEOUT"
    if result.broken_link or not result.checked:
        return "UNKNOWN"
    return "OK"


def _broken_link_note(access_payload: dict[str, Any]) -> str | None:
    access_status = str(access_payload["accessStatus"])
    http_status = access_payload.get("httpStatus")
    if access_status == ACCESS_STATUS_NO_ACCEDE:
        error_message = access_payload.get("errorMessage")
        if isinstance(error_message, str) and error_message.strip():
            return f"broken_link: {error_message.strip()}"
        if isinstance(http_status, int):
            return f"broken_link: URL devuelve {http_status}."
        return "broken_link: no se pudo acceder a la URL."
    return None


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
        if not cleaned:
            resource["notes"] = [note]
        elif note not in cleaned:
            resource["notes"] = [cleaned, note]
