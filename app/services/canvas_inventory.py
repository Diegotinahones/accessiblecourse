from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from uuid import NAMESPACE_URL, uuid5

from app.core.errors import AppError
from app.models.entities import ResourceHealthStatus, ResourceType
from app.services.access_check import build_access_status_counts
from app.services.canvas_client import CanvasClient, CanvasCredentials, CanvasFile, CanvasModule, CanvasModuleItem
from app.services.url_check import URLCheckService, UrlCheckResult

logger = logging.getLogger("accessiblecourse.canvas")

EXCLUDED_EXTENSIONS = {
    ".imscc",
    ".imsmanifest",
    ".xml",
    ".xsd",
    ".qti",
    ".dtd",
}

ORIGIN_ONLINE_CANVAS = "ONLINE_CANVAS"
ORIGIN_EXTERNAL_URL = "EXTERNAL_URL"
ORIGIN_RALTI = "RALTI"
ORIGIN_LTI = "LTI"
ORIGIN_INTERNO = ORIGIN_ONLINE_CANVAS
ORIGIN_EXTERNO = ORIGIN_EXTERNAL_URL
SOURCE_CANVAS = "Canvas"
ACCESS_STATUS_OK = "OK"
ACCESS_STATUS_NO_ACCEDE = "NO_ACCEDE"
ACCESS_STATUS_REQUIRES_INTERACTION = "REQUIERE_INTERACCION"
ACCESS_STATUS_REQUIRES_SSO = "REQUIERE_SSO"
ACCESS_STATUS_ERROR = ACCESS_STATUS_NO_ACCEDE
RESOURCE_ID_NAMESPACE = uuid5(NAMESPACE_URL, "accessiblecourse.canvas.resource")
SSO_HOST_MARKERS = ("id-provider.uoc.edu", "ralti.uoc.edu", "login.uoc.edu", "sso.uoc.edu")
SSO_PATH_MARKERS = ("sso", "saml", "oauth", "login", "id-provider", "ralti")


@dataclass(slots=True, frozen=True)
class CanvasInventoryBuild:
    resources: list[dict[str, Any]]
    modules: list[dict[str, Any]]
    items_read: int
    accessible: int
    downloadable: int
    checked_urls: int
    by_status: dict[str, int]
    broken_links: list[dict[str, Any]]


def build_canvas_inventory(
    client: CanvasClient,
    *,
    course_id: str,
    modules: list[CanvasModule],
    url_checker: URLCheckService | None = None,
    credentials: CanvasCredentials | None = None,
    verify_access: bool = True,
) -> CanvasInventoryBuild:
    file_cache: dict[str, CanvasFile] = {}
    resources: list[dict[str, Any]] = []
    module_groups: list[dict[str, Any]] = []
    items_read = 0

    for module in modules:
        items = client.list_module_items(course_id, module.id)
        items_read += len(items)
        current_subheader: str | None = None
        module_resources: list[dict[str, Any]] = []

        for item in items:
            if item.type == "SubHeader":
                current_subheader = item.title
                continue

            resource = _build_resource(
                client,
                course_id=course_id,
                module=module,
                subheader=current_subheader,
                item=item,
                file_cache=file_cache,
                url_checker=url_checker,
                credentials=credentials,
                verify_access=verify_access,
            )
            if resource is None:
                continue

            resources.append(resource)
            module_resources.append(resource)
            _log_resource_result(resource)

        if module_resources:
            module_groups.append(_build_module_group(module, module_resources))

    if not resources:
        raise AppError(
            code="canvas_no_resources_found",
            message="No hemos encontrado recursos revisables en los modulos del curso de Canvas.",
            status_code=409,
        )

    by_status_counter = build_access_status_counts()
    for resource in resources:
        access_status = str(resource.get("accessStatus") or ACCESS_STATUS_ERROR)
        by_status_counter[access_status] = by_status_counter.get(access_status, 0) + 1
    broken_links = [_broken_link_payload(resource) for resource in resources if _resource_has_broken_link(resource)]

    return CanvasInventoryBuild(
        resources=resources,
        modules=module_groups,
        items_read=items_read,
        accessible=sum(1 for resource in resources if bool(resource.get("canAccess"))),
        downloadable=sum(1 for resource in resources if bool(resource.get("canDownload"))),
        checked_urls=sum(1 for resource in resources if bool((resource.get("details") or {}).get("urlCheck", {}).get("checked"))),
        by_status=by_status_counter,
        broken_links=broken_links,
    )


