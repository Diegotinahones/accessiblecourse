from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import urlparse
from uuid import NAMESPACE_URL, uuid5
from xml.etree import ElementTree as ET
from zipfile import BadZipFile, ZipFile

from bs4 import BeautifulSoup

from app.services.course_structure import normalize_course_structure

DEFAULT_MAX_ARCHIVE_MEMBERS = 2000
DEFAULT_MAX_ARCHIVE_MEMBER_SIZE = 256 * 1024 * 1024
DEFAULT_MAX_ARCHIVE_TOTAL_SIZE = 1024 * 1024 * 1024
HTML_DISCOVERY_NAMESPACE = uuid5(NAMESPACE_URL, "accessiblecourse.imscc.html-discovery")
HTML_RESOURCE_EXTENSIONS = {".html", ".htm"}
HTML_REFERENCE_ATTRIBUTES = (
    ("a", "href"),
    ("img", "src"),
    ("source", "src"),
    ("video", "src"),
    ("audio", "src"),
    ("iframe", "src"),
    ("embed", "src"),
    ("object", "data"),
)
IGNORED_REFERENCE_SCHEMES = {"mailto", "tel", "javascript", "data"}

EXCLUDED_METADATA_EXTENSIONS = {
    ".xml",
    ".xsd",
    ".dtd",
    ".qti",
    ".imsmanifest",
}


class ParserError(Exception):
    """Raised when an IMSCC package cannot be parsed safely."""


@dataclass(slots=True)
class ManifestResource:
    identifier: str
    resource_type: str | None
    href: str | None
    files: list[str]
    dependencies: list[str]
    title: str | None
    external_url: str | None


@dataclass(slots=True)
class ItemReference:
    item_identifier: str
    title: str | None
    course_path: str | None
    module_path: str | None


@dataclass(slots=True)
class ParsedManifest:
    course_title: str | None
    structure: dict[str, Any]
    resources: list[ManifestResource]
    item_map: dict[str, ItemReference]


@dataclass(slots=True)
class ManifestItem:
    node_id: str
    identifier: str | None
    raw_title: str | None
    resource_identifier: str | None
    children: list["ManifestItem"]


@dataclass(slots=True)
class ResolvedManifestItem:
    node_id: str
    identifier: str | None
    title: str
    resource_identifier: str | None
    children: list["ResolvedManifestItem"]


@dataclass(slots=True)
class HTMLReference:
    tag: str
    attribute: str
    reference: str
    title: str | None


@dataclass(slots=True)
class _OpenHTMLReference:
    tag: str
    reference: HTMLReference
    text_parts: list[str]


class HTMLReferenceParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.references: list[HTMLReference] = []
        self._open_references: list[_OpenHTMLReference] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        normalized_tag = tag.lower()
        attributes = {name.lower(): value for name, value in attrs if value is not None}
        for tag_name, attribute_name in HTML_REFERENCE_ATTRIBUTES:
            if normalized_tag != tag_name:
                continue
            raw_reference = attributes.get(attribute_name)
            if not raw_reference:
                continue
            title = attributes.get("title") or attributes.get("aria-label") or attributes.get("alt")
            reference = HTMLReference(
                tag=normalized_tag,
                attribute=attribute_name,
                reference=raw_reference.strip(),
                title=title.strip() if isinstance(title, str) and title.strip() else None,
            )
            self.references.append(reference)
            if normalized_tag == "a" and reference.title is None:
                self._open_references.append(_OpenHTMLReference(tag=normalized_tag, reference=reference, text_parts=[]))

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)

    def handle_data(self, data: str) -> None:
        for open_reference in self._open_references:
            open_reference.text_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        normalized_tag = tag.lower()
        for index in range(len(self._open_references) - 1, -1, -1):
            open_reference = self._open_references[index]
            if open_reference.tag != normalized_tag:
                continue
            self._apply_text_title(open_reference)
            del self._open_references[index:]
            return

    def close(self) -> None:
        super().close()
        for open_reference in self._open_references:
            self._apply_text_title(open_reference)
        self._open_references.clear()

    @staticmethod
    def _apply_text_title(open_reference: _OpenHTMLReference) -> None:
        if open_reference.reference.title is not None:
            return
        text = " ".join(part.strip() for part in open_reference.text_parts if part.strip()).strip()
        if text:
            open_reference.reference.title = " ".join(text.split())


def classify_resource(reference: str | None, *, is_external: bool = False) -> str:
    if not reference:
        return "OTHER"

    if is_external:
        host = urlparse(reference).netloc.lower()
        if any(domain in host for domain in ("youtube.com", "youtu.be", "vimeo.com")):
            return "VIDEO"
        return "WEB"

    suffix = Path(_strip_query_and_fragment(reference)).suffix.lower()
    if suffix in {".mp4", ".webm", ".mov"}:
        return "VIDEO"
    if suffix == ".pdf":
        return "PDF"
    if suffix in {".html", ".htm"}:
        return "WEB"
    if suffix == ".ipynb":
        return "NOTEBOOK"
    if suffix in {".png", ".jpg", ".jpeg", ".gif", ".svg"}:
        return "IMAGE"
    return "OTHER"


