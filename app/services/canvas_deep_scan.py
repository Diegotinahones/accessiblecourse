from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse
from uuid import NAMESPACE_URL, uuid5

from bs4 import BeautifulSoup

from app.core.errors import AppError
from app.models.entities import ResourceHealthStatus, ResourceType
from app.services.access_check import DOWNLOADABLE_EXTENSIONS
from app.services.canvas_client import CanvasClient, CanvasCredentials, CanvasFile
from app.services.url_check import URLCheckService, UrlCheckResult

logger = logging.getLogger("accessiblecourse.canvas.deep_scan")

EXCLUDED_EXTENSIONS = {".imscc", ".imsmanifest", ".xml", ".xsd", ".qti", ".dtd"}
HTML_LINK_TAGS = ("a", "iframe", "source")
HTML_LINK_ATTRIBUTES = ("href", "src", "data-api-endpoint", "data-url", "data-download-url")
ACCESS_STATUS_OK = "OK"
ACCESS_STATUS_NO_ACCEDE = "NO_ACCEDE"
ACCESS_STATUS_REQUIRES_INTERACTION = "REQUIERE_INTERACCION"
ACCESS_STATUS_REQUIRES_SSO = "REQUIERE_SSO"
ACCESS_STATUS_ERROR = ACCESS_STATUS_NO_ACCEDE
ORIGIN_ONLINE_CANVAS = "ONLINE_CANVAS"
ORIGIN_EXTERNAL_URL = "EXTERNAL_URL"
ORIGIN_RALTI = "RALTI"
DEEP_SCAN_NAMESPACE = uuid5(NAMESPACE_URL, "accessiblecourse.canvas.deep-scan.resource")
FILE_ID_PATTERN = re.compile(r"/files/([^/?#]+)(?:/download)?(?:[/?#]|$)")
PAGE_URL_PATTERN = re.compile(r"/courses/([^/]+)/pages/([^/?#]+)")
SSO_HOST_MARKERS = ("id-provider.uoc.edu", "ralti.uoc.edu", "login.uoc.edu", "sso.uoc.edu")
SSO_PATH_MARKERS = ("sso", "saml", "oauth", "login", "id-provider", "ralti")


@dataclass(slots=True, frozen=True)
class DiscoveredCanvasLink:
    title: str
    url: str
    normalized_url: str
    html_tag: str
    html_attribute: str
    html_attrs: dict[str, str]
    parent_tag: str | None
    parent_attrs: dict[str, str]
    track_kinds: list[str]
    track_sources: list[str]
    file_id: str | None
    page_url: str | None
    is_internal: bool
    is_downloadable_candidate: bool
    resource_type: ResourceType


@dataclass(slots=True, frozen=True)
class CanvasDeepScanResult:
    discovered_resources: list[dict[str, Any]]
    scanned_pages: int
    skipped_pages: int
    rate_limited: int


