from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath
from typing import Any, Protocol
from urllib.parse import unquote, urlparse
from uuid import NAMESPACE_URL, uuid5

from app.core.config import Settings
from app.core.errors import AppError
from app.models.entities import ResourceHealthStatus
from app.services.access_check import build_access_status_counts
from app.services.canvas_client import CanvasClient, CanvasCredentials
from app.services.canvas_deep_scan import extract_canvas_links
from app.services.course_structure import build_section_key, section_key_from_path, section_title_from_path
from app.services.imscc_parser import IMSCCParser
from app.services.storage import get_extracted_dir, resolve_job_resource_path
from app.services.url_check import URLCheckService, UrlCheckResult

logger = logging.getLogger("accessiblecourse.access")

ACCESS_STATUS_OK = "OK"
ACCESS_STATUS_NO_ACCEDE = "NO_ACCEDE"
ACCESS_STATUS_REQUIRES_INTERACTION = "REQUIERE_INTERACCION"
ACCESS_STATUS_REQUIRES_SSO = "REQUIERE_SSO"
ACCESS_STATUS_ERROR = ACCESS_STATUS_NO_ACCEDE
DISCOVERED_BY_DEEP_SCAN = "access_deep_scan"

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

HTML_EXTENSIONS = {".html", ".htm", ".xhtml"}
IGNORED_DISCOVERY_EXTENSIONS = {".xml", ".xsd", ".dtd", ".qti", ".imsmanifest"}
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
ORIGIN_ONLINE_CANVAS = "ONLINE_CANVAS"
ORIGIN_EXTERNAL_URL = "EXTERNAL_URL"
ORIGIN_RALTI = "RALTI"
ORIGIN_LTI = "LTI"
NO_ACCESS_REASON_NOT_FOUND = "NOT_FOUND"
NO_ACCESS_REASON_TIMEOUT = "TIMEOUT"
NO_ACCESS_REASON_AUTH_REQUIRED = "AUTH_REQUIRED"
NO_ACCESS_REASON_FORBIDDEN = "FORBIDDEN"
NO_ACCESS_REASON_SSL_ERROR = "SSL_ERROR"
NO_ACCESS_REASON_DNS_ERROR = "DNS_ERROR"
NO_ACCESS_REASON_NETWORK_ERROR = "NETWORK_ERROR"
NO_ACCESS_REASON_INVALID_URL = "INVALID_URL"
NO_ACCESS_REASON_UNKNOWN = "UNKNOWN"


@dataclass(slots=True, frozen=True)
class AccessProbeResult:
    can_access: bool
    access_status: str
    http_status: int | None = None
    error_message: str | None = None
    url_status: str | None = None
    final_url: str | None = None
    checked_at: datetime | str | None = None
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True, frozen=True)
class DownloadProbeResult:
    can_download: bool
    http_status: int | None = None
    error_message: str | None = None
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True, frozen=True)
class AccessAnalysisResult:
    resources: list[dict[str, Any]]
    summary: dict[str, Any]
    discovered_count: int


class AccessAnalysisAdapter(Protocol):
    mode: str

    def probe_access(self, resource: dict[str, Any]) -> AccessProbeResult:
        ...

    def probe_download(self, resource: dict[str, Any], access: AccessProbeResult) -> DownloadProbeResult:
        ...

    def fetch_html(self, resource: dict[str, Any]) -> str | None:
        ...

    def resolve_children(self, html: str, base_resource: dict[str, Any]) -> list[dict[str, Any]]:
        ...


def analyze_access(
    *,
    job_id: str,
    resources: list[dict[str, Any]],
    adapter: AccessAnalysisAdapter,
    progress: int = 100,
    clean_discovered: bool = True,
) -> AccessAnalysisResult:
    max_depth = max(0, int(getattr(adapter, "max_depth", 1)))
    max_pages = max(0, int(getattr(adapter, "max_pages", 50)))
    max_discovered = max(0, int(getattr(adapter, "max_discovered", 500)))
    base_resources = [
        dict(resource)
        for resource in resources
        if not clean_discovered or not _is_deep_scan_child(resource)
    ]
    analyzed: list[dict[str, Any]] = []
    seen_keys: set[tuple[str, str]] = set()
    scan_queue: list[tuple[dict[str, Any], int]] = []
    parent_children: dict[str, list[str]] = {}
    discovered_count = 0
    scanned_pages = 0
    skipped_pages = 0

    for resource in base_resources:
        _normalize_resource_defaults(resource)
        _analyze_resource(resource, adapter)
        analyzed.append(resource)
        seen_keys.add(_dedupe_key(resource))

        if _should_deep_scan(resource):
            scan_queue.append((resource, 0))

    while scan_queue:
        parent_resource, depth = scan_queue.pop(0)
        if depth >= max_depth or scanned_pages >= max_pages:
            skipped_pages += 1
            continue

        html = adapter.fetch_html(parent_resource)
        if not html:
            skipped_pages += 1
            continue

        scanned_pages += 1
        for child in adapter.resolve_children(html, parent_resource):
            if discovered_count >= max_discovered:
                skipped_pages += 1
                break
            _normalize_child_resource(job_id, child, parent_resource, depth=depth + 1)
            key = _dedupe_key(child)
            if key in seen_keys:
                continue
            _analyze_resource(child, adapter)
            analyzed.append(child)
            seen_keys.add(key)
            child_details = child.get("details") if isinstance(child.get("details"), dict) else {}
            if not child_details.get("indirectDeepScan"):
                parent_children.setdefault(str(parent_resource.get("id")), []).append(str(child.get("id")))
            discovered_count += 1

            if _should_deep_scan(child) and depth + 1 < max_depth:
                scan_queue.append((child, depth + 1))

    _attach_discovered_children(analyzed, parent_children)
    discovered_total = sum(1 for resource in analyzed if _is_discovered_resource(resource))
    summary = build_access_summary(job_id=job_id, resources=analyzed, progress=progress, status="done")
    summary["discovered"] = discovered_total
    summary["deepScan"] = {
        "maxDepth": max_depth,
        "maxPages": max_pages,
        "maxDiscovered": max_discovered,
        "scannedPages": scanned_pages,
        "skippedPages": skipped_pages,
    }
    return AccessAnalysisResult(resources=analyzed, summary=summary, discovered_count=discovered_total)


