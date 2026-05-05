from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pypdf import PdfReader

from app.core.config import Settings
from app.services.html_accessibility import (
    AccessibilityCheckResult,
    AccessibilityReport,
    append_accessibility_resource_result,
    load_accessibility_report,
    recompute_accessibility_summary,
    remove_accessibility_results,
    save_accessibility_report,
)
from app.services.resource_core import ResourceContentResult, get_resource_content, normalize_resource

GENERIC_PDF_TITLES = {
    "document",
    "documento",
    "untitled",
    "sin titulo",
    "sin título",
    "pdf",
}


def analyze_pdf_accessibility(resource: Any, pdf_path: Path) -> list[AccessibilityCheckResult]:
    try:
        reader = PdfReader(str(pdf_path))
    except Exception as exc:
        return [
            _result(
                "pdf.open",
                "PDF legible/no cifrado",
                "ERROR",
                f"No se pudo abrir el PDF: {exc.__class__.__name__}.",
                "Comprueba que el fichero sea un PDF válido antes de analizarlo.",
            )
        ]

    if getattr(reader, "is_encrypted", False):
        return _encrypted_pdf_checks()

    context = _PDFContext.from_reader(resource, pdf_path, reader)
    return [
        _check_readable(),
        _check_extractable_text(context),
        _check_language(context),
        _check_title(context),
        _check_tagged_pdf(context),
        _check_structured_headings(context),
        _check_figure_alt(context),
        _check_structured_tables(context),
        _check_links(context),
        _check_bookmarks(context),
    ]


def run_pdf_accessibility_scan(
    *,
    settings: Settings,
    job_id: str,
    resources: list[dict[str, Any]],
    canvas_client: Any | None = None,
    canvas_credentials: Any | None = None,
    course_id: str | None = None,
) -> AccessibilityReport:
    report = load_accessibility_report(settings, job_id)
    report.generatedAt = datetime.now(UTC)
    remove_accessibility_results(report, "PDF")

    for resource in resources:
        core = normalize_resource(resource)
        if not _should_attempt_pdf_scan(core):
            continue

        try:
            content = get_resource_content(
                job_id,
                core.id,
                settings=settings,
                resources=resources,
                canvas_client=canvas_client,
                canvas_credentials=canvas_credentials,
                course_id=course_id,
            )
        except Exception as exc:
            checks = [
                _result(
                    "pdf.content.available",
                    "Contenido PDF disponible",
                    "ERROR",
                    f"No se pudo recuperar el PDF: {exc.__class__.__name__}.",
                    "Comprueba que el recurso PDF sea accesible para el backend.",
                )
            ]
            append_accessibility_resource_result(report, resource, checks, analysis_type="PDF")
            continue

        if not content.ok:
            checks = [
                _result(
                    "pdf.content.available",
                    "Contenido PDF disponible",
                    "ERROR",
                    content.errorDetail or "No se pudo recuperar el PDF del recurso.",
                    "Comprueba que el recurso PDF sea accesible para el backend.",
                )
            ]
            append_accessibility_resource_result(report, resource, checks, analysis_type="PDF")
            continue

        if not _content_is_pdf(content):
            continue

        if not content.binaryPath:
            checks = [
                _result(
                    "pdf.content.available",
                    "Contenido PDF disponible",
                    "ERROR",
                    "El recurso PDF no tiene ruta binaria segura para analizar.",
                    "Asegura que el PDF se pueda resolver o cachear desde el backend.",
                )
            ]
            append_accessibility_resource_result(report, resource, checks, analysis_type="PDF")
            continue

        checks = analyze_pdf_accessibility(resource, Path(content.binaryPath))
        append_accessibility_resource_result(report, resource, checks, analysis_type="PDF")

    recompute_accessibility_summary(report)
    save_accessibility_report(settings, job_id, report)
    return report


def ensure_pdf_accessibility_report(
    *,
    settings: Settings,
    job_id: str,
    resources: list[dict[str, Any]],
    canvas_client: Any | None = None,
    canvas_credentials: Any | None = None,
    course_id: str | None = None,
) -> AccessibilityReport:
    report = load_accessibility_report(settings, job_id)
    eligible_count = sum(1 for resource in resources if _should_attempt_pdf_scan(normalize_resource(resource)))
    if eligible_count == 0 or report.summary.pdfResourcesTotal >= eligible_count:
        return report
    return run_pdf_accessibility_scan(
        settings=settings,
        job_id=job_id,
        resources=resources,
        canvas_client=canvas_client,
        canvas_credentials=canvas_credentials,
        course_id=course_id,
    )


