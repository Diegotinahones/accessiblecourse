from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse
from uuid import uuid4

from app.core.errors import AppError
from app.models.entities import ResourceHealthStatus, ResourceType
from app.services.canvas_client import CanvasClient, CanvasFile, CanvasModule

EXCLUDED_EXTENSIONS = {
    ".imscc",
    ".imsmanifest",
    ".xml",
    ".xsd",
    ".qti",
    ".dtd",
}

ORIGIN_INTERNO = "interno"
ORIGIN_EXTERNO = "externo"


@dataclass(slots=True, frozen=True)
class CanvasInventoryBuild:
    resources: list[dict[str, object]]
    items_read: int


def build_canvas_inventory(
    client: CanvasClient,
    *,
    course_id: str,
    modules: list[CanvasModule],
) -> CanvasInventoryBuild:
    file_cache: dict[str, CanvasFile] = {}
    resources: list[dict[str, object]] = []
    items_read = 0

    for module in modules:
        items = client.list_module_items(course_id, module.id)
        items_read += len(items)
        current_subheader: str | None = None

        for item in items:
            if item.type == "SubHeader":
                current_subheader = item.title
                continue

            if item.type == "File" and item.content_id:
                if item.content_id not in file_cache:
                    file_cache[item.content_id] = client.get_file(course_id, item.content_id)
                resource = _file_resource(
                    item=item,
                    module=module.name,
                    subheader=current_subheader,
                    file=file_cache[item.content_id],
                )
            else:
                resource = _generic_resource(
                    item_type=item.type,
                    title=item.title,
                    module=module.name,
                    subheader=current_subheader,
                    url=item.external_url or item.html_url,
                )

            if resource is None:
                continue

            resources.append(resource)

    if not resources:
        raise AppError(
            code="canvas_no_resources_found",
            message="No hemos encontrado recursos revisables en los modulos del curso de Canvas.",
            status_code=409,
        )

    return CanvasInventoryBuild(resources=resources, items_read=items_read)


def _file_resource(*, item, module: str, subheader: str | None, file: CanvasFile) -> dict[str, object] | None:
    local_path = _build_local_path(file.folder_full_name, file.filename)
    if _should_skip_resource(local_path):
        return None

    resource_type = _infer_resource_type(
        item_type="File",
        reference=local_path or file.url or item.html_url,
        content_type=file.content_type,
    )
    if resource_type is None:
        return None

    return {
        "id": str(uuid4()),
        "title": file.display_name or item.title,
        "type": resource_type.value,
        "origin": ORIGIN_INTERNO,
        "url": item.html_url or file.preview_url or file.html_url or file.url,
        "path": local_path,
        "localPath": local_path,
        "course_path": _build_course_path(module, subheader),
        "coursePath": _build_course_path(module, subheader),
        "status": _default_status(resource_type, ORIGIN_INTERNO).value,
        "details": {
            "canvasType": "File",
            "contentType": file.content_type,
        },
    }


def _generic_resource(
    *,
    item_type: str,
    title: str,
    module: str,
    subheader: str | None,
    url: str | None,
) -> dict[str, object] | None:
    if item_type == "ExternalTool" and not url:
        return None
    if not url and item_type not in {"Assignment", "Discussion", "Page", "Quiz"}:
        return None
    if _should_skip_resource(url):
        return None

    resource_type = _infer_resource_type(item_type=item_type, reference=url)
    if resource_type is None:
        return None
    origin = ORIGIN_EXTERNO if item_type == "ExternalUrl" else ORIGIN_INTERNO
    course_path = _build_course_path(module, subheader)

    return {
        "id": str(uuid4()),
        "title": title or "Recurso sin titulo",
        "type": resource_type.value,
        "origin": origin,
        "url": url,
        "path": None,
        "localPath": None,
        "course_path": course_path,
        "coursePath": course_path,
        "status": _default_status(resource_type, origin).value,
        "details": {
            "canvasType": item_type,
        },
    }


def _build_course_path(module: str, subheader: str | None) -> str:
    if subheader:
        return f"{module} > {subheader}"
    return module or "Curso online"


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