def _build_resource(
    client: CanvasClient,
    *,
    course_id: str,
    module: CanvasModule,
    subheader: str | None,
    item: CanvasModuleItem,
    file_cache: dict[str, CanvasFile],
    url_checker: URLCheckService | None,
    credentials: CanvasCredentials | None,
    verify_access: bool,
) -> dict[str, Any] | None:
    if item.type == "File":
        return _build_file_resource(
            client,
            course_id=course_id,
            module=module,
            subheader=subheader,
            item=item,
            file_cache=file_cache,
            url_checker=url_checker,
            credentials=credentials,
            verify_access=verify_access,
        )
    return _build_non_file_resource(
        client,
        course_id=course_id,
        module=module,
        subheader=subheader,
        item=item,
        url_checker=url_checker,
        credentials=credentials,
        verify_access=verify_access,
    )


def _build_file_resource(
    client: CanvasClient,
    *,
    course_id: str,
    module: CanvasModule,
    subheader: str | None,
    item: CanvasModuleItem,
    file_cache: dict[str, CanvasFile],
    url_checker: URLCheckService | None,
    credentials: CanvasCredentials | None,
    verify_access: bool,
) -> dict[str, Any] | None:
    file: CanvasFile | None = None
    file_error: AppError | None = None

    if item.content_id:
        try:
            if item.content_id not in file_cache:
                file_cache[item.content_id] = client.get_file(course_id, item.content_id)
            file = file_cache[item.content_id]
        except AppError as exc:
            file_error = exc

    local_path = _build_local_path(file.folder_full_name if file else None, file.filename if file else None)
    if _should_skip_resource(local_path or item.html_url or item.title):
        return None

    resource_type = _infer_resource_type(
        item_type="File",
        reference=local_path or item.html_url or item.title,
        content_type=file.content_type if file else None,
    )
    if resource_type is None:
        return None

    title = file.display_name if file and file.display_name else item.title or "Fichero sin titulo"
    resource = _base_resource(
        course_id=course_id,
        module=module,
        subheader=subheader,
        item=item,
        title=title,
        resource_type=resource_type,
        origin=ORIGIN_INTERNO,
        url=item.html_url or (file.html_url if file else None) or (file.url if file else None),
        local_path=local_path,
    )
    details = dict(resource["details"])
    details.update(
        {
            "canvasType": "File",
            "contentType": file.content_type if file else None,
            "downloadUrl": file.url if file else None,
            "filename": file.filename if file else None,
            "displayName": file.display_name if file else None,
        }
    )
    resource["fileId"] = item.content_id
    resource["downloadUrl"] = file.url if file else None
    resource["download_url"] = resource["downloadUrl"]
    resource["details"] = details

    if file_error is not None:
        _apply_app_error(
            resource,
            file_error,
            default_message="No hemos podido obtener los metadatos del fichero en Canvas.",
        )
        return resource

    if not verify_access:
        return resource

    if url_checker is None:
        _set_access_state(
            resource,
            can_access=True,
            access_status=ACCESS_STATUS_OK,
            http_status=200,
            can_download=bool(file and file.url),
        )
        return resource

    if not file or not file.url:
        _set_access_state(
            resource,
            can_access=True,
            access_status=ACCESS_STATUS_ERROR,
            can_download=False,
            error_message="Canvas no ha devuelto una URL de descarga para este fichero.",
        )
        _append_note(resource, "download_unavailable: Canvas no ha proporcionado URL de descarga.")
        return resource

    _apply_url_result(
        resource,
        url_checker.check_url(file.url, credentials=credentials),
        target_url=file.url,
        allow_download=True,
    )
    return resource