class _PDFContext:
    def __init__(
        self,
        *,
        resource_title: str,
        filename_stem: str,
        page_count: int,
        text: str,
        lang: str | None,
        title: str | None,
        tagged: bool,
        structure_tags: list[str],
        figure_alt_values: list[str | None],
        link_destinations: list[bool],
        bookmark_count: int,
    ) -> None:
        self.resource_title = resource_title
        self.filename_stem = filename_stem
        self.page_count = page_count
        self.text = text
        self.lang = lang
        self.title = title
        self.tagged = tagged
        self.structure_tags = structure_tags
        self.figure_alt_values = figure_alt_values
        self.link_destinations = link_destinations
        self.bookmark_count = bookmark_count

    @classmethod
    def from_reader(cls, resource: Any, pdf_path: Path, reader: PdfReader) -> _PDFContext:
        root = _catalog(reader)
        structure_tags, figure_alt_values = _collect_structure(root)
        return cls(
            resource_title=_resource_title(resource),
            filename_stem=pdf_path.stem,
            page_count=_page_count(reader),
            text=_extract_text(reader),
            lang=_pdf_text(root.get("/Lang")) if isinstance(root, dict) else None,
            title=_metadata_title(reader),
            tagged=_is_tagged(root),
            structure_tags=structure_tags,
            figure_alt_values=figure_alt_values,
            link_destinations=_link_destinations(reader),
            bookmark_count=_bookmark_count(reader),
        )


def _check_readable() -> AccessibilityCheckResult:
    return _result(
        "pdf.readable",
        "PDF legible/no cifrado",
        "PASS",
        "El PDF se puede abrir sin contraseña.",
        "Mantén el documento sin restricciones que impidan su lectura por tecnologías de apoyo.",
    )


def _check_extractable_text(context: _PDFContext) -> AccessibilityCheckResult:
    text_length = len(context.text)
    if text_length >= 40:
        return _result(
            "pdf.extractable_text",
            "Texto extraíble",
            "PASS",
            f"Se han extraído {text_length} caracteres de texto.",
            "Verifica igualmente la lectura semántica del documento.",
            "WCAG 1.4.5",
        )
    if text_length > 0:
        return _result(
            "pdf.extractable_text",
            "Texto extraíble",
            "WARNING",
            f"Solo se han extraído {text_length} caracteres de texto.",
            "Revisa si el PDF contiene texto real suficiente o si necesita una versión accesible.",
            "WCAG 1.4.5",
        )
    return _result(
        "pdf.extractable_text",
        "Texto extraíble",
        "FAIL",
        "No se ha podido extraer texto significativo; podría ser un PDF escaneado.",
        "Publica una versión con texto seleccionable o añade OCR en el proceso de creación.",
        "WCAG 1.4.5",
    )


def _check_language(context: _PDFContext) -> AccessibilityCheckResult:
    if context.lang:
        return _result(
            "pdf.lang",
            "Idioma del documento",
            "PASS",
            f"El PDF declara /Lang={context.lang}.",
            "Mantén el idioma del documento actualizado.",
            "WCAG 3.1.1",
        )
    return _result(
        "pdf.lang",
        "Idioma del documento",
        "FAIL",
        "No se ha encontrado /Lang en el catálogo del PDF.",
        "Define el idioma principal del documento en las propiedades del PDF.",
        "WCAG 3.1.1",
    )


def _check_title(context: _PDFContext) -> AccessibilityCheckResult:
    title = _normalize_text(context.title or "")
    if title and not _is_generic_pdf_title(title, context):
        return _result(
            "pdf.title",
            "Título del documento",
            "PASS",
            f"El PDF tiene título de metadatos: \"{_shorten(title)}\".",
            "Usa títulos únicos y descriptivos en los metadatos.",
            "WCAG 2.4.2",
        )
    return _result(
        "pdf.title",
        "Título del documento",
        "WARNING",
        "No hay título de metadatos útil o parece el nombre del archivo.",
        "Añade un título descriptivo en las propiedades del PDF.",
        "WCAG 2.4.2",
    )


def _check_tagged_pdf(context: _PDFContext) -> AccessibilityCheckResult:
    if context.tagged:
        return _result(
            "pdf.tagged",
            "PDF etiquetado",
            "PASS",
            "El PDF declara /MarkInfo Marked=true y tiene /StructTreeRoot.",
            "Mantén la estructura etiquetada al exportar nuevas versiones.",
            "WCAG 1.3.1",
        )
    return _result(
        "pdf.tagged",
        "PDF etiquetado",
        "FAIL",
        "No se detecta estructura etiquetada completa.",
        "Exporta el documento como PDF etiquetado con árbol de estructura.",
        "WCAG 1.3.1",
    )


