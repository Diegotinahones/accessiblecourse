from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from app.core.config import Settings

COURSE_STRUCTURE_FILENAME = "course_structure.json"
FALLBACK_ORGANIZATION_TITLE = "Estructura del curso"
UNTITLED_LABEL = "Sin título"


def save_course_structure(settings: Settings, job_id: str, structure: dict[str, Any]) -> None:
    structure_path = get_course_structure_path(settings, job_id)
    structure_path.parent.mkdir(parents=True, exist_ok=True)
    structure_path.write_text(
        json.dumps(structure, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def load_course_structure(settings: Settings, job_id: str) -> dict[str, Any] | None:
    structure_path = get_course_structure_path(settings, job_id)
    if not structure_path.exists():
        return None

    payload = json.loads(structure_path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else None


def filter_course_structure(
    structure: Mapping[str, Any] | None,
    *,
    visible_resource_ids: set[str],
) -> dict[str, Any] | None:
    if structure is None:
        return None

    organizations_payload = structure.get("organizations")
    organizations: list[dict[str, Any]] = []
    if isinstance(organizations_payload, list):
        for organization in organizations_payload:
            if not isinstance(organization, Mapping):
                continue

            children = [
                filtered
                for child in _coerce_children(organization.get("children"))
                if (filtered := _filter_node(child, visible_resource_ids)) is not None
            ]
            if not children:
                continue

            organizations.append(
                {
                    "nodeId": _coerce_text(organization.get("nodeId")) or "organization:filtered",
                    "identifier": _coerce_text(organization.get("identifier")),
                    "title": _coerce_text(organization.get("title")) or FALLBACK_ORGANIZATION_TITLE,
                    "children": children,
                }
            )

    unplaced_payload = structure.get("unplacedResourceIds")
    unplaced = [
        resource_id
        for resource_id in (unplaced_payload if isinstance(unplaced_payload, list) else [])
        if isinstance(resource_id, str) and resource_id in visible_resource_ids
    ]

    return {
        "title": _coerce_text(structure.get("title")) or FALLBACK_ORGANIZATION_TITLE,
        "organizations": organizations,
        "unplacedResourceIds": unplaced,
    }


def build_fallback_course_structure(
    resources: Sequence[Mapping[str, Any]],
    *,
    title: str | None = None,
) -> dict[str, Any]:
    organization = {
        "nodeId": "organization:fallback",
        "identifier": None,
        "title": title or FALLBACK_ORGANIZATION_TITLE,
        "children": [],
    }
    child_lookup: dict[tuple[str, str, str | None], dict[str, Any]] = {}
    unplaced_resource_ids: list[str] = []

    for resource in resources:
        resource_id = _coerce_text(resource.get("id"))
        if not resource_id:
            continue

        resource_title = _coerce_text(resource.get("title")) or UNTITLED_LABEL
        item_path = _coerce_text(resource.get("itemPath") or resource.get("item_path"))
        course_path = _coerce_text(resource.get("coursePath") or resource.get("course_path"))
        segments = _split_course_path(item_path or course_path)

        if not segments:
            unplaced_resource_ids.append(resource_id)
            continue

        if _normalize_label(segments[-1]) != _normalize_label(resource_title):
            segments = [*segments, resource_title]

        parent_node = organization
        for index, segment in enumerate(segments):
            is_leaf = index == len(segments) - 1
            node_key = (
                _coerce_text(parent_node.get("nodeId")) or "organization:fallback",
                segment,
                resource_id if is_leaf else None,
            )
            node = child_lookup.get(node_key)
            if node is None:
                node_id_suffix = "/".join(_normalize_label(part) or UNTITLED_LABEL for part in segments[: index + 1])
                node = {
                    "nodeId": f"fallback:{node_id_suffix}:{resource_id}" if is_leaf else f"fallback:{node_id_suffix}",
                    "identifier": None,
                    "title": segment,
                    "resourceId": resource_id if is_leaf else None,
                    "children": [],
                }
                child_lookup[node_key] = node
                parent_node["children"].append(node)
            parent_node = node

    return {
        "title": title or FALLBACK_ORGANIZATION_TITLE,
        "organizations": [organization] if organization["children"] else [],
        "unplacedResourceIds": unplaced_resource_ids,
    }


def _filter_node(node: Mapping[str, Any], visible_resource_ids: set[str]) -> dict[str, Any] | None:
    children = [
        filtered
        for child in _coerce_children(node.get("children"))
        if (filtered := _filter_node(child, visible_resource_ids)) is not None
    ]
    resource_id = _coerce_text(node.get("resourceId"))

    if resource_id is not None and resource_id not in visible_resource_ids:
        resource_id = None

    if resource_id is None and not children:
        return None

    return {
        "nodeId": _coerce_text(node.get("nodeId")) or "node:filtered",
        "identifier": _coerce_text(node.get("identifier")),
        "title": _coerce_text(node.get("title")) or UNTITLED_LABEL,
        "resourceId": resource_id,
        "children": children,
    }


def _coerce_children(value: Any) -> list[Mapping[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, Mapping)]


def _coerce_text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    return cleaned or None


def _normalize_label(value: str | None) -> str:
    if not value:
        return ""
    return " ".join(value.lower().split())


def _split_course_path(value: str | None) -> list[str]:
    if not value:
        return []

    separator = " > " if " > " in value else "/"
    return [segment.strip() for segment in value.split(separator) if segment and segment.strip()]


def get_course_structure_path(settings: Settings, job_id: str) -> Path:
    return Path(settings.data_dir) / "jobs" / job_id / COURSE_STRUCTURE_FILENAME