def extract_canvas_links(
    html: str,
    *,
    base_url: str,
    course_id: str,
    allowed_host: str,
) -> list[DiscoveredCanvasLink]:
    soup = BeautifulSoup(html or "", "html.parser")

    discovered: dict[str, DiscoveredCanvasLink] = {}
    seen_file_ids: set[str] = set()

    for candidate in soup.find_all(HTML_LINK_TAGS):
        for attribute in HTML_LINK_ATTRIBUTES:
            raw_url = _html_attr(candidate, attribute)
            if not isinstance(raw_url, str) or not raw_url.strip():
                continue

            absolute_url = _normalize_absolute_url(raw_url, base_url)
            if absolute_url is None or _should_skip_url(absolute_url):
                continue

            normalized_url = normalize_url(absolute_url)
            parsed = urlparse(normalized_url)
            is_internal = parsed.netloc.lower() == allowed_host.lower()
            file_id = _extract_file_id(normalized_url)
            page_url = _extract_page_url(normalized_url, course_id=course_id)
            is_downloadable_candidate = _is_downloadable_candidate(normalized_url, file_id=file_id)
            resource_type = _infer_resource_type(normalized_url, is_downloadable_candidate=is_downloadable_candidate)
            title = _extract_link_title(candidate, absolute_url)
            dedupe_key = f"file:{file_id}" if file_id else f"url:{normalized_url}"

            if file_id and file_id in seen_file_ids:
                continue
            existing = discovered.get(dedupe_key)
            if existing and existing.is_downloadable_candidate:
                continue

            if file_id:
                seen_file_ids.add(file_id)
            discovered[dedupe_key] = DiscoveredCanvasLink(
                title=title,
                url=absolute_url,
                normalized_url=normalized_url,
                html_tag=str(getattr(candidate, "name", "") or "").lower(),
                html_attribute=attribute,
                html_attrs=_html_attrs_payload(candidate),
                parent_tag=_html_parent_tag(candidate),
                parent_attrs=_html_attrs_payload(getattr(candidate, "parent", None)),
                track_kinds=_html_track_values(candidate, "kind"),
                track_sources=_html_track_values(candidate, "src"),
                file_id=file_id,
                page_url=page_url,
                is_internal=is_internal,
                is_downloadable_candidate=is_downloadable_candidate,
                resource_type=resource_type,
            )

    return list(discovered.values())


def deep_scan_canvas_resources(
    client: CanvasClient,
    *,
    course_id: str,
    resources: list[dict[str, Any]],
    url_checker: URLCheckService,
    credentials: CanvasCredentials,
    max_depth: int = 2,
    max_pages: int = 50,
) -> CanvasDeepScanResult:
    if max_depth <= 0 or max_pages <= 0:
        return CanvasDeepScanResult(discovered_resources=[], scanned_pages=0, skipped_pages=0, rate_limited=0)

    allowed_host = urlparse(credentials.base_url).netloc.lower()
    seen_urls = _collect_seen_urls(resources)
    seen_file_ids = _collect_seen_file_ids(resources)
    discovered_resources: list[dict[str, Any]] = []
    parent_children: dict[str, list[str]] = {}
    queue: list[tuple[dict[str, Any], int]] = [
        (resource, 0)
        for resource in resources
        if _is_scannable_html_resource(resource, allowed_host=allowed_host, course_id=course_id)
    ]
    visited_pages: set[str] = set()
    scanned_pages = 0
    skipped_pages = 0
    rate_limited = 0

    while queue:
        parent_resource, depth = queue.pop(0)
        if depth >= max_depth:
            skipped_pages += 1
            continue
        if scanned_pages >= max_pages:
            skipped_pages += 1
            continue

        page_key = _page_dedupe_key(parent_resource)
        if page_key in visited_pages:
            continue
        visited_pages.add(page_key)

        html, page_status = _load_resource_html(client, course_id=course_id, resource=parent_resource)
        if html is None:
            if page_status == 429:
                rate_limited += 1
                _backoff(rate_limited)
            skipped_pages += 1
            continue

        scanned_pages += 1
        links = extract_canvas_links(
            html,
            base_url=_resource_url(parent_resource) or credentials.base_url,
            course_id=course_id,
            allowed_host=allowed_host,
        )

        for link in links:
            if link.file_id and link.file_id in seen_file_ids:
                continue
            if link.normalized_url in seen_urls:
                continue

            child = _build_discovered_resource(
                course_id=course_id,
                parent_resource=parent_resource,
                link=link,
                depth=depth + 1,
            )
            if link.file_id:
                seen_file_ids.add(link.file_id)
            seen_urls.add(link.normalized_url)

            _verify_discovered_resource(
                client,
                course_id=course_id,
                resource=child,
                link=link,
                url_checker=url_checker,
                credentials=credentials,
            )
            if child.get("downloadUrl"):
                seen_urls.add(normalize_url(str(child["downloadUrl"])))
            if child.get("downloadStatusCode") == 429 or child.get("accessStatusCode") == 429:
                rate_limited += 1
                _backoff(rate_limited)

            resources.append(child)
            discovered_resources.append(child)
            parent_children.setdefault(str(parent_resource["id"]), []).append(str(child["id"]))
            _log_discovered_resource(parent_resource, child)

            if (
                link.is_internal
                and child.get("canAccess") is True
                and child.get("type") == ResourceType.WEB.value
                and not child.get("canDownload")
                and depth + 1 < max_depth
            ):
                queue.append((child, depth + 1))

    _attach_parent_child_counts(resources, parent_children)
    return CanvasDeepScanResult(
        discovered_resources=discovered_resources,
        scanned_pages=scanned_pages,
        skipped_pages=skipped_pages,
        rate_limited=rate_limited,
    )