def _build_non_file_resource(
    client: CanvasClient,
    *,
    course_id: str,
    module: CanvasModule,
    subheader: str | None,
    item: CanvasModuleItem,
    url_checker: URLCheckService | None,
    credentials: CanvasCredentials | None,
    verify_access: bool,
) -> dict[str, Any] | None:
    resolved_url = item.external_url or item.html_url
    if item.type == "ExternalTool":
        resolved_url = item.external_url or item.html_url
    if not resolved_url and item.type not in {"Assignment", "Discussion", "Page", "Quiz", "ExternalTool"}:
        return None
    if _should_skip_resource(resolved_url or item.title):
        return None

    resource_type = _infer_resource_type(item_type=item.type, reference=resolved_url or item.title)
    if resource_type is None:
        return None

    origin = _origin_for_canvas_item(item, resolved_url)
    resource = _base_resource(
        course_id=course_id,
        module=module,
        subheader=subheader,
        item=item,
        title=item.title or "Recurso sin titulo",
        resource_type=resource_type,
        origin=origin,
        url=resolved_url,
        local_path=None,
    )
    resource["pageId"] = item.page_url
    details = dict(resource["details"])
    details["canvasType"] = item.type
    resource["details"] = details

    if not verify_access:
        return resource

    if item.type in {"Assignment", "Discussion", "Quiz"}:
        _set_access_state(
            resource,
            can_access=False,
            access_status=ACCESS_STATUS_REQUIRES_INTERACTION,
            can_download=False,
            error_message="Este recurso existe en Canvas, pero requiere una interaccion o sesion de navegador.",
        )
        resource["status"] = ResourceHealthStatus.WARN.value
        _append_note(resource, "requires_interaction: recurso Canvas que requiere sesion o accion del usuario.")
        return resource

    if item.type == "ExternalTool":
        if resolved_url and url_checker is not None:
            _apply_url_result(
                resource,
                url_checker.check_url(resolved_url, credentials=None),
                target_url=resolved_url,
                allow_download=False,
            )
            return resource
        _set_access_state(
            resource,
            can_access=False,
            access_status=ACCESS_STATUS_REQUIRES_INTERACTION,
            can_download=False,
            error_message="Herramienta externa/LTI sin URL verificable; requiere sesion interactiva.",
        )
        resource["status"] = ResourceHealthStatus.WARN.value
        _append_note(resource, "requires_interaction: herramienta externa o LTI.")
        return resource

    if url_checker is None and item.type == "ExternalUrl":
        return resource

    if item.type == "ExternalUrl" and resolved_url and url_checker is not None:
        _apply_url_result(
            resource,
            url_checker.check_url(resolved_url, credentials=credentials),
            target_url=resolved_url,
            allow_download=False,
        )
        return resource

    if item.type == "Page":
        if not item.page_url and not item.url:
            _set_access_state(
                resource,
                can_access=False,
                access_status=ACCESS_STATUS_ERROR,
                can_download=False,
                error_message="Canvas no ha devuelto una referencia API válida para esta página.",
            )
            return resource
        try:
            payload = (
                client.get_page(course_id, item.page_url)
                if item.page_url
                else client.get_json(item.url or "")
            )
        except AppError as exc:
            _apply_app_error(
                resource,
                exc,
                default_message="No hemos podido acceder al contenido de la pagina en Canvas.",
            )
            return resource

        _set_access_state(
            resource,
            can_access=True,
            access_status=ACCESS_STATUS_OK,
            http_status=200,
            can_download=False,
        )
        resource["details"] = {
            **dict(resource.get("details") or {}),
            **details,
            "pageUrl": payload.get("url"),
            "pageUpdatedAt": payload.get("updated_at"),
        }
        return resource

    api_reference = item.url or item.html_url
    if not api_reference:
        _set_access_state(
            resource,
            can_access=False,
            access_status=ACCESS_STATUS_ERROR,
            can_download=False,
            error_message="Canvas no ha devuelto una referencia util para comprobar este recurso.",
        )
        return resource

    try:
        if item.url:
            client.get_json(item.url)
            _set_access_state(
                resource,
                can_access=True,
                access_status=ACCESS_STATUS_OK,
                http_status=200,
                can_download=False,
            )
        elif url_checker is not None:
            _apply_url_result(
                resource,
                url_checker.check_url(api_reference, credentials=credentials),
                target_url=api_reference,
                allow_download=False,
            )
        else:
            _set_access_state(
                resource,
                can_access=False,
                access_status=ACCESS_STATUS_ERROR,
                can_download=False,
                error_message="No hemos podido verificar este recurso sin un comprobador de URLs.",
            )
    except AppError as exc:
        _apply_app_error(
            resource,
            exc,
            default_message="No hemos podido acceder al recurso interno de Canvas.",
        )

    return resource