def build_access_summary(
    *,
    job_id: str,
    resources: list[dict[str, Any]],
    progress: int,
    status: str,
) -> dict[str, Any]:
    by_status = build_access_status_counts()
    groups_by_module: dict[str, dict[str, Any]] = {}
    group_priorities: dict[str, int] = {}

    for resource in resources:
        access_status = str(resource.get("accessStatus") or ACCESS_STATUS_ERROR)
        by_status.setdefault(access_status, 0)
        by_status[access_status] += 1

        module_path = _module_path(resource)
        group_key = _module_group_key(resource)
        group = groups_by_module.setdefault(
            group_key,
            {
                "modulePath": module_path,
                "total": 0,
                "accessible": 0,
                "downloadable": 0,
                "downloadableAccessible": 0,
                "ok_count": 0,
                "no_accede_count": 0,
                "requires_interaction_count": 0,
                "requires_sso_count": 0,
                "requiere_interaccion_count": 0,
                "requiere_sso_count": 0,
                "downloadables_total": 0,
                "downloadables_ok": 0,
                "byStatus": build_access_status_counts(),
                "resources": [],
            },
        )
        current_priority = 0 if not _is_discovered_resource(resource) else 1
        previous_priority = group_priorities.get(group_key)
        if previous_priority is None or current_priority < previous_priority:
            group["modulePath"] = module_path
            group_priorities[group_key] = current_priority
        group["total"] += 1
        group["accessible"] += int(bool(resource.get("canAccess")))
        group["downloadable"] += int(bool(resource.get("canDownload")))
        group["downloadableAccessible"] += int(bool(resource.get("canAccess")) and bool(resource.get("canDownload")))
        group["ok_count"] += int(access_status == ACCESS_STATUS_OK)
        group["no_accede_count"] += int(access_status == ACCESS_STATUS_NO_ACCEDE)
        group["requires_interaction_count"] += int(access_status == ACCESS_STATUS_REQUIRES_INTERACTION)
        group["requires_sso_count"] += int(access_status == ACCESS_STATUS_REQUIRES_SSO)
        group["requiere_interaccion_count"] += int(access_status == ACCESS_STATUS_REQUIRES_INTERACTION)
        group["requiere_sso_count"] += int(access_status == ACCESS_STATUS_REQUIRES_SSO)
        group["downloadables_total"] += int(bool(resource.get("canDownload")))
        group["downloadables_ok"] += int(bool(resource.get("canAccess")) and bool(resource.get("canDownload")))
        group["byStatus"].setdefault(access_status, 0)
        group["byStatus"][access_status] += 1
        group["resources"].append(
            {
                "id": str(resource.get("id")),
                "title": str(resource.get("title") or "Recurso sin titulo"),
                "type": str(resource.get("type") or "OTHER"),
                "accessStatus": access_status,
                "canAccess": bool(resource.get("canAccess")),
                "canDownload": bool(resource.get("canDownload")),
                "downloadStatus": resource.get("downloadStatus"),
                "accessStatusCode": resource.get("accessStatusCode"),
                "downloadStatusCode": resource.get("downloadStatusCode"),
                "discovered": _is_discovered_resource(resource),
                "accessNote": resource.get("accessNote") or resource.get("errorMessage"),
                "badge": _badge_for(access_status),
            }
        )

    groups = list(groups_by_module.values())
    ok_count = sum(1 for resource in resources if resource.get("accessStatus") == ACCESS_STATUS_OK)
    no_accede_count = sum(1 for resource in resources if resource.get("accessStatus") == ACCESS_STATUS_NO_ACCEDE)
    requiere_interaccion_count = sum(
        1 for resource in resources if resource.get("accessStatus") == ACCESS_STATUS_REQUIRES_INTERACTION
    )
    requiere_sso_count = sum(1 for resource in resources if resource.get("accessStatus") == ACCESS_STATUS_REQUIRES_SSO)
    downloadables_total = sum(1 for resource in resources if bool(resource.get("canDownload")))
    downloadables_ok = sum(
        1 for resource in resources if bool(resource.get("canAccess")) and bool(resource.get("canDownload"))
    )
    return {
        "jobId": job_id,
        "status": status,
        "progress": progress,
        "total": len(resources),
        "accessible": sum(1 for resource in resources if bool(resource.get("canAccess"))),
        "downloadable": downloadables_total,
        "downloadableAccessible": downloadables_ok,
        "ok_count": ok_count,
        "no_accede_count": no_accede_count,
        "requires_interaction_count": requiere_interaccion_count,
        "requires_sso_count": requiere_sso_count,
        "requiere_interaccion_count": requiere_interaccion_count,
        "requiere_sso_count": requiere_sso_count,
        "downloadables_total": downloadables_total,
        "downloadables_ok": downloadables_ok,
        "byStatus": by_status,
        "groups": groups,
    }


class OfflineAccessAdapter:
    mode = "OFFLINE"

    def __init__(self, *, settings: Settings, job_id: str, url_checker: URLCheckService) -> None:
        self.settings = settings
        self.job_id = job_id
        self.extracted_dir = get_extracted_dir(settings, job_id)
        self.url_checker = url_checker
        self._url_cache: dict[str, UrlCheckResult] = {}
        self._excluded_extensions = {extension.lower() for extension in settings.offline_excluded_extensions}

    def probe_access(self, resource: dict[str, Any]) -> AccessProbeResult:
        source_url = _resource_source_url(resource)
        if source_url:
            return _access_from_url_result(self._check_url(source_url), allow_canvas_forbidden=False)

        relative_path = _resource_file_path(resource)
        if not relative_path:
            return AccessProbeResult(
                can_access=False,
                access_status=ACCESS_STATUS_ERROR,
                error_message="El recurso no tiene un fichero asociado dentro del paquete.",
            )

        try:
            resolved_path = resolve_job_resource_path(self.settings, self.job_id, relative_path)
        except AppError:
            return AccessProbeResult(
                can_access=False,
                access_status=ACCESS_STATUS_ERROR,
                error_message="La ruta del recurso no es valida dentro del paquete extraido.",
            )

        if not resolved_path.exists() or not resolved_path.is_file():
            return AccessProbeResult(
                can_access=False,
                access_status=ACCESS_STATUS_NO_ACCEDE,
                error_message="No se ha encontrado el fichero extraido para este recurso.",
            )

        return AccessProbeResult(can_access=True, access_status=ACCESS_STATUS_OK, http_status=200)

    def probe_download(self, resource: dict[str, Any], access: AccessProbeResult) -> DownloadProbeResult:
        source_url = _resource_source_url(resource)
        if source_url:
            return DownloadProbeResult(
                can_download=False,
                http_status=access.http_status,
            )

        return DownloadProbeResult(
            can_download=access.access_status == ACCESS_STATUS_OK,
            http_status=200 if access.access_status == ACCESS_STATUS_OK else None,
        )

    def fetch_html(self, resource: dict[str, Any]) -> str | None:
        relative_path = _resource_file_path(resource)
        if not relative_path or not _is_html_reference(relative_path):
            return None
        try:
            resolved_path = resolve_job_resource_path(self.settings, self.job_id, relative_path)
        except AppError:
            return None
        if not resolved_path.exists() or not resolved_path.is_file():
            return None
        return resolved_path.read_text(encoding="utf-8", errors="ignore")

    def resolve_children(self, html: str, base_resource: dict[str, Any]) -> list[dict[str, Any]]:
        children: list[dict[str, Any]] = []
        relative_path = _resource_file_path(base_resource)
        if not relative_path:
            return children

        try:
            html_path = resolve_job_resource_path(self.settings, self.job_id, relative_path)
        except AppError:
            return children

        parser = IMSCCParser()
        for candidate in parser.extract_html_links(html_path, self.extracted_dir):
            if candidate["kind"] == "external":
                reference = candidate["url"]
                if self._excluded(reference):
                    continue
                children.append(
                    _build_discovered_resource(
                        reference=reference,
                        base_resource=base_resource,
                        source_url=reference,
                        title=candidate.get("title"),
                    )
                )
                continue

            normalized_path = candidate["path"]
            if _is_html_reference(normalized_path):
                try:
                    nested_html_path = resolve_job_resource_path(self.settings, self.job_id, normalized_path)
                except AppError:
                    continue
                if nested_html_path.exists() and nested_html_path.is_file():
                    for nested_candidate in parser.extract_html_links(nested_html_path, self.extracted_dir):
                        self._append_discovered_offline_candidate(
                            children,
                            base_resource,
                            nested_candidate,
                            indirect=True,
                        )
                continue
            if self._excluded(normalized_path):
                continue
            children.append(
                _build_discovered_resource(
                    reference=normalized_path,
                    base_resource=base_resource,
                    file_path=normalized_path,
                    title=candidate.get("title"),
                )
            )

        return children

    def _append_discovered_offline_candidate(
        self,
        children: list[dict[str, Any]],
        base_resource: dict[str, Any],
        candidate: dict[str, str],
        *,
        indirect: bool = False,
    ) -> None:
        if candidate["kind"] == "external":
            reference = candidate["url"]
            if self._excluded(reference):
                return
            child = _build_discovered_resource(
                reference=reference,
                base_resource=base_resource,
                source_url=reference,
                title=candidate.get("title"),
            )
            if indirect:
                child["details"] = {**dict(child.get("details") or {}), "indirectDeepScan": True}
            children.append(child)
            return

        normalized_path = candidate["path"]
        if _is_html_reference(normalized_path) or self._excluded(normalized_path):
            return
        child = _build_discovered_resource(
            reference=normalized_path,
            base_resource=base_resource,
            file_path=normalized_path,
            title=candidate.get("title"),
        )
        if indirect:
            child["details"] = {**dict(child.get("details") or {}), "indirectDeepScan": True}
        children.append(child)

    def _check_url(self, url: str) -> UrlCheckResult:
        if url not in self._url_cache:
            self._url_cache[url] = _check_url_with_service(self.url_checker, url)
        return self._url_cache[url]

    def _excluded(self, reference: str) -> bool:
        suffix = Path(urlparse(reference).path or reference).suffix.lower()
        return suffix in self._excluded_extensions