def normalize_url(url: str) -> str:
    parsed = urlparse(url)
    query = urlencode(sorted(parse_qsl(parsed.query, keep_blank_values=True)), doseq=True)
    return urlunparse(
        (
            parsed.scheme.lower(),
            parsed.netloc.lower(),
            parsed.path or "/",
            "",
            query,
            "",
        )
    )


def _normalize_absolute_url(raw_url: str, base_url: str) -> str | None:
    stripped = raw_url.strip()
    if not stripped or stripped.startswith(("#", "mailto:", "tel:", "javascript:")):
        return None
    return urljoin(base_url, stripped)


def _should_skip_url(url: str) -> bool:
    suffix = Path(urlparse(url).path).suffix.lower()
    return suffix in EXCLUDED_EXTENSIONS


def _extract_file_id(url: str) -> str | None:
    match = FILE_ID_PATTERN.search(urlparse(url).path)
    return match.group(1) if match else None


def _extract_page_url(url: str, *, course_id: str) -> str | None:
    match = PAGE_URL_PATTERN.search(urlparse(url).path)
    if not match or match.group(1) != str(course_id):
        return None
    return match.group(2)


def _is_downloadable_candidate(url: str, *, file_id: str | None) -> bool:
    if file_id:
        return True
    parsed = urlparse(url)
    suffix = Path(parsed.path).suffix.lower()
    if suffix in DOWNLOADABLE_EXTENSIONS:
        return True
    normalized_query = parsed.query.lower()
    return "download" in parsed.path.lower() or "download" in normalized_query or "attachment" in normalized_query


def _infer_resource_type(url: str, *, is_downloadable_candidate: bool) -> ResourceType:
    parsed = urlparse(url)
    suffix = Path(parsed.path).suffix.lower()
    host = parsed.netloc.lower()
    if suffix == ".pdf":
        return ResourceType.PDF
    if suffix == ".docx":
        return ResourceType.DOCX
    if suffix in {".mp4", ".mov", ".webm", ".m4v"} or any(domain in host for domain in ("youtube.com", "youtu.be", "vimeo.com")):
        return ResourceType.VIDEO
    if suffix == ".ipynb":
        return ResourceType.NOTEBOOK
    if suffix in {".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp"}:
        return ResourceType.IMAGE
    if suffix in {".html", ".htm", ".xhtml"} or not is_downloadable_candidate:
        return ResourceType.WEB
    return ResourceType.OTHER


def _html_attr(candidate: Any, attribute: str) -> str | None:
    get_attr = getattr(candidate, "get", None)
    attrs = getattr(candidate, "attrs", None)
    if callable(get_attr):
        value = get_attr(attribute)
    elif isinstance(attrs, dict):
        value = attrs.get(attribute)
    else:
        return None

    if isinstance(value, list):
        return " ".join(str(item) for item in value if str(item).strip()).strip() or None
    return str(value).strip() if value is not None and str(value).strip() else None