def _base_resource(
    *,
    course_id: str,
    module: CanvasModule,
    subheader: str | None,
    item: CanvasModuleItem,
    title: str,
    resource_type: ResourceType,
    origin: str,
    url: str | None,
    local_path: str | None,
) -> dict[str, Any]:
    course_path = _build_course_path(module.name, subheader)
    item_path = _build_item_path(module.name, subheader, title)
    return {
        "id": _build_resource_id(
            course_id=course_id,
            module_id=module.id,
            item_id=item.id,
            item_type=item.type,
            content_id=item.content_id,
            page_url=item.page_url,
            external_url=item.external_url,
        ),
        "courseId": course_id,
        "moduleId": module.id,
        "moduleName": module.name,
        "position": item.position,
        "itemId": item.id,
        "contentId": item.content_id,
        "pageId": item.page_url,
        "fileId": item.content_id,
        "title": title,
        "type": resource_type.value,
        "origin": origin,
        "source": SOURCE_CANVAS,
        "url": url,
        "sourceUrl": url,
        "downloadUrl": None,
        "download_url": None,
        "path": local_path,
        "localPath": local_path,
        "filePath": local_path,
        "course_path": course_path,
        "coursePath": course_path,
        "module_path": course_path,
        "modulePath": course_path,
        "item_path": item_path,
        "itemPath": item_path,
        "status": _default_status(resource_type, origin).value,
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
        "downloadStatus": None,
        "download_status": None,
        "downloadStatusCode": None,
        "download_status_code": None,
        "discovered": False,
        "discoveredChildrenCount": 0,
        "discovered_children_count": 0,
        "accessNote": None,
        "access_note": None,
        "errorMessage": None,
        "error_message": None,
        "notes": None,
        "details": {
            "canvasType": item.type,
            "contentId": item.content_id,
            "courseId": course_id,
            "moduleId": module.id,
            "moduleName": module.name,
            "position": item.position,
            "htmlUrl": item.html_url,
            "externalUrl": item.external_url,
            "pageUrl": item.page_url,
            "apiUrl": item.url,
        },
    }


def _build_resource_id(
    *,
    course_id: str,
    module_id: str,
    item_id: str,
    item_type: str,
    content_id: str | None,
    page_url: str | None,
    external_url: str | None,
) -> str:
    seed = "|".join(
        [
            f"course:{course_id}",
            f"module:{module_id}",
            f"item:{item_id}",
            f"type:{item_type}",
            f"content:{content_id or ''}",
            f"page:{page_url or ''}",
            f"external:{external_url or ''}",
        ]
    )
    return str(uuid5(RESOURCE_ID_NAMESPACE, seed))


