from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.core.config import Settings
from app.services.resource_core import ResourceContentResult, get_resource_content, normalize_resource

AccessibilityStatus = Literal["PASS", "FAIL", "WARNING", "NOT_APPLICABLE", "ERROR"]
AccessibilityAnalysisType = Literal["HTML", "PDF"]

GENERIC_PAGE_TITLES = {
    "home",
    "inicio",
    "index",
    "page",
    "pagina",
    "página",
    "sin titulo",
    "sin título",
    "untitled",
    "document",
    "documento",
}
GENERIC_LINK_TEXTS = {
    "aqui",
    "aquí",
    "mas",
    "más",
    "ver mas",
    "ver más",
    "leer mas",
    "leer más",
    "click aqui",
    "click aquí",
    "clic aqui",
    "clic aquí",
    "pincha aqui",
    "pincha aquí",
    "enlace",
    "link",
    "saber mas",
    "saber más",
}
BUTTON_INPUT_TYPES = {"button", "submit", "reset", "image"}
SKIPPED_INPUT_TYPES = {"hidden", "button", "submit", "reset", "image"}
URL_TEXT_RE = re.compile(r"^(?:https?://|www\.)\S+$", re.IGNORECASE)


class AccessibilityCheckResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    checkId: str
    checkTitle: str
    status: AccessibilityStatus
    evidence: str
    recommendation: str
    wcagHint: str | None = None


class AccessibilityResourceResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    resourceId: str
    title: str
    type: str
    analysisType: AccessibilityAnalysisType | None = None
    accessStatus: str
    checks: list[AccessibilityCheckResult] = Field(default_factory=list)


class AccessibilityModuleResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str
    resources: list[AccessibilityResourceResult] = Field(default_factory=list)


class AccessibilityTypeSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    resourcesTotal: int = 0
    resourcesAnalyzed: int = 0
    passCount: int = 0
    failCount: int = 0
    warningCount: int = 0
    notApplicableCount: int = 0
    errorCount: int = 0


class AccessibilitySummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    htmlResourcesTotal: int = 0
    htmlResourcesAnalyzed: int = 0
    pdfResourcesTotal: int = 0
    pdfResourcesAnalyzed: int = 0
    passCount: int = 0
    failCount: int = 0
    warningCount: int = 0
    notApplicableCount: int = 0
    errorCount: int = 0
    byType: dict[str, AccessibilityTypeSummary] = Field(default_factory=dict)


class AccessibilityReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    jobId: str
    generatedAt: datetime | None = None
    summary: AccessibilitySummary
    modules: list[AccessibilityModuleResult] = Field(default_factory=list)


@dataclass
class _Element:
    tag: str
    attrs: dict[str, str]
    text_parts: list[str] = field(default_factory=list)

    @property
    def text(self) -> str:
        return _normalize_text(" ".join(self.text_parts))


@dataclass
class _TableState:
    has_header: bool = False
    has_caption: bool = False
    has_headers_attr: bool = False
    rows: int = 0
    max_cells_per_row: int = 0
    current_row_cells: int = 0