class OnlineAccessAdapter:
    mode = "ONLINE"

    def __init__(
        self,
        *,
        client: CanvasClient,
        credentials: CanvasCredentials,
        course_id: str,
        url_checker: URLCheckService,
        max_depth: int = 2,
        max_pages: int = 50,
        max_discovered: int = 500,
    ) -> None:
        self.client = client
        self.credentials = credentials
        self.course_id = course_id
        self.url_checker = url_checker
        self.max_depth = max_depth
        self.max_pages = max_pages
        self.max_discovered = max_discovered
        self.allowed_host = urlparse(credentials.base_url).netloc.lower()
        self._url_cache: dict[str, UrlCheckResult] = {}
        self._download_cache: dict[str, UrlCheckResult] = {}
        self._page_cache: dict[str, dict[str, Any]] = {}
        self._assignment_cache: dict[str, dict[str, Any]] = {}
        self._discussion_cache: dict[str, dict[str, Any]] = {}
        self._quiz_cache: dict[str, dict[str, Any]] = {}

    def probe_access(self, resource: dict[str, Any]) -> AccessProbeResult:
        canvas_type = _canvas_type(resource)
        source_url = _resource_source_url(resource)
        if source_url and not self.credentials.is_canvas_url(source_url):
            return _access_from_url_result(self._check_url(source_url), allow_canvas_forbidden=False)

        if canvas_type == "File" and resource.get("fileId"):
            try:
                canvas_file = self._get_file(str(resource["fileId"]))
                _merge_discovered_file(resource, canvas_file)
            except AppError as exc:
                return _access_from_app_error(exc)
            return AccessProbeResult(
                can_access=True,
                access_status=ACCESS_STATUS_OK,
                http_status=200,
                details={"contentAvailable": True, "canvasType": "File"},
            )

        if canvas_type == "Assignment":
            return self._probe_canvas_api_resource(resource, cache_name="assignment")

        if canvas_type == "Discussion":
            return self._probe_canvas_api_resource(resource, cache_name="discussion")

        if canvas_type == "Quiz":
            return self._probe_quiz(resource)

        if canvas_type == "ExternalTool":
            if source_url and _is_sso_url(source_url):
                return _access_from_url_result(self._check_url(source_url), allow_canvas_forbidden=False)
            return _requires_interaction_result(canvas_type)

        if canvas_type == "Page" and resource.get("pageId"):
            try:
                payload = self._get_page(str(resource["pageId"]))
            except AppError as exc:
                return _access_from_app_error(exc)
            return AccessProbeResult(
                can_access=True,
                access_status=ACCESS_STATUS_OK,
                http_status=200,
                details={"contentAvailable": _payload_has_html(payload), "canvasType": "Page"},
            )

        if resource.get("pageId"):
            try:
                payload = self._get_page(str(resource["pageId"]))
            except AppError as exc:
                return _access_from_app_error(exc)
            return AccessProbeResult(
                can_access=True,
                access_status=ACCESS_STATUS_OK,
                http_status=200,
                details={"contentAvailable": _payload_has_html(payload), "canvasType": "Page"},
            )

        target_url = _download_url(resource) or source_url
        if target_url:
            return _access_from_url_result(self._check_url(target_url), allow_canvas_forbidden=True)

        return AccessProbeResult(
            can_access=False,
            access_status=ACCESS_STATUS_ERROR,
            error_message="No hemos podido resolver una URL o referencia Canvas para este recurso.",
        )

    def probe_download(self, resource: dict[str, Any], access: AccessProbeResult) -> DownloadProbeResult:
        if access.access_status != ACCESS_STATUS_OK:
            return DownloadProbeResult(can_download=False)

        download_url = _download_url(resource)
        if download_url:
            result = self._check_download_url(download_url)
            can_download = _download_result_is_ok(result)
            return DownloadProbeResult(
                can_download=can_download,
                http_status=result.status_code,
                error_message=None if can_download else result.error_message,
                details=_url_probe_details(result),
            )

        source_url = _resource_source_url(resource)
        if not source_url:
            return DownloadProbeResult(can_download=False)

        result = self._check_download_url(source_url)
        can_download = _download_result_is_ok(result) and _looks_downloadable_url(
            final_reference=result.redirect_location or result.final_url or source_url,
            content_type=result.content_type,
            content_disposition=result.content_disposition,
        )
        return DownloadProbeResult(
            can_download=can_download,
            http_status=result.status_code,
            error_message=None if can_download else result.error_message,
            details=_url_probe_details(result),
        )

    def fetch_html(self, resource: dict[str, Any]) -> str | None:
        canvas_type = _canvas_type(resource)
        if canvas_type == "Page" and resource.get("pageId"):
            try:
                payload = self._get_page(str(resource["pageId"]))
            except AppError:
                return None
            body = payload.get("body") or payload.get("html")
            return str(body) if isinstance(body, str) and body.strip() else None
        if canvas_type == "Assignment":
            payload = self._get_cached_canvas_payload(resource, cache_name="assignment")
            body = payload.get("description") if payload else None
            return str(body) if isinstance(body, str) and body.strip() else None
        if canvas_type == "Discussion":
            payload = self._get_cached_canvas_payload(resource, cache_name="discussion")
            body = (payload.get("message") or payload.get("description")) if payload else None
            return str(body) if isinstance(body, str) and body.strip() else None
        if canvas_type == "Quiz":
            payload = self._get_cached_canvas_payload(resource, cache_name="quiz")
            body = payload.get("description") if payload else None
            return str(body) if isinstance(body, str) and body.strip() else None
        source_url = _resource_source_url(resource)
        if not source_url or not self.credentials.is_canvas_url(source_url):
            return None
        if f"/courses/{self.course_id}/" not in urlparse(source_url).path:
            return None
        page_id = _extract_canvas_page_id(source_url, course_id=self.course_id)
        if page_id:
            try:
                payload = self._get_page(page_id)
            except AppError:
                return None
            body = payload.get("body") or payload.get("html")
            return str(body) if isinstance(body, str) and body.strip() else None
        try:
            response = self.client.get_text(source_url)
        except AppError:
            return None
        if response.content_type and "html" not in response.content_type.lower():
            return None
        return response.text

    def resolve_children(self, html: str, base_resource: dict[str, Any]) -> list[dict[str, Any]]:
        base_url = str(base_resource.get("finalUrl") or base_resource.get("sourceUrl") or base_resource.get("url") or self.credentials.base_url)
        children: list[dict[str, Any]] = []
        links = extract_canvas_links(
            html,
            base_url=base_url,
            course_id=self.course_id,
            allowed_host=self.allowed_host,
        )
        for link in links:
            resolved_url = link.url
            is_internal = link.is_internal
            child = _build_discovered_resource(
                reference=resolved_url,
                base_resource=base_resource,
                source_url=resolved_url,
                origin=_origin_for_link(resolved_url, is_internal=is_internal),
                title=link.title,
                resource_type=link.resource_type.value,
                file_id=link.file_id,
                page_id=link.page_url,
                normalized_url=link.normalized_url,
                download_candidate=link.is_downloadable_candidate,
            )
            if link.file_id:
                try:
                    canvas_file = self._get_file(link.file_id)
                    _merge_discovered_file(child, canvas_file)
                except AppError as exc:
                    details = dict(child.get("details") or {})
                    details["canvasFileError"] = {"code": exc.code, "statusCode": exc.status_code, "message": exc.message}
                    child["details"] = details
            children.append(child)
        return children

    def _check_url(self, url: str) -> UrlCheckResult:
        if url not in self._url_cache:
            self._url_cache[url] = _check_url_with_service(self.url_checker, url, credentials=self.credentials)
        return self._url_cache[url]

    def _check_download_url(self, url: str) -> UrlCheckResult:
        if url not in self._download_cache:
            self._download_cache[url] = _check_url_with_service(
                self.url_checker,
                url,
                credentials=self.credentials,
            )
        return self._download_cache[url]

    def _get_page(self, page_id: str) -> dict[str, Any]:
        if page_id not in self._page_cache:
            self._page_cache[page_id] = self.client.get_page(self.course_id, page_id)
        return self._page_cache[page_id]

    def _get_file(self, file_id: str):
        get_file_by_id = getattr(self.client, "get_file_by_id", None)
        if callable(get_file_by_id):
            return get_file_by_id(file_id)
        return self.client.get_file(self.course_id, file_id)

    def _probe_canvas_api_resource(self, resource: dict[str, Any], *, cache_name: str) -> AccessProbeResult:
        try:
            payload = self._get_cached_canvas_payload(resource, cache_name=cache_name, raise_errors=True)
        except AppError as exc:
            if exc.status_code in {401, 403, 404} and cache_name in {"assignment", "discussion"}:
                return _requires_interaction_result(
                    "Assignment" if cache_name == "assignment" else "Discussion",
                    http_status=exc.status_code,
                    message=exc.message,
                )
            return _access_from_app_error(exc)
        content_available = _payload_has_html(payload)
        if cache_name == "assignment":
            return _requires_interaction_result(
                "Assignment",
                message="La entrega existe y su descripcion es legible, pero la actividad requiere interacción manual.",
                details={"contentAvailable": content_available},
            )
        return AccessProbeResult(
            can_access=True,
            access_status=ACCESS_STATUS_OK,
            http_status=200,
            details={
                "contentAvailable": content_available,
                "canvasType": "Discussion" if cache_name == "discussion" else cache_name.title(),
            },
        )

    def _probe_quiz(self, resource: dict[str, Any]) -> AccessProbeResult:
        try:
            payload = self._get_cached_canvas_payload(resource, cache_name="quiz", raise_errors=True)
        except AppError as exc:
            if exc.status_code in {401, 403, 404}:
                return _requires_interaction_result("Quiz", http_status=exc.status_code, message=exc.message)
            return _access_from_app_error(exc)
        return _requires_interaction_result(
            "Quiz",
            message="El cuestionario existe en Canvas, pero requiere interacción manual.",
            details={"contentAvailable": _payload_has_html(payload)},
        )

    def _get_cached_canvas_payload(
        self,
        resource: dict[str, Any],
        *,
        cache_name: str,
        raise_errors: bool = False,
    ) -> dict[str, Any] | None:
        resource_id = _canvas_content_id(resource)
        api_url = _canvas_api_url(resource)
        cache_key = resource_id or api_url
        if not cache_key:
            if raise_errors:
                raise AppError(
                    code="canvas_resource_id_missing",
                    message="Canvas no ha devuelto un identificador API para este recurso.",
                    status_code=409,
                )
            return None

        cache = {
            "assignment": self._assignment_cache,
            "discussion": self._discussion_cache,
            "quiz": self._quiz_cache,
        }[cache_name]
        if cache_key not in cache:
            if api_url and not resource_id:
                cache[cache_key] = self.client.get_json(api_url)
            elif cache_name == "assignment":
                cache[resource_id] = self.client.get_assignment(self.course_id, resource_id)
            elif cache_name == "discussion":
                cache[resource_id] = self.client.get_discussion_topic(self.course_id, resource_id)
            else:
                cache[resource_id] = self.client.get_quiz(self.course_id, resource_id)
        return cache[cache_key]