def _build_module_group(module: CanvasModule, resources: list[dict[str, Any]]) -> dict[str, Any]:
    by_status = build_access_status_counts()
    for resource in resources:
        access_status = str(resource.get("accessStatus") or ACCESS_STATUS_ERROR)
        by_status[access_status] = by_status.get(access_status, 0) + 1
    return {
        "moduleId": module.id,
        "moduleName": module.name,
        "total": len(resources),
        "accessible": sum(1 for resource in resources if bool(resource.get("canAccess"))),
        "downloadable": sum(1 for resource in resources if bool(resource.get("canDownload"))),
        "byStatus": by_status,
        "resources": resources,
    }


def _apply_url_result(
    resource: dict[str, Any],
    result: UrlCheckResult,
    *,
    target_url: str,
    allow_download: bool,
) -> None:
    details = dict(resource.get("details") or {})
    url_check_details: dict[str, Any] = {
        "checked": result.checked,
        "url": target_url,
    }
    if result.status_code is not None:
        url_check_details["statusCode"] = result.status_code
        resource["httpStatus"] = result.status_code
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

    if _is_sso_url(result.final_url) or _is_sso_url(result.redirect_location) or _is_sso_url(target_url):
        _set_access_state(
            resource,
            can_access=False,
            access_status=ACCESS_STATUS_REQUIRES_SSO,
            http_status=result.status_code,
            can_download=False,
            error_message="Requiere autenticacion SSO de UOC.",
        )
        resource["status"] = ResourceHealthStatus.WARN.value
        _append_note(resource, "requires_sso: el recurso redirige al SSO de UOC.")
        resource["details"] = {**dict(resource.get("details") or {}), **details}
        return

    if not result.checked:
        _set_access_state(
            resource,
            can_access=False,
            access_status=ACCESS_STATUS_ERROR,
            can_download=False,
            error_message=_url_check_message(result.reason),
        )
        resource["details"] = {**dict(resource.get("details") or {}), **details}
        return

    if result.reason == "canvas_auth_required":
        _set_access_state(
            resource,
            can_access=False,
            access_status=ACCESS_STATUS_NO_ACCEDE,
            http_status=result.status_code,
            can_download=False,
            error_message="Canvas ha rechazado el acceso al recurso con el token configurado.",
        )
        if not allow_download:
            resource["status"] = ResourceHealthStatus.WARN.value
        _append_note(resource, "forbidden: Canvas requiere permisos adicionales.")
        resource["details"] = {**dict(resource.get("details") or {}), **details}
        return

    if result.broken_link:
        _set_access_state(
            resource,
            can_access=False,
            access_status=_broken_link_status(result.reason),
            http_status=result.status_code,
            can_download=False,
            error_message=_url_check_message(result.reason, status_code=result.status_code),
        )
        details["broken_link"] = {
            "url": target_url,
            "reason": result.reason,
            "statusCode": result.status_code,
        }
        _append_note(resource, f"broken_link: {_url_check_message(result.reason, status_code=result.status_code)}")
        resource["details"] = {**dict(resource.get("details") or {}), **details}
        return

    _set_access_state(
        resource,
        can_access=True,
        access_status=ACCESS_STATUS_OK,
        http_status=result.status_code,
        can_download=allow_download,
    )
    resource["details"] = {**dict(resource.get("details") or {}), **details}


def _apply_app_error(resource: dict[str, Any], exc: AppError, *, default_message: str) -> None:
    http_status = exc.status_code if exc.status_code >= 400 else None
    access_status = ACCESS_STATUS_NO_ACCEDE
    resource["status"] = ResourceHealthStatus.ERROR.value

    _set_access_state(
        resource,
        can_access=False,
        access_status=access_status,
        http_status=http_status,
        can_download=False,
        error_message=exc.message or default_message,
    )
    details = dict(resource.get("details") or {})
    details["canvasError"] = {
        "code": exc.code,
        "message": exc.message or default_message,
        "statusCode": http_status,
    }
    if exc.status_code == 404:
        details["broken_link"] = {
            "url": resource.get("url"),
            "reason": "404_not_found",
            "statusCode": http_status,
        }
        _append_note(resource, "broken_link: Canvas devuelve 404 para este recurso.")
    elif exc.status_code in {401, 403}:
        _append_note(resource, "forbidden: Canvas no permite acceder al recurso con el token actual.")
    else:
        _append_note(resource, f"access_error: {exc.message or default_message}")
    resource["details"] = details