class _HTMLAccessibilityParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: list[_Element] = []
        self.html_lang: str | None = None
        self.title: str | None = None
        self.headings: list[tuple[int, str]] = []
        self.images: list[dict[str, str]] = []
        self.links: list[tuple[dict[str, str], str]] = []
        self.buttons: list[tuple[dict[str, str], str]] = []
        self.form_controls: list[tuple[str, dict[str, str], bool]] = []
        self.labels_for: set[str] = set()
        self.iframes: list[dict[str, str]] = []
        self.tables: list[_TableState] = []
        self._table_stack: list[_TableState] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        normalized_tag = tag.lower()
        attrs_dict = {name.lower(): value.strip() if isinstance(value, str) else "" for name, value in attrs}

        if normalized_tag == "html":
            self.html_lang = attrs_dict.get("lang")
        if normalized_tag == "img":
            self.images.append(attrs_dict)
        if normalized_tag == "iframe":
            self.iframes.append(attrs_dict)
        if normalized_tag == "table":
            self._table_stack.append(_TableState())
        if normalized_tag == "tr" and self._table_stack:
            self._table_stack[-1].current_row_cells = 0
        if normalized_tag in {"td", "th"} and self._table_stack:
            table = self._table_stack[-1]
            table.current_row_cells += 1
            if normalized_tag == "th":
                table.has_header = True
            if attrs_dict.get("headers"):
                table.has_headers_attr = True
        if normalized_tag == "caption" and self._table_stack:
            self._table_stack[-1].has_caption = True

        if normalized_tag in {"input", "select", "textarea"}:
            if normalized_tag == "input" and attrs_dict.get("type", "text").lower() in BUTTON_INPUT_TYPES:
                self.buttons.append((attrs_dict, _accessible_name(attrs_dict)))
            elif normalized_tag != "input" or attrs_dict.get("type", "text").lower() not in SKIPPED_INPUT_TYPES:
                self.form_controls.append((normalized_tag, attrs_dict, self._inside_label()))

        self.stack.append(_Element(tag=normalized_tag, attrs=attrs_dict))

    def handle_endtag(self, tag: str) -> None:
        normalized_tag = tag.lower()
        element = self._pop_element(normalized_tag)
        if element is None:
            return

        if normalized_tag == "title":
            self.title = element.text
        elif normalized_tag in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            self.headings.append((int(normalized_tag[1]), element.text))
        elif normalized_tag == "a":
            self.links.append((element.attrs, element.text))
        elif normalized_tag == "button":
            self.buttons.append((element.attrs, element.text))
        elif element.attrs.get("role", "").lower() == "button":
            self.buttons.append((element.attrs, element.text))
        elif normalized_tag == "label":
            target_id = element.attrs.get("for", "").strip()
            if target_id:
                self.labels_for.add(target_id)
        elif normalized_tag == "tr" and self._table_stack:
            table = self._table_stack[-1]
            table.rows += 1
            table.max_cells_per_row = max(table.max_cells_per_row, table.current_row_cells)
            table.current_row_cells = 0
        elif normalized_tag == "table" and self._table_stack:
            self.tables.append(self._table_stack.pop())

    def handle_data(self, data: str) -> None:
        if not data.strip():
            return
        for element in self.stack:
            element.text_parts.append(data)

    def _inside_label(self) -> bool:
        return any(element.tag == "label" for element in self.stack)

    def _pop_element(self, tag: str) -> _Element | None:
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index].tag == tag:
                element = self.stack.pop(index)
                return element
        return None


def analyze_html_accessibility(resource: Any, html: str) -> list[AccessibilityCheckResult]:
    parser = _HTMLAccessibilityParser()
    try:
        parser.feed(html or "")
        parser.close()
    except Exception as exc:  # HTMLParser is forgiving, but keep the job resilient.
        return [
            AccessibilityCheckResult(
                checkId="html.parse",
                checkTitle="Lectura del HTML",
                status="ERROR",
                evidence=f"No se pudo interpretar el HTML: {exc.__class__.__name__}.",
                recommendation="Revisa que el recurso HTML no este corrupto antes de analizarlo.",
            )
        ]

    resource_title = _resource_title(resource)
    return [
        _check_language(parser),
        _check_title(parser, resource_title),
        _check_main_heading(parser),
        _check_heading_hierarchy(parser),
        _check_image_alt(parser),
        _check_descriptive_links(parser),
        _check_button_names(parser),
        _check_form_labels(parser),
        _check_iframe_titles(parser),
        _check_table_headers(parser),
    ]