def _html_attrs_payload(candidate: Any) -> dict[str, str]:
    attrs = getattr(candidate, "attrs", None)
    if not isinstance(attrs, dict):
        return {}
    payload: dict[str, str] = {}
    for key, value in attrs.items():
        if isinstance(value, list):
            payload[str(key)] = " ".join(str(item) for item in value if str(item).strip())
        elif value is None:
            payload[str(key)] = ""
        else:
            payload[str(key)] = str(value)
    return payload


def _html_parent_tag(candidate: Any) -> str | None:
    parent = getattr(candidate, "parent", None)
    name = getattr(parent, "name", None)
    return str(name).lower() if isinstance(name, str) and name else None


def _html_track_values(candidate: Any, attribute: str) -> list[str]:
    search_root = candidate
    parent = getattr(candidate, "parent", None)
    if getattr(parent, "name", None) == "video":
        search_root = parent
    find_all = getattr(search_root, "find_all", None)
    if not callable(find_all):
        return []
    values: list[str] = []
    for track in find_all("track"):
        value = _html_attr(track, attribute)
        if value:
            values.append(value)
    return values


def _extract_link_title(candidate: Any, url: str) -> str:
    text = getattr(candidate, "text", "")
    if not isinstance(text, str):
        get_text = getattr(candidate, "get_text", None)
        text = get_text(" ", strip=True) if callable(get_text) else ""
    text = re.sub(r"\s+", " ", text).strip()
    if text:
        return text
    for attribute in ("aria-label", "title", "download"):
        value = _html_attr(candidate, attribute)
        if isinstance(value, str) and value.strip():
            return value.strip()
    filename = Path(urlparse(url).path).name
    return filename or url


def _collect_seen_urls(resources: list[dict[str, Any]]) -> set[str]:
    seen: set[str] = set()
    for resource in resources:
        for key in ("sourceUrl", "url", "downloadUrl"):
            value = resource.get(key)
            if isinstance(value, str) and value.startswith(("http://", "https://")):
                seen.add(normalize_url(value))
    return seen


def _collect_seen_file_ids(resources: list[dict[str, Any]]) -> set[str]:
    return {
        str(file_id)
        for resource in resources
        if (file_id := resource.get("fileId")) is not None and str(file_id).strip()
    }


def _is_scannable_html_resource(resource: dict[str, Any], *, allowed_host: str, course_id: str) -> bool:
    if resource.get("canAccess") is not True:
        return False
    if resource.get("type") != ResourceType.WEB.value:
        return False
    details = resource.get("details") if isinstance(resource.get("details"), dict) else {}
    if details.get("canvasType") == "Page" or resource.get("pageId"):
        return True
    url = _resource_url(resource)
    if not url:
        return False
    parsed = urlparse(url)
    return parsed.netloc.lower() == allowed_host and f"/courses/{course_id}/" in parsed.path


def _resource_url(resource: dict[str, Any]) -> str | None:
    for key in ("sourceUrl", "url"):
        value = resource.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _page_dedupe_key(resource: dict[str, Any]) -> str:
    if resource.get("pageId"):
        return f"page:{resource['pageId']}"
    url = _resource_url(resource)
    return f"url:{normalize_url(url)}" if url else f"resource:{resource.get('id')}"


def _load_resource_html(
    client: CanvasClient,
    *,
    course_id: str,
    resource: dict[str, Any],
) -> tuple[str | None, int | None]:
    page_url = resource.get("pageId")
    url = _resource_url(resource)
    if not page_url and url:
        page_url = _extract_page_url(url, course_id=course_id)

    try:
        if isinstance(page_url, str) and page_url.strip():
            payload = client.get_page(course_id, page_url.strip())
            body = payload.get("body")
            if isinstance(body, str) and body.strip():
                return body, 200
            if not url:
                return "", 200
        if url:
            response = client.get_text(url)
            return response.text, response.status_code
    except AppError as exc:
        _attach_deep_scan_error(resource, exc)
        return None, exc.status_code
    return None, None