def _set_access_state(
    resource: dict[str, Any],
    *,
    can_access: bool,
    access_status: str,
    http_status: int | None = None,
    can_download: bool,
    error_message: str | None = None,
) -> None:
    resource["canAccess"] = can_access
    resource["can_access"] = can_access
    resource["accessStatus"] = access_status
    resource["access_status"] = access_status
    resource["httpStatus"] = http_status
    resource["http_status"] = http_status
    resource["accessStatusCode"] = http_status
    resource["access_status_code"] = http_status
    resource["canDownload"] = can_download
    resource["can_download"] = can_download
    resource["downloadStatus"] = "OK" if can_download else "NO_DESCARGABLE"
    resource["download_status"] = resource["downloadStatus"]
    resource["downloadStatusCode"] = http_status if can_download else None
    resource["download_status_code"] = resource["downloadStatusCode"]
    resource["errorMessage"] = error_message
    resource["error_message"] = error_message
    resource["accessNote"] = error_message
    resource["access_note"] = error_message
    details = dict(resource.get("details") or {})
    details["accessCheck"] = {
        "canAccess": can_access,
        "accessStatus": access_status,
        "httpStatus": http_status,
        "canDownload": can_download,
        "errorMessage": error_message,
    }
    resource["details"] = details
    if access_status == ACCESS_STATUS_OK:
        resource["status"] = ResourceHealthStatus.OK.value
    elif access_status in {ACCESS_STATUS_REQUIRES_INTERACTION, ACCESS_STATUS_REQUIRES_SSO}:
        resource["status"] = ResourceHealthStatus.WARN.value
    else:
        resource["status"] = ResourceHealthStatus.ERROR.value


def _resource_has_broken_link(resource: dict[str, Any]) -> bool:
    details = resource.get("details") or {}
    return isinstance(details, dict) and isinstance(details.get("broken_link"), dict)


def _broken_link_payload(resource: dict[str, Any]) -> dict[str, Any]:
    details = resource.get("details") or {}
    broken_link = details.get("broken_link") if isinstance(details, dict) else {}
    return {
        "resourceId": resource.get("id"),
        "title": resource.get("title"),
        "url": resource.get("sourceUrl") or resource.get("url"),
        "reason": broken_link.get("reason") if isinstance(broken_link, dict) else None,
        "statusCode": resource.get("httpStatus"),
        "urlStatus": resource.get("urlStatus"),
    }


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


def _url_check_message(reason: str | None, *, status_code: int | None = None) -> str:
    if reason == "404_not_found":
        return "URL devuelve 404."
    if reason == "timeout":
        return "La URL ha excedido el tiempo de espera."
    if reason == "canvas_auth_required":
        return "Canvas requiere permisos adicionales para este recurso."
    if status_code is not None and status_code >= 400:
        return f"URL devuelve {status_code}."
    if reason == "limit_not_checked":
        return "No se ha verificado la URL por limite de comprobaciones."
    return "No hemos podido verificar el acceso al recurso."


def _broken_link_status(reason: str | None) -> str:
    return ACCESS_STATUS_NO_ACCEDE


def _is_sso_url(url: str | None) -> bool:
    if not isinstance(url, str) or not url.strip():
        return False
    host = urlparse(url).netloc.lower()
    path = urlparse(url).path.lower()
    query = urlparse(url).query.lower()
    if any(marker in host for marker in SSO_HOST_MARKERS):
        return True
    return host.endswith(".uoc.edu") and any(marker in f"{path}?{query}" for marker in SSO_PATH_MARKERS)