class _HTMLReferenceParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.references: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_names = {"href"} if tag in {"a", "link"} else {"src", "data", "href"}
        for name, value in attrs:
            if name.lower() in attr_names and value:
                self.references.append(value.strip())


def extract_html_references(html: str) -> list[str]:
    parser = _HTMLReferenceParser()
    parser.feed(html)
    return [reference for reference in parser.references if reference]


def _check_url_with_service(
    url_checker: Any,
    url: str,
    *,
    credentials: CanvasCredentials | None = None,
) -> UrlCheckResult:
    check_url = getattr(url_checker, "check_url", None)
    if callable(check_url):
        try:
            return check_url(url, credentials=credentials)
        except TypeError:
            return check_url(url)

    check = getattr(url_checker, "check", None)
    if callable(check):
        resource = {"id": "__probe__", "url": url, "sourceUrl": url}
        try:
            results = check([resource], credentials=credentials)
        except TypeError:
            results = check([resource])
        if isinstance(results, dict):
            result = results.get("__probe__") or next(iter(results.values()), None)
            if isinstance(result, UrlCheckResult):
                return result

    return UrlCheckResult(
        url=url,
        checked=True,
        broken_link=True,
        reason="request_error",
        url_status="error",
        error_message="No se pudo acceder a la URL.",
    )


def _analyze_resource(resource: dict[str, Any], adapter: AccessAnalysisAdapter) -> None:
    access = adapter.probe_access(resource)
    download = adapter.probe_download(resource, access)
    _merge_analysis(resource, access, download, adapter.mode)