def _check_structured_headings(context: _PDFContext) -> AccessibilityCheckResult:
    if not context.tagged:
        return _result(
            "pdf.headings",
            "Encabezados estructurados",
            "NOT_APPLICABLE",
            "No se evalúan encabezados porque el PDF no está etiquetado.",
            "Primero genera un PDF etiquetado y después verifica los encabezados.",
            "WCAG 1.3.1",
        )
    headings = [tag for tag in context.structure_tags if tag in {"H", "H1", "H2", "H3", "H4", "H5", "H6"}]
    if headings:
        return _result(
            "pdf.headings",
            "Encabezados estructurados",
            "PASS",
            f"Se detectan etiquetas de encabezado: {', '.join(headings[:5])}.",
            "Comprueba manualmente que la jerarquía sea lógica.",
            "WCAG 1.3.1",
        )
    return _result(
        "pdf.headings",
        "Encabezados estructurados",
        "WARNING",
        "El PDF está etiquetado, pero no se detectan H1/H2/H3.",
        "Añade encabezados semánticos a la estructura del PDF.",
        "WCAG 1.3.1",
    )


def _check_figure_alt(context: _PDFContext) -> AccessibilityCheckResult:
    if not context.tagged:
        return _result(
            "pdf.figure_alt",
            "Imágenes con texto alternativo",
            "WARNING",
            "No se puede determinar el texto alternativo porque el PDF no está etiquetado.",
            "Etiqueta las figuras y añade /Alt cuando transmitan información.",
            "WCAG 1.1.1",
        )
    if not context.figure_alt_values:
        return _result(
            "pdf.figure_alt",
            "Imágenes con texto alternativo",
            "NOT_APPLICABLE",
            "No se detectan figuras etiquetadas.",
            "Cuando haya figuras informativas, añade texto alternativo.",
            "WCAG 1.1.1",
        )
    missing = [value for value in context.figure_alt_values if not value]
    if missing:
        return _result(
            "pdf.figure_alt",
            "Imágenes con texto alternativo",
            "FAIL",
            f"{len(missing)} figura(s) etiquetadas no tienen /Alt.",
            "Añade texto alternativo a las figuras informativas.",
            "WCAG 1.1.1",
        )
    return _result(
        "pdf.figure_alt",
        "Imágenes con texto alternativo",
        "PASS",
        "Todas las figuras etiquetadas tienen /Alt.",
        "Mantén textos alternativos equivalentes al propósito de cada imagen.",
        "WCAG 1.1.1",
    )


def _check_structured_tables(context: _PDFContext) -> AccessibilityCheckResult:
    tags = set(context.structure_tags)
    if "Table" in tags:
        if {"TR", "TD"}.issubset(tags) or {"TR", "TH"}.issubset(tags):
            return _result(
                "pdf.tables",
                "Tablas estructuradas",
                "PASS",
                "Se detecta estructura Table/TR con celdas TH o TD.",
                "Verifica manualmente encabezados y asociaciones en tablas complejas.",
                "WCAG 1.3.1",
            )
        return _result(
            "pdf.tables",
            "Tablas estructuradas",
            "WARNING",
            "Hay etiqueta Table, pero la estructura de filas/celdas no es clara.",
            "Reestructura la tabla con Table, TR, TH y TD.",
            "WCAG 1.3.1",
        )
    if _looks_like_visual_table(context.text):
        return _result(
            "pdf.tables",
            "Tablas estructuradas",
            "WARNING",
            "El texto sugiere una tabla visual, pero no hay estructura Table.",
            "Etiqueta las tablas de datos con estructura semántica.",
            "WCAG 1.3.1",
        )
    return _result(
        "pdf.tables",
        "Tablas estructuradas",
        "NOT_APPLICABLE",
        "No se detectan tablas estructuradas ni indicios claros de tabla visual.",
        "Si el documento contiene tablas, revisa manualmente su estructura.",
        "WCAG 1.3.1",
    )


