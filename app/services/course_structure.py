from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import re
from typing import TYPE_CHECKING, Any, Mapping, Sequence
import unicodedata

if TYPE_CHECKING:
    from app.core.config import Settings

COURSE_STRUCTURE_FILENAME = "course_structure.json"
FALLBACK_ORGANIZATION_TITLE = "Estructura del curso"
UNTITLED_LABEL = "Sin título"
GLOBAL_UNPLACED_TITLE = "Recursos globales o no ubicados en la estructura del curso"
SECTION_KEY_SEP = " > "
PEC_KEY_RE = re.compile(r"\bpec\s*0*(\d+)\b", re.IGNORECASE)


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
    if not isinstance(payload, dict):
        return None
    return normalize_course_structure(payload)


def normalize_course_structure(structure: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if structure is None:
        return None

    organizations_payload = structure.get("organizations")
    organizations: list[dict[str, Any]] = []
    if isinstance(organizations_payload, list):
        for organization in organizations_payload:
            if not isinstance(organization, Mapping):
                continue

            children = _normalize_children(_coerce_children(organization.get("children")))
            if not children:
                continue

            organizations.append(
                {
                    "nodeId": _coerce_text(organization.get("nodeId")) or "organization:normalized",
                    "identifier": _coerce_text(organization.get("identifier")),
                    "title": _coerce_text(organization.get("title")) or FALLBACK_ORGANIZATION_TITLE,
                    "children": children,
                }
            )

    unplaced_payload = structure.get("unplacedResourceIds")
    unplaced = [
        resource_id
        for resource_id in (unplaced_payload if isinstance(unplaced_payload, list) else [])
        if isinstance(resource_id, str)
    ]

    return {
        "title": _coerce_text(structure.get("title")) or FALLBACK_ORGANIZATION_TITLE,
        "organizations": organizations,
        "unplacedResourceIds": unplaced,
    }


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

    return normalize_course_structure(
        {
            "title": _coerce_text(structure.get("title")) or FALLBACK_ORGANIZATION_TITLE,
            "organizations": organizations,
            "unplacedResourceIds": unplaced,
        }
    )


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

    return normalize_course_structure(
        {
            "title": title or FALLBACK_ORGANIZATION_TITLE,
            "organizations": [organization] if organization["children"] else [],
            "unplacedResourceIds": unplaced_resource_ids,
        }
    ) or {
        "title": title or FALLBACK_ORGANIZATION_TITLE,
        "organizations": [],
        "unplacedResourceIds": unplaced_resource_ids,
    }


def build_section_key(title: str | None, *, hierarchy: Sequence[str] | None = None) -> str:
    normalized_title = _normalize_section_fragment(title)
    normalized_hierarchy = [
        normalized
        for normalized in (_normalize_section_fragment(part) for part in (hierarchy or []))
        if normalized
    ]
    parts = [*normalized_hierarchy, normalized_title] if normalized_title else normalized_hierarchy
    return SECTION_KEY_SEP.join(parts)


def section_key_from_path(path: str | None) -> str | None:
    segments = _split_course_path(path)
    if not segments:
        return None
    return build_section_key(segments[-1], hierarchy=segments[:-1]) or None


def section_title_from_path(path: str | None) -> str | None:
    segments = _split_course_path(path)
    return segments[-1] if segments else None


def augment_course_structure(
    structure: Mapping[str, Any] | None,
    resources: Sequence[Mapping[str, Any]],
) -> dict[str, Any] | None:
    normalized = normalize_course_structure(structure)
    if normalized is None:
        return None

    augmented = deepcopy(normalized)
    organizations = augmented.get("organizations")
    if not isinstance(organizations, list) or not organizations:
        fallback_title = _coerce_text(augmented.get("title")) or FALLBACK_ORGANIZATION_TITLE
        return build_fallback_course_structure(resources, title=fallback_title)

    for organization in organizations:
        children = _coerce_children(organization.get("children"))
        organization["children"] = _merge_equivalent_sections(children, ancestors=[organization.get("title")])

    index = _build_structure_index(augmented)
    resource_ids = [_coerce_text(resource.get("id")) for resource in resources]
    visible_ids = [resource_id for resource_id in resource_ids if resource_id]

    for resource in resources:
        resource_id = _coerce_text(resource.get("id"))
        if not resource_id or resource_id in index["resourceNodes"]:
            continue

        is_discovered = bool(resource.get("discovered"))
        parent_id = _coerce_text(resource.get("parentResourceId") or resource.get("parent_resource_id"))
        if not is_discovered and parent_id is None:
            continue

        new_node = _resource_to_structure_node(resource)
        target_node = index["resourceNodes"].get(parent_id) if parent_id else None

        if target_node is None:
            section_key = _resource_section_key(resource)
            title_key = build_section_key(_resource_section_title(resource))
            target_node = (
                index["sectionNodesByPath"].get(section_key or "")
                or index["sectionNodesByTitle"].get(title_key)
            )

        if target_node is None:
            section_title = _resource_section_title(resource) or GLOBAL_UNPLACED_TITLE
            section_key = _resource_section_key(resource) or build_section_key(section_title)
            organization = organizations[0]
            target_node = {
                "nodeId": f"section:auto:{section_key or resource_id}",
                "identifier": None,
                "title": section_title,
                "resourceId": None,
                "children": [],
            }
            organization.setdefault("children", []).append(target_node)

        target_node.setdefault("children", []).append(new_node)

        for organization in organizations:
            children = _coerce_children(organization.get("children"))
            organization["children"] = _merge_equivalent_sections(children, ancestors=[organization.get("title")])
        index = _build_structure_index(augmented)

    attached_resource_ids = list(index["resourceNodes"].keys())
    existing_unplaced = [
        resource_id
        for resource_id in (
            augmented.get("unplacedResourceIds") if isinstance(augmented.get("unplacedResourceIds"), list) else []
        )
        if isinstance(resource_id, str) and resource_id in visible_ids and resource_id not in attached_resource_ids
    ]
    remaining_visible = [
        resource_id
        for resource_id in visible_ids
        if resource_id not in attached_resource_ids and resource_id not in existing_unplaced
    ]
    augmented["unplacedResourceIds"] = [*existing_unplaced, *remaining_visible]
    return normalize_course_structure(augmented)


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


def _build_structure_index(structure: Mapping[str, Any]) -> dict[str, dict[str, dict[str, Any]]]:
    section_nodes_by_path: dict[str, dict[str, Any]] = {}
    section_nodes_by_title: dict[str, dict[str, Any]] = {}
    resource_nodes: dict[str, dict[str, Any]] = {}

    def visit(node: dict[str, Any], ancestors: list[str]) -> None:
        title = _coerce_text(node.get("title")) or UNTITLED_LABEL
        resource_id = _coerce_text(node.get("resourceId"))
        path_key = build_section_key(title, hierarchy=ancestors)
        title_key = build_section_key(title)

        section_nodes_by_path.setdefault(path_key, node)
        section_nodes_by_title.setdefault(title_key, node)
        if resource_id:
            resource_nodes.setdefault(resource_id, node)

        current_ancestors = [*ancestors, title]
        for child in _coerce_children(node.get("children")):
            visit(child, current_ancestors)

    for organization in _coerce_children(structure.get("organizations")):
        organization_title = _coerce_text(organization.get("title")) or FALLBACK_ORGANIZATION_TITLE
        for child in _coerce_children(organization.get("children")):
            visit(child, [organization_title])

    return {
        "sectionNodesByPath": section_nodes_by_path,
        "sectionNodesByTitle": section_nodes_by_title,
        "resourceNodes": resource_nodes,
    }


def _merge_equivalent_sections(
    nodes: list[Mapping[str, Any]],
    *,
    ancestors: Sequence[str],
) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    merged_by_key: dict[str, dict[str, Any]] = {}

    for raw_node in nodes:
        title = _coerce_text(raw_node.get("title")) or UNTITLED_LABEL
        normalized_children = _merge_equivalent_sections(
            _coerce_children(raw_node.get("children")),
            ancestors=[*ancestors, title],
        )
        node = {
            "nodeId": _coerce_text(raw_node.get("nodeId")) or "node:merged",
            "identifier": _coerce_text(raw_node.get("identifier")),
            "title": title,
            "resourceId": _coerce_text(raw_node.get("resourceId")),
            "children": normalized_children,
        }

        merge_key = build_section_key(title, hierarchy=ancestors)
        existing = merged_by_key.get(merge_key)
        if existing is None:
            merged_by_key[merge_key] = node
            merged.append(node)
            continue

        existing_resource_id = _coerce_text(existing.get("resourceId"))
        node_resource_id = _coerce_text(node.get("resourceId"))
        existing_children = existing.setdefault("children", [])
        existing_children.extend(node.get("children", []))

        if existing_resource_id is None:
            existing["resourceId"] = node_resource_id
        elif node_resource_id and node_resource_id != existing_resource_id:
            existing_children.append(
                {
                    "nodeId": node.get("nodeId") or f"{existing.get('nodeId')}:resource:{node_resource_id}",
                    "identifier": node.get("identifier"),
                    "title": node.get("title") or UNTITLED_LABEL,
                    "resourceId": node_resource_id,
                    "children": [],
                }
            )

    return merged


def _resource_to_structure_node(resource: Mapping[str, Any]) -> dict[str, Any]:
    resource_id = _coerce_text(resource.get("id")) or "resource:auto"
    title = _coerce_text(resource.get("title")) or UNTITLED_LABEL
    return {
        "nodeId": f"resource:auto:{resource_id}",
        "identifier": resource_id,
        "title": title,
        "resourceId": resource_id,
        "children": [],
    }


def _resource_section_path(resource: Mapping[str, Any]) -> str | None:
    for key in ("modulePath", "module_path", "coursePath", "course_path"):
        value = _coerce_text(resource.get(key))
        if value:
            return value
    return None


def _resource_section_title(resource: Mapping[str, Any]) -> str | None:
    for key in ("sectionTitle", "section_title", "moduleTitle", "module_title"):
        value = _coerce_text(resource.get(key))
        if value:
            return value
    return section_title_from_path(_resource_section_path(resource))


def _resource_section_key(resource: Mapping[str, Any]) -> str | None:
    section_path = _resource_section_path(resource)
    path_key = section_key_from_path(section_path)
    if path_key:
        return path_key
    section_title = _resource_section_title(resource)
    if section_title:
        return build_section_key(section_title)
    return None


def _normalize_children(nodes: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    normalized_nodes: list[dict[str, Any]] = []
    for node in nodes:
        normalized = _normalize_node(node)
        if normalized is None:
            continue
        if _should_promote_children(normalized):
            normalized_nodes.extend(
                child for child in normalized.get("children", []) if isinstance(child, dict)
            )
            continue
        normalized_nodes.append(normalized)
    return normalized_nodes


def _normalize_node(node: Mapping[str, Any]) -> dict[str, Any] | None:
    children = _normalize_children(_coerce_children(node.get("children")))
    resource_id = _coerce_text(node.get("resourceId"))
    title = _coerce_text(node.get("title")) or UNTITLED_LABEL

    if resource_id is None and not children:
        return None

    normalized = {
        "nodeId": _coerce_text(node.get("nodeId")) or "node:normalized",
        "identifier": _coerce_text(node.get("identifier")),
        "title": title,
        "resourceId": resource_id,
        "children": children,
    }

    if resource_id is None and len(children) == 1:
        only_child = children[0]
        if _should_collapse_into_child(normalized, only_child):
            return only_child

    if resource_id is not None and len(children) == 1:
        only_child = children[0]
        if _should_absorb_child(normalized, only_child):
            normalized["children"] = only_child.get("children", [])

    return normalized


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


def _normalize_section_fragment(value: str | None) -> str:
    if not value:
        return ""
    normalized = unicodedata.normalize("NFKD", value)
    ascii_text = "".join(char for char in normalized if not unicodedata.combining(char))
    ascii_text = ascii_text.lower().replace(":", " ")
    ascii_text = PEC_KEY_RE.sub(lambda match: f"pec {int(match.group(1))}", ascii_text)
    ascii_text = re.sub(r"[^a-z0-9]+", " ", ascii_text)
    return " ".join(ascii_text.split())


def _should_collapse_into_child(parent: Mapping[str, Any], child: Mapping[str, Any]) -> bool:
    parent_title = _coerce_text(parent.get("title")) or UNTITLED_LABEL
    child_title = _coerce_text(child.get("title")) or UNTITLED_LABEL
    return parent_title == UNTITLED_LABEL or _normalize_label(parent_title) == _normalize_label(child_title)


def _should_absorb_child(parent: Mapping[str, Any], child: Mapping[str, Any]) -> bool:
    if _coerce_text(child.get("resourceId")) is not None:
        return False
    parent_title = _coerce_text(parent.get("title")) or UNTITLED_LABEL
    child_title = _coerce_text(child.get("title")) or UNTITLED_LABEL
    return _normalize_label(parent_title) == _normalize_label(child_title)


def _should_promote_children(node: Mapping[str, Any]) -> bool:
    if _coerce_text(node.get("resourceId")) is not None:
        return False

    children = [child for child in node.get("children", []) if isinstance(child, Mapping)]
    if len(children) <= 1:
        return False

    node_title = _coerce_text(node.get("title")) or UNTITLED_LABEL
    first_child_title = _coerce_text(children[0].get("title")) or UNTITLED_LABEL
    return _normalize_label(node_title) == _normalize_label(first_child_title)


def _split_course_path(value: str | None) -> list[str]:
    if not value:
        return []

    separator = " > " if " > " in value else "/"
    return [segment.strip() for segment in value.split(separator) if segment and segment.strip()]


def get_course_structure_path(settings: Settings, job_id: str) -> Path:
    return Path(settings.data_dir) / "jobs" / job_id / COURSE_STRUCTURE_FILENAME