def _merge_analysis(
    resource: dict[str, Any],
    access: AccessProbeResult,
    download: DownloadProbeResult,
    mode: str,
) -> None:
    http_status = access.http_status if access.http_status is not None else download.http_status
    resolved_access_status = _resolve_access_status(resource, access, http_status=http_status)
    effective_access = (
        access
        if resolved_access_status == access.access_status
        else AccessProbeResult(
            can_access=False,
            access_status=resolved_access_status,
            http_status=access.http_status,
            error_message=SSO_REASON_DETAIL,
            url_status=access.url_status,
            final_url=access.final_url,
            checked_at=access.checked_at,
            details=access.details,
        )
    )
    reason_code = _normalize_no_access_reason_code(effective_access, http_status=http_status)
    if effective_access.access_status == ACCESS_STATUS_REQUIRES_SSO:
        reason_code = NO_ACCESS_REASON_AUTH_REQUIRED
    error_message = _normalized_reason_detail(effective_access, download, http_status=http_status, reason_code=reason_code)
    content_available = bool(effective_access.details.get("contentAvailable")) or bool(download.can_download)

    resource["canAccess"] = effective_access.can_access
    resource["can_access"] = effective_access.can_access
    resource["accessStatus"] = effective_access.access_status
    resource["access_status"] = effective_access.access_status
    resource["httpStatus"] = http_status
    resource["http_status"] = http_status
    resource["accessStatusCode"] = effective_access.http_status
    resource["access_status_code"] = effective_access.http_status
    resource["canDownload"] = download.can_download
    resource["can_download"] = download.can_download
    resource["downloadStatusCode"] = download.http_status
    resource["download_status_code"] = download.http_status
    resource["downloadStatus"] = "OK" if download.can_download else "NO_DESCARGABLE"
    resource["download_status"] = resource["downloadStatus"]
    if _download_url(resource):
        resource["downloadUrl"] = _download_url(resource)
        resource["download_url"] = resource["downloadUrl"]
    resource["errorMessage"] = error_message
    resource["error_message"] = error_message
    resource["accessNote"] = error_message
    resource["access_note"] = error_message
    resource["reasonCode"] = reason_code
    resource["reason_code"] = reason_code
    resource["reasonDetail"] = error_message
    resource["reason_detail"] = error_message
    resource["contentAvailable"] = content_available
    resource["content_available"] = content_available
    if effective_access.url_status is not None:
        resource["urlStatus"] = effective_access.url_status
    if effective_access.final_url is not None:
        resource["finalUrl"] = effective_access.final_url
    if effective_access.checked_at is not None:
        resource["checkedAt"] = effective_access.checked_at.isoformat() if isinstance(effective_access.checked_at, datetime) else effective_access.checked_at

    resource["status"] = _health_status_for(effective_access.access_status)
    details = dict(resource.get("details") or {})
    details["accessCheck"] = {
        "mode": mode,
        "canAccess": effective_access.can_access,
        "accessStatus": effective_access.access_status,
        "httpStatus": http_status,
        "canDownload": download.can_download,
        "contentAvailable": content_available,
        "errorMessage": error_message,
        "reasonCode": reason_code,
        "reasonDetail": error_message,
    }
    if effective_access.details:
        details["accessCheck"].update(effective_access.details)
    if download.details:
        details["downloadCheck"] = download.details
    if effective_access.access_status == ACCESS_STATUS_NO_ACCEDE:
        details["broken_link"] = {
            "url": resource.get("sourceUrl") or resource.get("url"),
            "reason": reason_code or effective_access.access_status,
            "statusCode": http_status,
        }
        _append_note(resource, _broken_link_note(effective_access.access_status, http_status))
    elif effective_access.access_status == ACCESS_STATUS_REQUIRES_INTERACTION:
        _append_note(resource, "requires_interaction: recurso Canvas que requiere sesión o acción del usuario.")
    elif effective_access.access_status == ACCESS_STATUS_REQUIRES_SSO:
        _append_note(resource, "requires_sso: el recurso redirige al SSO de UOC.")
    resource["details"] = details
    _log_access_result(resource)


def _access_from_url_result(result: UrlCheckResult, *, allow_canvas_forbidden: bool) -> AccessProbeResult:
    access_status = ACCESS_STATUS_OK
    if _url_result_requires_external_auth(result):
        access_status = ACCESS_STATUS_REQUIRES_SSO
    elif result.reason in {"timeout", "404_not_found", "forbidden", "canvas_auth_required"}:
        access_status = ACCESS_STATUS_NO_ACCEDE
    elif result.status_code in {401, 403, 404}:
        access_status = ACCESS_STATUS_NO_ACCEDE
    elif result.broken_link or not result.checked:
        access_status = ACCESS_STATUS_NO_ACCEDE

    return AccessProbeResult(
        can_access=access_status == ACCESS_STATUS_OK,
        access_status=access_status,
        http_status=result.status_code,
        error_message=result.error_message or _url_result_message(result, access_status),
        url_status=result.url_status,
        final_url=result.final_url,
        checked_at=result.checked_at,
        details={"url": result.url, "reason": result.reason, "checked": result.checked},
    )


def _access_from_app_error(exc: AppError) -> AccessProbeResult:
    return AccessProbeResult(
        can_access=False,
        access_status=ACCESS_STATUS_NO_ACCEDE,
        http_status=exc.status_code if exc.status_code >= 400 else None,
        error_message=exc.message,
        details={"code": exc.code},
    )


def _url_result_message(result: UrlCheckResult, access_status: str) -> str | None:
    if access_status == ACCESS_STATUS_OK:
        return None
    if access_status == ACCESS_STATUS_REQUIRES_SSO:
        return SSO_REASON_DETAIL
    if result.reason == "404_not_found" or result.status_code == 404:
        return "La URL devolvió 404."
    if result.reason in {"forbidden", "canvas_auth_required"} or result.status_code in {401, 403}:
        return f"La URL devolvió {result.status_code or 403}."
    if result.reason == "timeout":
        return "La URL ha excedido el tiempo de espera."
    if result.status_code is not None:
        return f"La URL devolvió {result.status_code}."
    return "No se ha podido acceder a la URL."


def _resolve_access_status(resource: dict[str, Any], access: AccessProbeResult, *, http_status: int | None) -> str:
    if access.access_status != ACCESS_STATUS_NO_ACCEDE:
        return access.access_status
    reason = str(access.details.get("reason") or "").strip().lower() if isinstance(access.details, dict) else ""
    if reason not in {"auth_required", "canvas_auth_required"} and http_status not in {401, 403}:
        return access.access_status
    if any(_is_sso_or_protected_auth_url(candidate if isinstance(candidate, str) else None) for candidate in _resource_url_candidates(resource, access)):
        return ACCESS_STATUS_REQUIRES_SSO
    return access.access_status