def _origin_for_canvas_item(item: CanvasModuleItem, url: str | None) -> str:
    if item.type == "ExternalTool":
        return ORIGIN_RALTI if _is_sso_url(url) else ORIGIN_LTI
    if item.type == "ExternalUrl":
        return ORIGIN_RALTI if _is_sso_url(url) else ORIGIN_EXTERNAL_URL
    return ORIGIN_ONLINE_CANVAS


def _build_course_path(module: str, subheader: str | None) -> str:
    if subheader:
        return f"{module} > {subheader}"
    return module or "Curso online"


def _build_item_path(module: str, subheader: str | None, title: str) -> str:
    segments = [segment for segment in [module or "Curso online", subheader, title or "Recurso sin titulo"] if segment]
    return " > ".join(segments)


def _build_local_path(folder_full_name: str | None, filename: str | None) -> str | None:
    if not filename:
        return None
    if folder_full_name:
        return f"{folder_full_name.rstrip('/')}/{filename}"
    return filename


def _should_skip_resource(reference: str | None) -> bool:
    if not reference:
        return False
    parsed = urlparse(reference)
    filename = Path(parsed.path or reference)
    if filename.name.lower() == "imsmanifest.xml":
        return True
    return filename.suffix.lower() in EXCLUDED_EXTENSIONS


def _infer_resource_type(
    *,
    item_type: str,
    reference: str | None,
    content_type: str | None = None,
) -> ResourceType | None:
    normalized_content_type = (content_type or "").lower()
    if normalized_content_type.startswith("video/"):
        return ResourceType.VIDEO
    if normalized_content_type == "application/pdf":
        return ResourceType.PDF
    if normalized_content_type == "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
        return ResourceType.DOCX
    if normalized_content_type.startswith("image/"):
        return ResourceType.IMAGE

    parsed = urlparse(reference or "")
    suffix = Path(parsed.path or reference or "").suffix.lower()
    host = parsed.netloc.lower()

    if item_type in {"Page", "Assignment", "Discussion", "Quiz", "ExternalTool"}:
        return ResourceType.WEB
    if item_type == "ExternalUrl" and any(domain in host for domain in ("youtube.com", "youtu.be", "vimeo.com")):
        return ResourceType.VIDEO
    if suffix in {".html", ".htm", ".xhtml"}:
        return ResourceType.WEB
    if suffix == ".pdf":
        return ResourceType.PDF
    if suffix == ".docx":
        return ResourceType.DOCX
    if suffix in {".mp4", ".mov", ".webm", ".m4v"}:
        return ResourceType.VIDEO
    if suffix == ".ipynb":
        return ResourceType.NOTEBOOK
    if suffix in {".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp"}:
        return ResourceType.IMAGE
    if suffix in EXCLUDED_EXTENSIONS:
        return None

    return ResourceType.WEB if item_type == "ExternalUrl" else ResourceType.OTHER


def _default_status(resource_type: ResourceType, origin: str) -> ResourceHealthStatus:
    if resource_type == ResourceType.WEB and origin == ORIGIN_INTERNO:
        return ResourceHealthStatus.OK
    return ResourceHealthStatus.WARN


def _log_resource_result(resource: dict[str, Any]) -> None:
    logger.info(
        "Canvas resource verified",
        extra={
            "event": "canvas_resource_check",
            "details": {
                "resourceId": resource.get("id"),
                "moduleId": resource.get("moduleId"),
                "moduleName": resource.get("moduleName"),
                "itemId": resource.get("itemId"),
                "title": resource.get("title"),
                "canvasType": (resource.get("details") or {}).get("canvasType"),
                "accessStatus": resource.get("accessStatus"),
                "httpStatus": resource.get("httpStatus"),
                "canDownload": resource.get("canDownload"),
            },
        },
    )