def _build_discovered_resource(
    *,
    course_id: str,
    parent_resource: dict[str, Any],
    link: DiscoveredCanvasLink,
    depth: int,
) -> dict[str, Any]:
    parent_id = str(parent_resource["id"])
    resource_id = str(uuid5(DEEP_SCAN_NAMESPACE, f"{course_id}|{parent_id}|{link.file_id or link.normalized_url}"))
    parent_path = parent_resource.get("itemPath") or parent_resource.get("title")
    module_path = parent_path or parent_resource.get("modulePath") or parent_resource.get("coursePath") or "Curso online"
    return {
        "id": resource_id,
        "courseId": course_id,
        "moduleId": parent_resource.get("moduleId"),
        "moduleName": parent_resource.get("moduleName"),
        "itemId": None,
        "pageId": link.page_url,
        "fileId": link.file_id,
        "title": link.title,
        "type": link.resource_type.value,
        "origin": _origin_for_link(link.url, is_internal=link.is_internal),
        "source": "Canvas",
        "url": link.url,
        "sourceUrl": link.url,
        "downloadUrl": None,
        "download_url": None,
        "path": None,
        "localPath": None,
        "filePath": None,
        "course_path": module_path,
        "coursePath": module_path,
        "module_path": module_path,
        "modulePath": module_path,
        "item_path": f"{parent_path} > {link.title}",
        "itemPath": f"{parent_path} > {link.title}",
        "parentResourceId": parent_id,
        "parentId": parent_id,
        "parent_resource_id": parent_id,
        "discovered": True,
        "discoveredChildrenCount": 0,
        "discovered_children_count": 0,
        "status": ResourceHealthStatus.WARN.value,
        "canAccess": False,
        "can_access": False,
        "accessStatus": ACCESS_STATUS_ERROR,
        "access_status": ACCESS_STATUS_ERROR,
        "httpStatus": None,
        "http_status": None,
        "accessStatusCode": None,
        "access_status_code": None,
        "canDownload": False,
        "can_download": False,
        "downloadStatusCode": None,
        "download_status_code": None,
        "accessNote": None,
        "access_note": None,
        "errorMessage": None,
        "error_message": None,
        "notes": None,
        "details": {
            "canvasType": "DiscoveredLink",
            "deepScan": {
                "parentResourceId": parent_id,
                "depth": depth,
                "normalizedUrl": link.normalized_url,
                "tag": link.html_tag,
                "attribute": link.html_attribute,
                "elementAttrs": link.html_attrs,
                "parentTag": link.parent_tag,
                "parentAttrs": link.parent_attrs,
                "trackKinds": link.track_kinds,
                "trackSources": link.track_sources,
                "fileId": link.file_id,
                "pageUrl": link.page_url,
                "downloadCandidate": link.is_downloadable_candidate,
                "internal": link.is_internal,
            },
        },
    }


def _verify_discovered_resource(
    client: CanvasClient,
    *,
    course_id: str,
    resource: dict[str, Any],
    link: DiscoveredCanvasLink,
    url_checker: URLCheckService,
    credentials: CanvasCredentials,
) -> None:
    if not link.is_internal:
        _set_resource_state(
            resource,
            can_access=True,
            access_status=ACCESS_STATUS_OK,
            can_download=False,
            error_message="Enlace externo detectado en deep scan; se conserva sin seguirlo ni descargarlo.",
        )
        resource["status"] = ResourceHealthStatus.WARN.value
        _append_note(resource, "external_link: enlace externo no verificado.")
        return

    if link.is_downloadable_candidate:
        download_url = link.url
        if link.file_id:
            try:
                canvas_file = client.get_file(course_id, link.file_id)
                _merge_canvas_file_metadata(resource, canvas_file)
                download_url = canvas_file.url or link.url
            except AppError as exc:
                _attach_deep_scan_error(resource, exc)

        result = url_checker.check_url_no_redirects(download_url, credentials=credentials)
        _apply_download_check(resource, result, download_url=download_url)
        return

    if link.page_url:
        try:
            client.get_page(course_id, link.page_url)
            _set_resource_state(
                resource,
                can_access=True,
                access_status=ACCESS_STATUS_OK,
                status_code=200,
                can_download=False,
                error_message=None,
            )
        except AppError as exc:
            _apply_app_error(resource, exc)
        return

    result = url_checker.check_url_no_redirects(link.url, credentials=credentials)
    _apply_access_check(resource, result)


