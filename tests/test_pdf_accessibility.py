from __future__ import annotations

from pathlib import Path

from pypdf import PdfWriter
from reportlab.pdfgen import canvas

from app.services.pdf_accessibility import analyze_pdf_accessibility, run_pdf_accessibility_scan


def _write_text_pdf(path: Path, *, title: str | None = "Guia docente") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pdf = canvas.Canvas(str(path))
    if title is not None:
        pdf.setTitle(title)
    pdf.drawString(
        72,
        720,
        "Este documento PDF contiene texto real suficiente para validar la extraccion automatica.",
    )
    pdf.drawString(72, 700, "Incluye varias palabras y una frase larga para superar el umbral minimo.")
    pdf.save()


def _status_by_check(path: Path) -> dict[str, str]:
    checks = analyze_pdf_accessibility({"id": "pdf", "title": "Guia docente", "type": "PDF"}, path)
    return {check.checkId: check.status for check in checks}


def test_pdf_accessibility_passes_extractable_text(tmp_path) -> None:
    pdf_path = tmp_path / "guide.pdf"
    _write_text_pdf(pdf_path)

    statuses = _status_by_check(pdf_path)

    assert statuses["pdf.readable"] == "PASS"
    assert statuses["pdf.extractable_text"] == "PASS"


def test_pdf_accessibility_fails_encrypted_pdf(tmp_path) -> None:
    pdf_path = tmp_path / "locked.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    writer.encrypt("secret")
    with pdf_path.open("wb") as output:
        writer.write(output)

    statuses = _status_by_check(pdf_path)

    assert statuses["pdf.readable"] == "FAIL"


def test_pdf_accessibility_fails_missing_language(tmp_path) -> None:
    pdf_path = tmp_path / "guide.pdf"
    _write_text_pdf(pdf_path)

    statuses = _status_by_check(pdf_path)

    assert statuses["pdf.lang"] == "FAIL"


def test_pdf_accessibility_warns_missing_title(tmp_path) -> None:
    pdf_path = tmp_path / "guide.pdf"
    _write_text_pdf(pdf_path, title=None)

    statuses = _status_by_check(pdf_path)

    assert statuses["pdf.title"] == "WARNING"


def test_pdf_accessibility_fails_untagged_pdf(tmp_path) -> None:
    pdf_path = tmp_path / "guide.pdf"
    _write_text_pdf(pdf_path)

    statuses = _status_by_check(pdf_path)

    assert statuses["pdf.tagged"] == "FAIL"


def test_pdf_accessibility_job_scan_skips_non_pdf_resources(test_settings) -> None:
    report = run_pdf_accessibility_scan(
        settings=test_settings,
        job_id="33333333-3333-3333-3333-333333333333",
        resources=[
            {
                "id": "text-file",
                "title": "Apuntes",
                "type": "FILE",
                "origin": "INTERNAL_FILE",
                "localPath": "docs/notes.txt",
                "accessStatus": "OK",
                "contentAvailable": True,
            }
        ],
    )

    assert report.summary.pdfResourcesTotal == 0
    assert report.modules == []
