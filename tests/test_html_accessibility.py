from __future__ import annotations

from app.services.html_accessibility import analyze_html_accessibility, run_html_accessibility_scan
from app.services.storage import get_extracted_dir


def _status_by_check(html: str) -> dict[str, str]:
    checks = analyze_html_accessibility({"id": "html", "title": "Leccion accesible", "type": "WEB"}, html)
    return {check.checkId: check.status for check in checks}


def test_html_accessibility_passes_basic_accessible_html() -> None:
    statuses = _status_by_check(
        """
        <html lang="es">
          <head><title>Lección accesible</title></head>
          <body>
            <h1>Lección accesible</h1>
            <img src="diagram.png" alt="Diagrama del proceso">
            <a href="guide.html">Guía de evaluación</a>
          </body>
        </html>
        """
    )

    assert statuses["html.lang"] == "PASS"
    assert statuses["html.title"] == "PASS"
    assert statuses["html.h1"] == "PASS"
    assert statuses["html.img_alt"] == "PASS"
    assert statuses["html.link_text"] == "PASS"


def test_html_accessibility_fails_missing_language() -> None:
    statuses = _status_by_check("<html><head><title>Unidad 1</title></head><body><h1>Unidad 1</h1></body></html>")

    assert statuses["html.lang"] == "FAIL"


def test_html_accessibility_fails_image_without_alt() -> None:
    statuses = _status_by_check(
        '<html lang="es"><head><title>Unidad</title></head><body><h1>Unidad</h1><img src="chart.png"></body></html>'
    )

    assert statuses["html.img_alt"] == "FAIL"


def test_html_accessibility_fails_generic_link_text() -> None:
    statuses = _status_by_check(
        '<html lang="es"><head><title>Unidad</title></head><body><h1>Unidad</h1><a href="guide.html">aquí</a></body></html>'
    )

    assert statuses["html.link_text"] == "FAIL"


def test_html_accessibility_warns_heading_hierarchy_skip() -> None:
    statuses = _status_by_check(
        """
        <html lang="es">
          <head><title>Unidad</title></head>
          <body><h1>Unidad</h1><h2>Sección</h2><h4>Detalle</h4></body>
        </html>
        """
    )

    assert statuses["html.heading_hierarchy"] == "WARNING"


def test_html_accessibility_job_scan_skips_non_html_resources(test_settings) -> None:
    job_id = "11111111-1111-1111-1111-111111111111"
    extracted_dir = get_extracted_dir(test_settings, job_id)
    pdf_path = extracted_dir / "docs" / "guide.pdf"
    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    pdf_path.write_bytes(b"%PDF-1.4\n")

    report = run_html_accessibility_scan(
        settings=test_settings,
        job_id=job_id,
        resources=[
            {
                "id": "pdf-guide",
                "title": "Guia PDF",
                "type": "PDF",
                "origin": "INTERNAL_FILE",
                "localPath": "docs/guide.pdf",
                "accessStatus": "OK",
                "canAccess": True,
                "canDownload": True,
                "contentAvailable": True,
            }
        ],
    )

    assert report.summary.htmlResourcesTotal == 0
    assert report.modules == []


def test_html_accessibility_job_scan_skips_sso_resources(test_settings) -> None:
    report = run_html_accessibility_scan(
        settings=test_settings,
        job_id="22222222-2222-2222-2222-222222222222",
        resources=[
            {
                "id": "ralti-link",
                "title": "Herramienta RALTI",
                "type": "WEB",
                "origin": "RALTI",
                "url": "https://ralti.uoc.edu/tool",
                "accessStatus": "OK",
                "contentAvailable": True,
            }
        ],
    )

    assert report.summary.htmlResourcesTotal == 0
    assert report.modules == []