class IMSCCParser:
    def __init__(
        self,
        *,
        max_members: int = DEFAULT_MAX_ARCHIVE_MEMBERS,
        max_member_size: int = DEFAULT_MAX_ARCHIVE_MEMBER_SIZE,
        max_total_size: int = DEFAULT_MAX_ARCHIVE_TOTAL_SIZE,
    ) -> None:
        self.max_members = max_members
        self.max_member_size = max_member_size
        self.max_total_size = max_total_size

    def safe_extract_archive(self, archive_path: Path, destination: Path) -> list[str]:
        try:
            with ZipFile(archive_path) as archive:
                members = archive.infolist()
                if len(members) > self.max_members:
                    raise ParserError(f"El paquete contiene demasiados archivos ({len(members)}).")

                destination.mkdir(parents=True, exist_ok=True)
                root = destination.resolve()
                total_size = 0
                extracted_files: list[str] = []

                for member in members:
                    total_size += member.file_size
                    if member.file_size > self.max_member_size:
                        raise ParserError(f"El archivo '{member.filename}' excede el tamaño permitido.")
                    if total_size > self.max_total_size:
                        raise ParserError("El paquete IMSCC excede el tamaño total permitido.")

                    normalized_name = member.filename.replace("\\", "/")
                    if not normalized_name:
                        continue

                    pure_path = PurePosixPath(normalized_name)
                    if pure_path.is_absolute():
                        raise ParserError("El paquete contiene rutas absolutas no permitidas.")

                    target_path = (destination / normalized_name).resolve()
                    if not _is_within_root(target_path, root):
                        raise ParserError(f"Se detectó una ruta insegura en el zip: '{member.filename}'.")

                    if member.is_dir():
                        target_path.mkdir(parents=True, exist_ok=True)
                        continue

                    target_path.parent.mkdir(parents=True, exist_ok=True)
                    with archive.open(member, "r") as source, target_path.open("wb") as target:
                        shutil.copyfileobj(source, target, length=1024 * 1024)
                    extracted_files.append(target_path.relative_to(root).as_posix())

                return extracted_files
        except BadZipFile as exc:
            raise ParserError("El archivo subido no es un zip/IMSCC válido.") from exc

    def find_manifest(self, extracted_root: Path) -> Path:
        preferred = [
            extracted_root / "imsmanifest.xml",
            extracted_root / "course" / "imsmanifest.xml",
            extracted_root / "cc" / "imsmanifest.xml",
        ]
        for candidate in preferred:
            if candidate.exists():
                return candidate

        candidates = sorted(
            [path for path in extracted_root.rglob("*") if path.is_file() and path.name.lower() == "imsmanifest.xml"],
            key=lambda path: (len(path.relative_to(extracted_root).parts), str(path)),
        )
        if not candidates:
            raise ParserError("No se encontró 'imsmanifest.xml' dentro del paquete IMSCC.")
        return candidates[0]

    def parse_manifest(self, manifest_path: Path, extracted_root: Path) -> ParsedManifest:
        try:
            tree = ET.parse(manifest_path)
        except ET.ParseError as exc:
            raise ParserError("No se pudo parsear imsmanifest.xml.") from exc

        root = tree.getroot()
        course_title = self._extract_course_title(root) or manifest_path.parent.name or "Course"
        resources: list[ManifestResource] = []
        manifest_dir = manifest_path.parent
        for resources_node in self._find_children(root, "resources"):
            for resource in self._find_children(resources_node, "resource"):
                files = [
                    href
                    for href in (child.attrib.get("href") for child in self._find_children(resource, "file"))
                    if href
                ]
                dependencies = [
                    identifier_ref
                    for identifier_ref in (
                        child.attrib.get("identifierref") for child in self._find_children(resource, "dependency")
                    )
                    if identifier_ref
                ]
                manifest_resource = ManifestResource(
                    identifier=resource.attrib.get("identifier", ""),
                    resource_type=resource.attrib.get("type"),
                    href=resource.attrib.get("href"),
                    files=files,
                    dependencies=dependencies,
                    title=None,
                    external_url=resource.attrib.get("href").strip()
                    if resource.attrib.get("href") and self._is_external_url(resource.attrib.get("href"))
                    else None,
                )
                manifest_resource.title = self._resolve_resource_title(
                    manifest_resource,
                    manifest_dir=manifest_dir,
                    extracted_root=extracted_root,
                )
                resources.append(manifest_resource)

        resource_titles = {
            resource.identifier: resource.title for resource in resources if resource.identifier and resource.title
        }
        organization_nodes: list[dict[str, Any]] = []
        for organizations_index, organizations_node in enumerate(self._find_children(root, "organizations")):
            for organization_index, organization in enumerate(self._find_children(organizations_node, "organization")):
                parsed_children = [
                    self._collect_item(item, [organizations_index, organization_index, item_index])
                    for item_index, item in enumerate(self._find_children(organization, "item"))
                ]
                resolved_children = [self._resolve_item_titles(item, resource_titles) for item in parsed_children]
                organization_title = (
                    self._normalize_title(self._direct_child_text(organization, "title"))
                    or course_title
                    or "Estructura del curso"
                )
                children = [self._build_item_node(item, []) for item in resolved_children]
                organization_nodes.append(
                    {
                        "nodeId": f"organization:{organizations_index}:{organization_index}",
                        "identifier": organization.attrib.get("identifier"),
                        "title": organization_title,
                        "children": children,
                    }
                )

        normalized_structure = normalize_course_structure(
            {
                "title": course_title or "Estructura del curso",
                "organizations": organization_nodes,
                "unplacedResourceIds": [],
            }
        ) or {
            "title": course_title or "Estructura del curso",
            "organizations": [],
            "unplacedResourceIds": [],
        }

        item_map: dict[str, ItemReference] = {}
        for organization in normalized_structure.get("organizations", []):
            if not isinstance(organization, dict):
                continue
            for child in organization.get("children", []):
                if isinstance(child, dict):
                    self._register_item_paths(child, [], item_map)

        unplaced_resource_ids = [
            resource.identifier
            for resource in resources
            if resource.identifier and resource.identifier not in item_map
        ]

        return ParsedManifest(
            course_title=course_title,
            structure={**normalized_structure, "unplacedResourceIds": unplaced_resource_ids},
            resources=resources,
            item_map=item_map,
        )

    def build_resource_inventory(
        self,
        parsed_manifest: ParsedManifest,
        manifest_path: Path,
        extracted_root: Path,
        *,
        excluded_extensions: set[str] | None = None,
    ) -> list[dict[str, Any]]:
        inventory: list[dict[str, Any]] = []
        manifest_dir = manifest_path.parent
        resolved_root = extracted_root.resolve()
        effective_excluded_extensions = {
            extension.lower() for extension in (excluded_extensions or EXCLUDED_METADATA_EXTENSIONS)
        }

        for resource in parsed_manifest.resources:
            item_ref = parsed_manifest.item_map.get(resource.identifier)
            notes: list[str] = []
            status = "OK"
            declared_files = _unique_preserving_order(
                [
                    normalized
                    for normalized in (
                        self._normalize_reference(reference) for reference in [resource.href, *resource.files]
                    )
                    if normalized and not self._is_external_url(normalized)
                ]
            )
            resolved_files = [
                resolved_path
                for resolved_path in (
                    self._resolve_reference(reference, manifest_dir, extracted_root) for reference in declared_files
                )
                if resolved_path is not None
            ]
            resolved_file_refs = _unique_preserving_order(
                [path.relative_to(resolved_root).as_posix() for path in resolved_files]
            )

            external_url = resource.external_url

            path: str | None = None
            url: str | None = None
            origin = "INTERNAL_FILE"
            declared_href = self._normalize_reference(resource.href)
            content_available = False

            if external_url:
                origin = "EXTERNAL_URL"
                url = external_url
                primary_reference = external_url
            else:
                if declared_href and not self._is_external_url(declared_href):
                    resolved_href = self._resolve_reference(declared_href, manifest_dir, extracted_root)
                    if resolved_href is not None:
                        path = resolved_href.relative_to(resolved_root).as_posix()
                        content_available = True
                    elif resolved_file_refs:
                        path = resolved_file_refs[0]
                        content_available = True
                        notes.append(
                            f"El href principal '{declared_href}' no existe dentro del paquete; se usa el primer file disponible."
                        )
                        status = "WARN"
                    else:
                        notes.append(f"El href principal '{declared_href}' no existe dentro del paquete.")
                        status = "WARN"
                        path = declared_href
                elif resolved_file_refs:
                    path = resolved_file_refs[0]
                    content_available = True
                elif declared_files:
                    path = declared_files[0]
                    notes.append(f"El recurso referencia '{declared_files[0]}' pero no se encontró en el paquete.")
                    status = "WARN"
                else:
                    status = "ERROR"
                    notes.append("El recurso no define un href o file válido.")

                primary_reference = path or declared_href or resource.href

                if path and Path(path).suffix.lower() in HTML_RESOURCE_EXTENSIONS:
                    origin = "INTERNAL_PAGE"

            title = (item_ref.title if item_ref else None) or resource.title or _derive_title(primary_reference) or "Sin título"
            module_title = _module_title_from_item_ref(item_ref)
            section_title = _section_title_from_item_ref(item_ref, fallback_title=title)
            downloadable = bool(
                origin == "INTERNAL_FILE" and path and Path(path).suffix.lower() not in HTML_RESOURCE_EXTENSIONS
            )

            inventory.append(
                {
                    "id": resource.identifier,
                    "identifier": resource.identifier,
                    "title": title,
                    "type": classify_resource(url if origin == "external" else path, is_external=origin == "external"),
                    "origin": origin,
                    "url": url,
                    "sourceUrl": url,
                    "path": path if origin != "EXTERNAL_URL" else None,
                    "filePath": path if origin != "EXTERNAL_URL" else None,
                    "localPath": path if origin != "EXTERNAL_URL" else None,
                    "href": resource.href,
                    "files": resolved_file_refs or declared_files,
                    "dependencies": resource.dependencies,
                    "coursePath": item_ref.module_path if item_ref else None,
                    "course_path": item_ref.module_path if item_ref else None,
                    "modulePath": item_ref.module_path if item_ref else None,
                    "module_path": item_ref.module_path if item_ref else None,
                    "itemPath": item_ref.course_path if item_ref else None,
                    "item_path": item_ref.course_path if item_ref else None,
                    "moduleTitle": module_title,
                    "module_title": module_title,
                    "sectionTitle": section_title,
                    "section_title": section_title,
                    "parentId": None,
                    "parent_id": None,
                    "parentResourceId": None,
                    "parent_resource_id": None,
                    "discovered": False,
                    "downloadable": downloadable,
                    "contentAvailable": content_available,
                    "content_available": content_available,
                    "details": {
                        "mappedToCourseStructure": bool(item_ref),
                        "manifestResourceType": resource.resource_type,
                    },
                    "status": status,
                    "notes": notes,
                }
            )

        filtered_inventory = [
            resource
            for resource in inventory
            if not _should_skip_metadata_resource(
                resource.get("filePath") if isinstance(resource.get("filePath"), str) else None,
                resource.get("sourceUrl") if isinstance(resource.get("sourceUrl"), str) else None,
                effective_excluded_extensions,
            )
        ]
        return self._order_inventory_by_structure(filtered_inventory, parsed_manifest)

    def discover_html_linked_resources(
        self,
        inventory: list[dict[str, Any]],
        extracted_root: Path,
        *,
        excluded_extensions: set[str] | None = None,
    ) -> list[dict[str, Any]]:
        effective_excluded_extensions = {
            extension.lower() for extension in (excluded_extensions or EXCLUDED_METADATA_EXTENSIONS)
        }
        resources_by_path: dict[str, dict[str, Any]] = {}
        resources_by_url: dict[str, dict[str, Any]] = {}

        for resource in inventory:
            relative_path = _inventory_file_path(resource)
            if relative_path:
                resources_by_path.setdefault(relative_path, resource)
            source_url = _inventory_source_url(resource)
            if source_url:
                resources_by_url.setdefault(_normalize_external_url(source_url), resource)

        parent_child_ids: dict[str, list[str]] = {}
        discovered_resources: list[dict[str, Any]] = []

        for html_relative_path in self._collect_html_targets(inventory, extracted_root):
            html_path = _resolve_relative_path(extracted_root, html_relative_path)
            if html_path is None or not html_path.exists() or not html_path.is_file():
                continue

            parent_resource = resources_by_path.get(html_relative_path)
            context_resource = parent_resource or _find_context_resource_for_html(html_relative_path, resources_by_path)
            for candidate in self.extract_html_links(html_path, extracted_root):
                if candidate["kind"] == "external":
                    source_url = str(candidate["url"])
                    existing_resource = resources_by_url.get(_normalize_external_url(source_url))
                    child_resource = existing_resource
                    if child_resource is None:
                        child_resource = self._build_discovered_html_resource(
                            candidate,
                            parent_resource=parent_resource,
                            context_resource=context_resource,
                            parent_html_path=html_relative_path,
                        )
                        resources_by_url[_normalize_external_url(source_url)] = child_resource
                        discovered_resources.append(child_resource)
                    self._register_html_child(parent_resource, child_resource, parent_child_ids)
                    continue

                relative_path = str(candidate["path"])
                if Path(relative_path).suffix.lower() in HTML_RESOURCE_EXTENSIONS:
                    continue
                if _should_skip_metadata_resource(relative_path, None, effective_excluded_extensions):
                    continue

                existing_resource = resources_by_path.get(relative_path)
                child_resource = existing_resource
                if child_resource is None:
                    child_resource = self._build_discovered_html_resource(
                        candidate,
                        parent_resource=parent_resource,
                        context_resource=context_resource,
                        parent_html_path=html_relative_path,
                    )
                    resources_by_path[relative_path] = child_resource
                    discovered_resources.append(child_resource)
                self._register_html_child(parent_resource, child_resource, parent_child_ids)

        self._apply_html_discovery_details(inventory, parent_child_ids)
        return discovered_resources

    def extract_html_links(self, html_path: Path, extracted_root: Path) -> list[dict[str, str]]:
        relative_html_path = html_path.resolve().relative_to(extracted_root.resolve()).as_posix()
        soup = BeautifulSoup(html_path.read_text(encoding="utf-8", errors="ignore"), "html.parser")
        discovered: list[dict[str, str]] = []
        local_seen: set[str] = set()
        external_seen: set[str] = set()

        for tag_name, attribute_name in HTML_REFERENCE_ATTRIBUTES:
            for element in soup.find_all(tag_name):
                raw_reference = element.get(attribute_name)
                if not isinstance(raw_reference, str):
                    continue
                reference = raw_reference.strip()
                if not reference or reference.startswith("#") or self._should_skip_html_reference(reference):
                    continue

                title = _extract_html_reference_title(element, reference)
                if self._is_external_url(reference):
                    source_url = reference.strip()
                    normalized_url = _normalize_external_url(source_url)
                    if _looks_like_xml_reference(source_url) or normalized_url in external_seen:
                        continue
                    external_seen.add(normalized_url)
                    discovered.append(
                        {
                            "kind": "external",
                            "url": source_url,
                            "title": title or _derive_title(source_url),
                            "tag": tag_name,
                            "attribute": attribute_name,
                            "parentHtmlPath": relative_html_path,
                        }
                    )
                    continue

                resolved_path = self.resolve_html_reference(reference, html_path, extracted_root)
                if resolved_path is None or not resolved_path.exists() or not resolved_path.is_file():
                    continue

                relative_path = resolved_path.resolve().relative_to(extracted_root.resolve()).as_posix()
                if _looks_like_xml_reference(relative_path) or relative_path in local_seen:
                    continue
                local_seen.add(relative_path)
                discovered.append(
                    {
                        "kind": "local",
                        "path": relative_path,
                        "title": title or _derive_title(relative_path),
                        "tag": tag_name,
                        "attribute": attribute_name,
                        "parentHtmlPath": relative_html_path,
                    }
                )

        return discovered

    def _order_inventory_by_structure(
        self,
        inventory: list[dict[str, Any]],
        parsed_manifest: ParsedManifest,
    ) -> list[dict[str, Any]]:
        ordered_ids = list(_iter_structure_resource_ids(parsed_manifest.structure))
        if not ordered_ids:
            return inventory

        resources_by_id = {
            str(resource.get("id")): resource
            for resource in inventory
            if isinstance(resource.get("id"), str) and resource.get("id")
        }
        ordered_inventory: list[dict[str, Any]] = []
        seen_ids: set[str] = set()

        for resource_id in ordered_ids:
            resource = resources_by_id.get(resource_id)
            if resource is None or resource_id in seen_ids:
                continue
            seen_ids.add(resource_id)
            ordered_inventory.append(resource)

        for resource in inventory:
            resource_id = resource.get("id")
            if isinstance(resource_id, str) and resource_id in seen_ids:
                continue
            ordered_inventory.append(resource)

        return ordered_inventory

    def resolve_html_reference(self, reference: str | None, html_path: Path, extracted_root: Path) -> Path | None:
        raw_reference = (reference or "").strip().replace("\\", "/")
        normalized = self._normalize_reference(reference)
        if normalized is None or self._is_external_url(normalized):
            return None

        parsed = urlparse(reference or "")
        if parsed.scheme.lower() in IGNORED_REFERENCE_SCHEMES:
            return None

        root = extracted_root
        root_for_checks = extracted_root.resolve()
        stripped = _strip_query_and_fragment(normalized).replace("\\", "/")
        if not stripped:
            return None

        pure_reference = PurePosixPath(stripped)
        if raw_reference.startswith("/") or pure_reference.is_absolute():
            relative_target = PurePosixPath(*[part for part in pure_reference.parts if part not in {"", "/"}])
        else:
            try:
                html_parent = html_path.relative_to(root).parent
            except ValueError:
                html_parent = html_path.resolve().relative_to(root_for_checks).parent
            relative_target = PurePosixPath(html_parent.as_posix()) / pure_reference

        candidate = Path(os.path.normpath(root / Path(*relative_target.parts)))
        candidate_for_checks = candidate.resolve()
        if not _is_within_root(candidate_for_checks, root_for_checks):
            return None
        return candidate

    def _collect_item(self, item: ET.Element, position: list[int]) -> ManifestItem:
        return ManifestItem(
            node_id=f"item:{'.'.join(str(value) for value in position)}",
            identifier=item.attrib.get("identifier"),
            raw_title=self._normalize_title(self._direct_child_text(item, "title")),
            resource_identifier=item.attrib.get("identifierref"),
            children=[
                self._collect_item(child, [*position, child_index])
                for child_index, child in enumerate(self._find_children(item, "item"))
            ],
        )

    def _resolve_item_titles(
        self,
        item: ManifestItem,
        resource_titles: dict[str, str],
    ) -> ResolvedManifestItem:
        resolved_children = [self._resolve_item_titles(child, resource_titles) for child in item.children]
        inherited_title = self._first_useful_title(child.title for child in resolved_children)
        title = item.raw_title or resource_titles.get(item.resource_identifier or "") or inherited_title or "Sin título"
        return ResolvedManifestItem(
            node_id=item.node_id,
            identifier=item.identifier,
            title=title,
            resource_identifier=item.resource_identifier,
            children=resolved_children,
        )

    def _build_item_node(
        self,
        item: ResolvedManifestItem,
        ancestors: list[str],
    ) -> dict[str, Any]:
        current_path = [*ancestors, item.title]
        return {
            "nodeId": item.node_id,
            "identifier": item.identifier,
            "title": item.title,
            "resourceId": item.resource_identifier,
            "children": [self._build_item_node(child, current_path) for child in item.children],
        }

    def _register_item_paths(
        self,
        node: dict[str, Any],
        ancestors: list[str],
        item_map: dict[str, ItemReference],
    ) -> None:
        title = self._normalize_title(str(node.get("title") or "")) or "Sin título"
        current_path = [*ancestors, title]
        resource_identifier = node.get("resourceId")
        if isinstance(resource_identifier, str) and resource_identifier and resource_identifier not in item_map:
            module_path = " > ".join(ancestors) if ancestors else title
            item_map[resource_identifier] = ItemReference(
                item_identifier=str(node.get("identifier") or ""),
                title=title,
                course_path=" > ".join(current_path),
                module_path=module_path,
            )

        for child in node.get("children", []):
            if isinstance(child, dict):
                self._register_item_paths(child, current_path, item_map)

    def _extract_course_title(self, root: ET.Element) -> str | None:
        metadata = next(iter(self._find_children(root, "metadata")), None)
        if metadata is not None:
            for node in metadata.iter():
                if _local_name(node.tag) == "title":
                    title = _text_content(node)
                    if title:
                        return title

        organizations = next(iter(self._find_children(root, "organizations")), None)
        if organizations is not None:
            organization = next(iter(self._find_children(organizations, "organization")), None)
            if organization is not None:
                return self._direct_child_text(organization, "title")
        return None

    def _extract_external_link(
        self,
        resource: ManifestResource,
        manifest_dir: Path,
        extracted_root: Path,
    ) -> tuple[str | None, str | None]:
        candidates = [
            candidate
            for candidate in [resource.href, *resource.files]
            if candidate and _strip_query_and_fragment(candidate).lower().endswith(".xml")
        ]
        for candidate in candidates:
            xml_path = self._resolve_reference(candidate, manifest_dir, extracted_root)
            if xml_path is None or not xml_path.exists():
                continue
            try:
                tree = ET.parse(xml_path)
            except ET.ParseError:
                continue

            title: str | None = None
            for node in tree.getroot().iter():
                if _local_name(node.tag) == "title" and not title:
                    title = _text_content(node)
                for attribute_name in ("href", "src", "url"):
                    value = node.attrib.get(attribute_name)
                    if value and self._is_external_url(value):
                        return value.strip(), title
                text = (node.text or "").strip()
                if self._is_external_url(text):
                    return text, title
        return None, None

    def _resolve_resource_title(
        self,
        resource: ManifestResource,
        *,
        manifest_dir: Path,
        extracted_root: Path,
    ) -> str | None:
        external_url = resource.external_url
        external_title = None
        if external_url is None:
            external_url, external_title = self._extract_external_link(resource, manifest_dir, extracted_root)
            resource.external_url = external_url
        candidates = [
            self._normalize_title(external_title),
            _derive_title(external_url) if external_url else None,
            *(_derive_title(reference) for reference in [resource.href, *resource.files]),
        ]
        for candidate in candidates:
            normalized = self._normalize_title(candidate)
            if normalized:
                return normalized
        return None

    def _first_useful_title(self, titles: list[str] | tuple[str, ...] | Any) -> str | None:
        for title in titles:
            normalized = self._normalize_title(title)
            if normalized and normalized != "Sin título":
                return normalized
        return None

    def _normalize_title(self, title: str | None) -> str | None:
        if title is None:
            return None
        cleaned = title.strip()
        if not cleaned:
            return None
        if cleaned.lower() in {"untitled item", "untitled resource"}:
            return None
        return cleaned

    def _normalize_reference(self, reference: str | None) -> str | None:
        if not reference:
            return None
        stripped = reference.strip()
        if not stripped:
            return None
        if self._is_external_url(stripped):
            return stripped
        raw_path = _strip_query_and_fragment(stripped).replace("\\", "/")
        parts = [part for part in PurePosixPath(raw_path).parts if part not in {"", ".", "/"}]
        normalized = "/".join(parts)
        return normalized or None

    def _resolve_reference(self, reference: str | None, manifest_dir: Path, extracted_root: Path) -> Path | None:
        normalized = self._normalize_reference(reference)
        if not normalized or self._is_external_url(normalized):
            return None
        candidate = (manifest_dir / normalized).resolve()
        root = extracted_root.resolve()
        if not _is_within_root(candidate, root):
            return None
        return candidate if candidate.exists() else None

    def _direct_child_text(self, element: ET.Element, child_name: str) -> str | None:
        for child in list(element):
            if _local_name(child.tag) == child_name:
                value = _text_content(child)
                if value:
                    return value
        return None

    def _find_children(self, element: ET.Element, child_name: str) -> list[ET.Element]:
        return [child for child in list(element) if _local_name(child.tag) == child_name]

    @staticmethod
    def _is_external_url(reference: str | None) -> bool:
        if not reference:
            return False
        parsed = urlparse(reference)
        return parsed.scheme.lower() in {"http", "https"} and bool(parsed.netloc)

    def _build_discovered_html_resource(
        self,
        candidate: dict[str, str],
        *,
        parent_resource: dict[str, Any] | None,
        context_resource: dict[str, Any] | None,
        parent_html_path: str,
    ) -> dict[str, Any]:
        is_external = candidate["kind"] == "external"
        primary_reference = candidate["url"] if is_external else candidate["path"]
        title = candidate.get("title") or _derive_title(primary_reference) or "Sin título"
        module_context = parent_resource or context_resource
        module_path = _inherit_html_course_path(module_context, parent_html_path)
        module_title = _module_title_from_resource(module_context, fallback_path=module_path)
        section_title = _section_title_from_resource(module_context) or module_title
        parent_item_path = _inventory_item_path(parent_resource)
        item_path = f"{parent_item_path} > {title}" if parent_item_path else f"{module_path} > {title}" if module_path else title

        details = {
            "htmlDiscovery": {
                "discovered": True,
                "parentResourceId": str(parent_resource.get("id")) if parent_resource and parent_resource.get("id") else None,
                "contextResourceId": str(context_resource.get("id")) if context_resource and context_resource.get("id") else None,
                "parentHtmlPath": parent_html_path,
                "tag": candidate["tag"],
                "attribute": candidate["attribute"],
            }
        }

        resource_id = str(uuid5(HTML_DISCOVERY_NAMESPACE, f"{candidate['kind']}|{primary_reference}"))
        return {
            "id": resource_id,
            "identifier": resource_id,
            "title": title,
            "type": classify_resource(primary_reference, is_external=is_external),
            "origin": "EXTERNAL_URL" if is_external else "INTERNAL_FILE",
            "url": primary_reference if is_external else None,
            "sourceUrl": primary_reference if is_external else None,
            "path": None if is_external else primary_reference,
            "filePath": None if is_external else primary_reference,
            "localPath": None if is_external else primary_reference,
            "coursePath": module_path,
            "course_path": module_path,
            "modulePath": module_path,
            "module_path": module_path,
            "itemPath": item_path,
            "item_path": item_path,
            "moduleTitle": module_title,
            "module_title": module_title,
            "sectionTitle": section_title,
            "section_title": section_title,
            "status": "OK",
            "files": [primary_reference] if not is_external else [],
            "dependencies": [],
            "discoveredChildrenCount": 0,
            "discovered_children_count": 0,
            "parentResourceId": details["htmlDiscovery"]["parentResourceId"],
            "parent_resource_id": details["htmlDiscovery"]["parentResourceId"],
            "parentId": details["htmlDiscovery"]["parentResourceId"],
            "parent_id": details["htmlDiscovery"]["parentResourceId"],
            "discovered": True,
            "notes": None,
            "localFile": not is_external,
            "local_file": not is_external,
            "downloadable": not is_external,
            "external": is_external,
            "contentAvailable": not is_external,
            "content_available": not is_external,
            "details": details,
        }

    def _register_html_child(
        self,
        parent_resource: dict[str, Any] | None,
        child_resource: dict[str, Any],
        parent_child_ids: dict[str, list[str]],
    ) -> None:
        if parent_resource is None:
            return

        parent_id = parent_resource.get("id")
        child_id = child_resource.get("id")
        if not isinstance(parent_id, str) or not parent_id or not isinstance(child_id, str) or not child_id:
            return
        if parent_id == child_id:
            return

        parent_child_ids.setdefault(parent_id, [])
        if child_id not in parent_child_ids[parent_id]:
            parent_child_ids[parent_id].append(child_id)

    def _apply_html_discovery_details(
        self,
        inventory: list[dict[str, Any]],
        parent_child_ids: dict[str, list[str]],
    ) -> None:
        for resource in inventory:
            resource_id = resource.get("id")
            if not isinstance(resource_id, str) or resource_id not in parent_child_ids:
                continue
            details = dict(resource.get("details") or {})
            details["htmlDiscovery"] = {
                **dict(details.get("htmlDiscovery") or {}),
                "containsLinkedResources": True,
                "linkedResourceCount": len(parent_child_ids[resource_id]),
                "linkedResourceIds": list(parent_child_ids[resource_id]),
            }
            resource["discoveredChildrenCount"] = len(parent_child_ids[resource_id])
            resource["discovered_children_count"] = len(parent_child_ids[resource_id])
            resource["details"] = details

    def _collect_html_targets(self, inventory: list[dict[str, Any]], extracted_root: Path) -> list[str]:
        targets: list[str] = []
        seen: set[str] = set()

        for resource in inventory:
            relative_path = _inventory_file_path(resource)
            if not relative_path or Path(relative_path).suffix.lower() not in HTML_RESOURCE_EXTENSIONS:
                continue
            if relative_path not in seen:
                seen.add(relative_path)
                targets.append(relative_path)

        for html_path in sorted(path for path in extracted_root.rglob("*") if path.is_file()):
            relative_path = html_path.resolve().relative_to(extracted_root.resolve()).as_posix()
            if Path(relative_path).suffix.lower() not in HTML_RESOURCE_EXTENSIONS or relative_path in seen:
                continue
            seen.add(relative_path)
            targets.append(relative_path)

        return targets

    def _should_skip_html_reference(self, reference: str) -> bool:
        parsed = urlparse(reference.strip())
        return parsed.scheme.lower() in IGNORED_REFERENCE_SCHEMES