def _merge_canvas_file_metadata(resource: dict[str, Any], canvas_file: CanvasFile) -> None:
    resource["fileId"] = canvas_file.id
    resource["downloadUrl"] = canvas_file.url
    resource["download_url"] = canvas_file.url
    resource["title"] = canvas_file.display_name or canvas_file.filename or resource["title"]
    resource["type"] = _infer_resource_type(canvas_file.filename or canvas_file.url or "", is_downloadable_candidate=True).value
    details = dict(resource.get("details") or {})
    details.update(
        {
            "contentType": canvas_file.content_type,
            "filename": canvas_file.filename,
            "displayName": canvas_file.display_name,
            "downloadUrl": canvas_file.url,
            "htmlUrl": canvas_file.html_url,
        }
    )
    resource["details"] = details


def _apply_download_check(resource: dict[str, Any], result: UrlCheckResult, *, download_url: str) -> None:
    downloadable = result.checked and not result.broken_link and (
        result.status_code is not None and 200 <= result.status_code < 400
    )
    access_status = ACCESS_STATUS_OK if downloadable else _result_access_status(result)
    _set_resource_state(
        resource,
        can_access=downloadable,
        access_status=access_status,
        status_code=result.status_code,
        can_download=downloadable,
        download_status_code=result.status_code,
        error_message=None if downloadable else _result_error_message(result),
    )
    details = dict(resource.get("details") or {})
    details["downloadCheck"] = _url_result_payload(result, url=download_url)
    resource["details"] = details
    if not downloadable:
        _append_note(resource, f"download_unavailable: {_result_error_message(result)}")


def _apply_access_check(resource: dict[str, Any], result: UrlCheckResult) -> None:
    accessible = result.checked and not result.broken_link and (
        result.status_code is not None and 200 <= result.status_code < 400
    )
    _set_resource_state(
        resource,
        can_access=accessible,
        access_status=ACCESS_STATUS_OK if accessible else _result_access_status(result),
        status_code=result.status_code,
        can_download=False,
        error_message=None if accessible else _result_error_message(result),
    )
    details = dict(resource.get("details") or {})
    details["accessCheck"] = _url_result_payload(result, url=result.url)
    resource["details"] = details


def _apply_app_error(resource: dict[str, Any], exc: AppError) -> None:
    _set_resource_state(
        resource,
        can_access=False,
        access_status=_app_error_status(exc),
        status_code=exc.status_code,
        can_download=False,
        error_message=exc.message,
    )
    _attach_deep_scan_error(resource, exc)


def _set_resource_state(
    resource: dict[str, Any],
    *,
    can_access: bool,
    access_status: str,
    can_download: bool,
    status_code: int | None = None,
    download_status_code: int | None = None,
    error_message: str | None,
) -> None:
    resource["canAccess"] = can_access
    resource["can_access"] = can_access
    resource["accessStatus"] = access_status
    resource["access_status"] = access_status
    resource["httpStatus"] = status_code
    resource["http_status"] = status_code
    resource["accessStatusCode"] = status_code
    resource["access_status_code"] = status_code
    resource["canDownload"] = can_download
    resource["can_download"] = can_download
    resource["downloadStatusCode"] = download_status_code
    resource["download_status_code"] = download_status_code
    resource["errorMessage"] = error_message
    resource["error_message"] = error_message
    resource["accessNote"] = error_message
    resource["access_note"] = error_message
    resource["status"] = (
        ResourceHealthStatus.OK.value
        if access_status == ACCESS_STATUS_OK
        else ResourceHealthStatus.WARN.value
        if access_status in {ACCESS_STATUS_REQUIRES_INTERACTION, ACCESS_STATUS_REQUIRES_SSO}
        else ResourceHealthStatus.ERROR.value
    )


