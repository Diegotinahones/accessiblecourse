from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

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

NOTEBOOK_MIME_TYPES = {"application/x-ipynb+json"}
JSON_MIME_TYPES = NOTEBOOK_MIME_TYPES | {"application/json"}
GENERIC_IMAGE_ALT_TEXTS = {
    "image",
    "imagen",
    "figura",
    "grafico",
    "gráfico",
    "plot",
    "chart",
    "screenshot",
    "captura",
}
GENERIC_LINK_TEXTS = {
    "aqui",
    "aquí",
    "click aqui",
    "click aquí",
    "clic aqui",
    "clic aquí",
    "leer mas",
    "leer más",
    "mas",
    "más",
    "ver mas",
    "ver más",
    "enlace",
    "link",
}
VISUAL_OUTPUT_MIME_TYPES = {
    "image/png",
    "image/jpeg",
    "image/jpg",
    "image/svg+xml",
    "image/gif",
    "application/vnd.plotly.v1+json",
}
NOTEBOOK_ANALYSIS_SCOPE_NOTE = (
    "Los notebooks se analizan de forma estática. AccessibleCourse no ejecuta código ni instala kernels; "
    "revisa estructura, celdas Markdown, salidas guardadas, enlaces, imágenes y errores almacenados."
)
MARKDOWN_HEADING_RE = re.compile(r"^\s*(#{1,6})\s+\S", re.MULTILINE)
MARKDOWN_IMAGE_RE = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")
MARKDOWN_LINK_RE = re.compile(r"(?<!!)\[([^\]]+)\]\(([^)]+)\)")
URL_TEXT_RE = re.compile(r"(?:^|\s)(https?://\S+|www\.\S+)", re.IGNORECASE)
TABLE_SEPARATOR_RE = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)+\|?\s*$")


@dataclass(slots=True)
class _NotebookContext:
    resource_title: str
    cells: list[dict[str, Any]]
    markdown_cells: list[tuple[int, str]]
    code_cells: list[tuple[int, dict[str, Any]]]
    heading_levels: list[int]
    image_alts: list[str]
    link_texts: list[str]
    naked_urls: list[str]
    visual_output_cells: list[int]
    error_outputs: int
    execution_counts: list[int | None]
    table_lines: list[str]
    valid_table_count: int

    @classmethod
    def from_payload(cls, resource: Any, notebook: dict[str, Any]) -> _NotebookContext:
        cells = [cell for cell in notebook.get("cells", []) if isinstance(cell, dict)]
        markdown_cells: list[tuple[int, str]] = []
        code_cells: list[tuple[int, dict[str, Any]]] = []
        heading_levels: list[int] = []
        image_alts: list[str] = []
        link_texts: list[str] = []
        naked_urls: list[str] = []
        visual_output_cells: list[int] = []
        error_outputs = 0
        execution_counts: list[int | None] = []
        table_lines: list[str] = []
        valid_table_count = 0

        for index, cell in enumerate(cells):
            cell_type = str(cell.get("cell_type") or "").lower()
            source = _source_text(cell.get("source"))
            if cell_type == "markdown":
                markdown_cells.append((index, source))
                heading_levels.extend(len(match.group(1)) for match in MARKDOWN_HEADING_RE.finditer(source))
                image_alts.extend(match.group(1).strip() for match in MARKDOWN_IMAGE_RE.finditer(source))
                link_texts.extend(match.group(1).strip() for match in MARKDOWN_LINK_RE.finditer(source))
                naked_urls.extend(match.group(1).strip() for match in URL_TEXT_RE.finditer(_strip_markdown_links(source)))
                table_lines.extend(_markdown_table_like_lines(source))
                valid_table_count += _count_valid_markdown_tables(source)
            elif cell_type == "code":
                code_cells.append((index, cell))
                execution_count = cell.get("execution_count")
                execution_counts.append(execution_count if isinstance(execution_count, int) else None)
                outputs = cell.get("outputs") if isinstance(cell.get("outputs"), list) else []
                for output in outputs:
                    if not isinstance(output, dict):
                        continue
                    if output.get("output_type") == "error":
                        error_outputs += 1
                    if _is_visual_output(output):
                        visual_output_cells.append(index)

        return cls(
            resource_title=_resource_title(resource),
            cells=cells,
            markdown_cells=markdown_cells,
            code_cells=code_cells,
            heading_levels=heading_levels,
            image_alts=image_alts,
            link_texts=link_texts,
            naked_urls=naked_urls,
            visual_output_cells=visual_output_cells,
            error_outputs=error_outputs,
            execution_counts=execution_counts,
            table_lines=table_lines,
            valid_table_count=valid_table_count,
        )