def _normalize_no_access_reason_code(access: AccessProbeResult, *, http_status: int | None) -> str | None:
    if access.access_status != ACCESS_STATUS_NO_ACCEDE:
        return None

    reason = access.details.get("reason") if isinstance(access.details, dict) else None
    normalized_reason = str(reason or "").strip().lower()

    if normalized_reason in {"404_not_found", "not_found"} or http_status == 404:
        return NO_ACCESS_REASON_NOT_FOUND
    if normalized_reason == "timeout":
        return NO_ACCESS_REASON_TIMEOUT
    if normalized_reason in {"canvas_auth_required", "auth_required", "forbidden"} or http_status in {401, 403}:
        return NO_ACCESS_REASON_FORBIDDEN
    if normalized_reason in {"ssl_error", "tls_error", "certificate_error"}:
        return NO_ACCESS_REASON_SSL_ERROR
    if normalized_reason in {"dns_error", "name_not_resolved"}:
        return NO_ACCESS_REASON_DNS_ERROR
    if normalized_reason in {"invalid_url", "unsupported_protocol"}:
        return NO_ACCESS_REASON_INVALID_URL

    detail_text = " ".join(
        part.strip().lower()
        for part in (access.error_message, access.details.get("code") if isinstance(access.details, dict) else None)
        if isinstance(part, str) and part.strip()
    )
    if any(marker in detail_text for marker in ("ssl", "certificate", "tls")):
        return NO_ACCESS_REASON_SSL_ERROR
    if any(marker in detail_text for marker in ("dns", "name or service not known", "name not resolved")):
        return NO_ACCESS_REASON_DNS_ERROR
    if any(marker in detail_text for marker in ("invalid url", "unsupported protocol")):
        return NO_ACCESS_REASON_INVALID_URL
    if normalized_reason in {"request_error", "network_error", "connect_error", "read_error", "write_error"} or detail_text:
        return NO_ACCESS_REASON_NETWORK_ERROR
    return NO_ACCESS_REASON_UNKNOWN


def _normalized_reason_detail(
    access: AccessProbeResult,
    download: DownloadProbeResult,
    *,
    http_status: int | None,
    reason_code: str | None,
) -> str | None:
    if access.access_status == ACCESS_STATUS_OK:
        return None
    if access.access_status == ACCESS_STATUS_REQUIRES_SSO:
        return SSO_REASON_DETAIL
    if access.access_status == ACCESS_STATUS_REQUIRES_INTERACTION:
        return INTERACTION_REASON_DETAIL

    detail = access.error_message or download.error_message
    if detail:
        return detail
    if access.access_status != ACCESS_STATUS_NO_ACCEDE:
        return "No se pudo determinar el estado de acceso del recurso."

    if reason_code == NO_ACCESS_REASON_NOT_FOUND:
        return "La URL o el recurso devolvió 404 y no se encontró."
    if reason_code == NO_ACCESS_REASON_TIMEOUT:
        return "La comprobación de acceso agotó el tiempo de espera."
    if reason_code == NO_ACCESS_REASON_AUTH_REQUIRED:
        return f"El recurso requiere autenticación y devolvió {http_status or 401}."
    if reason_code == NO_ACCESS_REASON_FORBIDDEN:
        return f"El acceso al recurso fue rechazado con {http_status or 403}."
    if reason_code == NO_ACCESS_REASON_SSL_ERROR:
        return "La conexión falló por un problema SSL/TLS."
    if reason_code == NO_ACCESS_REASON_DNS_ERROR:
        return "No se pudo resolver el dominio del recurso."
    if reason_code == NO_ACCESS_REASON_INVALID_URL:
        return "La URL del recurso no es válida o no puede interpretarse."
    if reason_code == NO_ACCESS_REASON_NETWORK_ERROR:
        return "La comprobación de acceso falló por un problema de red."
    return "Se intentó acceder al recurso, pero no fue posible determinar un motivo más preciso."


def _build_discovered_resource(
    *,
    reference: str,
    base_resource: dict[str, Any],
    source_url: str | None = None,
    file_path: str | None = None,
    origin: str | None = None,
    title: str | None = None,
    resource_type: str | None = None,
    file_id: str | None = None,
    page_id: str | None = None,
    normalized_url: str | None = None,
    download_candidate: bool = False,
) -> dict[str, Any]:
    resolved_resource_type = resource_type or _infer_resource_type(reference)
    resolved_title = title or _title_from_reference(reference)
    parent_item_path = _resource_item_path(base_resource)
    module_path = parent_item_path or _module_path(base_resource)
    module_title = _resource_module_title(base_resource) or section_title_from_path(module_path) or module_path
    section_title = _resource_section_title(base_resource) or section_title_from_path(module_path) or module_title
    item_path = (
        f"{parent_item_path} > {resolved_title}"
        if parent_item_path
        else f"{module_path} > {resolved_title}"
        if module_path
        else resolved_title
    )
    parent_id = base_resource.get("id")
    resolved_origin = origin or (
        "EXTERNAL_URL"
        if source_url
        else "INTERNAL_PAGE"
        if file_path and _is_html_reference(file_path)
        else "INTERNAL_FILE"
    )
    return {
        "id": "",
        "title": resolved_title,
        "type": resolved_resource_type,
        "origin": resolved_origin,
        "url": source_url,
        "sourceUrl": source_url,
        "downloadUrl": None,
        "download_url": None,
        "downloadStatus": None,
        "download_status": None,
        "path": file_path,
        "filePath": file_path,
        "localPath": file_path,
        "fileId": file_id,
        "pageId": page_id,
        "course_path": module_path,
        "coursePath": module_path,
        "module_path": module_path,
        "modulePath": module_path,
        "moduleTitle": module_title,
        "module_title": module_title,
        "sectionTitle": section_title,
        "section_title": section_title,
        "item_path": item_path,
        "itemPath": item_path,
        "parentResourceId": parent_id,
        "parentId": parent_id,
        "parent_resource_id": parent_id,
        "discovered": True,
        "contentAvailable": bool(file_path),
        "content_available": bool(file_path),
        "discoveredChildrenCount": 0,
        "discovered_children_count": 0,
        "status": ResourceHealthStatus.WARN.value,
        "accessNote": None,
        "access_note": None,
        "errorMessage": None,
        "error_message": None,
        "notes": None,
        "details": {
            "discoveredBy": DISCOVERED_BY_DEEP_SCAN,
            "parentResourceId": parent_id,
            "reference": reference,
            "normalizedUrl": normalized_url or normalize_url(reference) if source_url else None,
            "fileId": file_id,
            "pageId": page_id,
            "downloadCandidate": download_candidate,
        },
    }


def _normalize_child_resource(job_id: str, child: dict[str, Any], parent: dict[str, Any], *, depth: int) -> None:
    details = dict(child.get("details") or {})
    details.setdefault("discoveredBy", DISCOVERED_BY_DEEP_SCAN)
    details.setdefault("parentResourceId", parent.get("id"))
    details["discoveryDepth"] = depth
    child["details"] = details
    child["parentResourceId"] = details.get("parentResourceId")
    child["parentId"] = details.get("parentResourceId")
    child["parent_resource_id"] = details.get("parentResourceId")
    child["discoveryDepth"] = depth
    if not child.get("id"):
        seed = "|".join(
            [
                job_id,
                str(parent.get("id") or ""),
                str(child.get("fileId") or ""),
                str(child.get("sourceUrl") or child.get("url") or child.get("filePath") or child.get("path") or ""),
            ]
        )
        child["id"] = str(uuid5(NAMESPACE_URL, seed))
    _normalize_resource_defaults(child)


def _normalize_resource_defaults(resource: dict[str, Any]) -> None:
    resource.setdefault("type", _infer_resource_type(str(resource.get("sourceUrl") or resource.get("filePath") or "")))
    resource.setdefault("status", ResourceHealthStatus.WARN.value)
    resource.setdefault("discoveredChildrenCount", 0)
    resource.setdefault("discovered_children_count", resource.get("discoveredChildrenCount", 0))
    resource.setdefault("details", {})
    resource.setdefault("discovered", _is_discovered_resource(resource))
    module_path = _module_path(resource)
    resource.setdefault("coursePath", module_path)
    resource.setdefault("modulePath", module_path)
    resource.setdefault("course_path", resource.get("coursePath"))
    resource.setdefault("module_path", resource.get("modulePath"))
    resource.setdefault(
        "origin",
        "EXTERNAL_URL"
        if _resource_source_url(resource)
        else "INTERNAL_PAGE"
        if _is_html_reference(_resource_file_path(resource) or "")
        else "INTERNAL_FILE"
        if _resource_file_path(resource)
        else resource.get("origin"),
    )
    resource.setdefault("contentAvailable", bool(_resource_file_path(resource)))
    resource.setdefault("content_available", resource.get("contentAvailable"))


