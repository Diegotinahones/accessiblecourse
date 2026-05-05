from __future__ import annotations

import json
from types import SimpleNamespace

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
    assert offline.htmlPath == "pages/page.html"
    assert online.origin == "ONLINE_CANVAS"


def test_auth_required_protected_external_resource_is_not_no_accede() -> None:
    core = normalize_resource(
        {
            "id": "library-book",
            "title": "Libro protegido",
            "type": "WEB",
            "origin": "EXTERNAL_URL",
            "sourceUrl": "https://biblioteca.uoc.edu/books/protected",
            "accessStatus": "NO_ACCEDE",
            "reasonCode": "AUTH_REQUIRED",
            "httpStatus": 401,
        }
    )

    assert core.accessStatus == "REQUIERE_SSO"
    assert core.reasonCode == "AUTH_REQUIRED"
    assert core.reasonDetail == "Requiere autenticación externa o capa SSO no accesible mediante API Canvas."


def test_protected_external_404_stays_no_accede_not_sso() -> None:
    core = normalize_resource(
        {
            "id": "library-missing",
            "title": "Libro no encontrado",
            "type": "WEB",
            "origin": "EXTERNAL_URL",
            "sourceUrl": "https://biblioteca.uoc.edu/books/missing",
            "accessStatus": "NO_ACCEDE",
            "reasonCode": "NOT_FOUND",
            "httpStatus": 404,
        }
    )

    assert core.accessStatus == "NO_ACCEDE"
    assert core.reasonCode == "NOT_FOUND"


def test_unknown_401_stays_no_accede_as_forbidden() -> None:
    core = normalize_resource(
        {
            "id": "unknown-private",
            "title": "Privado desconocido",
            "type": "WEB",
            "origin": "EXTERNAL_URL",
            "sourceUrl": "https://private.example.com/secret",
            "accessStatus": "NO_ACCEDE",
            "httpStatus": 401,
        }
    )

    assert core.accessStatus == "NO_ACCEDE"
    assert core.reasonCode == "FORBIDDEN"


def test_unknown_auth_required_stays_no_accede_as_forbidden() -> None:
    core = normalize_resource(
        {
            "id": "unknown-auth",
            "title": "Auth desconocida",
            "type": "WEB",
            "origin": "EXTERNAL_URL",
            "sourceUrl": "https://private.example.com/secret",
            "accessStatus": "NO_ACCEDE",
            "reasonCode": "AUTH_REQUIRED",
            "httpStatus": 401,
        }
    )

    assert core.accessStatus == "NO_ACCEDE"
    assert core.reasonCode == "FORBIDDEN"


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
                "htmlPath": "pages/page.html",
                "accessStatus": "OK",
                "canAccess": True,
            }
        ],
    )

    result = get_resource_content(JOB_ID, "offline-html", settings=test_settings)

    assert result.ok is True
    assert result.resourceId == "offline-html"
    assert result.title == "Pagina local"
    assert result.origin == "INTERNAL_PAGE"
    assert result.contentKind == "HTML"
    assert result.mimeType == "text/html"
    assert result.htmlContent == "<html><body>Contenido local</body></html>"
    assert result.binaryPath == str(html_path)


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

    result = get_resource_content(JOB_ID, "offline-pdf", settings=test_settings)

    assert result.ok is True
    assert result.resourceId == "offline-pdf"
    assert result.title == "Guia PDF"
    assert result.origin == "INTERNAL_FILE"
    assert result.contentKind == "PDF"
    assert result.mimeType == "application/pdf"
    assert result.binaryPath == str(pdf_path)
    assert result.htmlContent is None
    assert result.textContent is None


def test_external_resource_is_not_marked_downloadable_or_local() -> None:
    core = normalize_resource(
        {
            "id": "external-link",
            "title": "Enlace externo",
            "type": "WEB",
            "origin": "EXTERNAL_URL",
            "sourceUrl": "https://example.com/resource",
            "accessStatus": "OK",
            "canAccess": True,
            "canDownload": True,
            "downloadable": True,
        }
    )

    assert core.origin == "EXTERNAL_URL"
    assert core.sourceUrl == "https://example.com/resource"
    assert core.localPath is None
    assert core.htmlPath is None
    assert core.downloadable is False


def test_get_resource_content_reads_canvas_page_from_api_mock(test_settings) -> None:
    class CanvasPageClient:
        def get_page(self, course_id: str, page_url: str):
            assert course_id == "77"
            assert page_url == "bienvenida"
            return {"body": "<p>Contenido Canvas</p>"}

    result = get_resource_content(
        JOB_ID,
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
    assert result.resourceId == "canvas-page"
    assert result.title == "Pagina Canvas"
    assert result.origin == "ONLINE_CANVAS"
    assert result.contentKind == "HTML"
    assert result.mimeType == "text/html"
    assert result.filename == "bienvenida.html"
    assert result.htmlContent == "<p>Contenido Canvas</p>"


def test_get_resource_content_downloads_canvas_file_from_api_mock(test_settings) -> None:
    class DownloadHandle:
        content_type = "application/pdf"

        def iter_bytes(self):
            yield b"%PDF-1.4\n%canvas\n"

    class CanvasFileClient:
        def get_file_by_id(self, file_id: str):
            assert file_id == "123"
            return SimpleNamespace(
                url="https://canvas.example.edu/files/123/download",
                filename="canvas-guide.pdf",
                display_name="Canvas guide",
                content_type="application/pdf",
            )

        def stream_download(self, url: str, *, filename: str | None = None):
            assert url == "https://canvas.example.edu/files/123/download"
            assert filename == "canvas-guide.pdf"
            return DownloadHandle()

    result = get_resource_content(
        JOB_ID,
        "canvas-file",
        settings=test_settings,
        resources=[
            {
                "id": "canvas-file",
                "title": "Canvas PDF",
                "type": "PDF",
                "source": "Canvas",
                "sourceUrl": "https://canvas.example.edu/courses/77/files/123",
                "accessStatus": "OK",
                "canAccess": True,
                "canDownload": True,
                "details": {"canvasType": "File", "courseId": "77", "fileId": "123"},
            }
        ],
        canvas_client=CanvasFileClient(),
    )

    assert result.ok is True
    assert result.resourceId == "canvas-file"
    assert result.title == "Canvas PDF"
    assert result.origin == "ONLINE_CANVAS"
    assert result.contentKind == "PDF"
    assert result.mimeType == "application/pdf"
    assert result.filename == "canvas-guide.pdf"
    assert result.binaryPath is not None
    assert result.binaryPath.endswith("online_downloads/canvas-file/canvas-guide.pdf")
    assert result.sourceUrl is None


def test_get_resource_content_marks_ralti_as_not_analyzable(test_settings) -> None:
    result = get_resource_content(
        JOB_ID,
        "ralti",
        settings=test_settings,
        resources=[
            {
                "id": "ralti",
                "title": "RALTI",
                "type": "WEB",
                "origin": "RALTI",
                "sourceUrl": "https://ralti.uoc.edu/lti/launch",
                "accessStatus": "REQUIERE_SSO",
                "canAccess": False,
            }
        ],
    )

    assert result.ok is False
    assert result.resourceId == "ralti"
    assert result.title == "RALTI"
    assert result.origin == "RALTI"
    assert result.contentKind == "NOT_ANALYZABLE"
    assert result.errorCode == "REQUIERE_SSO"
    assert result.errorDetail