def _url_result_payload(result: UrlCheckResult, *, url: str) -> dict[str, Any]:
    return {
        "url": url,
        "checked": result.checked,
        "statusCode": result.status_code,
        "urlStatus": result.url_status,
        "finalUrl": result.final_url,
        "reason": result.reason,
        "contentType": result.content_type,
        "contentDisposition": result.content_disposition,
        "redirected": result.redirected,
        "redirectLocation": result.redirect_location,
        "checkedAt": result.checked_at.isoformat() if result.checked_at else None,
    }


def _result_access_status(result: UrlCheckResult) -> str:
    if _is_sso_url(result.final_url) or _is_sso_url(result.redirect_location) or _is_sso_url(result.url):
        return ACCESS_STATUS_REQUIRES_SSO
    return ACCESS_STATUS_NO_ACCEDE


def _result_error_message(result: UrlCheckResult) -> str:
    if result.error_message:
        return result.error_message
    if result.status_code is not None:
        return f"La URL devolvio {result.status_code}."
    if result.reason == "timeout":
        return "La URL ha excedido el tiempo de espera."
    return "No se ha podido verificar el recurso descubierto."


def _app_error_status(exc: AppError) -> str:
    return ACCESS_STATUS_NO_ACCEDE


def _is_sso_url(url: str | None) -> bool:
    if not isinstance(url, str) or not url.strip():
        return False
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    if any(marker in host for marker in SSO_HOST_MARKERS):
        return True
    return host.endswith(".uoc.edu") and any(marker in f"{parsed.path.lower()}?{parsed.query.lower()}" for marker in SSO_PATH_MARKERS)


def _origin_for_link(url: str | None, *, is_internal: bool) -> str:
    if _is_sso_url(url):
        return ORIGIN_RALTI
    return ORIGIN_ONLINE_CANVAS if is_internal else ORIGIN_EXTERNAL_URL


def _attach_deep_scan_error(resource: dict[str, Any], exc: AppError) -> None:
    details = dict(resource.get("details") or {})
    deep_scan = dict(details.get("deepScan") or {})
    deep_scan["error"] = {"code": exc.code, "statusCode": exc.status_code, "message": exc.message}
    details["deepScan"] = deep_scan
    resource["details"] = details


def _attach_parent_child_counts(resources: list[dict[str, Any]], parent_children: dict[str, list[str]]) -> None:
    for resource in resources:
        resource_id = str(resource.get("id"))
        children = parent_children.get(resource_id, [])
        if not children:
            resource.setdefault("discoveredChildrenCount", 0)
            resource.setdefault("discovered_children_count", 0)
            continue

        resource["discoveredChildrenCount"] = len(children)
        resource["discovered_children_count"] = len(children)
        details = dict(resource.get("details") or {})
        deep_scan = dict(details.get("deepScan") or {})
        deep_scan["children"] = children
        deep_scan["childrenCount"] = len(children)
        details["deepScan"] = deep_scan
        resource["details"] = details


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


def _backoff(rate_limited_count: int) -> None:
    time.sleep(min(0.25 * max(rate_limited_count, 1), 2.0))


def _log_discovered_resource(parent: dict[str, Any], child: dict[str, Any]) -> None:
    logger.info(
        "Canvas deep scan resource discovered",
        extra={
            "event": "canvas_deep_scan_resource",
            "details": {
                "parentResourceId": parent.get("id"),
                "resourceId": child.get("id"),
                "title": child.get("title"),
                "accessStatus": child.get("accessStatus"),
                "accessStatusCode": child.get("accessStatusCode"),
                "canDownload": child.get("canDownload"),
                "downloadStatusCode": child.get("downloadStatusCode"),
            },
        },
    )