def _merge_discovered_file(resource: dict[str, Any], canvas_file) -> None:
    resource["fileId"] = canvas_file.id
    resource["downloadUrl"] = canvas_file.url
    resource["download_url"] = canvas_file.url
    resource["title"] = canvas_file.display_name or canvas_file.filename or resource.get("title")
    resource["type"] = _infer_resource_type(canvas_file.filename or canvas_file.url or "")
    details = dict(resource.get("details") or {})
    details.update(
        {
            "downloadUrl": canvas_file.url,
            "filename": canvas_file.filename,
            "displayName": canvas_file.display_name,
            "contentType": canvas_file.content_type,
            "htmlUrl": canvas_file.html_url,
        }
    )
    resource["details"] = details


def _attach_discovered_children(resources: list[dict[str, Any]], parent_children: dict[str, list[str]]) -> None:
    for resource in resources:
        resource_id = str(resource.get("id"))
        child_ids = parent_children.get(resource_id, [])
        if not child_ids:
            resource.setdefault("discoveredChildrenCount", 0)
            resource.setdefault("discovered_children_count", resource.get("discoveredChildrenCount", 0))
            continue

        resource["discoveredChildrenCount"] = len(child_ids)
        resource["discovered_children_count"] = len(child_ids)
        details = dict(resource.get("details") or {})
        deep_scan = dict(details.get("deepScan") or {})
        deep_scan["children"] = child_ids
        deep_scan["childrenCount"] = len(child_ids)
        details["deepScan"] = deep_scan
        resource["details"] = details


def _resource_source_url(resource: dict[str, Any]) -> str | None:
    for key in ("sourceUrl", "url"):
        value = resource.get(key)
        if isinstance(value, str) and value.strip().startswith(("http://", "https://")):
            return value.strip()
    return None


def _resource_file_path(resource: dict[str, Any]) -> str | None:
    for key in ("filePath", "localPath", "path"):
        value = resource.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _download_url(resource: dict[str, Any]) -> str | None:
    for key in ("downloadUrl", "download_url"):
        value = resource.get(key)
        if isinstance(value, str) and value.strip().startswith(("http://", "https://")):
            return value.strip()
    details = resource.get("details")
    if isinstance(details, dict):
        value = details.get("downloadUrl")
        if isinstance(value, str) and value.strip().startswith(("http://", "https://")):
            return value.strip()
    return None


def _canvas_type(resource: dict[str, Any]) -> str | None:
    details = resource.get("details")
    if isinstance(details, dict) and isinstance(details.get("canvasType"), str):
        return details["canvasType"]
    return None


def _extract_canvas_page_id(url: str, *, course_id: str) -> str | None:
    parsed = urlparse(url)
    marker = f"/courses/{course_id}/pages/"
    if marker not in parsed.path:
        return None
    return unquote(parsed.path.split(marker, 1)[1].split("/", 1)[0])


def _extract_canvas_file_id(url: str) -> str | None:
    parsed = urlparse(url)
    parts = [part for part in parsed.path.split("/") if part]
    if "files" not in parts:
        return None
    index = parts.index("files")
    if index + 1 >= len(parts):
        return None
    candidate = parts[index + 1]
    return candidate if candidate.isdigit() else None


def _download_result_is_ok(result: UrlCheckResult) -> bool:
    return result.checked and not result.broken_link and result.status_code is not None and 200 <= result.status_code < 300


def _url_probe_details(result: UrlCheckResult) -> dict[str, Any]:
    return {
        "url": result.url,
        "checked": result.checked,
        "statusCode": result.status_code,
        "urlStatus": result.url_status,
        "finalUrl": result.final_url,
        "reason": result.reason,
        "contentType": result.content_type,
        "contentDisposition": result.content_disposition,
        "redirected": result.redirected,
        "redirectLocation": result.redirect_location,
        "checkedAt": result.checked_at.isoformat() if isinstance(result.checked_at, datetime) else result.checked_at,
    }


def _should_deep_scan(resource: dict[str, Any]) -> bool:
    if resource.get("accessStatus") != ACCESS_STATUS_OK and not bool(resource.get("contentAvailable")):
        return False
    if str(resource.get("type") or "").upper() != "WEB":
        return False
    reference = str(resource.get("sourceUrl") or resource.get("url") or resource.get("filePath") or resource.get("path") or "")
    if resource.get("canDownload") is True and _canvas_type(resource) != "Page" and not _is_html_reference(reference):
        return False
    return _canvas_type(resource) in {"Page", "Assignment", "Discussion"} or _is_html_reference(
        reference
    ) or "/courses/" in reference


def _is_deep_scan_child(resource: dict[str, Any]) -> bool:
    details = resource.get("details")
    return isinstance(details, dict) and details.get("discoveredBy") == DISCOVERED_BY_DEEP_SCAN


def _is_discovered_resource(resource: dict[str, Any]) -> bool:
    details = resource.get("details")
    if not isinstance(details, dict):
        return False
    if details.get("discoveredBy") == DISCOVERED_BY_DEEP_SCAN:
        return True
    html_discovery = details.get("htmlDiscovery")
    return isinstance(html_discovery, dict) and bool(html_discovery.get("discovered"))


def _dedupe_key(resource: dict[str, Any]) -> tuple[str, str]:
    file_id = resource.get("fileId")
    if file_id is not None and str(file_id).strip():
        return ("file", str(file_id).strip())

    page_id = resource.get("pageId")
    if page_id is not None and str(page_id).strip():
        return ("page", str(page_id).strip().lower())

    source_url = _resource_source_url(resource)
    if source_url:
        return ("url", normalize_url(source_url))
    file_path = _resource_file_path(resource)
    if file_path:
        return ("path", file_path.split("#", 1)[0].replace("\\", "/").lower())
    return ("id", str(resource.get("id")))


def normalize_url(url: str) -> str:
    parsed = urlparse(url.strip())
    normalized = parsed._replace(fragment="")
    return normalized.geturl().rstrip("/").lower()


def _module_path(resource: dict[str, Any]) -> str:
    for key in ("modulePath", "module_path", "coursePath", "course_path"):
        value = resource.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return "Modulo general"


def _resource_module_title(resource: dict[str, Any]) -> str | None:
    for key in ("moduleTitle", "module_title"):
        value = resource.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _resource_section_title(resource: dict[str, Any]) -> str | None:
    for key in ("sectionTitle", "section_title"):
        value = resource.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _resource_item_path(resource: dict[str, Any]) -> str | None:
    for key in ("itemPath", "item_path"):
        value = resource.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _module_group_key(resource: dict[str, Any]) -> str:
    module_path = _module_path(resource)
    key = section_key_from_path(module_path)
    if key:
        return key

    section_title = resource.get("sectionTitle") or resource.get("section_title") or section_title_from_path(module_path)
    if isinstance(section_title, str) and section_title.strip():
        return build_section_key(section_title.strip())
    return build_section_key(module_path)


