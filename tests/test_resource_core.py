from __future__ import annotations

import json

from app.services.resource_core import RESOURCE_CORE_FIELDS, get_resource_content, normalize_resource
from app.services.storage import get_extracted_dir


JOB_ID = "11111111-1111-1111-1111-111111111111"


def _write_inventory(test_settings, resources: list[dict[str, object]]) -> None:
    job_dir = test_settings.storage_root / "jobs" / JOB_ID
    job_dir.mkdir(parents=True, exist_ok=True)
    (job_dir / "resources.json").write_text(json.dumps(resources), encoding="utf-8")


def test_online_and_offline_resources_share_common_core_shape() -> None:
    offline = normalize_resource(
        {
            "id": "offline-html",
            "title": "Pagina local",
            "type": "WEB",
            "origin": "interno",
            "modulePath": "Reto 1 > Bloque 1",
            "sectionTitle": "Bloque 1",
            "localPath": "pages/page.html",
            "accessStatus": "OK",
            "canAccess": True,
            "canDownload": False,
        }
    )
    online = normalize_resource(
        {
            "id": "canvas-page",
            "title": "Pagina Canvas",
            "type": "WEB",
            "source": "Canvas",
            "modulePath": "Reto 1 > Bloque 1",
            "sectionTitle": "Bloque 1",
            "sourceUrl": "https://canvas.example.edu/courses/77/pages/bienvenida",
            "accessStatus": "OK",
            "canAccess": True,
            "details": {"canvasType": "Page", "courseId": "77", "pageUrl": "bienvenida"},
        }
    )

    assert set(offline.model_dump().keys()) == RESOURCE_CORE_FIELDS
    assert set(online.model_dump().keys()) == RESOURCE_CORE_FIELDS
    assert offline.modulePath == ["Reto 1", "Bloque 1"]
    assert online.modulePath == ["Reto 1", "Bloque 1"]
    assert offline.origin == "INTERNAL_PAGE"
    assert online.origin == "ONLINE_CANVAS"


def test_get_resource_content_reads_local_html(test_settings) -> None:
    extracted_dir = get_extracted_dir(test_settings, JOB_ID)
    html_path = extracted_dir / "pages" / "page.html"
    html_path.parent.mkdir(parents=True, exist_ok=True)
    html_path.write_text("<html><body>Contenido local</body></html>", encoding="utf-8")
    _write_inventory(
        test_settings,
        [
            {
                "id": "offline-html",
                "title": "Pagina local",
                "type": "WEB",
                "origin": "interno",
                "localPath": "pages/page.html",
                "accessStatus": "OK",
                "canAccess": True,
            }
        ],
    )

    result = get_resource_content("offline-html", settings=test_settings, job_id=JOB_ID)

    assert result.ok is True
    assert result.content_type == "text/html"
    assert result.text_content == "<html><body>Contenido local</body></html>"
    assert result.binary_path == str(html_path)


def test_get_resource_content_returns_local_pdf_path(test_settings) -> None:
    extracted_dir = get_extracted_dir(test_settings, JOB_ID)
    pdf_path = extracted_dir / "docs" / "guide.pdf"
    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    pdf_path.write_bytes(b"%PDF-1.4\n%test\n")
    _write_inventory(
        test_settings,
        [
            {
                "id": "offline-pdf",
                "title": "Guia PDF",
                "type": "PDF",
                "origin": "interno",
                "localPath": "docs/guide.pdf",
                "accessStatus": "OK",
                "canAccess": True,
                "canDownload": True,
            }
        ],
    )

    result = get_resource_content("offline-pdf", settings=test_settings, job_id=JOB_ID)

    assert result.ok is True
    assert result.content_type == "application/pdf"
    assert result.binary_path == str(pdf_path)
    assert result.text_content is None


def test_get_resource_content_reads_canvas_page_from_api_mock(test_settings) -> None:
    class CanvasPageClient:
        def get_page(self, course_id: str, page_url: str):
            assert course_id == "77"
            assert page_url == "bienvenida"
            return {"body": "<p>Contenido Canvas</p>"}

    result = get_resource_content(
        "canvas-page",
        settings=test_settings,
        resources=[
            {
                "id": "canvas-page",
                "title": "Pagina Canvas",
                "type": "WEB",
                "source": "Canvas",
                "sourceUrl": "https://canvas.example.edu/courses/77/pages/bienvenida",
                "accessStatus": "OK",
                "canAccess": True,
                "details": {"canvasType": "Page", "courseId": "77", "pageUrl": "bienvenida"},
            }
        ],
        canvas_client=CanvasPageClient(),
    )

    assert result.ok is True
    assert result.content_type == "text/html"
    assert result.filename == "bienvenida.html"
    assert result.text_content == "<p>Contenido Canvas</p>"
