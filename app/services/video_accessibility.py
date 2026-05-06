from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from bs4 import BeautifulSoup

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

VIDEO_EXTENSIONS = {".mp4", ".m4v", ".mov", ".webm", ".avi", ".mkv"}
VIDEO_MIME_PREFIX = "video/"
VIDEO_ANALYSIS_SCOPE_NOTE = (
    "No se descargan vídeos de plataformas externas por defecto. El análisis automático verifica metadatos, embed, "
    "subtítulos/transcripción detectables y señales de accesibilidad disponibles. La revisión completa del contenido "
    "audiovisual puede requerir acceso al proveedor o revisión humana."
)
CAPTION_EXTENSIONS = {".vtt", ".srt", ".ttml", ".dfxp"}
GENERIC_VIDEO_TITLES = {
    "video",
    "vídeo",
    "watch",
    "player",
    "embed",
    "recurso",
    "sin titulo",
    "sin título",
    "untitled",
}
TRANSCRIPT_RE = re.compile(r"\b(transcripci[oó]n|transcript|subt[ií]tulos?|captions?)\b", re.IGNORECASE)
AUDIO_DESCRIPTION_RE = re.compile(
    r"\b(audio\s*descripci[oó]n|audiodescripci[oó]n|audio\s*description|descripci[oó]n\s*extendida|"
    r"alternativa\s*textual)\b",
    re.IGNORECASE,
)
URL_LIKE_RE = re.compile(r"^(?:https?://|www\.|[A-Za-z0-9_-]{8,})")


@dataclass(slots=True)
class VideoAccessibilityContext:
    html: str | None = None
    binary_path: Path | None = None
    mime_type: str | None = None
    filename: str | None = None
    source_url: str | None = None
    content_error: str | None = None
    signals: "_VideoSignals" = field(default_factory=lambda: _VideoSignals())


@dataclass(slots=True)
class _VideoSignals:
    iframes: list[dict[str, str]] = field(default_factory=list)
    videos: list[dict[str, str]] = field(default_factory=list)
    tracks: list[dict[str, str]] = field(default_factory=list)
    links: list[dict[str, str]] = field(default_factory=list)
    text: str = ""


@dataclass(slots=True, frozen=True)
class _VideoProvider:
    name: str | None
    reference: str | None = None
    external: bool = False
    requires_manual_review: bool = False


@dataclass(slots=True, frozen=True)
class _VideoMetadata:
    ffprobe_available: bool
    duration_seconds: float | None = None
    subtitle_streams: int = 0
    error: str | None = None


def analyze_video_accessibility(resource: Any, context: Any = None) -> list[AccessibilityCheckResult]:
    core = normalize_resource(resource)
    video_context = _build_context(resource, context)
    provider = _detect_provider(resource, video_context)
    metadata = _inspect_video_metadata(video_context.binary_path) if video_context.binary_path else None

    return [
        _check_accessible(core, video_context, provider),
        _check_title(core),
        _check_provider(provider),
        _check_manual_review(provider),
        _check_iframe_title(video_context, provider),
        _check_captions(core, video_context, provider, metadata),
        _check_transcript(core, video_context, provider),
        _check_audio_description(video_context),
        _check_controls(core, video_context, provider),
        _check_autoplay(video_context),
        _check_local_metadata(core, video_context, metadata),
    ]


def detect_video_provider(resource: Any) -> tuple[str | None, str | None]:
    context = _build_context(resource)
    provider = _detect_provider(resource, context)
    host = urlparse(provider.reference).netloc.lower() if provider.reference else None
    return provider.name, host or None


