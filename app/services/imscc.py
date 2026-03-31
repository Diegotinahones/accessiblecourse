from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4
from xml.etree import ElementTree

from app.core.errors import AppError
from app.services.catalog import infer_origin, infer_status, infer_type


@dataclass(slots=True)
class ParsedResource:
    resource_id: str
    title: str
    href: str | None
    extracted_path: str | None
    resource_type: str
    origin: str
    status: str


def _get_namespace(root: ElementTree.Element) -> dict[str, str]:
    if root.tag.startswith("{"):
        namespace = root.tag.split("}", maxsplit=1)[0].strip("{")
        return {"ims": namespace}
    return {"ims": ""}


def parse_manifest(manifest_path: Path) -> list[dict[str, str | None]]:
    if not manifest_path.exists():
        raise AppError(
            code="manifest_missing",
            message="No hemos encontrado imsmanifest.xml dentro del paquete.",
            details={"manifestPath": str(manifest_path)},
        )

    tree = ElementTree.parse(manifest_path)
    root = tree.getroot()
    namespace = _get_namespace(root)

    item_titles: dict[str, str] = {}
    item_query = ".//ims:item" if namespace["ims"] else ".//item"
    title_query = "ims:title" if namespace["ims"] else "title"
    resource_query = ".//ims:resource" if namespace["ims"] else ".//resource"
    file_query = "ims:file" if namespace["ims"] else "file"

    for item in root.findall(item_query, namespace):
        identifier_ref = item.attrib.get("identifierref")
        title_node = item.find(title_query, namespace)
        title = title_node.text.strip() if title_node is not None and title_node.text else None
        if identifier_ref and title:
            item_titles[identifier_ref] = title

    resources: list[dict[str, str | None]] = []
    for resource in root.findall(resource_query, namespace):
        identifier = resource.attrib.get("identifier") or str(uuid4())
        href = resource.attrib.get("href")
        if not href:
            first_file = resource.find(file_query, namespace)
            href = first_file.attrib.get("href") if first_file is not None else None
        title = item_titles.get(identifier) or (Path(href).name if href else identifier)
        resources.append({"identifier": identifier, "title": title, "href": href})

    return resources


def build_resources_from_extracted(extracted_dir: Path) -> list[ParsedResource]:
    manifest_path = extracted_dir / "imsmanifest.xml"
    resources: list[ParsedResource] = []

    if manifest_path.exists():
        for manifest_resource in parse_manifest(manifest_path):
            href = manifest_resource.get("href")
            extracted_path = None
            if href:
                candidate = (extracted_dir / Path(href)).resolve()
                if candidate.exists() and str(candidate).startswith(str(extracted_dir.resolve())):
                    extracted_path = str(candidate.relative_to(extracted_dir))
            resource_type = infer_type(href)
            origin = infer_origin(href)
            resources.append(
                ParsedResource(
                    resource_id=str(uuid4()),
                    title=manifest_resource["title"] or "Recurso sin titulo",
                    href=href,
                    extracted_path=extracted_path,
                    resource_type=resource_type.value,
                    origin=origin.value,
                    status=infer_status(resource_type, origin).value,
                )
            )

    if resources:
        return resources

    for path in sorted(extracted_dir.rglob("*")):
        if not path.is_file() or path.name == "imsmanifest.xml":
            continue
        relative_path = str(path.relative_to(extracted_dir))
        resource_type = infer_type(relative_path)
        origin = infer_origin(relative_path)
        resources.append(
            ParsedResource(
                resource_id=str(uuid4()),
                title=path.stem.replace("-", " ").replace("_", " ").strip() or path.name,
                href=relative_path,
                extracted_path=relative_path,
                resource_type=resource_type.value,
                origin=origin.value,
                status=infer_status(resource_type, origin).value,
            )
        )

    return resources
