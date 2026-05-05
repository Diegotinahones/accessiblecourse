from __future__ import annotations

from enum import Enum
from pathlib import Path


class ResourceType(str, Enum):
    PDF = "PDF"
    DOCX = "DOCX"
    WEB = "Web"
    VIDEO = "Video"
    NOTEBOOK = "Notebook"
    OTHER = "Other"


class ResourceOrigin(str, Enum):
    INTERNO = "interno"
    EXTERNO = "externo"


class ResourceState(str, Enum):
    OK = "OK"
    WARNING = "AVISO"
    ERROR = "ERROR"


CHECKLIST_TEMPLATES: dict[str, list[dict[str, str]]] = {
    "Web": [
        {
            "id": "keyboard",
            "label": "Navegacion por teclado",
            "recommendation": "Asegura que toda la pagina se pueda usar sin raton.",
        },
        {
            "id": "focus",
            "label": "Foco visible",
            "recommendation": "Haz visible el indicador de foco en enlaces, botones y formularios.",
        },
        {
            "id": "headings",
            "label": "Jerarquia de headings",
            "recommendation": "Mantiene una jerarquia clara de encabezados para orientar a lectores de pantalla.",
        },
        {
            "id": "labels",
            "label": "Labels en formularios",
            "recommendation": "Relaciona cada campo con una etiqueta y un nombre accesible claro.",
        },
        {
            "id": "contrast",
            "label": "Contraste suficiente",
            "recommendation": "Revisa contraste de texto y controles para mejorar la legibilidad.",
        },
        {
            "id": "alt",
            "label": "Texto alternativo",
            "recommendation": "Describe imagenes y elementos visuales relevantes con alt significativo.",
        },
        {
            "id": "links",
            "label": "Enlaces descriptivos",
            "recommendation": "Usa nombres de enlace que expliquen el destino o la accion.",
        },
    ],
    "PDF": [
        {
            "id": "structure",
            "label": "Estructura y etiquetas",
            "recommendation": "Etiqueta el PDF para exponer titulos, listas y tablas a tecnologia asistiva.",
        },
        {
            "id": "reading-order",
            "label": "Orden de lectura",
            "recommendation": "Define un orden de lectura coherente para que el contenido se anuncie bien.",
        },
        {
            "id": "figures",
            "label": "Alternativas en figuras",
            "recommendation": "Anade descripciones alternativas a imagenes, diagramas y figuras clave.",
        },
        {
            "id": "tables",
            "label": "Tablas accesibles",
            "recommendation": "Marca encabezados y simplifica tablas complejas cuando sea posible.",
        },
        {
            "id": "language",
            "label": "Idioma definido",
            "recommendation": "Configura el idioma principal del documento para mejorar la pronunciacion sintetica.",
        },
        {
            "id": "ocr",
            "label": "OCR si esta escaneado",
            "recommendation": "Aplica OCR y corrige errores si el PDF viene de una imagen escaneada.",
        },
    ],
    "Video": [
        {
            "id": "captions",
            "label": "Subtitulos",
            "recommendation": "Incluye subtitulos sincronizados y revisados manualmente.",
        },
        {
            "id": "transcript",
            "label": "Transcripcion",
            "recommendation": "Ofrece una transcripcion descargable o visible junto al video.",
        },
        {
            "id": "language",
            "label": "Idioma identificado",
            "recommendation": "Especifica el idioma del audio y de los subtitulos.",
        },
        {
            "id": "controls",
            "label": "Control de reproduccion",
            "recommendation": "Garantiza que los controles sean accesibles por teclado y lector de pantalla.",
        },
    ],
    "Notebook": [
        {
            "id": "structure",
            "label": "Estructura clara",
            "recommendation": "Ordena el notebook con titulos, secciones y explicaciones antes del codigo.",
        },
        {
            "id": "images",
            "label": "Imagenes descritas",
            "recommendation": "Describe graficas e imagenes para que tambien se entiendan sin verlas.",
        },
        {
            "id": "tables",
            "label": "Tablas comprensibles",
            "recommendation": "Resume tablas complejas y evita depender solo del formato visual.",
        },
        {
            "id": "outputs",
            "label": "Salidas alternativas",
            "recommendation": "Acompana salidas visuales con explicaciones textuales o datos equivalentes.",
        },
    ],
    "Other": [
        {
            "id": "description",
            "label": "Descripcion textual",
            "recommendation": "Incluye una descripcion corta del recurso y su proposito.",
        },
        {
            "id": "legibility",
            "label": "Legibilidad y contraste",
            "recommendation": "Mejora contraste, tamano y claridad visual para facilitar la lectura.",
        },
        {
            "id": "alternative",
            "label": "Formato alternativo",
            "recommendation": "Ofrece una alternativa accesible si el recurso original es complejo.",
        },
    ],
}