def run_video_accessibility_scan(
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
    remove_accessibility_results(report, "VIDEO")

    for resource in resources:
        core = normalize_resource(resource)
        if not _should_attempt_video_scan(resource, core):
            continue

        context = _build_context(resource)
        if _should_load_binary_content(core):
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
                context = _merge_content(context, content)
            except Exception as exc:
                context.content_error = f"No se pudo recuperar el vídeo: {exc.__class__.__name__}."

        try:
            checks = analyze_video_accessibility(resource, context)
        except Exception as exc:
            checks = [
                _result(
                    "video.analysis",
                    "Análisis de vídeo",
                    "ERROR",
                    f"No se pudo analizar el recurso de vídeo: {exc.__class__.__name__}.",
                    "Revisa el recurso manualmente y vuelve a intentar el análisis.",
                )
            ]
        append_accessibility_resource_result(report, resource, checks, analysis_type="VIDEO")

    recompute_accessibility_summary(report)
    save_accessibility_report(settings, job_id, report)
    return report


def ensure_video_accessibility_report(
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
        1 for resource in resources if _should_attempt_video_scan(resource, normalize_resource(resource))
    )
    if eligible_count == 0 or report.summary.videoResourcesTotal >= eligible_count:
        return report
    return run_video_accessibility_scan(
        settings=settings,
        job_id=job_id,
        resources=resources,
        canvas_client=canvas_client,
        canvas_credentials=canvas_credentials,
        course_id=course_id,
    )


def _build_context(resource: Any, context: Any = None) -> VideoAccessibilityContext:
    if isinstance(context, VideoAccessibilityContext):
        base = context
    elif isinstance(context, ResourceContentResult):
        base = VideoAccessibilityContext(
            binary_path=Path(context.binaryPath) if context.binaryPath else None,
            mime_type=context.mimeType,
            filename=context.filename,
            source_url=context.sourceUrl,
            content_error=context.errorDetail if not context.ok else None,
        )
    elif isinstance(context, str):
        base = VideoAccessibilityContext(html=context)
    elif isinstance(context, dict):
        base = VideoAccessibilityContext(
            html=_string(context, "html", "htmlContent", "html_content"),
            binary_path=_path_or_none(_string(context, "binaryPath", "binary_path")),
            mime_type=_string(context, "mimeType", "mime_type", "contentType", "content_type"),
            filename=_string(context, "filename"),
            source_url=_string(context, "sourceUrl", "source_url", "url"),
            content_error=_string(context, "errorDetail", "error_detail", "errorMessage", "error_message"),
        )
    else:
        base = VideoAccessibilityContext()

    base.source_url = base.source_url or _string(resource, "sourceUrl", "source_url", "url", "finalUrl", "final_url")
    base.mime_type = base.mime_type or _string(resource, "mimeType", "mime_type", "contentType", "content_type")
    base.filename = base.filename or _string(resource, "filename")
    base.signals = _collect_video_signals(base.html)
    _merge_resource_discovery_signals(base.signals, resource)
    return base


def _merge_content(context: VideoAccessibilityContext, content: ResourceContentResult) -> VideoAccessibilityContext:
    if content.binaryPath:
        context.binary_path = Path(content.binaryPath)
    context.mime_type = content.mimeType or context.mime_type
    context.filename = content.filename or context.filename
    context.source_url = content.sourceUrl or context.source_url
    if not content.ok:
        context.content_error = content.errorDetail or "No se pudo recuperar el contenido de vídeo."
    return context


def _collect_video_signals(html: str | None) -> _VideoSignals:
    signals = _VideoSignals()
    if not html:
        return signals
    soup = BeautifulSoup(html, "html.parser")
    signals.text = soup.get_text(" ", strip=True)
    signals.iframes = [_attrs_dict(element) for element in soup.find_all("iframe")]
    for video in soup.find_all("video"):
        video_attrs = _attrs_dict(video)
        signals.videos.append(video_attrs)
        for track in video.find_all("track"):
            signals.tracks.append(_attrs_dict(track))
        for source in video.find_all("source"):
            source_attrs = _attrs_dict(source)
            if source_attrs:
                signals.links.append({"href": source_attrs.get("src", ""), "text": "", **source_attrs})
    for track in soup.find_all("track"):
        attrs = _attrs_dict(track)
        if attrs not in signals.tracks:
            signals.tracks.append(attrs)
    for link in soup.find_all(["a", "link"]):
        attrs = _attrs_dict(link)
        href = attrs.get("href", "")
        text = link.get_text(" ", strip=True)
        if href or text:
            signals.links.append({"href": href, "text": text, **attrs})
    return signals


def _merge_resource_discovery_signals(signals: _VideoSignals, resource: Any) -> None:
    details = _details(resource)
    iframe_title = _string(details, "iframeTitle", "iframe_title")
    transcript_url = _string(details, "transcriptUrl", "transcript_url")
    captions_url = _string(details, "captionsUrl", "captions_url", "subtitlesUrl", "subtitles_url")
    if iframe_title:
        signals.iframes.append(
            {
                "title": iframe_title,
                "src": _string(resource, "sourceUrl", "source_url", "url", "finalUrl", "final_url") or "",
            }
        )
    if transcript_url:
        signals.links.append({"href": transcript_url, "text": "transcript"})
    if captions_url:
        signals.tracks.append({"kind": "captions", "src": captions_url})

    html_discovery = _mapping(details.get("htmlDiscovery"))
    deep_scan = _mapping(details.get("deepScan"))
    discovery = html_discovery or deep_scan
    if not discovery:
        return

    tag = _string(discovery, "tag", "htmlTag")
    element_attrs = _mapping(discovery.get("elementAttrs") or discovery.get("htmlAttrs"))
    if tag == "iframe" or element_attrs.get("src"):
        iframe_attrs = {str(key): str(value) for key, value in element_attrs.items() if value is not None}
        if not iframe_attrs.get("src"):
            iframe_attrs["src"] = _string(resource, "sourceUrl", "url") or ""
        signals.iframes.append(iframe_attrs)

    parent_tag = _string(discovery, "parentTag")
    parent_attrs = _mapping(discovery.get("parentAttrs"))
    if tag == "video" or parent_tag == "video":
        video_attrs = {str(key): str(value) for key, value in (parent_attrs or element_attrs).items() if value is not None}
        signals.videos.append(video_attrs)

    for kind in _list_values(discovery.get("trackKinds")):
        signals.tracks.append({"kind": kind})
    for src in _list_values(discovery.get("trackSources")):
        signals.tracks.append({"src": src})


def _check_accessible(core: Any, context: VideoAccessibilityContext, provider: _VideoProvider) -> AccessibilityCheckResult:
    if core.origin in {"RALTI", "LTI"} or core.accessStatus == "REQUIERE_SSO":
        return _result(
            "video.accessible",
            "Recurso de vídeo accesible",
            "NOT_APPLICABLE",
            "El vídeo requiere SSO, RALTI o una herramienta externa no verificable desde el backend.",
            "Revísalo manualmente desde la sesión autenticada del aula.",
        )
    if core.accessStatus in {"REQUIERE_INTERACCION", "NO_ANALIZABLE"}:
        return _result(
            "video.accessible",
            "Recurso de vídeo accesible",
            "NOT_APPLICABLE",
            "El recurso requiere interacción o no es analizable automáticamente.",
            "Valida el vídeo manualmente desde el entorno original.",
        )
    if context.content_error:
        return _result(
            "video.accessible",
            "Recurso de vídeo accesible",
            "FAIL",
            context.content_error,
            "Comprueba que el enlace o fichero de vídeo sea accesible para el backend.",
        )
    if context.binary_path and context.binary_path.exists():
        return _result(
            "video.accessible",
            "Recurso de vídeo accesible",
            "PASS",
            "El fichero de vídeo local o cacheado existe y se puede inspeccionar de forma preliminar.",
            "Mantén el fichero disponible junto al curso.",
        )
    if core.accessStatus == "OK":
        if provider.requires_manual_review:
            return _result(
                "video.accessible",
                "Recurso de vídeo accesible",
                "WARNING",
                f"El recurso responde, pero {provider.name or 'el proveedor externo'} requiere revisión manual.",
                "Comprueba subtítulos, transcripción y controles desde el reproductor original.",
            )
        return _result(
            "video.accessible",
            "Recurso de vídeo accesible",
            "PASS",
            "El enlace o embed responde correctamente según el diagnóstico de acceso.",
            "Verifica manualmente los aspectos que dependan del reproductor.",
        )
    return _result(
        "video.accessible",
        "Recurso de vídeo accesible",
        "FAIL",
        core.reasonDetail or "El recurso de vídeo no está accesible.",
        "Corrige el enlace, permisos o disponibilidad del vídeo.",
    )


def _check_title(core: Any) -> AccessibilityCheckResult:
    if core.title and not _is_generic_title(core.title):
        return _result(
            "video.title",
            "Título descriptivo del vídeo",
            "PASS",
            f"El recurso tiene un título descriptivo: \"{_shorten(core.title)}\".",
            "Mantén títulos únicos que expliquen el contenido del vídeo.",
            "WCAG 2.4.2",
        )
    return _result(
        "video.title",
        "Título descriptivo del vídeo",
        "WARNING",
        "El título está vacío, parece genérico o se parece a una URL/id.",
        "Renombra el vídeo con un título comprensible para el alumnado.",
        "WCAG 2.4.2",
    )


def _check_provider(provider: _VideoProvider) -> AccessibilityCheckResult:
    if provider.name:
        return _result(
            "video.provider",
            "Proveedor/plataforma identificada",
            "PASS",
            f"Proveedor identificado: {provider.name}.",
            "Usa esta información para revisar las opciones de accesibilidad del reproductor.",
        )
    return _result(
        "video.provider",
        "Proveedor/plataforma identificada",
        "WARNING",
        "No se ha podido identificar claramente la plataforma del vídeo.",
        "Revisa manualmente el reproductor y documenta su origen.",
    )


def _check_manual_review(provider: _VideoProvider) -> AccessibilityCheckResult:
    if provider.requires_manual_review:
        return _result(
            "video.manual_review",
            "Revisión manual del proveedor",
            "WARNING",
            f"{provider.name or 'El proveedor externo'} no se descarga ni se inspecciona internamente.",
            "Revisa manualmente subtítulos, transcripción, controles y audio descripción desde el reproductor.",
        )
    return _result(
        "video.manual_review",
        "Revisión manual del proveedor",
        "NOT_APPLICABLE",
        "No se requiere revisión manual específica de proveedor externo.",
        "Mantén la revisión manual para aspectos pedagógicos o calidad de las alternativas.",
    )


def _check_iframe_title(context: VideoAccessibilityContext, provider: _VideoProvider) -> AccessibilityCheckResult:
    if not context.signals.iframes:
        if provider.requires_manual_review:
            return _result(
                "video.iframe_title",
                "Iframe con título accesible",
                "WARNING",
                "No hay HTML de iframe disponible para validar el atributo title del embed.",
                "Si el vídeo está incrustado, comprueba que el iframe tenga un title descriptivo.",
                "WCAG 4.1.2",
            )
        return _result(
            "video.iframe_title",
            "Iframe con título accesible",
            "NOT_APPLICABLE",
            "No se ha detectado iframe asociado al recurso.",
            "Si incrustas el vídeo con iframe, añade un title descriptivo.",
            "WCAG 4.1.2",
        )
    missing = [iframe for iframe in context.signals.iframes if not _useful_text(iframe.get("title"))]
    if missing:
        return _result(
            "video.iframe_title",
            "Iframe con título accesible",
            "FAIL",
            f"{len(missing)} iframe(s) de vídeo no tienen title descriptivo.",
            "Añade un atributo title que describa el vídeo o su función.",
            "WCAG 4.1.2",
        )
    return _result(
        "video.iframe_title",
        "Iframe con título accesible",
        "PASS",
        f"Los iframe(s) detectados tienen title. Proveedor: {provider.name or 'no identificado'}.",
        "Mantén títulos de iframe descriptivos y no redundantes.",
        "WCAG 4.1.2",
    )


def _check_captions(
    core: Any,
    context: VideoAccessibilityContext,
    provider: _VideoProvider,
    metadata: _VideoMetadata | None,
) -> AccessibilityCheckResult:
    if _has_caption_signal(context) or (metadata and metadata.subtitle_streams > 0):
        return _result(
            "video.captions",
            "Subtítulos detectables",
            "PASS",
            "Se han detectado pistas, enlaces o señales claras de subtítulos.",
            "Comprueba que los subtítulos estén sincronizados y sean completos.",
            "WCAG 1.2.2",
        )
    if _is_local_or_downloadable(core, context):
        return _result(
            "video.captions",
            "Subtítulos detectables",
            "FAIL",
            "El vídeo local o descargable no muestra pistas ni enlaces de subtítulos detectables.",
            "Añade subtítulos en formato VTT/SRT o una pista equivalente.",
            "WCAG 1.2.2",
        )
    if provider.requires_manual_review:
        return _result(
            "video.captions",
            "Subtítulos detectables",
            "WARNING",
            "No se pueden comprobar automáticamente los subtítulos del proveedor externo.",
            "Abre el reproductor y valida que existan subtítulos activables.",
            "WCAG 1.2.2",
        )
    return _result(
        "video.captions",
        "Subtítulos detectables",
        "WARNING",
        "No se han detectado señales de subtítulos.",
        "Revisa manualmente el recurso y añade subtítulos si contiene audio.",
        "WCAG 1.2.2",
    )


def _check_transcript(core: Any, context: VideoAccessibilityContext, provider: _VideoProvider) -> AccessibilityCheckResult:
    if _has_transcript_signal(context):
        return _result(
            "video.transcript",
            "Transcripción detectable",
            "PASS",
            "Se han detectado señales de transcripción, captions o recursos VTT/SRT relacionados.",
            "Asegura que la transcripción cubra el contenido relevante.",
            "WCAG 1.2.1",
        )
    if _is_local_or_downloadable(core, context):
        return _result(
            "video.transcript",
            "Transcripción detectable",
            "FAIL",
            "No se detecta transcripción para un vídeo local o descargable.",
            "Añade una transcripción textual junto al vídeo docente.",
            "WCAG 1.2.1",
        )
    if provider.requires_manual_review:
        return _result(
            "video.transcript",
            "Transcripción detectable",
            "WARNING",
            "No se ha encontrado transcripción, pero el proveedor externo podría ofrecerla dentro del reproductor.",
            "Comprueba manualmente si existe transcripción o material equivalente.",
            "WCAG 1.2.1",
        )
    return _result(
        "video.transcript",
        "Transcripción detectable",
        "WARNING",
        "No se ha detectado transcripción asociada.",
        "Proporciona transcripción o alternativa textual si el vídeo contiene información relevante.",
        "WCAG 1.2.1",
    )


def _check_audio_description(context: VideoAccessibilityContext) -> AccessibilityCheckResult:
    if AUDIO_DESCRIPTION_RE.search(_combined_signal_text(context)):
        return _result(
            "video.audio_description",
            "Audio descripción o alternativa equivalente",
            "PASS",
            "Se detectan señales de audio descripción o alternativa textual equivalente.",
            "Comprueba que la alternativa cubra la información visual importante.",
            "WCAG 1.2.3",
        )
    return _result(
        "video.audio_description",
        "Audio descripción o alternativa equivalente",
        "WARNING",
        "No se puede comprobar automáticamente si existe audio descripción o alternativa equivalente.",
        "Revisa manualmente si el contenido visual requiere audio descripción o alternativa textual.",
        "WCAG 1.2.3",
    )


def _check_controls(core: Any, context: VideoAccessibilityContext, provider: _VideoProvider) -> AccessibilityCheckResult:
    if context.signals.videos:
        missing_controls = [video for video in context.signals.videos if "controls" not in video]
        if missing_controls:
            return _result(
                "video.controls",
                "Controles del reproductor",
                "FAIL",
                f"{len(missing_controls)} etiqueta(s) <video> no tienen atributo controls.",
                "Añade controles nativos o documenta controles alternativos accesibles por teclado.",
                "WCAG 2.1.1",
            )
        return _result(
            "video.controls",
            "Controles del reproductor",
            "PASS",
            "El vídeo usa controles nativos mediante el atributo controls.",
            "Mantén controles accesibles por teclado.",
            "WCAG 2.1.1",
        )
    if provider.name in {"YouTube", "Vimeo", "Kaltura", "Canvas"}:
        return _result(
            "video.controls",
            "Controles del reproductor",
            "PASS",
            f"Se usa un reproductor conocido ({provider.name}) con controles propios.",
            "Valida manualmente que los controles funcionen con teclado y lector de pantalla.",
            "WCAG 2.1.1",
        )
    if _is_local_or_downloadable(core, context):
        return _result(
            "video.controls",
            "Controles del reproductor",
            "WARNING",
            "No hay HTML de reproductor para validar controles del vídeo local.",
            "Comprueba que la página que publica el vídeo use controles accesibles.",
            "WCAG 2.1.1",
        )
    return _result(
        "video.controls",
        "Controles del reproductor",
        "WARNING",
        "No se puede validar automáticamente si el reproductor externo tiene controles accesibles.",
        "Revisa manualmente navegación por teclado, pausa, volumen y pantalla completa.",
        "WCAG 2.1.1",
    )


def _check_autoplay(context: VideoAccessibilityContext) -> AccessibilityCheckResult:
    autoplay_items = [
        attrs for attrs in [*context.signals.videos, *context.signals.iframes] if _has_boolean_attr(attrs, "autoplay")
    ]
    if not autoplay_items:
        return _result(
            "video.autoplay",
            "Autoplay / reproducción automática",
            "PASS",
            "No se detecta autoplay problemático en el HTML disponible.",
            "Evita reproducción automática con audio.",
            "WCAG 2.2.2",
        )
    problematic = [
        attrs for attrs in autoplay_items if not _has_boolean_attr(attrs, "muted") and "mute=1" not in attrs.get("src", "")
    ]
    if problematic:
        return _result(
            "video.autoplay",
            "Autoplay / reproducción automática",
            "FAIL",
            "Se detecta autoplay sin muted o sin evidencia de control suficiente.",
            "Desactiva autoplay o asegúrate de que el usuario pueda pausar y controlar el audio.",
            "WCAG 2.2.2",
        )
    return _result(
        "video.autoplay",
        "Autoplay / reproducción automática",
        "WARNING",
        "Se detecta autoplay, aunque parece estar silenciado o depende del proveedor.",
        "Valida manualmente que no interrumpa al usuario y que se pueda pausar.",
        "WCAG 2.2.2",
    )


def _check_local_metadata(
    core: Any,
    context: VideoAccessibilityContext,
    metadata: _VideoMetadata | None,
) -> AccessibilityCheckResult:
    if not _is_local_or_downloadable(core, context):
        return _result(
            "video.local_metadata",
            "Fichero local con metadatos verificables",
            "NOT_APPLICABLE",
            "No se descarga ni inspecciona internamente un vídeo externo de proveedor.",
            "Si necesitas validación interna, proporciona un fichero de vídeo propio o metadatos del proveedor.",
        )
    if not context.binary_path or not context.binary_path.exists():
        return _result(
            "video.local_metadata",
            "Fichero local con metadatos verificables",
            "WARNING",
            "No hay fichero local disponible para inspeccionar metadatos.",
            "Asegura que el vídeo esté incluido en el paquete o sea descargable desde Canvas.",
        )
    size = context.binary_path.stat().st_size
    mime = context.mime_type or _guess_video_mime(context.binary_path)
    if metadata and metadata.ffprobe_available and metadata.error is None:
        subtitle_note = f" y {metadata.subtitle_streams} pista(s) de subtítulos" if metadata.subtitle_streams else ""
        duration_note = f" Duración aproximada: {metadata.duration_seconds:.1f}s." if metadata.duration_seconds else ""
        return _result(
            "video.local_metadata",
            "Fichero local con metadatos verificables",
            "PASS",
            f"ffprobe pudo inspeccionar el fichero ({mime}, {size} bytes){subtitle_note}.{duration_note}".strip(),
            "Revisa manualmente calidad de subtítulos y transcripción.",
        )
    if mime.startswith(VIDEO_MIME_PREFIX) or context.binary_path.suffix.lower() in VIDEO_EXTENSIONS:
        return _result(
            "video.local_metadata",
            "Fichero local con metadatos verificables",
            "PASS",
            f"El fichero existe y tiene metadatos básicos suficientes ({mime}, {size} bytes).",
            "Instala ffprobe opcionalmente si quieres inspeccionar duración y pistas internas.",
        )
    return _result(
        "video.local_metadata",
        "Fichero local con metadatos verificables",
        "WARNING",
        f"El fichero existe, pero no se ha podido confirmar MIME de vídeo ({mime}).",
        "Comprueba manualmente el formato del fichero.",
    )


def _should_attempt_video_scan(resource: Any, core: Any) -> bool:
    if core.origin in {"RALTI", "LTI"}:
        return False
    if core.accessStatus in {"REQUIERE_SSO", "REQUIERE_INTERACCION", "NO_ANALIZABLE"}:
        return False
    return core.type == "VIDEO" or _resource_has_video_reference(resource)


def _should_load_binary_content(core: Any) -> bool:
    if core.origin in {"RALTI", "LTI", "EXTERNAL_URL"}:
        return False
    if core.accessStatus in {"REQUIERE_SSO", "REQUIERE_INTERACCION", "NO_ANALIZABLE"}:
        return False
    return bool(core.downloadable or core.localPath or core.contentAvailable)


def _resource_has_video_reference(resource: Any) -> bool:
    values = [
        _string(resource, "localPath", "filePath", "path", "sourceUrl", "url", "downloadUrl", "title", "mimeType", "contentType")
    ]
    details = _details(resource)
    values.append(_string(details, "mimeType", "contentType", "filename", "downloadUrl", "htmlUrl"))
    for value in values:
        if not value:
            continue
        normalized = value.lower()
        if normalized.startswith(VIDEO_MIME_PREFIX):
            return True
        if Path(urlparse(normalized).path).suffix.lower() in VIDEO_EXTENSIONS:
            return True
        if _detect_provider_from_reference(normalized).name in {"YouTube", "Vimeo", "Kaltura"}:
            return True
    return False


def _detect_provider(resource: Any, context: VideoAccessibilityContext) -> _VideoProvider:
    references = [
        context.source_url,
        _string(resource, "sourceUrl", "source_url", "url", "finalUrl", "final_url", "downloadUrl", "download_url"),
        _string(_details(resource), "htmlUrl", "downloadUrl"),
        str(context.binary_path) if context.binary_path else None,
        _string(resource, "localPath", "filePath", "path"),
    ]
    for iframe in context.signals.iframes:
        references.append(iframe.get("src"))
    for link in context.signals.links:
        references.append(link.get("href") or link.get("src"))

    origin = _string(resource, "origin")
    if origin == "ONLINE_CANVAS":
        return _VideoProvider("Canvas", external=False, requires_manual_review=False)
    if origin in {"INTERNAL_FILE", "INTERNAL_PAGE", "OFFLINE_IMSCC"}:
        return _VideoProvider("Local", external=False, requires_manual_review=False)
    if origin == "RALTI":
        return _VideoProvider("RALTI", external=True, requires_manual_review=True)

    for reference in references:
        provider = _detect_provider_from_reference(reference)
        if provider.name:
            return provider
    return _VideoProvider(None)


def _detect_provider_from_reference(reference: str | None) -> _VideoProvider:
    if not reference:
        return _VideoProvider(None)
    parsed = urlparse(reference)
    host = parsed.netloc.lower()
    full = f"{host}{parsed.path.lower()}?{parsed.query.lower()}"
    if "youtube.com" in host or "youtu.be" in host:
        return _VideoProvider("YouTube", reference=reference, external=True, requires_manual_review=True)
    if "vimeo.com" in host:
        return _VideoProvider("Vimeo", reference=reference, external=True, requires_manual_review=True)
    if "kaltura" in full or "mediaspace" in full:
        return _VideoProvider("Kaltura", reference=reference, external=True, requires_manual_review=True)
    if host:
        return _VideoProvider("otro", reference=reference, external=True, requires_manual_review=True)
    suffix = Path(parsed.path).suffix.lower()
    if suffix in VIDEO_EXTENSIONS:
        return _VideoProvider("Local", reference=reference, external=False, requires_manual_review=False)
    return _VideoProvider(None)


def _has_caption_signal(context: VideoAccessibilityContext) -> bool:
    if _reference_has_caption_signal(context.source_url):
        return True
    for track in context.signals.tracks:
        kind = (track.get("kind") or "").lower()
        src = (track.get("src") or "").lower()
        if kind in {"captions", "subtitles"} or _reference_has_caption_signal(src):
            return True
    return _has_caption_reference(context)


def _has_caption_reference(context: VideoAccessibilityContext) -> bool:
    for link in context.signals.links:
        href = (link.get("href") or link.get("src") or "").lower()
        text = (link.get("text") or "").lower()
        if _reference_has_caption_signal(href) or "captions" in text or "subt" in text:
            return True
    return False


def _reference_has_caption_signal(reference: str | None) -> bool:
    if not reference:
        return False
    parsed = urlparse(reference)
    suffix = Path(parsed.path).suffix.lower()
    haystack = f"{parsed.path.lower()}?{parsed.query.lower()}"
    return suffix in CAPTION_EXTENSIONS or any(marker in haystack for marker in ("caption", "subtit", ".vtt", ".srt"))


def _has_transcript_signal(context: VideoAccessibilityContext) -> bool:
    if TRANSCRIPT_RE.search(_combined_signal_text(context)):
        return True
    return _has_caption_reference(context)


def _combined_signal_text(context: VideoAccessibilityContext) -> str:
    parts = [context.signals.text, context.source_url or ""]
    for collection in (context.signals.links, context.signals.iframes, context.signals.videos, context.signals.tracks):
        for item in collection:
            parts.extend(str(value) for value in item.values() if value)
    return " ".join(parts)


def _is_local_or_downloadable(core: Any, context: VideoAccessibilityContext) -> bool:
    return bool(context.binary_path or core.origin in {"INTERNAL_FILE", "OFFLINE_IMSCC", "ONLINE_CANVAS"} or core.downloadable)


def _inspect_video_metadata(path: Path | None) -> _VideoMetadata:
    if path is None or not path.exists():
        return _VideoMetadata(ffprobe_available=False, error="missing_file")
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        return _VideoMetadata(ffprobe_available=False)
    try:
        completed = subprocess.run(
            [
                ffprobe,
                "-v",
                "error",
                "-show_entries",
                "format=duration:stream=codec_type",
                "-of",
                "default=noprint_wrappers=1",
                str(path),
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return _VideoMetadata(ffprobe_available=True, error=exc.__class__.__name__)
    if completed.returncode != 0:
        return _VideoMetadata(ffprobe_available=True, error="ffprobe_failed")
    duration: float | None = None
    subtitle_streams = 0
    for line in completed.stdout.splitlines():
        if line.startswith("duration="):
            try:
                duration = float(line.split("=", 1)[1])
            except ValueError:
                duration = None
        elif line.strip() == "codec_type=subtitle":
            subtitle_streams += 1
    return _VideoMetadata(ffprobe_available=True, duration_seconds=duration, subtitle_streams=subtitle_streams)


def _is_generic_title(title: str) -> bool:
    normalized = _normalize_text(title).strip(" .:-_/").lower()
    if not normalized or normalized in GENERIC_VIDEO_TITLES:
        return True
    return bool(URL_LIKE_RE.match(normalized))


def _useful_text(value: str | None) -> bool:
    return bool(value and not _is_generic_title(value))


def _attrs_dict(element: Any) -> dict[str, str]:
    attrs: dict[str, str] = {}
    for key, value in getattr(element, "attrs", {}).items():
        if isinstance(value, list):
            attrs[str(key).lower()] = " ".join(str(item) for item in value)
        elif value is None:
            attrs[str(key).lower()] = ""
        else:
            attrs[str(key).lower()] = str(value)
    return attrs


def _has_boolean_attr(attrs: dict[str, str], name: str) -> bool:
    if name in attrs:
        return True
    src = attrs.get("src", "")
    return f"{name}=1" in src or f"{name}=true" in src


def _details(resource: Any) -> dict[str, Any]:
    details = _mapping(_as_mapping(resource).get("details"))
    return details


def _as_mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        dumped = model_dump(mode="python")
        return dumped if isinstance(dumped, dict) else {}
    return {key: getattr(value, key) for key in dir(value) if not key.startswith("_") and not callable(getattr(value, key))}


def _mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _string(source: Any, *keys: str) -> str | None:
    mapping = _as_mapping(source)
    for key in keys:
        value = mapping.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _list_values(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def _path_or_none(value: str | None) -> Path | None:
    return Path(value) if value else None


def _guess_video_mime(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".mp4" or suffix == ".m4v":
        return "video/mp4"
    if suffix == ".webm":
        return "video/webm"
    if suffix == ".mov":
        return "video/quicktime"
    if suffix == ".avi":
        return "video/x-msvideo"
    return "application/octet-stream"


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
