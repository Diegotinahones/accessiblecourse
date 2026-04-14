from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import urlparse
from xml.etree import ElementTree as ET
from zipfile import BadZipFile, ZipFile

DEFAULT_MAX_ARCHIVE_MEMBERS = 2000
DEFAULT_MAX_ARCHIVE_MEMBER_SIZE = 256 * 1024 * 1024
DEFAULT_MAX_ARCHIVE_TOTAL_SIZE = 1024 * 1024 * 1024

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
        item_map: dict[str, ItemReference] = {}

        organization_nodes: list[dict[str, Any]] = []
        for organizations_node in self._find_children(root, "organizations"):
            for organization in self._find_children(organizations_node, "organization"):
                organization_title = self._direct_child_text(organization, "title") or course_title
                children = [self._parse_item(item, [], item_map) for item in self._find_children(organization, "item")]
                organization_nodes.append(
                    {
                        "identifier": organization.attrib.get("identifier"),
                        "title": organization_title,
                        "path": None,
                        "resourceIdentifier": None,
                        "children": children,
                    }
                )

        resources: list[ManifestResource] = []
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
                resources.append(
                    ManifestResource(
                        identifier=resource.attrib.get("identifier", ""),
                        resource_type=resource.attrib.get("type"),
                        href=resource.attrib.get("href"),
                        files=files,
                        dependencies=dependencies,
                    )
                )

        return ParsedManifest(
            course_title=course_title,
            structure={"title": course_title, "organizations": organization_nodes},
            resources=resources,
            item_map=item_map,
        )

    def build_resource_inventory(
        self,
        parsed_manifest: ParsedManifest,
        manifest_path: Path,
        extracted_root: Path,
    ) -> list[dict[str, Any]]:
        inventory: list[dict[str, Any]] = []
        manifest_dir = manifest_path.parent
        resolved_root = extracted_root.resolve()

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

            external_url = None
            external_title = None
            if resource.href and self._is_external_url(resource.href):
                external_url = resource.href.strip()
            else:
                external_url, external_title = self._extract_external_link(resource, manifest_dir, extracted_root)

            path: str | None = None
            url: str | None = None
            origin = "internal"
            declared_href = self._normalize_reference(resource.href)

            if external_url:
                origin = "external"
                url = external_url
                primary_reference = external_url
            else:
                if declared_href and not self._is_external_url(declared_href):
                    resolved_href = self._resolve_reference(declared_href, manifest_dir, extracted_root)
                    if resolved_href is not None:
                        path = resolved_href.relative_to(resolved_root).as_posix()
                    elif resolved_file_refs:
                        path = resolved_file_refs[0]
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
                elif declared_files:
                    path = declared_files[0]
                    notes.append(f"El recurso referencia '{declared_files[0]}' pero no se encontró en el paquete.")
                    status = "WARN"
                else:
                    status = "ERROR"
                    notes.append("El recurso no define un href o file válido.")

                primary_reference = path or declared_href or resource.href

            title = (
                (item_ref.title if item_ref else None)
                or external_title
                or _derive_title(primary_reference)
                or resource.identifier
                or "Untitled resource"
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
                    "path": path if origin == "internal" else None,
                    "filePath": path if origin == "internal" else None,
                    "href": resource.href,
                    "files": resolved_file_refs or declared_files,
                    "dependencies": resource.dependencies,
                    "coursePath": item_ref.module_path if item_ref else None,
                    "course_path": item_ref.module_path if item_ref else None,
                    "modulePath": item_ref.module_path if item_ref else None,
                    "module_path": item_ref.module_path if item_ref else None,
                    "itemPath": item_ref.course_path if item_ref else None,
                    "item_path": item_ref.course_path if item_ref else None,
                    "status": status,
                    "notes": notes,
                }
            )

        return [
            resource
            for resource in inventory
            if not _should_skip_metadata_resource(
                resource.get("filePath") if isinstance(resource.get("filePath"), str) else None,
                resource.get("sourceUrl") if isinstance(resource.get("sourceUrl"), str) else None,
            )
        ]

    def _parse_item(self, item: ET.Element, ancestors: list[str], item_map: dict[str, ItemReference]) -> dict[str, Any]:
        title = self._direct_child_text(item, "title") or "Untitled item"
        current_path = [*ancestors, title]
        resource_identifier = item.attrib.get("identifierref")
        if resource_identifier and resource_identifier not in item_map:
            module_path = " > ".join(ancestors) if ancestors else title
            item_map[resource_identifier] = ItemReference(
                item_identifier=item.attrib.get("identifier", ""),
                title=title,
                course_path=" > ".join(current_path),
                module_path=module_path,
            )

        return {
            "identifier": item.attrib.get("identifier"),
            "title": title,
            "path": " > ".join(current_path),
            "resourceIdentifier": resource_identifier,
            "children": [
                self._parse_item(child, current_path, item_map) for child in self._find_children(item, "item")
            ],
        }

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


def _should_skip_metadata_resource(file_path: str | None, source_url: str | None) -> bool:
    if source_url:
        return False
    if not file_path:
        return False
    normalized_name = Path(_strip_query_and_fragment(file_path)).name.lower()
    if normalized_name == "imsmanifest.xml":
        return True
    return Path(normalized_name).suffix.lower() in EXCLUDED_METADATA_EXTENSIONS