def _check_links(context: _PDFContext) -> AccessibilityCheckResult:
    if not context.link_destinations:
        return _result(
            "pdf.links",
            "Enlaces detectables",
            "NOT_APPLICABLE",
            "No se detectan anotaciones de enlace.",
            "Cuando añadas enlaces, usa anotaciones con destino claro y texto contextual.",
            "WCAG 2.4.4",
        )
    missing = [has_destination for has_destination in context.link_destinations if not has_destination]
    if missing:
        return _result(
            "pdf.links",
            "Enlaces detectables",
            "WARNING",
            f"{len(missing)} enlace(s) no tienen destino claro.",
            "Comprueba destino y texto contextual de cada enlace.",
            "WCAG 2.4.4",
        )
    return _result(
        "pdf.links",
        "Enlaces detectables",
        "PASS",
        f"Se detectan {len(context.link_destinations)} enlace(s) con destino.",
        "Verifica manualmente que el texto del enlace describa el destino.",
        "WCAG 2.4.4",
    )


def _check_bookmarks(context: _PDFContext) -> AccessibilityCheckResult:
    if context.page_count <= 5:
        return _result(
            "pdf.bookmarks",
            "Marcadores en documentos largos",
            "NOT_APPLICABLE",
            f"El PDF tiene {context.page_count} página(s), no supera el umbral de documento largo.",
            "Añade marcadores cuando el documento sea largo o complejo.",
            "WCAG 2.4.5",
        )
    if context.bookmark_count > 0:
        return _result(
            "pdf.bookmarks",
            "Marcadores en documentos largos",
            "PASS",
            f"El PDF tiene {context.page_count} páginas y {context.bookmark_count} marcador(es).",
            "Mantén marcadores útiles para navegar por secciones.",
            "WCAG 2.4.5",
        )
    return _result(
        "pdf.bookmarks",
        "Marcadores en documentos largos",
        "WARNING",
        f"El PDF tiene {context.page_count} páginas y no se detectan marcadores.",
        "Añade marcadores para facilitar la navegación.",
        "WCAG 2.4.5",
    )


def _encrypted_pdf_checks() -> list[AccessibilityCheckResult]:
    blocked = "No se analiza este criterio porque el PDF está cifrado o bloqueado."
    return [
        _result(
            "pdf.readable",
            "PDF legible/no cifrado",
            "FAIL",
            "El PDF está cifrado o requiere contraseña.",
            "Publica una versión que se pueda abrir sin contraseña para revisión de accesibilidad.",
        ),
        _result("pdf.extractable_text", "Texto extraíble", "ERROR", blocked, "Desbloquea el PDF antes de analizarlo."),
        _result("pdf.lang", "Idioma del documento", "ERROR", blocked, "Desbloquea el PDF antes de analizarlo."),
        _result("pdf.title", "Título del documento", "ERROR", blocked, "Desbloquea el PDF antes de analizarlo."),
        _result("pdf.tagged", "PDF etiquetado", "ERROR", blocked, "Desbloquea el PDF antes de analizarlo."),
        _result("pdf.headings", "Encabezados estructurados", "ERROR", blocked, "Desbloquea el PDF antes de analizarlo."),
        _result("pdf.figure_alt", "Imágenes con texto alternativo", "ERROR", blocked, "Desbloquea el PDF antes de analizarlo."),
        _result("pdf.tables", "Tablas estructuradas", "ERROR", blocked, "Desbloquea el PDF antes de analizarlo."),
        _result("pdf.links", "Enlaces detectables", "ERROR", blocked, "Desbloquea el PDF antes de analizarlo."),
        _result("pdf.bookmarks", "Marcadores en documentos largos", "ERROR", blocked, "Desbloquea el PDF antes de analizarlo."),
    ]


def _should_attempt_pdf_scan(core: Any) -> bool:
    if core.origin in {"RALTI", "LTI", "EXTERNAL_URL"}:
        return False
    if core.accessStatus in {"REQUIERE_SSO", "REQUIERE_INTERACCION", "NO_ANALIZABLE"}:
        return False
    if core.type != "PDF":
        return False
    return bool(core.contentAvailable)


def _content_is_pdf(content: ResourceContentResult) -> bool:
    mime_type = (content.mimeType or "").split(";", 1)[0].strip().lower()
    filename = (content.filename or content.binaryPath or "").lower()
    return content.contentKind == "PDF" or mime_type == "application/pdf" or filename.endswith(".pdf")


def _catalog(reader: PdfReader) -> dict[str, Any]:
    try:
        return _resolve(reader.trailer["/Root"])
    except Exception:
        return {}


def _is_tagged(root: dict[str, Any]) -> bool:
    mark_info = _resolve(root.get("/MarkInfo")) if isinstance(root, dict) else None
    marked = bool(mark_info.get("/Marked")) if isinstance(mark_info, dict) else False
    return marked and bool(root.get("/StructTreeRoot"))