def _derive_title(reference: str | None) -> str | None:
    if not reference:
        return None
    parsed = urlparse(reference)
    candidate = parsed.path if parsed.scheme else reference
    name = Path(_strip_query_and_fragment(candidate)).name
    stem = Path(name).stem if name else ""
    cleaned = stem.replace("_", " ").replace("-", " ").strip()
    return cleaned or None


def _is_within_root(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _local_name(tag: Any) -> str:
    if not isinstance(tag, str):
        return ""
    return tag.rsplit("}", 1)[-1]


def _strip_query_and_fragment(reference: str) -> str:
    parsed = urlparse(reference)
    if parsed.scheme and parsed.netloc:
        return parsed.path
    return reference.split("#", 1)[0].split("?", 1)[0]


def _text_content(element: ET.Element) -> str | None:
    text = "".join(part.strip() for part in element.itertext() if part and part.strip())
    return text or None


def _unique_preserving_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    unique: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        unique.append(value)
    return unique


def _should_skip_metadata_resource(
    file_path: str | None,
    source_url: str | None,
    excluded_extensions: set[str],
) -> bool:
    if source_url:
        return False
    if not file_path:
        return False
    normalized_name = Path(_strip_query_and_fragment(file_path)).name.lower()
    if normalized_name == "imsmanifest.xml":
        return True
    return Path(normalized_name).suffix.lower() in excluded_extensions


def _inventory_file_path(resource: dict[str, Any] | None) -> str | None:
    if not isinstance(resource, dict):
        return None
    for key in ("filePath", "localPath", "path"):
        value = resource.get(key)
        if isinstance(value, str) and value.strip():
            normalized = value.strip().replace("\\", "/")
            return normalized or None
    return None


def _inventory_source_url(resource: dict[str, Any] | None) -> str | None:
    if not isinstance(resource, dict):
        return None
    for key in ("sourceUrl", "url"):
        value = resource.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _normalize_external_url(reference: str) -> str:
    stripped = reference.strip()
    without_fragment = stripped.split("#", 1)[0].rstrip("/")
    return without_fragment.lower()


def _inventory_item_path(resource: dict[str, Any] | None) -> str | None:
    if not isinstance(resource, dict):
        return None
    for key in ("itemPath", "item_path"):
        value = resource.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _module_title_from_item_ref(item_ref: ItemReference | None) -> str | None:
    if item_ref is None:
        return None
    return _first_path_segment(item_ref.module_path or item_ref.course_path)


def _section_title_from_item_ref(item_ref: ItemReference | None, *, fallback_title: str | None = None) -> str | None:
    if item_ref is None:
        return fallback_title
    parent_path = item_ref.course_path
    parts = _split_course_path(parent_path)
    if len(parts) >= 2:
        return parts[-2]
    return _last_path_segment(item_ref.module_path) or fallback_title


def _module_title_from_resource(resource: dict[str, Any] | None, *, fallback_path: str | None = None) -> str | None:
    if isinstance(resource, dict):
        for key in ("moduleTitle", "module_title"):
            value = resource.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        for key in ("modulePath", "module_path", "coursePath", "course_path"):
            value = resource.get(key)
            if isinstance(value, str) and value.strip():
                return _first_path_segment(value)
    return _first_path_segment(fallback_path)


def _section_title_from_resource(resource: dict[str, Any] | None) -> str | None:
    if not isinstance(resource, dict):
        return None
    for key in ("sectionTitle", "section_title"):
        value = resource.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    parts = _split_course_path(_inventory_item_path(resource))
    if len(parts) >= 2:
        return parts[-2]
    return _last_path_segment(resource.get("modulePath") if isinstance(resource.get("modulePath"), str) else None)


def _inherit_html_course_path(parent_resource: dict[str, Any] | None, parent_html_path: str) -> str | None:
    if isinstance(parent_resource, dict):
        for key in ("modulePath", "module_path", "coursePath", "course_path"):
            value = parent_resource.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()

    parent = PurePosixPath(parent_html_path).parent
    if parent.as_posix() in {"", "."}:
        return None
    return parent.as_posix()


def _split_course_path(value: str | None) -> list[str]:
    if not isinstance(value, str):
        return []
    return [part.strip() for part in value.split(">") if part.strip()]


def _first_path_segment(value: str | None) -> str | None:
    parts = _split_course_path(value)
    return parts[0] if parts else None


def _last_path_segment(value: str | None) -> str | None:
    parts = _split_course_path(value)
    return parts[-1] if parts else None


def _iter_structure_resource_ids(structure: dict[str, Any]) -> list[str]:
    ordered_ids: list[str] = []

    def visit(node: dict[str, Any]) -> None:
        resource_id = node.get("resourceId")
        if isinstance(resource_id, str) and resource_id:
            ordered_ids.append(resource_id)
        for child in node.get("children", []):
            if isinstance(child, dict):
                visit(child)

    for organization in structure.get("organizations", []):
        if not isinstance(organization, dict):
            continue
        for child in organization.get("children", []):
            if isinstance(child, dict):
                visit(child)
    return ordered_ids


def _find_context_resource_for_html(
    html_relative_path: str,
    resources_by_path: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    target_parent = PurePosixPath(html_relative_path).parent
    best_match: dict[str, Any] | None = None
    best_score: tuple[int, int, int] | None = None

    for candidate_path, resource in resources_by_path.items():
        candidate_parent = PurePosixPath(candidate_path).parent
        shared_parts = 0
        for target_part, candidate_part in zip(target_parent.parts, candidate_parent.parts):
            if target_part != candidate_part:
                break
            shared_parts += 1
        if shared_parts == 0:
            continue

        resource_is_html = int(Path(candidate_path).suffix.lower() in HTML_RESOURCE_EXTENSIONS)
        score = (shared_parts, resource_is_html, -abs(len(target_parent.parts) - len(candidate_parent.parts)))
        if best_score is None or score > best_score:
            best_match = resource
            best_score = score

    return best_match


def _resolve_relative_path(extracted_root: Path, relative_path: str) -> Path | None:
    root = extracted_root.resolve()
    normalized = PurePosixPath(relative_path.replace("\\", "/"))
    if normalized.is_absolute() or any(part == ".." for part in normalized.parts):
        return None
    candidate = (root / Path(*normalized.parts)).resolve()
    if not _is_within_root(candidate, root):
        return None
    return candidate


def _looks_like_xml_reference(reference: str) -> bool:
    return Path(_strip_query_and_fragment(reference)).suffix.lower() == ".xml"


def _extract_html_reference_title(element: Any, reference: str) -> str | None:
    for attribute_name in ("title", "aria-label", "alt"):
        value = element.get(attribute_name)
        if isinstance(value, str):
            cleaned = value.strip()
            if cleaned:
                return cleaned

    text = " ".join(part.strip() for part in element.stripped_strings if part and part.strip())
    if text:
        return text
    return _derive_title(reference)
