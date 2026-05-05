from __future__ import annotations

import json
import mimetypes
import re
from pathlib import Path
from typing import Any, Literal
from urllib.parse import unquote, urlparse

from pydantic import BaseModel, ConfigDict

from app.core.config import Settings
from app.core.errors import AppError
from app.models.entities import Resource
from app.services.canvas_client import CanvasClient, CanvasCredentials
from app.services.storage import get_job_dir, resolve_job_resource_path

CoreResourceType = Literal["WEB", "PDF", "DOCX", "VIDEO", "IMAGE", "NOTEBOOK", "FILE", "OTHER"]
CoreResourceOrigin = Literal[
    "ONLINE_CANVAS",
    "OFFLINE_IMSCC",
    "INTERNAL_FILE",
    "INTERNAL_PAGE",
    "EXTERNAL_URL",
    "RALTI",
    "LTI",
]
CoreAccessStatus = Literal["OK", "NO_ACCEDE", "REQUIERE_SSO", "REQUIERE_INTERACCION", "NO_ANALIZABLE"]
CoreReasonCode = Literal[
    "OK",
    "NOT_FOUND",
    "AUTH_REQUIRED",
    "FORBIDDEN",
    "TIMEOUT",
    "DNS_ERROR",
    "SSL_ERROR",
    "NETWORK_ERROR",
    "INVALID_URL",
    "UNKNOWN",
]
CoreDownloadStatus = Literal["OK", "FAIL", "N_A"]
ContentKind = Literal["HTML", "TEXT", "PDF", "BINARY", "URL", "NOT_ANALYZABLE"]

RESOURCE_CORE_FIELDS = {
    "id",
    "title",
    "type",
    "origin",
    "modulePath",
    "sectionTitle",
    "parentId",
    "discovered",
    "accessStatus",
    "reasonCode",
    "reasonDetail",
    "httpStatus",
    "finalUrl",
    "downloadable",
    "downloadStatus",
    "htmlPath",
    "localPath",
    "sourceUrl",
    "contentAvailable",
}

VALID_RESOURCE_TYPES: set[str] = {"WEB", "PDF", "DOCX", "VIDEO", "IMAGE", "NOTEBOOK", "FILE", "OTHER"}
VALID_ACCESS_STATUSES: set[str] = {"OK", "NO_ACCEDE", "REQUIERE_SSO", "REQUIERE_INTERACCION", "NO_ANALIZABLE"}
VALID_REASON_CODES: set[str] = {
    "OK",
    "NOT_FOUND",
    "AUTH_REQUIRED",
    "FORBIDDEN",
    "TIMEOUT",
    "DNS_ERROR",
    "SSL_ERROR",
    "NETWORK_ERROR",
    "INVALID_URL",
    "UNKNOWN",
}
VALID_DOWNLOAD_STATUSES: set[str] = {"OK", "FAIL", "N_A"}

PAGE_CANVAS_TYPES = {"Page", "WikiPage"}
HTML_CANVAS_TYPES = PAGE_CANVAS_TYPES | {"Assignment", "Discussion"}
SSO_HOST_MARKERS = ("id-provider.uoc.edu", "ralti.uoc.edu", "login.uoc.edu", "sso.uoc.edu")
SSO_PATH_MARKERS = ("sso", "saml", "oauth", "login", "id-provider", "ralti")
PROTECTED_EXTERNAL_HOST_MARKERS = (
    "biblioteca.uoc.edu",
    "materials.campus.uoc.edu",
    "recursos.uoc.edu",
    "ebookcentral.proquest.com",
    "proquest.com",
    "elibro.net",
    "sciencedirect.com",
    "springer.com",
    "oreilly.com",
    "microsoft.com",
)
PROTECTED_EXTERNAL_REFERENCE_MARKERS = (
    "biblioteca",
    "library",
    "ebook",
    "e-book",
    "elibro",
    "libro",
    "book",
    "books",
    "software",
    "llicencia",
    "licencia",
    "license",
    "materials",
    "recursos",
    "learning-resources",
    "protected",
)
SSO_REASON_DETAIL = "Requiere autenticación externa o capa SSO no accesible mediante API Canvas."
INTERACTION_REASON_DETAIL = "Recurso interactivo o entrega que no se analiza como contenido descargable."
PATH_SEPARATOR_RE = re.compile(r"\s*(?:>|/)\s*")