def run_html_accessibility_scan(
    *,
    settings: Settings,
    job_id: str,
    resources: list[dict[str, Any]],
    canvas_client: Any | None = None,
    canvas_credentials: Any | None = None,
    course_id: str | None = None,
) -> AccessibilityReport:
    modules_by_title: dict[str, AccessibilityModuleResult] = {}

    for resource in resources:
        core = normalize_resource(resource)
        if not _should_attempt_html_scan(core):
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
        except Exception as exc:  # Keep the scan resilient per resource.
            checks = [
                AccessibilityCheckResult(
                    checkId="html.content.available",
                    checkTitle="Contenido HTML disponible",
                    status="ERROR",
                    evidence=f"No se pudo recuperar el contenido: {exc.__class__.__name__}.",
                    recommendation="Comprueba que el recurso HTML sea accesible para el backend.",
                )
            ]
            _append_resource_result(modules_by_title, resource, checks, analysis_type="HTML")
            continue

        if not content.ok:
            checks = _checks_for_content(resource, content)
            _append_resource_result(modules_by_title, resource, checks, analysis_type="HTML")
            continue

        if content.contentKind != "HTML":
            continue

        checks = _checks_for_content(resource, content)
        _append_resource_result(modules_by_title, resource, checks, analysis_type="HTML")

    report = AccessibilityReport(
        jobId=job_id,
        generatedAt=datetime.now(UTC),
        summary=AccessibilitySummary(),
        modules=list(modules_by_title.values()),
    )
    recompute_accessibility_summary(report)
    save_accessibility_report(settings, job_id, report)
    return report


def ensure_accessibility_report(
    *,
    settings: Settings,
    job_id: str,
    resources: list[dict[str, Any]],
    canvas_client: Any | None = None,
    canvas_credentials: Any | None = None,
    course_id: str | None = None,
) -> AccessibilityReport:
    path = accessibility_report_path(settings, job_id)
    if path.exists():
        return load_accessibility_report(settings, job_id)
    return run_html_accessibility_scan(
        settings=settings,
        job_id=job_id,
        resources=resources,
        canvas_client=canvas_client,
        canvas_credentials=canvas_credentials,
        course_id=course_id,
    )