def analyze_notebook_accessibility(resource: Any, notebook_path: Path) -> list[AccessibilityCheckResult]:
    try:
        notebook = _read_notebook(notebook_path)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        return [
            _result(
                "notebook.readable",
                "Notebook legible",
                "FAIL",
                f"No se pudo abrir o parsear el notebook: {exc.__class__.__name__}.",
                "Comprueba que el fichero sea un .ipynb válido y no esté corrupto.",
            )
        ]

    context = _NotebookContext.from_payload(resource, notebook)
    return [
        _check_readable(),
        _check_intro_markdown(context),
        _check_title(context),
        _check_heading_hierarchy(context),
        _check_markdown_explanation(context),
        _check_image_alt(context),
        _check_links(context),
        _check_visual_outputs(context),
        _check_execution_errors(context),
        _check_execution_order(context),
        _check_markdown_tables(context),
    ]


def run_notebook_accessibility_scan(
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
    remove_accessibility_results(report, "NOTEBOOK")

    for resource in resources:
        core = normalize_resource(resource)
        if not _should_attempt_notebook_scan(resource, core):
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
            checks = _notebook_scan_error_checks(
                f"No se pudo recuperar el notebook: {exc.__class__.__name__}.",
                "Comprueba que el notebook sea accesible para el backend.",
            )
            append_accessibility_resource_result(report, resource, checks, analysis_type="NOTEBOOK")
            continue

        if not content.ok:
            checks = _notebook_scan_error_checks(
                content.errorDetail or "No se pudo recuperar el notebook del recurso.",
                "Comprueba que el notebook sea accesible para el backend.",
            )
            append_accessibility_resource_result(report, resource, checks, analysis_type="NOTEBOOK")
            continue

        if not _content_is_notebook(content):
            continue

        if not content.binaryPath:
            checks = _notebook_scan_error_checks(
                "El notebook no tiene ruta binaria segura para analizar.",
                "Asegura que el .ipynb se pueda resolver o cachear desde el backend.",
            )
            append_accessibility_resource_result(report, resource, checks, analysis_type="NOTEBOOK")
            continue

        try:
            checks = analyze_notebook_accessibility(resource, Path(content.binaryPath))
        except Exception as exc:
            checks = _notebook_scan_error_checks(
                f"No se pudo analizar el notebook: {exc.__class__.__name__}.",
                "Revisa el notebook manualmente y vuelve a intentar el analisis.",
            )
        append_accessibility_resource_result(report, resource, checks, analysis_type="NOTEBOOK")

    recompute_accessibility_summary(report)
    save_accessibility_report(settings, job_id, report)
    return report


def ensure_notebook_accessibility_report(
    *,
    settings: Settings,
    job_id: str,
    resources: list[dict[str, Any]],
    canvas_client: Any | None = None,
    canvas_credentials: Any | None = None,
    course_id: str | None = None,
) -> AccessibilityReport:
    report = load_accessibility_report(settings, job_id)
    eligible_count = sum(
        1 for resource in resources if _should_attempt_notebook_scan(resource, normalize_resource(resource))
    )
    if eligible_count == 0 or report.summary.notebookResourcesTotal >= eligible_count:
        return report
    return run_notebook_accessibility_scan(
        settings=settings,
        job_id=job_id,
        resources=resources,
        canvas_client=canvas_client,
        canvas_credentials=canvas_credentials,
        course_id=course_id,
    )


def _check_readable() -> AccessibilityCheckResult:
    return _result(
        "notebook.readable",
        "Notebook legible",
        "PASS",
        "El notebook se puede abrir y parsear como JSON.",
        "Mantén el .ipynb válido y sin dependencias de ejecución para poder analizarlo con seguridad.",
    )


def _check_intro_markdown(context: _NotebookContext) -> AccessibilityCheckResult:
    if not context.markdown_cells:
        return _result(
            "notebook.intro_markdown",
            "Texto explicativo inicial",
            "FAIL",
            "No hay celdas Markdown explicativas en el notebook.",
            "Añade una introducción en Markdown antes de las celdas de código.",
            "WCAG 3.3.2",
        )
    first_meaningful_index = _first_meaningful_cell_index(context.cells)
    if first_meaningful_index is not None and _cell_type(context.cells[first_meaningful_index]) == "markdown":
        return _result(
            "notebook.intro_markdown",
            "Texto explicativo inicial",
            "PASS",
            "El notebook empieza con una celda Markdown introductoria.",
            "Mantén una introducción clara antes de la actividad o práctica.",
            "WCAG 3.3.2",
        )
    return _result(
        "notebook.intro_markdown",
        "Texto explicativo inicial",
        "WARNING",
        "El notebook empieza directamente con código aunque contiene Markdown más adelante.",
        "Incluye una celda inicial que explique objetivo, requisitos y uso del notebook.",
        "WCAG 3.3.2",
    )


def _check_title(context: _NotebookContext) -> AccessibilityCheckResult:
    if any(level == 1 for level in context.heading_levels):
        return _result(
            "notebook.title",
            "Título principal",
            "PASS",
            "Se detecta un encabezado Markdown de nivel 1.",
            "Usa un único título principal descriptivo al inicio del notebook.",
            "WCAG 2.4.2",
        )
    return _result(
        "notebook.title",
        "Título principal",
        "WARNING",
        "No se detecta encabezado Markdown de nivel 1.",
        "Añade un título principal con '# Título' para orientar al alumnado.",
        "WCAG 2.4.2",
    )


def _check_heading_hierarchy(context: _NotebookContext) -> AccessibilityCheckResult:
    if not context.heading_levels:
        return _result(
            "notebook.heading_hierarchy",
            "Jerarquía de encabezados Markdown",
            "NOT_APPLICABLE",
            "No hay encabezados Markdown para evaluar.",
            "Usa encabezados Markdown para estructurar las secciones del notebook.",
            "WCAG 1.3.1",
        )
    skips: list[str] = []
    previous = context.heading_levels[0]
    for level in context.heading_levels[1:]:
        if level - previous > 1:
            skips.append(f"h{previous} -> h{level}")
        previous = level
    if not skips:
        return _result(
            "notebook.heading_hierarchy",
            "Jerarquía de encabezados Markdown",
            "PASS",
            "La secuencia de encabezados Markdown no presenta saltos bruscos.",
            "Mantén una jerarquía ordenada de títulos y subtítulos.",
            "WCAG 1.3.1",
        )
    return _result(
        "notebook.heading_hierarchy",
        "Jerarquía de encabezados Markdown",
        "WARNING",
        f"Se detectan saltos de jerarquía: {'; '.join(skips[:3])}.",
        "Inserta los niveles intermedios necesarios o ajusta los encabezados.",
        "WCAG 1.3.1",
    )


def _check_markdown_explanation(context: _NotebookContext) -> AccessibilityCheckResult:
    if not context.markdown_cells:
        return _result(
            "notebook.markdown_explanation",
            "Celdas Markdown descriptivas",
            "FAIL",
            "No hay explicación textual en celdas Markdown.",
            "Añade explicaciones, instrucciones y contexto en Markdown entre bloques de código.",
            "WCAG 3.3.2",
        )
    total_structural_cells = len(context.markdown_cells) + len(context.code_cells)
    markdown_ratio = len(context.markdown_cells) / total_structural_cells if total_structural_cells else 0
    markdown_text = " ".join(text for _index, text in context.markdown_cells)
    if markdown_ratio >= 0.25 and len(_normalize_text(markdown_text)) >= 40:
        return _result(
            "notebook.markdown_explanation",
            "Celdas Markdown descriptivas",
            "PASS",
            f"{len(context.markdown_cells)} de {total_structural_cells} celdas principales son Markdown.",
            "Mantén explicaciones antes de los pasos clave y resultados.",
            "WCAG 3.3.2",
        )
    return _result(
        "notebook.markdown_explanation",
        "Celdas Markdown descriptivas",
        "WARNING",
        "El notebook tiene poca explicación Markdown respecto al código.",
        "Añade más contexto textual para que el flujo sea comprensible sin ejecutar código.",
        "WCAG 3.3.2",
    )


def _check_image_alt(context: _NotebookContext) -> AccessibilityCheckResult:
    if not context.image_alts:
        return _result(
            "notebook.image_alt",
            "Imágenes con alternativa textual",
            "NOT_APPLICABLE",
            "No se detectan imágenes Markdown.",
            "Cuando incluyas imágenes, usa texto alternativo descriptivo.",
            "WCAG 1.1.1",
        )
    problematic = [alt for alt in context.image_alts if not _is_descriptive_image_alt(alt)]
    if problematic:
        return _result(
            "notebook.image_alt",
            "Imágenes con alternativa textual",
            "FAIL",
            f"{len(problematic)} imagen(es) Markdown tienen alt vacío o genérico.",
            "Describe la información o función de cada imagen en el texto alternativo.",
            "WCAG 1.1.1",
        )
    return _result(
        "notebook.image_alt",
        "Imágenes con alternativa textual",
        "PASS",
        "Todas las imágenes Markdown detectadas tienen alt descriptivo.",
        "Mantén alternativas textuales equivalentes al propósito de la imagen.",
        "WCAG 1.1.1",
    )


def _check_links(context: _NotebookContext) -> AccessibilityCheckResult:
    if not context.link_texts and not context.naked_urls:
        return _result(
            "notebook.links",
            "Enlaces descriptivos",
            "NOT_APPLICABLE",
            "No se detectan enlaces en celdas Markdown.",
            "Cuando añadas enlaces, usa textos que indiquen destino o acción.",
            "WCAG 2.4.4",
        )
    problematic = [text for text in context.link_texts if _is_generic_link_text(text) or URL_TEXT_RE.match(text)]
    problematic.extend(context.naked_urls)
    if problematic:
        return _result(
            "notebook.links",
            "Enlaces descriptivos",
            "FAIL",
            f"Hay enlaces poco descriptivos: {', '.join(_shorten(item) for item in problematic[:4])}.",
            "Sustituye textos como 'aquí' o URLs desnudas por descripciones del destino.",
            "WCAG 2.4.4",
        )
    return _result(
        "notebook.links",
        "Enlaces descriptivos",
        "PASS",
        "Los enlaces Markdown detectados tienen textos descriptivos.",
        "Mantén textos de enlace comprensibles fuera de contexto.",
        "WCAG 2.4.4",
    )


def _check_visual_outputs(context: _NotebookContext) -> AccessibilityCheckResult:
    if not context.visual_output_cells:
        return _result(
            "notebook.visual_outputs",
            "Salidas visuales explicadas",
            "NOT_APPLICABLE",
            "No se detectan outputs visuales guardados.",
            "Cuando generes gráficos, acompáñalos de una explicación textual.",
            "WCAG 1.1.1",
        )
    unexplained = [
        index for index in context.visual_output_cells if not _has_nearby_markdown_context(context, index)
    ]
    if unexplained:
        return _result(
            "notebook.visual_outputs",
            "Salidas visuales explicadas",
            "WARNING",
            f"{len(unexplained)} output(s) visual(es) no tienen Markdown cercano que los contextualice.",
            "Añade una explicación textual antes o después de cada gráfico relevante.",
            "WCAG 1.1.1",
        )
    return _result(
        "notebook.visual_outputs",
            "Salidas visuales explicadas",
            "PASS",
            "Los outputs visuales tienen Markdown cercano que aporta contexto.",
            "Mantén descripciones textuales para gráficos y resultados visuales.",
        "WCAG 1.1.1",
    )


def _check_execution_errors(context: _NotebookContext) -> AccessibilityCheckResult:
    output_count = sum(
        len(cell.get("outputs") if isinstance(cell.get("outputs"), list) else [])
        for _index, cell in context.code_cells
    )
    if context.error_outputs:
        return _result(
            "notebook.execution_errors",
            "Errores de ejecución guardados",
            "FAIL",
            f"Hay {context.error_outputs} output(s) de error guardados.",
            "Limpia o corrige las celdas con error antes de publicar el notebook.",
        )
    if output_count == 0:
        return _result(
            "notebook.execution_errors",
            "Errores de ejecución guardados",
            "NOT_APPLICABLE",
            "No hay outputs guardados para revisar errores.",
            "Si publicas outputs, verifica que no contengan trazas de error.",
        )
    return _result(
        "notebook.execution_errors",
        "Errores de ejecución guardados",
        "PASS",
        "No se detectan outputs de error guardados.",
        "Mantén el notebook ejecutado sin errores antes de compartirlo.",
    )


def _check_execution_order(context: _NotebookContext) -> AccessibilityCheckResult:
    counts = context.execution_counts
    non_null_counts = [count for count in counts if count is not None]
    if not non_null_counts:
        return _result(
            "notebook.execution_order",
            "Orden y limpieza de ejecución",
            "NOT_APPLICABLE",
            "No hay celdas de codigo ejecutadas.",
            "Si guardas ejecuciones, procura que sigan un orden claro.",
        )
    has_null_mixed = len(non_null_counts) != len(counts)
    is_ordered = non_null_counts == sorted(non_null_counts) and len(non_null_counts) == len(set(non_null_counts))
    if is_ordered and not has_null_mixed:
        return _result(
            "notebook.execution_order",
            "Orden y limpieza de ejecución",
            "PASS",
            "Los execution_count guardados son crecientes y sin duplicados.",
            "Mantén el notebook ejecutado de arriba abajo o limpio antes de publicarlo.",
        )
    return _result(
        "notebook.execution_order",
        "Orden y limpieza de ejecución",
        "WARNING",
        "Hay execution_count desordenados, duplicados o mezclados con celdas sin ejecutar.",
        "Reinicia el kernel, ejecuta todo en orden y limpia outputs innecesarios.",
    )


def _check_markdown_tables(context: _NotebookContext) -> AccessibilityCheckResult:
    if not context.table_lines:
        return _result(
            "notebook.markdown_tables",
            "Tablas Markdown estructuradas",
            "NOT_APPLICABLE",
            "No se detectan tablas Markdown.",
            "Cuando añadas tablas, incluye fila de encabezado y separador Markdown.",
            "WCAG 1.3.1",
        )
    if context.valid_table_count > 0:
        return _result(
            "notebook.markdown_tables",
            "Tablas Markdown estructuradas",
            "PASS",
            f"Se detectan {context.valid_table_count} tabla(s) Markdown con fila de encabezado.",
            "Verifica manualmente que los encabezados describan correctamente las columnas.",
            "WCAG 1.3.1",
        )
    return _result(
        "notebook.markdown_tables",
        "Tablas Markdown estructuradas",
        "WARNING",
        "Hay lineas con apariencia de tabla, pero falta separador/encabezado Markdown claro.",
        "Usa una tabla Markdown con encabezados y fila separadora.",
        "WCAG 1.3.1",
    )


def _should_attempt_notebook_scan(resource: Any, core: Any) -> bool:
    if core.origin in {"RALTI", "LTI", "EXTERNAL_URL"}:
        return False
    if core.accessStatus in {"REQUIERE_SSO", "REQUIERE_INTERACCION", "NO_ANALIZABLE"}:
        return False
    if not core.contentAvailable:
        return False
    return core.type == "NOTEBOOK" or _resource_has_notebook_reference(resource)


def _content_is_notebook(content: ResourceContentResult) -> bool:
    mime_type = (content.mimeType or "").split(";", 1)[0].strip().lower()
    filename = (content.filename or content.binaryPath or content.title or "").lower()
    if mime_type in NOTEBOOK_MIME_TYPES or filename.endswith(".ipynb"):
        return True
    if mime_type == "application/json":
        if content.binaryPath and _path_has_notebook_shape(Path(content.binaryPath)):
            return True
        if content.textContent and _text_has_notebook_shape(content.textContent):
            return True
    return False


def _notebook_scan_error_checks(evidence: str, recommendation: str) -> list[AccessibilityCheckResult]:
    return [
        _result(
            "notebook.analysis",
            "Análisis Notebook",
            "ERROR",
            evidence,
            recommendation,
        )
    ]


def _read_notebook(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not _has_notebook_shape(payload):
        raise ValueError("El JSON no tiene estructura nbformat/cells")
    return payload


def _has_notebook_shape(payload: Any) -> bool:
    return isinstance(payload, dict) and isinstance(payload.get("cells"), list) and "nbformat" in payload


def _path_has_notebook_shape(path: Path) -> bool:
    try:
        return _has_notebook_shape(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return False


def _text_has_notebook_shape(text: str) -> bool:
    try:
        return _has_notebook_shape(json.loads(text))
    except json.JSONDecodeError:
        return False


def _resource_has_notebook_reference(resource: Any) -> bool:
    values = _resource_reference_values(resource)
    for value in values:
        text = str(value).lower().split("?", 1)[0]
        if text.endswith(".ipynb") or text in JSON_MIME_TYPES:
            return True
    return False


def _resource_reference_values(resource: Any) -> list[Any]:
    payload = _as_mapping(resource)
    details = payload.get("details") if isinstance(payload.get("details"), dict) else {}
    keys = (
        "localPath",
        "filePath",
        "path",
        "sourceUrl",
        "downloadUrl",
        "url",
        "title",
        "filename",
        "mimeType",
        "contentType",
    )
    return [payload.get(key) for key in keys] + [details.get(key) for key in keys]


def _source_text(source: Any) -> str:
    if isinstance(source, str):
        return source
    if isinstance(source, list):
        return "".join(str(item) for item in source)
    return ""


def _first_meaningful_cell_index(cells: list[dict[str, Any]]) -> int | None:
    for index, cell in enumerate(cells):
        if _source_text(cell.get("source")).strip():
            return index
    return None


def _cell_type(cell: dict[str, Any]) -> str:
    return str(cell.get("cell_type") or "").lower()


def _is_visual_output(output: dict[str, Any]) -> bool:
    data = output.get("data")
    if not isinstance(data, dict):
        return False
    return any(str(key).lower() in VISUAL_OUTPUT_MIME_TYPES for key in data)


def _has_nearby_markdown_context(context: _NotebookContext, code_cell_index: int) -> bool:
    markdown_by_index = {index: _normalize_text(text) for index, text in context.markdown_cells}
    for nearby_index in (code_cell_index - 1, code_cell_index + 1):
        if len(markdown_by_index.get(nearby_index, "")) >= 20:
            return True
    return False


def _markdown_table_like_lines(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if "|" in line and line.strip().count("|") >= 2]


def _count_valid_markdown_tables(text: str) -> int:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    count = 0
    for index, line in enumerate(lines[:-1]):
        if "|" not in line:
            continue
        next_line = lines[index + 1]
        if TABLE_SEPARATOR_RE.match(next_line):
            count += 1
    return count


def _strip_markdown_links(text: str) -> str:
    return MARKDOWN_LINK_RE.sub("", text)


def _is_descriptive_image_alt(value: str) -> bool:
    normalized = _normalize_for_compare(value)
    return bool(normalized and len(normalized) > 3 and normalized not in {_normalize_for_compare(item) for item in GENERIC_IMAGE_ALT_TEXTS})


def _is_generic_link_text(value: str) -> bool:
    normalized = _normalize_for_compare(value)
    return normalized in {_normalize_for_compare(item) for item in GENERIC_LINK_TEXTS}


def _resource_title(resource: Any) -> str:
    payload = _as_mapping(resource)
    title = payload.get("title")
    return str(title).strip() if title else "Notebook sin titulo"


def _normalize_text(value: str) -> str:
    return " ".join(value.split())


def _normalize_for_compare(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value.strip().lower())
    return "".join(char for char in normalized if not unicodedata.combining(char))


def _shorten(value: str, *, limit: int = 80) -> str:
    normalized = _normalize_text(value)
    return normalized if len(normalized) <= limit else f"{normalized[: limit - 1]}..."


def _as_mapping(item: Any) -> dict[str, Any]:
    if hasattr(item, "model_dump"):
        payload = item.model_dump(mode="python")
        return payload if isinstance(payload, dict) else {}
    return item if isinstance(item, dict) else {}


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
