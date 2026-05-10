from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.core.config import Settings

COURSE_METADATA_FILENAME = "metadata.json"
DEFAULT_COURSE_TITLE = "Curso analizado"


def choose_course_title(*candidates: str | None, fallback: str | None = None) -> str:
    cleaned_candidates = [_clean_text(candidate) for candidate in candidates]
    cleaned_candidates = [candidate for candidate in cleaned_candidates if candidate]
    if fallback:
        cleaned_fallback = _clean_text(fallback)
        if cleaned_fallback:
            cleaned_candidates.append(cleaned_fallback)
    if not cleaned_candidates:
        return DEFAULT_COURSE_TITLE

    selected = cleaned_candidates[0]
    for candidate in cleaned_candidates[1:]:
        if _is_better_full_title(selected, candidate):
            selected = candidate
    return selected


def build_course_metadata(
    *,
    course_id: str | None = None,
    course_name: str | None = None,
    course_code: str | None = None,
    course_title: str | None = None,
    source: str | None = None,
) -> dict[str, str | None]:
    resolved_title = choose_course_title(course_title, course_name, course_code)
    resolved_name = _clean_text(course_name) or resolved_title
    return {
        "source": _clean_text(source),
        "courseId": _clean_text(course_id),
        "courseTitle": resolved_title,
        "courseName": resolved_name,
        "courseCode": _clean_text(course_code),
    }


def save_course_metadata(settings: Settings, job_id: str, metadata: dict[str, Any]) -> None:
    path = get_course_metadata_path(settings, job_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {key: value for key, value in metadata.items() if value is not None}
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def load_course_metadata(settings: Settings, job_id: str) -> dict[str, Any]:
    path = get_course_metadata_path(settings, job_id)
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def get_course_metadata_path(settings: Settings, job_id: str) -> Path:
    return settings.storage_root / "jobs" / job_id / COURSE_METADATA_FILENAME


def metadata_course_title(metadata: dict[str, Any], *fallbacks: str | None) -> str:
    return choose_course_title(
        _string(metadata, "courseTitle", "course_title"),
        _string(metadata, "courseName", "course_name"),
        _string(metadata, "courseCode", "course_code"),
        *fallbacks,
    )


def public_course_metadata(metadata: dict[str, Any], *, fallback_title: str | None = None) -> dict[str, str | None]:
    title = metadata_course_title(metadata, fallback_title)
    return {
        "courseTitle": title,
        "courseName": _string(metadata, "courseName", "course_name") or title,
        "courseCode": _string(metadata, "courseCode", "course_code"),
        "courseId": _string(metadata, "courseId", "course_id"),
    }


def _is_better_full_title(current: str, candidate: str) -> bool:
    if candidate == current:
        return False
    if len(candidate) <= len(current):
        return False
    current_normalized = current.lower()
    candidate_normalized = candidate.lower()
    current_is_short = len(current) <= 4 or len(current.split()) == 1
    candidate_contains_current = (
        candidate_normalized.startswith(f"{current_normalized}.")
        or candidate_normalized.startswith(f"{current_normalized} ")
        or candidate_normalized.startswith(f"{current_normalized} -")
        or current_normalized in candidate_normalized
    )
    if current_is_short and candidate_contains_current:
        return True
    return False


def _clean_text(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = " ".join(str(value).strip().split())
    return cleaned or None


def _string(payload: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = payload.get(key)
        cleaned = _clean_text(value if isinstance(value, str) else str(value) if value is not None else None)
        if cleaned:
            return cleaned
    return None