def _badge_for(access_status: str) -> dict[str, str]:
    labels = {
        ACCESS_STATUS_OK: "OK",
        ACCESS_STATUS_NO_ACCEDE: "NO ACCEDE",
        ACCESS_STATUS_REQUIRES_INTERACTION: "REQUIERE INTERACCION",
        ACCESS_STATUS_REQUIRES_SSO: "REQUIERE SSO",
    }
    tones = {
        ACCESS_STATUS_OK: "success",
        ACCESS_STATUS_NO_ACCEDE: "danger",
        ACCESS_STATUS_REQUIRES_INTERACTION: "warning",
        ACCESS_STATUS_REQUIRES_SSO: "warning",
    }
    return {"label": labels.get(access_status, "Error"), "tone": tones.get(access_status, "danger")}


def _health_status_for(access_status: str) -> str:
    if access_status == ACCESS_STATUS_OK:
        return ResourceHealthStatus.OK.value
    if access_status in {ACCESS_STATUS_REQUIRES_INTERACTION, ACCESS_STATUS_REQUIRES_SSO}:
        return ResourceHealthStatus.WARN.value
    return ResourceHealthStatus.ERROR.value


def _broken_link_note(access_status: str, http_status: int | None) -> str:
    if http_status is not None:
        return f"broken_link: URL devuelve {http_status}."
    return "broken_link: no se pudo acceder al recurso."


def _requires_interaction_result(
    canvas_type: str,
    *,
    http_status: int | None = None,
    message: str | None = None,
    details: dict[str, Any] | None = None,
) -> AccessProbeResult:
    return AccessProbeResult(
        can_access=False,
        access_status=ACCESS_STATUS_REQUIRES_INTERACTION,
        http_status=http_status,
        error_message=message or INTERACTION_REASON_DETAIL,
        details={"requiresInteraction": True, "canvasType": canvas_type, **dict(details or {})},
    )


def _canvas_content_id(resource: dict[str, Any]) -> str | None:
    for key in ("contentId", "content_id", "assignmentId", "discussionId", "quizId", "itemContentId", "fileId"):
        value = resource.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    details = resource.get("details")
    if isinstance(details, dict):
        for key in ("contentId", "assignmentId", "discussionId", "quizId"):
            value = details.get(key)
            if value is not None and str(value).strip():
                return str(value).strip()
    return None


def _canvas_api_url(resource: dict[str, Any]) -> str | None:
    for key in ("apiUrl", "api_url"):
        value = resource.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    details = resource.get("details")
    if isinstance(details, dict):
        value = details.get("apiUrl")
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _is_sso_url(url: str | None) -> bool:
    if not isinstance(url, str) or not url.strip():
        return False
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    if any(marker in host for marker in SSO_HOST_MARKERS):
        return True
    return host.endswith(".uoc.edu") and any(marker in f"{parsed.path.lower()}?{parsed.query.lower()}" for marker in SSO_PATH_MARKERS)


def _is_protected_external_auth_url(url: str | None) -> bool:
    if not isinstance(url, str) or not url.strip():
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


def _url_result_requires_external_auth(result: UrlCheckResult) -> bool:
    if not (
        result.reason in {"auth_required", "canvas_auth_required", "forbidden"}
        or result.status_code in {401, 403}
    ):
        return _is_sso_url(result.final_url) or _is_sso_url(result.redirect_location) or _is_sso_url(result.url)
    return any(
        _is_sso_or_protected_auth_url(candidate)
        for candidate in (result.final_url, result.redirect_location, result.url)
    )


def _resource_url_candidates(resource: dict[str, Any], access: AccessProbeResult) -> tuple[str | None, ...]:
    details_url = access.details.get("url") if isinstance(access.details, dict) else None
    download_details = resource.get("details") if isinstance(resource.get("details"), dict) else {}
    detail_download = download_details.get("downloadUrl") if isinstance(download_details, dict) else None
    return (
        access.final_url,
        details_url if isinstance(details_url, str) else None,
        resource.get("finalUrl") if isinstance(resource.get("finalUrl"), str) else None,
        resource.get("sourceUrl") if isinstance(resource.get("sourceUrl"), str) else None,
        resource.get("url") if isinstance(resource.get("url"), str) else None,
        detail_download if isinstance(detail_download, str) else None,
    )


def _origin_for_link(url: str | None, *, is_internal: bool) -> str:
    if _is_sso_url(url):
        return ORIGIN_RALTI
    return ORIGIN_ONLINE_CANVAS if is_internal else ORIGIN_EXTERNAL_URL


def _payload_has_html(payload: dict[str, Any] | None) -> bool:
    if not isinstance(payload, dict):
        return False
    for key in ("body", "html", "description", "message"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return True
    return False


def _log_access_result(resource: dict[str, Any]) -> None:
    logger.info(
        "Resource access analyzed",
        extra={
            "event": "resource_access_analyzed",
            "details": {
                "resourceId": resource.get("id"),
                "type": resource.get("type"),
                "canvasType": (resource.get("details") or {}).get("canvasType")
                if isinstance(resource.get("details"), dict)
                else None,
                "accessStatus": resource.get("accessStatus"),
                "httpStatus": resource.get("httpStatus"),
                "downloadStatusCode": resource.get("downloadStatusCode"),
                "canDownload": resource.get("canDownload"),
            },
        },
    )


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


def _is_html_reference(reference: str) -> bool:
    return Path(urlparse(reference).path or reference).suffix.lower() in HTML_EXTENSIONS


def _infer_resource_type(reference: str) -> str:
    parsed = urlparse(reference)
    suffix = Path(parsed.path or reference).suffix.lower()
    host = parsed.netloc.lower()
    if suffix == ".pdf":
        return "PDF"
    if suffix == ".docx":
        return "DOCX"
    if suffix in {".mp4", ".mov", ".webm", ".m4v"} or any(domain in host for domain in ("youtube.com", "youtu.be", "vimeo.com")):
        return "VIDEO"
    if suffix == ".ipynb":
        return "NOTEBOOK"
    if suffix in {".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp"}:
        return "IMAGE"
    if suffix in HTML_EXTENSIONS or parsed.scheme in {"http", "https"}:
        return "WEB"
    return "OTHER"


def _title_from_reference(reference: str) -> str:
    parsed = urlparse(reference)
    candidate = Path(unquote(parsed.path)).name or parsed.netloc or reference
    return candidate.strip() or "Recurso descubierto"


def _is_ignored_reference(reference: str) -> bool:
    cleaned = reference.strip().lower()
    return not cleaned or cleaned.startswith(("#", "mailto:", "tel:", "javascript:", "data:"))


def _normalize_relative_child_path(base_parent: PurePosixPath, reference: str) -> str | None:
    cleaned = reference.split("#", 1)[0].split("?", 1)[0].strip().replace("\\", "/")
    if not cleaned:
        return None
    path = PurePosixPath(unquote(cleaned))
    if path.is_absolute() or any(part == ".." for part in path.parts):
        return None
    return (base_parent / path).as_posix()


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
    return normalized_content_type.startswith(("application/", "audio/", "image/", "video/"))


def _looks_downloadable_reference(reference: str) -> bool:
    suffix = Path(urlparse(reference).path).suffix.lower()
    return suffix in DOWNLOADABLE_EXTENSIONS