def save_accessibility_report(settings: Settings, job_id: str, report: AccessibilityReport) -> None:
    path = accessibility_report_path(settings, job_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = report.model_dump(mode="json")
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def load_accessibility_report(settings: Settings, job_id: str) -> AccessibilityReport:
    path = accessibility_report_path(settings, job_id)
    if not path.exists():
        return AccessibilityReport(jobId=job_id, summary=AccessibilitySummary(), modules=[])
    payload = json.loads(path.read_text(encoding="utf-8"))
    return AccessibilityReport.model_validate(payload)


def accessibility_report_path(settings: Settings, job_id: str) -> Path:
    return settings.storage_root / "jobs" / job_id / "accessibility.json"


def remove_accessibility_results(report: AccessibilityReport, analysis_type: AccessibilityAnalysisType) -> None:
    modules: list[AccessibilityModuleResult] = []
    for module in report.modules:
        module.resources = [
            resource
            for resource in module.resources
            if _resource_analysis_type(resource) != analysis_type
        ]
        if module.resources:
            modules.append(module)
    report.modules = modules
    recompute_accessibility_summary(report)


def append_accessibility_resource_result(
    report: AccessibilityReport,
    resource: dict[str, Any],
    checks: list[AccessibilityCheckResult],
    *,
    analysis_type: AccessibilityAnalysisType,
) -> None:
    core = normalize_resource(resource)
    module_title = _module_title(resource)
    module = next((item for item in report.modules if item.title == module_title), None)
    if module is None:
        module = AccessibilityModuleResult(title=module_title)
        report.modules.append(module)
    module.resources.append(
        AccessibilityResourceResult(
            resourceId=core.id,
            title=core.title,
            type=core.type,
            analysisType=analysis_type,
            accessStatus=core.accessStatus,
            checks=checks,
        )
    )


def recompute_accessibility_summary(report: AccessibilityReport) -> AccessibilitySummary:
    summary = AccessibilitySummary()
    for module in report.modules:
        for resource in module.resources:
            analysis_type = _resource_analysis_type(resource)
            _increment_resource_counts(summary, analysis_type)
            _increment_summary(summary, resource.checks, analysis_type=analysis_type)
    report.summary = summary
    return summary


def _checks_for_content(resource: dict[str, Any], content: ResourceContentResult) -> list[AccessibilityCheckResult]:
    if not content.ok or content.htmlContent is None:
        return [
            AccessibilityCheckResult(
                checkId="html.content.available",
                checkTitle="Contenido HTML disponible",
                status="ERROR",
                evidence=content.errorDetail or "No se pudo recuperar el HTML del recurso.",
                recommendation="Comprueba que el recurso HTML sea accesible para el backend.",
            )
        ]
    return analyze_html_accessibility(resource, content.htmlContent)


def _append_resource_result(
    modules_by_title: dict[str, AccessibilityModuleResult],
    resource: dict[str, Any],
    checks: list[AccessibilityCheckResult],
    *,
    analysis_type: AccessibilityAnalysisType,
) -> None:
    core = normalize_resource(resource)
    module_title = _module_title(resource)
    module = modules_by_title.setdefault(module_title, AccessibilityModuleResult(title=module_title))
    module.resources.append(
        AccessibilityResourceResult(
            resourceId=core.id,
            title=core.title,
            type=core.type,
            analysisType=analysis_type,
            accessStatus=core.accessStatus,
            checks=checks,
        )
    )


def _should_attempt_html_scan(core: Any) -> bool:
    if core.origin in {"RALTI", "LTI"}:
        return False
    if core.accessStatus in {"REQUIERE_SSO", "REQUIERE_INTERACCION", "NO_ANALIZABLE"}:
        return False
    if core.type != "WEB":
        return False
    return bool(core.contentAvailable)


def _resource_analysis_type(resource: AccessibilityResourceResult) -> AccessibilityAnalysisType:
    if resource.analysisType in {"HTML", "PDF"}:
        return resource.analysisType
    if resource.type == "PDF":
        return "PDF"
    return "HTML"


def _increment_resource_counts(summary: AccessibilitySummary, analysis_type: AccessibilityAnalysisType) -> None:
    type_summary = summary.byType.setdefault(analysis_type, AccessibilityTypeSummary())
    type_summary.resourcesTotal += 1
    type_summary.resourcesAnalyzed += 1
    if analysis_type == "HTML":
        summary.htmlResourcesTotal += 1
        summary.htmlResourcesAnalyzed += 1
    elif analysis_type == "PDF":
        summary.pdfResourcesTotal += 1
        summary.pdfResourcesAnalyzed += 1


def _increment_summary(
    summary: AccessibilitySummary,
    checks: list[AccessibilityCheckResult],
    *,
    analysis_type: AccessibilityAnalysisType | None = None,
) -> None:
    type_summary = summary.byType.setdefault(analysis_type, AccessibilityTypeSummary()) if analysis_type else None
    for check in checks:
        if check.status == "PASS":
            summary.passCount += 1
            if type_summary:
                type_summary.passCount += 1
        elif check.status == "FAIL":
            summary.failCount += 1
            if type_summary:
                type_summary.failCount += 1
        elif check.status == "WARNING":
            summary.warningCount += 1
            if type_summary:
                type_summary.warningCount += 1
        elif check.status == "NOT_APPLICABLE":
            summary.notApplicableCount += 1
            if type_summary:
                type_summary.notApplicableCount += 1
        elif check.status == "ERROR":
            summary.errorCount += 1
            if type_summary:
                type_summary.errorCount += 1


def _check_language(parser: _HTMLAccessibilityParser) -> AccessibilityCheckResult:
    lang = (parser.html_lang or "").strip()
    if lang:
        return _result(
            "html.lang",
            "Idioma principal definido",
            "PASS",
            f"El documento declara lang=\"{lang}\".",
            "Mantén el atributo lang actualizado con el idioma real del contenido.",
            "WCAG 3.1.1",
        )
    return _result(
        "html.lang",
        "Idioma principal definido",
        "FAIL",
        "No se ha encontrado un atributo lang no vacío en <html>.",
        "Añade lang al elemento <html>, por ejemplo <html lang=\"es\">.",
        "WCAG 3.1.1",
    )


def _check_title(parser: _HTMLAccessibilityParser, resource_title: str) -> AccessibilityCheckResult:
    title = _normalize_text(parser.title or "")
    if title and not _is_generic_text(title, GENERIC_PAGE_TITLES):
        return _result(
            "html.title",
            "Título de página",
            "PASS",
            f"El documento tiene un title descriptivo: \"{_shorten(title)}\".",
            "Usa títulos únicos y descriptivos para cada página del curso.",
            "WCAG 2.4.2",
        )
    if resource_title and not _is_generic_text(resource_title, GENERIC_PAGE_TITLES):
        return _result(
            "html.title",
            "Título de página",
            "PASS",
            f"No hay title útil, pero el recurso tiene título: \"{_shorten(resource_title)}\".",
            "Si puedes editar el HTML, replica este título en <title>.",
            "WCAG 2.4.2",
        )
    return _result(
        "html.title",
        "Título de página",
        "WARNING",
        "El <title> está vacío, ausente o parece genérico.",
        "Define un <title> específico que identifique el recurso.",
        "WCAG 2.4.2",
    )


def _check_main_heading(parser: _HTMLAccessibilityParser) -> AccessibilityCheckResult:
    h1_count = sum(1 for level, _ in parser.headings if level == 1)
    if h1_count == 1:
        return _result(
            "html.h1",
            "Encabezado principal",
            "PASS",
            "Se ha encontrado exactamente un encabezado h1.",
            "Mantén un único h1 que describa el propósito principal de la página.",
            "WCAG 2.4.6",
        )
    evidence = "No se ha encontrado ningún h1." if h1_count == 0 else f"Se han encontrado {h1_count} elementos h1."
    return _result(
        "html.h1",
        "Encabezado principal",
        "WARNING",
        evidence,
        "Usa exactamente un h1 como encabezado principal del recurso.",
        "WCAG 2.4.6",
    )


def _check_heading_hierarchy(parser: _HTMLAccessibilityParser) -> AccessibilityCheckResult:
    if len(parser.headings) < 2:
        return _result(
            "html.heading_hierarchy",
            "Jerarquía de encabezados",
            "PASS",
            "No hay suficientes encabezados para detectar saltos de jerarquía.",
            "Cuando añadas secciones, evita saltos como h2 a h4.",
            "WCAG 1.3.1",
        )
    skips: list[str] = []
    previous_level = parser.headings[0][0]
    for level, text in parser.headings[1:]:
        if level - previous_level > 1:
            skips.append(f"h{previous_level} -> h{level} ({_shorten(text) or 'sin texto'})")
        previous_level = level
    if not skips:
        return _result(
            "html.heading_hierarchy",
            "Jerarquía de encabezados",
            "PASS",
            "La secuencia de encabezados no presenta saltos bruscos.",
            "Conserva una jerarquía de encabezados ordenada.",
            "WCAG 1.3.1",
        )
    return _result(
        "html.heading_hierarchy",
        "Jerarquía de encabezados",
        "WARNING",
        f"Se detectan saltos de jerarquía: {'; '.join(skips[:3])}.",
        "Inserta los niveles intermedios necesarios o ajusta los encabezados.",
        "WCAG 1.3.1",
    )


def _check_image_alt(parser: _HTMLAccessibilityParser) -> AccessibilityCheckResult:
    if not parser.images:
        return _result(
            "html.img_alt",
            "Imágenes con texto alternativo",
            "NOT_APPLICABLE",
            "No se han encontrado imágenes.",
            "Cuando añadas imágenes informativas, incluye un alt descriptivo.",
            "WCAG 1.1.1",
        )
    missing = [image for image in parser.images if "alt" not in image]
    empty_not_decorative = [
        image for image in parser.images if "alt" in image and not image.get("alt", "").strip() and not _looks_decorative_image(image)
    ]
    if missing:
        return _result(
            "html.img_alt",
            "Imágenes con texto alternativo",
            "FAIL",
            f"{len(missing)} imagen(es) no tienen atributo alt.",
            "Añade alt descriptivo a las imágenes informativas o alt=\"\" si son decorativas.",
            "WCAG 1.1.1",
        )
    if empty_not_decorative:
        return _result(
            "html.img_alt",
            "Imágenes con texto alternativo",
            "WARNING",
            f"{len(empty_not_decorative)} imagen(es) tienen alt vacío y no parecen decorativas.",
            "Verifica si esas imágenes transmiten información y añade un alt descriptivo si aplica.",
            "WCAG 1.1.1",
        )
    return _result(
        "html.img_alt",
        "Imágenes con texto alternativo",
        "PASS",
        "Todas las imágenes tienen alt o parecen decorativas.",
        "Mantén textos alternativos equivalentes al propósito de cada imagen.",
        "WCAG 1.1.1",
    )


def _check_descriptive_links(parser: _HTMLAccessibilityParser) -> AccessibilityCheckResult:
    if not parser.links:
        return _result(
            "html.link_text",
            "Enlaces descriptivos",
            "NOT_APPLICABLE",
            "No se han encontrado enlaces.",
            "Cuando añadas enlaces, usa textos que indiquen destino o acción.",
            "WCAG 2.4.4",
        )
    problematic: list[str] = []
    for attrs, text in parser.links:
        name = _accessible_name(attrs, fallback=text)
        if not name or _is_generic_text(name, GENERIC_LINK_TEXTS) or URL_TEXT_RE.match(name):
            problematic.append(name or attrs.get("href", "enlace sin texto"))
    if problematic:
        return _result(
            "html.link_text",
            "Enlaces descriptivos",
            "FAIL",
            f"Hay enlaces con texto poco descriptivo: {', '.join(_shorten(item) for item in problematic[:4])}.",
            "Sustituye textos como “aquí” o URLs desnudas por descripciones del destino.",
            "WCAG 2.4.4",
        )
    return _result(
        "html.link_text",
        "Enlaces descriptivos",
        "PASS",
        "Los enlaces tienen textos accesibles suficientemente descriptivos.",
        "Mantén textos de enlace comprensibles fuera de contexto.",
        "WCAG 2.4.4",
    )


def _check_button_names(parser: _HTMLAccessibilityParser) -> AccessibilityCheckResult:
    if not parser.buttons:
        return _result(
            "html.button_name",
            "Botones con nombre accesible",
            "NOT_APPLICABLE",
            "No se han encontrado botones.",
            "Cuando añadas botones, asegúrate de que tengan nombre visible o aria-label.",
            "WCAG 4.1.2",
        )
    unnamed = [(attrs, text) for attrs, text in parser.buttons if not _accessible_name(attrs, fallback=text)]
    if unnamed:
        return _result(
            "html.button_name",
            "Botones con nombre accesible",
            "FAIL",
            f"{len(unnamed)} botón(es) no tienen nombre accesible.",
            "Añade texto visible, aria-label o title útil a cada botón.",
            "WCAG 4.1.2",
        )
    return _result(
        "html.button_name",
        "Botones con nombre accesible",
        "PASS",
        "Todos los botones tienen nombre accesible.",
        "Mantén nombres de botón claros y orientados a la acción.",
        "WCAG 4.1.2",
    )


def _check_form_labels(parser: _HTMLAccessibilityParser) -> AccessibilityCheckResult:
    if not parser.form_controls:
        return _result(
            "html.form_label",
            "Campos de formulario con etiqueta",
            "NOT_APPLICABLE",
            "No se han encontrado campos de formulario.",
            "Cuando añadas formularios, asocia cada campo a una etiqueta.",
            "WCAG 1.3.1",
        )
    unlabeled = [
        (tag, attrs)
        for tag, attrs, inside_label in parser.form_controls
        if not _control_has_label(attrs, parser.labels_for, inside_label)
    ]
    if unlabeled:
        return _result(
            "html.form_label",
            "Campos de formulario con etiqueta",
            "FAIL",
            f"{len(unlabeled)} campo(s) no tienen label, aria-label ni aria-labelledby.",
            "Asocia cada campo con <label for>, label envolvente, aria-label o aria-labelledby.",
            "WCAG 1.3.1",
        )
    return _result(
        "html.form_label",
        "Campos de formulario con etiqueta",
        "PASS",
        "Todos los campos de formulario tienen etiqueta accesible.",
        "Mantén etiquetas persistentes y comprensibles para cada campo.",
        "WCAG 1.3.1",
    )


def _check_iframe_titles(parser: _HTMLAccessibilityParser) -> AccessibilityCheckResult:
    if not parser.iframes:
        return _result(
            "html.iframe_title",
            "Iframes con título",
            "NOT_APPLICABLE",
            "No se han encontrado iframes.",
            "Cuando insertes iframes, añade title descriptivo.",
            "WCAG 4.1.2",
        )
    missing = [iframe for iframe in parser.iframes if not iframe.get("title", "").strip()]
    if missing:
        return _result(
            "html.iframe_title",
            "Iframes con título",
            "FAIL",
            f"{len(missing)} iframe(s) no tienen title.",
            "Añade un title que describa el contenido o función de cada iframe.",
            "WCAG 4.1.2",
        )
    return _result(
        "html.iframe_title",
        "Iframes con título",
        "PASS",
        "Todos los iframes tienen title.",
        "Mantén títulos de iframe específicos y no repetitivos.",
        "WCAG 4.1.2",
    )


def _check_table_headers(parser: _HTMLAccessibilityParser) -> AccessibilityCheckResult:
    data_tables = [table for table in parser.tables if _looks_like_data_table(table)]
    if not data_tables:
        return _result(
            "html.table_headers",
            "Tablas con encabezados",
            "NOT_APPLICABLE",
            "No se han encontrado tablas de datos evidentes.",
            "Si usas tablas de datos, define th, caption o headers.",
            "WCAG 1.3.1",
        )
    missing_headers = [
        table for table in data_tables if not table.has_header and not table.has_caption and not table.has_headers_attr
    ]
    if missing_headers:
        return _result(
            "html.table_headers",
            "Tablas con encabezados",
            "WARNING",
            f"{len(missing_headers)} tabla(s) de datos no tienen encabezados detectables.",
            "Añade th para encabezados, caption si aporta contexto y headers cuando la tabla sea compleja.",
            "WCAG 1.3.1",
        )
    return _result(
        "html.table_headers",
        "Tablas con encabezados",
        "PASS",
        "Las tablas de datos tienen encabezados o estructura equivalente.",
        "Verifica manualmente que los encabezados describen filas y columnas.",
        "WCAG 1.3.1",
    )


def _result(
    check_id: str,
    title: str,
    status: AccessibilityStatus,
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


def _is_generic_text(value: str, generic_values: set[str]) -> bool:
    normalized = _normalize_text(value).strip(" .:-").lower()
    return normalized in generic_values


def _accessible_name(attrs: dict[str, str], fallback: str = "") -> str:
    for key in ("aria-label", "title", "value", "alt"):
        value = attrs.get(key, "").strip()
        if value:
            return _normalize_text(value)
    return _normalize_text(fallback)


def _looks_decorative_image(attrs: dict[str, str]) -> bool:
    role = attrs.get("role", "").lower()
    aria_hidden = attrs.get("aria-hidden", "").lower()
    class_name = attrs.get("class", "").lower()
    return role in {"presentation", "none"} or aria_hidden == "true" or "decorative" in class_name


def _control_has_label(attrs: dict[str, str], labels_for: set[str], inside_label: bool) -> bool:
    if inside_label:
        return True
    if attrs.get("aria-label", "").strip() or attrs.get("aria-labelledby", "").strip():
        return True
    control_id = attrs.get("id", "").strip()
    return bool(control_id and control_id in labels_for)


def _looks_like_data_table(table: _TableState) -> bool:
    return table.has_header or table.has_caption or table.has_headers_attr or (
        table.rows >= 2 and table.max_cells_per_row >= 2
    )


def _resource_title(resource: Any) -> str:
    if isinstance(resource, dict):
        return _normalize_text(str(resource.get("title") or ""))
    return _normalize_text(str(getattr(resource, "title", "") or ""))


def _module_title(resource: dict[str, Any]) -> str:
    for key in ("modulePath", "coursePath", "sectionTitle", "moduleTitle"):
        value = resource.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return "Módulo general"
