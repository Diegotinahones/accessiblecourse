from __future__ import annotations

from sqlmodel import Session, select

from app.models.entities import ChecklistItem, ChecklistTemplate, ResourceType


TEMPLATE_DEFINITIONS: dict[ResourceType, list[dict[str, str | None]]] = {
    ResourceType.WEB: [
        {"key": "keyboard", "label": "Se puede usar solo con teclado", "description": None, "recommendation": "Asegura que todo el recorrido principal se complete solo con teclado."},
        {"key": "focus", "label": "El foco visible se ve con claridad", "description": None, "recommendation": "Añade un indicador de foco visible y consistente."},
        {"key": "headings", "label": "Los encabezados siguen una estructura lógica", "description": None, "recommendation": "Reordena los encabezados para reflejar la jerarquía real."},
        {"key": "labels", "label": "Los campos tienen etiquetas claras", "description": None, "recommendation": "Asocia cada campo con una etiqueta visible."},
        {"key": "contrast", "label": "El contraste del texto es suficiente", "description": None, "recommendation": "Aumenta el contraste entre texto y fondo."},
        {"key": "alt_text", "label": "Las imágenes tienen texto alternativo útil", "description": None, "recommendation": "Añade texto alternativo breve y descriptivo."},
        {"key": "link_text", "label": "Los enlaces se entienden fuera de contexto", "description": None, "recommendation": "Usa textos de enlace descriptivos."},
        {"key": "lang", "label": "El idioma principal está identificado", "description": None, "recommendation": "Declara el idioma principal del recurso."},
    ],
    ResourceType.PDF: [
        {"key": "tagged", "label": "El PDF está etiquetado", "description": None, "recommendation": "Exporta el PDF con etiquetas activadas."},
        {"key": "reading_order", "label": "El orden de lectura es correcto", "description": None, "recommendation": "Corrige el orden de lectura."},
        {"key": "headings", "label": "Los títulos están marcados correctamente", "description": None, "recommendation": "Marca los títulos como encabezados reales."},
        {"key": "alt_images", "label": "Las imágenes relevantes tienen alternativa textual", "description": None, "recommendation": "Añade descripción breve a las imágenes."},
        {"key": "tables", "label": "Las tablas tienen estructura clara", "description": None, "recommendation": "Marca cabeceras de tabla."},
        {"key": "bookmarks", "label": "El documento incluye marcadores", "description": None, "recommendation": "Crea marcadores a partir de los encabezados."},
        {"key": "lang", "label": "El idioma del documento está definido", "description": None, "recommendation": "Configura el idioma principal del documento."},
        {"key": "ocr_scan", "label": "El texto es seleccionable y no es solo una imagen", "description": None, "recommendation": "Aplica OCR o vuelve a exportar el documento."},
    ],
    ResourceType.VIDEO: [
        {"key": "captions", "label": "Incluye subtítulos sincronizados", "description": None, "recommendation": "Añade subtítulos revisados y sincronizados."},
        {"key": "transcript", "label": "Hay transcripción disponible", "description": None, "recommendation": "Publica una transcripción editable y localizable."},
        {"key": "language", "label": "El idioma del audio está indicado", "description": None, "recommendation": "Indica el idioma del vídeo y de los subtítulos."},
        {"key": "player_controls", "label": "El reproductor se maneja con teclado", "description": None, "recommendation": "Usa un reproductor accesible por teclado."},
        {"key": "audio_description", "label": "La información visual también se explica", "description": None, "recommendation": "Describe verbalmente gráficos y acciones relevantes."},
        {"key": "speaker_identification", "label": "Se identifica quién habla cuando hace falta", "description": None, "recommendation": "Añade identificación de voz cuando aporte contexto."},
        {"key": "visual_context", "label": "Las acciones visuales se entienden sin ver la pantalla", "description": None, "recommendation": "Acompaña los cambios visuales con explicación oral o textual."},
        {"key": "playback_speed", "label": "La velocidad de reproducción se puede ajustar", "description": None, "recommendation": "Ofrece un reproductor con control de velocidad estable."},
    ],
    ResourceType.NOTEBOOK: [
        {"key": "structure", "label": "El cuaderno está dividido en secciones claras", "description": None, "recommendation": "Organiza el notebook con títulos claros."},
        {"key": "alt_images", "label": "Las imágenes o gráficos tienen explicación", "description": None, "recommendation": "Añade texto explicativo a las imágenes."},
        {"key": "tables", "label": "Las tablas son legibles y comprensibles", "description": None, "recommendation": "Incluye encabezados claros y contexto."},
        {"key": "outputs", "label": "Las salidas de código se entienden", "description": None, "recommendation": "Explica el resultado de cada celda importante."},
        {"key": "navigation", "label": "La navegación entre celdas es razonable", "description": None, "recommendation": "Ordena las celdas para que la lectura sea lineal."},
        {"key": "headings", "label": "Los títulos del notebook son consistentes", "description": None, "recommendation": "Usa encabezados markdown coherentes."},
        {"key": "code_comments", "label": "El código relevante está explicado", "description": None, "recommendation": "Añade comentarios o texto de apoyo al código clave."},
        {"key": "execution_order", "label": "El orden de ejecución es coherente", "description": None, "recommendation": "Comprueba que el notebook funciona de arriba abajo."},
    ],
    ResourceType.OTHER: [
        {"key": "descriptive_title", "label": "El recurso tiene un título claro", "description": None, "recommendation": "Usa un título descriptivo."},
        {"key": "clear_structure", "label": "La información sigue una estructura clara", "description": None, "recommendation": "Divide el contenido en secciones breves."},
        {"key": "keyboard_access", "label": "El recurso se puede manejar con teclado", "description": None, "recommendation": "Asegura que la interacción principal se complete con teclado."},
        {"key": "readable_text", "label": "El texto es legible y con buen contraste", "description": None, "recommendation": "Mejora tamaño, espaciado y contraste."},
        {"key": "alternative_text", "label": "Los elementos visuales tienen alternativa", "description": None, "recommendation": "Añade alternativas textuales a los elementos visuales."},
        {"key": "clear_language", "label": "El lenguaje es directo y comprensible", "description": None, "recommendation": "Simplifica instrucciones ambiguas o demasiado técnicas."},
        {"key": "downloadable_format", "label": "Hay un formato alternativo descargable", "description": None, "recommendation": "Ofrece una alternativa reutilizable si el formato principal es limitado."},
        {"key": "contact_support", "label": "Se indica cómo pedir apoyo", "description": None, "recommendation": "Añade un canal de apoyo para incidencias de accesibilidad."},
    ],
}


def seed_templates(session: Session) -> None:
    existing = {template.resource_type for template in session.exec(select(ChecklistTemplate)).all()}
    for resource_type, items in TEMPLATE_DEFINITIONS.items():
        if resource_type in existing:
            continue
        template = ChecklistTemplate(id=f"template-{resource_type.value.lower()}", resource_type=resource_type)
        session.add(template)
        session.flush()
        for index, item in enumerate(items):
            session.add(
                ChecklistItem(
                    template_id=template.id,
                    key=str(item["key"]),
                    label=str(item["label"]),
                    description=item.get("description"),
                    recommendation=item.get("recommendation"),
                    display_order=index,
                )
            )
    session.commit()