class ResourceCore(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    title: str
    type: CoreResourceType
    origin: CoreResourceOrigin
    modulePath: list[str]
    sectionTitle: str | None = None
    parentId: str | None = None
    discovered: bool = False
    accessStatus: CoreAccessStatus
    reasonCode: CoreReasonCode
    reasonDetail: str | None = None
    httpStatus: int | None = None
    finalUrl: str | None = None
    downloadable: bool = False
    downloadStatus: CoreDownloadStatus = "N_A"
    htmlPath: str | None = None
    localPath: str | None = None
    sourceUrl: str | None = None
    contentAvailable: bool = False


class ResourceContentResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ok: bool
    resourceId: str
    title: str
    type: str
    origin: str | None = None
    contentKind: ContentKind
    textContent: str | None = None
    htmlContent: str | None = None
    binaryPath: str | None = None
    sourceUrl: str | None = None
    filename: str | None = None
    mimeType: str | None = None
    errorCode: str | None = None
    errorDetail: str | None = None

    @property
    def resource_id(self) -> str:
        return self.resourceId

    @property
    def content_type(self) -> str | None:
        return self.mimeType

    @property
    def text_content(self) -> str | None:
        return self.htmlContent if self.htmlContent is not None else self.textContent

    @property
    def binary_path(self) -> str | None:
        return self.binaryPath

    @property
    def url(self) -> str | None:
        return self.sourceUrl

    @property
    def error_code(self) -> str | None:
        return self.errorCode

    @property
    def error_detail(self) -> str | None:
        return self.errorDetail


def normalize_resource(resource: Any, inventory_item: Any | None = None) -> ResourceCore:
    source = _as_mapping(inventory_item) if inventory_item is not None else _as_mapping(resource)
    fallback = _as_mapping(resource)
    details = _details(source) or _details(fallback)
    canvas_type = _string(source, "canvasType") or _string(details, "canvasType")
    source_url = _string(source, "sourceUrl", "source_url", "url") or _string(fallback, "sourceUrl", "source_url", "url")
    final_url = _string(source, "finalUrl", "final_url") or _string(fallback, "finalUrl", "final_url")
    html_path = _string(source, "htmlPath", "html_path") or _string(fallback, "htmlPath", "html_path")
    content_type = (
        _string(source, "mimeType", "mime_type", "contentType", "content_type")
        or _string(details, "mimeType", "mime_type", "contentType", "content_type")
        or _string(fallback, "mimeType", "mime_type", "contentType", "content_type")
    )
    local_path = _string(source, "localPath", "filePath", "file_path", "path") or _string(
        fallback,
        "localPath",
        "filePath",
        "file_path",
        "path",
    )
    access_status = _normalize_access_status(source, fallback, source_url=source_url, final_url=final_url, canvas_type=canvas_type)
    origin = _normalize_origin(
        source,
        fallback,
        source_url=source_url,
        final_url=final_url,
        local_path=local_path,
        html_path=html_path,
        canvas_type=canvas_type,
    )
    if html_path is None and origin == "INTERNAL_PAGE":
        html_path = local_path
    downloadable = _bool(source, "downloadable", "canDownload", "can_download")
    if downloadable is None:
        downloadable = bool(_bool(fallback, "downloadable", "canDownload", "can_download"))
    if origin == "EXTERNAL_URL":
        downloadable = False
    explicit_content_available = _bool(source, "contentAvailable", "content_available")
    if explicit_content_available is None:
        explicit_content_available = _bool(fallback, "contentAvailable", "content_available")
    reason_detail = _normalize_reason_detail(source, fallback, access_status=access_status)

    return ResourceCore(
        id=_string(source, "id") or _string(fallback, "id") or "",
        title=_string(source, "title") or _string(fallback, "title") or "Recurso sin titulo",
        type=_normalize_resource_type(
            source,
            fallback,
            local_path=local_path,
            source_url=source_url,
            canvas_type=canvas_type,
            content_type=content_type,
        ),
        origin=origin,
        modulePath=_normalize_module_path(source, fallback),
        sectionTitle=_string(source, "sectionTitle", "section_title", "moduleTitle", "module_title")
        or _string(fallback, "sectionTitle", "section_title", "moduleTitle", "module_title"),
        parentId=_string(source, "parentId", "parentResourceId", "parent_resource_id")
        or _string(fallback, "parentId", "parentResourceId", "parent_resource_id"),
        discovered=bool(_bool(source, "discovered") or _bool(fallback, "discovered")),
        accessStatus=access_status,
        reasonCode=_normalize_reason_code(source, fallback, access_status=access_status),
        reasonDetail=reason_detail,
        httpStatus=_int(source, "httpStatus", "http_status", "accessStatusCode", "access_status_code")
        or _int(fallback, "httpStatus", "http_status", "accessStatusCode", "access_status_code"),
        finalUrl=final_url,
        downloadable=downloadable,
        downloadStatus=_normalize_download_status(source, fallback, downloadable=downloadable),
        htmlPath=html_path,
        localPath=local_path,
        sourceUrl=source_url,
        contentAvailable=explicit_content_available
        if explicit_content_available is not None
        else _content_available(
            access_status=access_status,
            downloadable=downloadable,
            local_path=local_path,
            html_path=html_path,
            source_url=source_url,
            canvas_type=canvas_type,
            resource_type=_normalize_resource_type(
                source,
                fallback,
                local_path=local_path,
                source_url=source_url,
                canvas_type=canvas_type,
                content_type=content_type,
            ),
        ),
    )


def normalize_resources(resources: list[Any]) -> list[ResourceCore]:
    return [normalize_resource(resource) for resource in resources]


def get_resource_content(
    job_id: str,
    resource_id: str,
    *,
    settings: Settings | None = None,
    resources: list[Any] | None = None,
    canvas_client: CanvasClient | Any | None = None,
    canvas_credentials: CanvasCredentials | None = None,
    course_id: str | None = None,
) -> ResourceContentResult:
    settings = settings or Settings()
    items = resources if resources is not None else _load_raw_inventory(settings, job_id)
    raw_resource = next((_as_mapping(item) for item in items if _string(item, "id") == resource_id), None)
    if raw_resource is None:
        return _content_error(resource_id, "NOT_FOUND", "No hemos encontrado el recurso en el inventario.")

    core = normalize_resource(raw_resource)
    details = _details(raw_resource)
    canvas_type = _string(raw_resource, "canvasType") or _string(details, "canvasType")
    resolved_course_id = (
        course_id
        or _string(raw_resource, "courseId", "course_id")
        or _string(details, "courseId", "course_id")
        or _course_id_from_url(core.sourceUrl or core.finalUrl)
    )

    if core.origin in {"RALTI", "LTI"} or core.accessStatus == "REQUIERE_SSO":
        return ResourceContentResult(
            ok=False,
            resourceId=resource_id,
            title=core.title,
            type=core.type,
            origin=core.origin,
            contentKind="NOT_ANALYZABLE",
            errorCode="REQUIERE_SSO",
            errorDetail=core.reasonDetail or "Este recurso requiere SSO o una sesion externa.",
        )

    if core.accessStatus == "REQUIERE_INTERACCION":
        return ResourceContentResult(
            ok=False,
            resourceId=resource_id,
            title=core.title,
            type=core.type,
            origin=core.origin,
            contentKind="NOT_ANALYZABLE",
            errorCode="REQUIERE_INTERACCION",
            errorDetail=core.reasonDetail or "Este recurso requiere interaccion manual antes de analizarse.",
        )

    if core.origin == "EXTERNAL_URL":
        if core.accessStatus != "OK":
            return _content_error(
                resource_id,
                core.reasonCode if core.reasonCode != "OK" else "NO_ANALIZABLE",
                core.reasonDetail or "La URL externa no esta accesible para analisis.",
                core=core,
            )
        return ResourceContentResult(
            ok=True,
            resourceId=resource_id,
            title=core.title,
            type=core.type,
            origin=core.origin,
            contentKind="URL",
            sourceUrl=core.sourceUrl or core.finalUrl,
            mimeType=None,
        )

    if core.origin in {"INTERNAL_FILE", "INTERNAL_PAGE", "OFFLINE_IMSCC"} and (core.htmlPath or core.localPath):
        return _read_local_resource(settings, job_id, core)

    if core.origin == "ONLINE_CANVAS":
        client = canvas_client or _build_canvas_client(settings, canvas_credentials)
        if client is None:
            return _content_error(
                resource_id,
                "AUTH_REQUIRED",
                "Falta configuracion de Canvas para obtener el contenido.",
                core=core,
            )
        if canvas_type == "File" or _string(raw_resource, "fileId", "file_id") or _string(details, "fileId", "file_id"):
            return _download_canvas_file(settings, job_id, raw_resource, core, client, resolved_course_id)
        if canvas_type in PAGE_CANVAS_TYPES:
            page_url = (
                _string(raw_resource, "pageId", "page_url", "pageUrl")
                or _string(details, "pageUrl", "page_url", "pageId")
                or _page_id_from_url(core.sourceUrl or core.finalUrl, resolved_course_id)
            )
            return _read_canvas_html(core, client.get_page, resolved_course_id, page_url, ("body",))
        if canvas_type == "Assignment":
            assignment_id = _string(raw_resource, "contentId", "content_id") or _string(details, "contentId", "content_id")
            return _read_canvas_html(core, client.get_assignment, resolved_course_id, assignment_id, ("description", "body"))
        if canvas_type == "Discussion":
            topic_id = _string(raw_resource, "contentId", "content_id") or _string(details, "contentId", "content_id")
            return _read_canvas_html(core, client.get_discussion_topic, resolved_course_id, topic_id, ("message", "description", "body"))
        if canvas_type == "Quiz":
            quiz_id = _string(raw_resource, "contentId", "content_id") or _string(details, "contentId", "content_id")
            return _read_canvas_html(core, client.get_quiz, resolved_course_id, quiz_id, ("description", "body"))

    return ResourceContentResult(
        ok=False,
        resourceId=resource_id,
        title=core.title,
        type=core.type,
        origin=core.origin,
        contentKind="NOT_ANALYZABLE",
        sourceUrl=(core.sourceUrl or core.finalUrl) if core.origin == "EXTERNAL_URL" else None,
        errorCode="NO_ANALIZABLE",
        errorDetail=core.reasonDetail or "Este tipo de recurso todavia no tiene extractor de contenido.",
    )


def _load_raw_inventory(settings: Settings, job_id: str | None) -> list[dict[str, Any]]:
    if job_id is None:
        return []
    inventory_path = get_job_dir(settings, job_id) / "resources.json"
    if not inventory_path.exists():
        return []
    payload = json.loads(inventory_path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        return []
    return [item for item in payload if isinstance(item, dict)]


def _read_local_resource(settings: Settings, job_id: str, core: ResourceCore) -> ResourceContentResult:
    relative_path = core.htmlPath if core.origin == "INTERNAL_PAGE" else core.localPath or core.htmlPath
    if not relative_path:
        return _content_error(core.id, "NOT_FOUND", "El recurso no tiene ruta local.", core=core)
    try:
        resolved_path = resolve_job_resource_path(settings, job_id, relative_path)
    except AppError as exc:
        return _content_error(core.id, "INVALID_URL", exc.message, core=core)
    if not resolved_path.exists() or not resolved_path.is_file():
        return _content_error(core.id, "NOT_FOUND", "No existe el fichero local asociado al recurso.", core=core)

    content_type = _guess_content_type(resolved_path)
    content_kind = _content_kind_for_file(resolved_path, content_type, core.type)
    if content_kind in {"HTML", "TEXT"}:
        try:
            content = resolved_path.read_text(encoding="utf-8", errors="replace")
            return ResourceContentResult(
                ok=True,
                resourceId=core.id,
                title=core.title,
                type=core.type,
                origin=core.origin,
                contentKind=content_kind,
                textContent=content if content_kind == "TEXT" else None,
                htmlContent=content if content_kind == "HTML" else None,
                binaryPath=str(resolved_path),
                filename=resolved_path.name,
                mimeType=content_type,
            )
        except OSError as exc:
            return _content_error(core.id, "NETWORK_ERROR", str(exc), core=core)

    return ResourceContentResult(
        ok=True,
        resourceId=core.id,
        title=core.title,
        type=core.type,
        origin=core.origin,
        contentKind=content_kind,
        binaryPath=str(resolved_path),
        filename=resolved_path.name,
        mimeType=content_type,
    )


def _download_canvas_file(
    settings: Settings,
    job_id: str | None,
    raw_resource: dict[str, Any],
    core: ResourceCore,
    client: Any,
    course_id: str | None,
) -> ResourceContentResult:
    details = _details(raw_resource)
    file_id = _string(raw_resource, "fileId", "file_id", "contentId", "content_id") or _string(
        details,
        "fileId",
        "file_id",
        "contentId",
        "content_id",
    )
    download_url = _string(raw_resource, "downloadUrl", "download_url") or core.sourceUrl
    filename = _filename_from_url(download_url) or core.title
    content_type: str | None = None

    try:
        if file_id and hasattr(client, "get_file_by_id"):
            canvas_file = client.get_file_by_id(file_id)
            download_url = canvas_file.url or download_url
            filename = canvas_file.filename or canvas_file.display_name or filename
            content_type = canvas_file.content_type or content_type
        elif file_id and course_id and hasattr(client, "get_file"):
            canvas_file = client.get_file(course_id, file_id)
            download_url = canvas_file.url or download_url
            filename = canvas_file.filename or canvas_file.display_name or filename
            content_type = canvas_file.content_type or content_type
    except AppError as exc:
        return _content_error(core.id, _error_code_from_status(exc.status_code), exc.message, core=core)

    if not download_url:
        return _content_error(core.id, "NOT_FOUND", "Canvas no ha devuelto URL descargable para este fichero.", core=core)

    if not job_id:
        return _content_error(
            core.id,
            "NO_ANALIZABLE",
            "Hace falta un job_id para cachear la descarga de Canvas antes de analizarla.",
            core=core,
        )

    target_dir = get_job_dir(settings, job_id) / "online_downloads" / core.id
    target_dir.mkdir(parents=True, exist_ok=True)
    target_path = target_dir / _safe_filename(filename)

    try:
        handle = client.stream_download(download_url, filename=filename)
        content_type = getattr(handle, "content_type", None) or content_type or _guess_content_type(target_path)
        with target_path.open("wb") as output:
            for chunk in handle.iter_bytes():
                output.write(chunk)
    except AppError as exc:
        return _content_error(core.id, _error_code_from_status(exc.status_code), exc.message, core=core)
    except OSError as exc:
        return _content_error(core.id, "NETWORK_ERROR", str(exc), core=core)

    return ResourceContentResult(
        ok=True,
        resourceId=core.id,
        title=core.title,
        type=core.type,
        origin=core.origin,
        contentKind=_content_kind_for_file(target_path, content_type, core.type),
        binaryPath=str(target_path),
        filename=target_path.name,
        mimeType=content_type,
    )


def _read_canvas_html(
    core: ResourceCore,
    getter: Any,
    course_id: str | None,
    content_id: str | None,
    body_keys: tuple[str, ...],
) -> ResourceContentResult:
    if not course_id or not content_id:
        return _content_error(core.id, "NOT_FOUND", "Faltan identificadores de Canvas para obtener el HTML.", core=core)
    try:
        payload = getter(course_id, content_id)
    except AppError as exc:
        return _content_error(core.id, _error_code_from_status(exc.status_code), exc.message, core=core)

    if not isinstance(payload, dict):
        return _content_error(core.id, "UNKNOWN", "Canvas ha devuelto una respuesta inesperada.", core=core)
    for key in body_keys:
        value = payload.get(key)
        if isinstance(value, str):
            return ResourceContentResult(
                ok=True,
                resourceId=core.id,
                title=core.title,
                type=core.type,
                origin=core.origin,
                contentKind="HTML",
                htmlContent=value,
                filename=f"{content_id}.html",
                mimeType="text/html",
            )
    return _content_error(core.id, "NOT_FOUND", "La respuesta de Canvas no contiene HTML reutilizable.", core=core)


def _course_id_from_url(url: str | None) -> str | None:
    if not isinstance(url, str) or not url.strip():
        return None
    parts = [unquote(part) for part in urlparse(url).path.split("/") if part]
    if "courses" not in parts:
        return None
    index = parts.index("courses")
    return parts[index + 1] if index + 1 < len(parts) else None


def _page_id_from_url(url: str | None, course_id: str | None) -> str | None:
    if not isinstance(url, str) or not url.strip() or not course_id:
        return None
    marker = f"/courses/{course_id}/pages/"
    path = urlparse(url).path
    if marker not in path:
        return None
    return unquote(path.split(marker, 1)[1].split("/", 1)[0])


def _build_canvas_client(settings: Settings, canvas_credentials: CanvasCredentials | None) -> CanvasClient | None:
    credentials = canvas_credentials
    if credentials is None and settings.canvas_base_url and settings.canvas_token:
        credentials = CanvasCredentials.create(base_url=settings.canvas_base_url, token=settings.canvas_token)
    if credentials is None:
        return None
    return CanvasClient(credentials, timeout_seconds=settings.canvas_timeout_seconds)


def _as_mapping(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    if isinstance(value, Resource):
        return {
            "id": value.id,
            "job_id": value.job_id,
            "title": value.title,
            "type": value.type,
            "origin": value.origin,
            "sourceUrl": value.url,
            "downloadUrl": value.download_url,
            "finalUrl": value.final_url,
            "htmlPath": value.path if value.origin == "INTERNAL_PAGE" else None,
            "localPath": value.path,
            "coursePath": value.course_path,
            "status": value.status,
            "canAccess": value.can_access,
            "accessStatus": value.access_status,
            "httpStatus": value.http_status,
            "accessStatusCode": value.access_status_code,
            "canDownload": value.can_download,
            "downloadStatus": value.download_status,
            "downloadStatusCode": value.download_status_code,
            "discoveredChildrenCount": value.discovered_children_count,
            "parentResourceId": value.parent_resource_id,
            "discovered": value.discovered,
            "reasonCode": value.reason_code,
            "reasonDetail": value.reason_detail,
            "contentAvailable": value.content_available,
            "accessNote": value.access_note,
            "errorMessage": value.error_message,
            "notes": value.notes,
        }
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="python")
    return {
        key: getattr(value, key)
        for key in dir(value)
        if not key.startswith("_") and not callable(getattr(value, key, None))
    }


def _details(value: Any) -> dict[str, Any]:
    mapping = _as_mapping(value)
    details = mapping.get("details")
    return details if isinstance(details, dict) else {}


def _string(value: Any, *keys: str) -> str | None:
    mapping = _as_mapping(value)
    for key in keys:
        item = mapping.get(key)
        if item is None and "_" in key:
            camel = _snake_to_camel(key)
            item = mapping.get(camel)
        if hasattr(item, "value"):
            item = item.value
        if item is None:
            continue
        cleaned = str(item).strip()
        if cleaned:
            return cleaned
    return None


def _bool(value: Any, *keys: str) -> bool | None:
    mapping = _as_mapping(value)
    for key in keys:
        item = mapping.get(key)
        if item is None and "_" in key:
            item = mapping.get(_snake_to_camel(key))
        if item is None:
            continue
        return bool(item)
    return None


def _int(value: Any, *keys: str) -> int | None:
    raw = _string(value, *keys)
    if raw is None:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def _snake_to_camel(value: str) -> str:
    head, *tail = value.split("_")
    return head + "".join(part.capitalize() for part in tail)


def _normalize_resource_type(
    source: Any,
    fallback: Any,
    *,
    local_path: str | None,
    source_url: str | None,
    canvas_type: str | None,
    content_type: str | None,
) -> CoreResourceType:
    raw_type = (_string(source, "type") or _string(fallback, "type") or "OTHER").upper()
    normalized_content_type = (content_type or "").split(";", 1)[0].strip().lower()
    if normalized_content_type == "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
        return "DOCX"
    reference = source_url or local_path or ""
    suffix = Path(urlparse(reference).path).suffix.lower()
    if suffix == ".pdf":
        return "PDF"
    if suffix == ".docx":
        return "DOCX"
    if suffix in {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg"}:
        return "IMAGE"
    if suffix in {".mp4", ".mov", ".m4v", ".webm", ".avi"}:
        return "VIDEO"
    if suffix == ".ipynb":
        return "NOTEBOOK"
    if suffix in {".html", ".htm", ".xhtml"}:
        return "WEB"
    if raw_type in VALID_RESOURCE_TYPES:
        if raw_type == "OTHER" and canvas_type == "File":
            return "FILE"
        return raw_type  # type: ignore[return-value]
    if canvas_type in PAGE_CANVAS_TYPES or canvas_type in {"Assignment", "Discussion"}:
        return "WEB"
    if canvas_type == "File":
        return "FILE"
    return "OTHER"


def _normalize_origin(
    source: Any,
    fallback: Any,
    *,
    source_url: str | None,
    final_url: str | None,
    local_path: str | None,
    html_path: str | None,
    canvas_type: str | None,
) -> CoreResourceOrigin:
    raw_origin = (_string(source, "origin") or _string(fallback, "origin") or "").lower()
    raw_source = (_string(source, "source") or _string(fallback, "source") or "").lower()
    url = final_url or source_url or ""
    if _is_sso_url(url):
        return "RALTI"
    if raw_origin in {"online_canvas", "canvas"}:
        return "ONLINE_CANVAS"
    if raw_origin in {"external_url", "external", "externo"}:
        return "EXTERNAL_URL"
    if raw_origin == "ralti":
        return "RALTI"
    if raw_origin == "lti":
        return "LTI"
    if canvas_type == "ExternalTool":
        return "LTI"
    if raw_source == "canvas" or canvas_type:
        return "ONLINE_CANVAS"
    if source_url and source_url.startswith(("http://", "https://")):
        return "EXTERNAL_URL"
    if html_path:
        return "INTERNAL_PAGE"
    if local_path:
        suffix = Path(local_path).suffix.lower()
        return "INTERNAL_PAGE" if suffix in {".html", ".htm", ".xhtml"} else "INTERNAL_FILE"
    if raw_origin == "internal_page":
        return "INTERNAL_PAGE"
    if raw_origin == "internal_file":
        return "INTERNAL_FILE"
    return "OFFLINE_IMSCC"


def _normalize_module_path(source: Any, fallback: Any) -> list[str]:
    raw = _as_mapping(source).get("modulePath")
    if raw is None:
        raw = _as_mapping(source).get("module_path")
    if raw is None:
        raw = _as_mapping(source).get("coursePath")
    if raw is None:
        raw = _as_mapping(source).get("course_path")
    if raw is None:
        raw = _as_mapping(fallback).get("modulePath") or _as_mapping(fallback).get("course_path")
    if isinstance(raw, list):
        return [str(item).strip() for item in raw if str(item).strip()]
    if isinstance(raw, str) and raw.strip():
        return [part for part in PATH_SEPARATOR_RE.split(raw.strip()) if part]
    return []


def _normalize_access_status(
    source: Any,
    fallback: Any,
    *,
    source_url: str | None,
    final_url: str | None,
    canvas_type: str | None,
) -> CoreAccessStatus:
    raw_status = (_string(source, "accessStatus", "access_status") or _string(fallback, "accessStatus", "access_status") or "").upper()
    raw_reason = (_string(source, "reasonCode", "reason_code") or _string(fallback, "reasonCode", "reason_code") or "").upper()
    analysis_category = (_string(source, "analysisCategory", "analysis_category") or "").upper()
    http_status = _int(source, "httpStatus", "http_status", "accessStatusCode", "access_status_code") or _int(
        fallback,
        "httpStatus",
        "http_status",
        "accessStatusCode",
        "access_status_code",
    )
    reference_url = final_url or source_url or ""
    real_failure_reason = raw_reason in {
        "NOT_FOUND",
        "TIMEOUT",
        "DNS_ERROR",
        "SSL_ERROR",
        "NETWORK_ERROR",
        "INVALID_URL",
    }
    if (
        not real_failure_reason
        and http_status != 404
        and (
            _is_sso_url(reference_url)
            or (
                _is_protected_external_auth_url(reference_url)
                and (raw_reason in {"AUTH_REQUIRED", "FORBIDDEN"} or http_status in {401, 403})
            )
        )
    ):
        return "REQUIERE_SSO"
    if canvas_type in {"ExternalTool", "Quiz"} and raw_status != "REQUIERE_SSO":
        return "REQUIERE_INTERACCION"
    if analysis_category and analysis_category != "MAIN_ANALYZABLE" and raw_status != "REQUIERE_SSO":
        return "NO_ANALIZABLE"
    if raw_status in VALID_ACCESS_STATUSES:
        return raw_status  # type: ignore[return-value]
    if raw_status in {"NOT_FOUND", "FORBIDDEN", "TIMEOUT", "ERROR"}:
        return "NO_ACCEDE"
    return "NO_ACCEDE"


def _normalize_reason_code(source: Any, fallback: Any, *, access_status: str) -> CoreReasonCode:
    raw_reason = (_string(source, "reasonCode", "reason_code") or _string(fallback, "reasonCode", "reason_code") or "").upper()
    http_status = _int(source, "httpStatus", "http_status", "accessStatusCode", "access_status_code") or _int(
        fallback,
        "httpStatus",
        "http_status",
        "accessStatusCode",
        "access_status_code",
    )
    if access_status == "OK":
        return "OK"
    if access_status == "REQUIERE_SSO":
        return "AUTH_REQUIRED"
    if access_status in {"REQUIERE_INTERACCION", "NO_ANALIZABLE"}:
        return "UNKNOWN"
    if raw_reason in {"404_NOT_FOUND", "NOT_FOUND"} or http_status == 404:
        return "NOT_FOUND"
    if raw_reason == "TIMEOUT":
        return "TIMEOUT"
    if raw_reason in {"DNS_ERROR", "SSL_ERROR", "NETWORK_ERROR", "INVALID_URL"}:
        return raw_reason  # type: ignore[return-value]
    if raw_reason in {"AUTH_REQUIRED", "FORBIDDEN"} or http_status in {401, 403}:
        return "FORBIDDEN"
    if raw_reason in VALID_REASON_CODES:
        return raw_reason  # type: ignore[return-value]
    if _contains_text(source, fallback, "timeout"):
        return "TIMEOUT"
    if _contains_text(source, fallback, "dns"):
        return "DNS_ERROR"
    if _contains_text(source, fallback, "ssl"):
        return "SSL_ERROR"
    if _contains_text(source, fallback, "invalid"):
        return "INVALID_URL"
    return "UNKNOWN"


def _normalize_reason_detail(source: Any, fallback: Any, *, access_status: str) -> str | None:
    if access_status == "REQUIERE_SSO":
        return SSO_REASON_DETAIL
    if access_status == "REQUIERE_INTERACCION":
        return INTERACTION_REASON_DETAIL
    return _string(source, "reasonDetail", "reason_detail", "accessNote", "access_note", "errorMessage", "error_message") or _string(
        fallback,
        "reasonDetail",
        "reason_detail",
        "accessNote",
        "access_note",
        "errorMessage",
        "error_message",
    )


def _normalize_download_status(source: Any, fallback: Any, *, downloadable: bool) -> CoreDownloadStatus:
    raw_status = (_string(source, "downloadStatus", "download_status") or _string(fallback, "downloadStatus", "download_status") or "").upper()
    if raw_status in VALID_DOWNLOAD_STATUSES:
        return raw_status  # type: ignore[return-value]
    if not downloadable:
        return "N_A"
    can_access = _bool(source, "canAccess", "can_access")
    if can_access is None:
        can_access = _bool(fallback, "canAccess", "can_access")
    return "OK" if can_access else "FAIL"


def _content_available(
    *,
    access_status: str,
    downloadable: bool,
    local_path: str | None,
    html_path: str | None,
    source_url: str | None,
    canvas_type: str | None,
    resource_type: str,
) -> bool:
    if access_status != "OK":
        return False
    if local_path or html_path:
        return True
    if canvas_type in HTML_CANVAS_TYPES:
        return True
    if canvas_type == "File" and (downloadable or source_url):
        return True
    return bool(downloadable and resource_type in {"PDF", "DOCX", "FILE", "IMAGE", "VIDEO", "NOTEBOOK"})


def _contains_text(source: Any, fallback: Any, needle: str) -> bool:
    haystack = " ".join(
        filter(
            None,
            [
                _string(source, "reasonDetail", "reason_detail", "errorMessage", "error_message", "accessNote", "access_note"),
                _string(fallback, "reasonDetail", "reason_detail", "errorMessage", "error_message", "accessNote", "access_note"),
            ],
        )
    ).lower()
    return needle in haystack


def _is_sso_url(url: str | None) -> bool:
    if not url:
        return False
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    if any(marker in host for marker in SSO_HOST_MARKERS):
        return True
    return host.endswith(".uoc.edu") and any(marker in f"{parsed.path.lower()}?{parsed.query.lower()}" for marker in SSO_PATH_MARKERS)


def _is_protected_external_auth_url(url: str | None) -> bool:
    if not url:
        return False
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    reference = f"{host}{parsed.path.lower()}?{parsed.query.lower()}"
    if any(marker in host for marker in PROTECTED_EXTERNAL_HOST_MARKERS):
        return True
    if host.endswith(".uoc.edu") and any(marker in reference for marker in PROTECTED_EXTERNAL_REFERENCE_MARKERS):
        return True
    return any(marker in reference for marker in PROTECTED_EXTERNAL_REFERENCE_MARKERS)


def _is_sso_or_protected_auth_url(url: str | None) -> bool:
    return _is_sso_url(url) or _is_protected_external_auth_url(url)


def _guess_content_type(path: Path) -> str:
    return mimetypes.guess_type(path.name)[0] or "application/octet-stream"


def _is_textual_file(path: Path, content_type: str | None) -> bool:
    suffix = path.suffix.lower()
    return bool(
        (content_type and (content_type.startswith("text/") or content_type in {"application/xhtml+xml", "application/json"}))
        or suffix in {".html", ".htm", ".xhtml", ".txt", ".md", ".json", ".csv"}
    )


def _content_kind_for_file(path: Path, content_type: str | None, resource_type: str | None) -> ContentKind:
    suffix = path.suffix.lower()
    normalized_content_type = (content_type or "").split(";", 1)[0].strip().lower()
    normalized_resource_type = (resource_type or "").upper()
    if suffix in {".html", ".htm", ".xhtml"} or normalized_content_type in {"text/html", "application/xhtml+xml"}:
        return "HTML"
    if suffix == ".pdf" or normalized_content_type == "application/pdf" or normalized_resource_type == "PDF":
        return "PDF"
    if _is_textual_file(path, content_type):
        return "TEXT"
    return "BINARY"


def _filename_from_url(url: str | None) -> str | None:
    if not url:
        return None
    name = Path(urlparse(url).path).name.strip()
    return name or None


def _safe_filename(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", Path(value).name.strip()).strip("-._")
    return cleaned or "canvas-resource.bin"


def _error_code_from_status(status_code: int | None) -> str:
    if status_code == 404:
        return "NOT_FOUND"
    if status_code == 401:
        return "AUTH_REQUIRED"
    if status_code == 403:
        return "FORBIDDEN"
    if status_code == 504:
        return "TIMEOUT"
    return "NETWORK_ERROR" if status_code and status_code >= 500 else "UNKNOWN"


def _content_error(
    resource_id: str,
    code: str,
    detail: str,
    *,
    core: ResourceCore | None = None,
) -> ResourceContentResult:
    return ResourceContentResult(
        ok=False,
        resourceId=resource_id,
        title=core.title if core is not None else "Recurso no encontrado",
        type=core.type if core is not None else "OTHER",
        origin=core.origin if core is not None else None,
        contentKind="NOT_ANALYZABLE",
        errorCode=code,
        errorDetail=detail,
    )
