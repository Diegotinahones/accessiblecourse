from __future__ import annotations

from typing import Any, Literal

from app.services.resource_core import normalize_resource

CheckResponsibility = Literal[
    "PROFESSOR_ACTIONABLE",
    "PLATFORM_CONTROLLED",
    "MANUAL_REVIEW",
    "NOT_COVERED",
    "PROVIDER_EXTERNAL",
]

PROFESSOR_ACTIONABLE = "PROFESSOR_ACTIONABLE"
PLATFORM_CONTROLLED = "PLATFORM_CONTROLLED"
MANUAL_REVIEW = "MANUAL_REVIEW"
NOT_COVERED = "NOT_COVERED"
PROVIDER_EXTERNAL = "PROVIDER_EXTERNAL"
RESPONSIBILITY_VALUES = {
    PROFESSOR_ACTIONABLE,
    PLATFORM_CONTROLLED,
    MANUAL_REVIEW,
    NOT_COVERED,
    PROVIDER_EXTERNAL,
}

ISSUE_STATUSES = {"FAIL", "WARNING", "ERROR"}

HTML_PLATFORM_CONTROLLED_CHECKS = {
    "html.lang",
    "html.title",
    "html.h1",
    "html.button_name",
    "html.form_label",
    "html.form_labels",
    "html.iframe_title",
}

HTML_PROFESSOR_ACTIONABLE_CHECKS = {
    "html.heading_hierarchy",
    "html.img_alt",
    "html.images_alt",
    "html.link_text",
    "html.links_descriptive",
    "html.table_headers",
    "html.tables",
}

VIDEO_EXTERNAL_MANUAL_REVIEW_CHECKS = {
    "video.accessible",
    "video.manual_review",
    "video.captions",
    "video.transcript",
    "video.audio_description",
    "video.controls",
    "video.local_metadata",
}

VIDEO_PROVIDER_CHECKS = {"video.provider"}


def classify_check_responsibility(
    check_id: str,
    *,
    analysis_type: str | None = None,
    status: str | None = None,
    resource: Any | None = None,
    inventory_item: Any | None = None,
) -> CheckResponsibility:
    normalized_id = str(check_id or "")
    normalized_type = str(analysis_type or "").upper()
    normalized_status = str(status or "").upper()

    if normalized_id in HTML_PLATFORM_CONTROLLED_CHECKS:
        return PLATFORM_CONTROLLED
    if normalized_type == "HTML" and normalized_id not in HTML_PROFESSOR_ACTIONABLE_CHECKS:
        return PLATFORM_CONTROLLED

    if normalized_type == "VIDEO" or normalized_id.startswith("video."):
        is_external = _is_external_video(resource=resource, inventory_item=inventory_item)
        if normalized_id == "video.manual_review" and normalized_status in ISSUE_STATUSES:
            return MANUAL_REVIEW
        if is_external and normalized_id in VIDEO_PROVIDER_CHECKS:
            return PROVIDER_EXTERNAL
        if is_external and normalized_id in VIDEO_EXTERNAL_MANUAL_REVIEW_CHECKS:
            return MANUAL_REVIEW if normalized_status in ISSUE_STATUSES else PROVIDER_EXTERNAL
        return PROFESSOR_ACTIONABLE

    if normalized_type in {"PDF", "DOCX", "NOTEBOOK"}:
        return PROFESSOR_ACTIONABLE

    if normalized_id.startswith(("pdf.", "docx.", "notebook.")):
        return PROFESSOR_ACTIONABLE

    return PROFESSOR_ACTIONABLE


def responsibility_label(responsibility: str | None) -> str:
    return {
        PROFESSOR_ACTIONABLE: "Accionable por el profesorado",
        PLATFORM_CONTROLLED: "Depende de Canvas/UOC",
        MANUAL_REVIEW: "Requiere revisión manual",
        PROVIDER_EXTERNAL: "Proveedor externo",
        NOT_COVERED: "No cubierto automáticamente",
    }.get(str(responsibility or ""), "Accionable por el profesorado")


def responsibility_note(responsibility: str | None, check_title: str | None = None) -> str:
    title = str(check_title or "Este aspecto")
    if responsibility == PLATFORM_CONTROLLED:
        return (
            f"{title}: no contabilizado. Este elemento depende de la configuración o plataforma Canvas/UOC "
            "y no se considera una incidencia accionable por el profesorado."
        )
    if responsibility == MANUAL_REVIEW:
        return (
            f"{title}: requiere revisión manual. No se descargan vídeos de plataformas externas; se verifican "
            "señales disponibles y se marca revisión manual cuando no se puede comprobar automáticamente."
        )
    if responsibility == PROVIDER_EXTERNAL:
        return (
            f"{title}: depende de un proveedor externo. Se recomienda revisar la evidencia desde el entorno "
            "original antes de atribuir una acción correctiva al profesorado."
        )
    if responsibility == NOT_COVERED:
        return (
            f"{title}: no cubierto automáticamente. No penaliza el score y requiere una revisión manual si es "
            "relevante para la experiencia de aprendizaje."
        )
    return "Incidencia accionable por el profesorado o por la preparación del material subido al aula."


def is_scored_responsibility(responsibility: str | None) -> bool:
    return responsibility == PROFESSOR_ACTIONABLE


def is_actionable_issue(responsibility: str | None, status: str | None) -> bool:
    return responsibility == PROFESSOR_ACTIONABLE and str(status or "").upper() in {"FAIL", "ERROR"}


def is_warning_or_manual_review(responsibility: str | None, status: str | None) -> bool:
    normalized_status = str(status or "").upper()
    return (
        (responsibility == PROFESSOR_ACTIONABLE and normalized_status == "WARNING")
        or (responsibility in {MANUAL_REVIEW, PROVIDER_EXTERNAL} and normalized_status in ISSUE_STATUSES)
    )


def is_provider_external_observation(responsibility: str | None, status: str | None) -> bool:
    return responsibility == PROVIDER_EXTERNAL and str(status or "").upper() in ISSUE_STATUSES


def is_platform_observation(responsibility: str | None, status: str | None) -> bool:
    return responsibility == PLATFORM_CONTROLLED and str(status or "").upper() in ISSUE_STATUSES


def is_reportable_issue(responsibility: str | None, status: str | None) -> bool:
    return (
        is_actionable_issue(responsibility, status)
        or is_warning_or_manual_review(responsibility, status)
        or is_provider_external_observation(responsibility, status)
    )


def _is_external_video(*, resource: Any | None, inventory_item: Any | None) -> bool:
    source = inventory_item if inventory_item is not None else resource
    if source is None:
        return False
    try:
        core = normalize_resource(source)
    except Exception:
        return False
    return core.type == "VIDEO" and core.origin in {"EXTERNAL_URL", "RALTI", "LTI", "ONLINE_CANVAS"}