def _collect_structure(root: dict[str, Any]) -> tuple[list[str], list[str | None]]:
    struct_root = _resolve(root.get("/StructTreeRoot")) if isinstance(root, dict) else None
    tags: list[str] = []
    figure_alt_values: list[str | None] = []
    visited: set[int] = set()

    def walk(value: Any) -> None:
        value = _resolve(value)
        marker = id(value)
        if marker in visited:
            return
        visited.add(marker)

        if isinstance(value, list):
            for item in value:
                walk(item)
            return
        if not isinstance(value, dict):
            return

        tag = _pdf_name(value.get("/S"))
        if tag:
            tags.append(tag)
            if tag == "Figure":
                figure_alt_values.append(_pdf_text(value.get("/Alt")))
        if "/K" in value:
            walk(value.get("/K"))

    if isinstance(struct_root, dict):
        walk(struct_root.get("/K"))
    return tags, figure_alt_values


def _link_destinations(reader: PdfReader) -> list[bool]:
    destinations: list[bool] = []
    for page in _safe_pages(reader):
        annotations = _resolve(page.get("/Annots", []))
        if not isinstance(annotations, list):
            continue
        for annotation_ref in annotations:
            annotation = _resolve(annotation_ref)
            if not isinstance(annotation, dict) or _pdf_name(annotation.get("/Subtype")) != "Link":
                continue
            action = _resolve(annotation.get("/A"))
            has_destination = bool(annotation.get("/Dest"))
            if isinstance(action, dict):
                has_destination = has_destination or bool(action.get("/URI") or action.get("/D"))
            destinations.append(has_destination)
    return destinations


def _extract_text(reader: PdfReader) -> str:
    parts: list[str] = []
    for page in _safe_pages(reader):
        try:
            text = page.extract_text() or ""
        except Exception:
            continue
        if text.strip():
            parts.append(text)
    return _normalize_text(" ".join(parts))


def _page_count(reader: PdfReader) -> int:
    try:
        return len(reader.pages)
    except Exception:
        return 0


def _safe_pages(reader: PdfReader) -> list[Any]:
    try:
        return list(reader.pages)
    except Exception:
        return []


def _metadata_title(reader: PdfReader) -> str | None:
    try:
        metadata = reader.metadata
    except Exception:
        return None
    if metadata is None:
        return None
    title = getattr(metadata, "title", None)
    if title:
        return str(title)
    try:
        raw_title = metadata.get("/Title")
    except Exception:
        return None
    return str(raw_title) if raw_title else None


def _bookmark_count(reader: PdfReader) -> int:
    try:
        outline = reader.outline
    except Exception:
        return 0
    return _count_outline_items(outline)


def _count_outline_items(value: Any) -> int:
    if isinstance(value, list):
        return sum(_count_outline_items(item) for item in value)
    return 1 if value else 0


def _resolve(value: Any) -> Any:
    try:
        return value.get_object()
    except Exception:
        return value


def _pdf_name(value: Any) -> str:
    value = _resolve(value)
    return str(value or "").lstrip("/")


def _pdf_text(value: Any) -> str | None:
    value = _resolve(value)
    text = str(value or "").strip()
    return text or None


def _looks_like_visual_table(text: str) -> bool:
    rows = [
        line
        for line in text.splitlines()
        if "\t" in line or len([part for part in line.split("  ") if part.strip()]) >= 3
    ]
    return len(rows) >= 2


def _is_generic_pdf_title(title: str, context: _PDFContext) -> bool:
    normalized = _normalize_text(title).strip(" .:-").lower()
    filename = _normalize_text(context.filename_stem).strip(" .:-").lower()
    return normalized in GENERIC_PDF_TITLES or normalized == filename


def _resource_title(resource: Any) -> str:
    if isinstance(resource, dict):
        return _normalize_text(str(resource.get("title") or ""))
    return _normalize_text(str(getattr(resource, "title", "") or ""))


def _result(
    check_id: str,
    title: str,
    status: str,
    evidence: str,
    recommendation: str,
    wcag_hint: str | None = None,
) -> AccessibilityCheckResult:
    return AccessibilityCheckResult(
        checkId=check_id,
        checkTitle=title,
        status=status,
        evidence=evidence,
        recommendation=recommendation,
        wcagHint=wcag_hint,
    )


def _normalize_text(value: str) -> str:
    return " ".join(value.strip().split())


def _shorten(value: str, limit: int = 80) -> str:
    normalized = _normalize_text(value)
    return normalized if len(normalized) <= limit else f"{normalized[: limit - 1]}…"