ITEM_SEVERITY: dict[str, str] = {
    "keyboard": "HIGH",
    "focus": "HIGH",
    "labels": "HIGH",
    "structure": "HIGH",
    "reading-order": "HIGH",
    "reading_order": "HIGH",
    "tagged": "HIGH",
    "captions": "HIGH",
    "transcript": "HIGH",
    "controls": "HIGH",
    "player_controls": "HIGH",
    "ocr": "HIGH",
    "ocr_scan": "HIGH",
    "alternative": "HIGH",
    "keyboard_access": "HIGH",
    "contrast": "MED",
    "alt": "MED",
    "alt_text": "MED",
    "alt_images": "MED",
    "figures": "MED",
    "tables": "MED",
    "headings": "MED",
    "language": "MED",
    "lang": "MED",
    "images": "MED",
    "outputs": "MED",
    "legibility": "MED",
    "audio_description": "MED",
    "visual_context": "MED",
    "navigation": "MED",
    "execution_order": "MED",
    "readable_text": "MED",
    "alternative_text": "MED",
    "bookmarks": "LOW",
    "links": "LOW",
    "link_text": "LOW",
    "description": "LOW",
    "descriptive_title": "LOW",
    "clear_structure": "LOW",
    "clear_language": "LOW",
    "downloadable_format": "LOW",
    "contact_support": "LOW",
    "speaker_identification": "LOW",
    "playback_speed": "LOW",
    "code_comments": "LOW",
}

SEVERITY_ORDER = {"HIGH": 0, "MED": 1, "LOW": 2}
STATUS_ORDER = {"FAIL": 0, "PENDING": 3}


def get_checklist_template(resource_type: str) -> list[dict[str, str]]:
    return [dict(item) for item in CHECKLIST_TEMPLATES.get(resource_type, CHECKLIST_TEMPLATES["Other"])]


def get_item_severity(item_key: str) -> str:
    return ITEM_SEVERITY.get(item_key, "MED")


def infer_type(source: str | None) -> ResourceType:
    if not source:
        return ResourceType.OTHER

    extension = Path(source).suffix.lower()
    if extension == ".pdf":
        return ResourceType.PDF
    if extension == ".docx":
        return ResourceType.DOCX
    if extension in {".html", ".htm", ".xhtml"}:
        return ResourceType.WEB
    if extension in {".mp4", ".mov", ".webm", ".m4v"}:
        return ResourceType.VIDEO
    if extension == ".ipynb":
        return ResourceType.NOTEBOOK
    return ResourceType.OTHER


def infer_origin(source: str | None) -> ResourceOrigin:
    if source and source.startswith(("http://", "https://")):
        return ResourceOrigin.EXTERNO
    return ResourceOrigin.INTERNO


def infer_status(resource_type: ResourceType, origin: ResourceOrigin) -> ResourceState:
    if resource_type == ResourceType.WEB and origin == ResourceOrigin.INTERNO:
        return ResourceState.OK
    return ResourceState.WARNING
