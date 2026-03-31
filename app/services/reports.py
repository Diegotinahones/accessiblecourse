from __future__ import annotations

from pathlib import Path

from docx import Document
from fastapi import status
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from sqlmodel import Session, select

from app.core.config import Settings
from app.core.errors import AppError
from app.models import ChecklistEntry, ReportRecord, ResourceRecord, utcnow
from app.schemas import GeneratedReportResponse, ReportDownloads, ReportFailure, ReportGroup
from app.services.jobs import get_job_or_404, record_job_event, serialize_resource
from app.services.storage import get_reports_dir


def _report_downloads(job_id: str) -> ReportDownloads:
    return ReportDownloads(
        pdfUrl=f'/api/reports/{job_id}/download/pdf',
        docxUrl=f'/api/reports/{job_id}/download/docx',
    )


def _build_text_lines(report: GeneratedReportResponse, brand_name: str) -> list[str]:
    lines = [
        f'{brand_name} - Informe generado',
        '',
        f'Recursos revisados: {report.resourceCount}',
        f'No cumplidos: {report.failedItemCount}',
        '',
    ]

    if not report.groups:
        lines.append('No se han marcado incumplimientos en este informe.')
        return lines

    for group in report.groups:
        lines.append(group.resource.title)
        for failure in group.failures:
            lines.append(f'- {failure.label}: {failure.recommendation}')
        lines.append('')

    return lines


def _write_pdf(destination: Path, lines: list[str]) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    pdf = canvas.Canvas(str(destination), pagesize=A4)
    _, height = A4
    y = height - 60
    pdf.setTitle(destination.stem)
    pdf.setFont('Helvetica-Bold', 16)
    pdf.drawString(48, y, lines[0])
    y -= 28
    pdf.setFont('Helvetica', 11)
    for line in lines[1:]:
        if y <= 48:
            pdf.showPage()
            pdf.setFont('Helvetica', 11)
            y = height - 60
        pdf.drawString(48, y, line)
        y -= 18
    pdf.save()


def _write_docx(destination: Path, lines: list[str]) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    document = Document()
    document.add_heading(lines[0], level=1)
    for line in lines[1:]:
        document.add_paragraph(line)
    document.save(destination)


def get_report_or_404(session: Session, job_id: str) -> ReportRecord:
    report = session.exec(select(ReportRecord).where(ReportRecord.job_id == job_id)).first()
    if not report:
        raise AppError(code='report_not_found', message='Todavia no existe un informe para ese analisis.', status_code=404)
    return report


def load_report(session: Session, job_id: str) -> GeneratedReportResponse:
    report = get_report_or_404(session, job_id)
    return GeneratedReportResponse.model_validate(report.payload)


def generate_report(session: Session, settings: Settings, job_id: str) -> GeneratedReportResponse:
    job = get_job_or_404(session, job_id)
    if job.status != 'done':
        raise AppError(
            code='job_not_ready',
            message='El informe solo se puede generar cuando el analisis ha terminado.',
            status_code=status.HTTP_409_CONFLICT,
            job_id=job_id,
        )

    resources = session.exec(select(ResourceRecord).where(ResourceRecord.job_id == job_id).order_by(ResourceRecord.title)).all()
    entries = session.exec(select(ChecklistEntry).where(ChecklistEntry.job_id == job_id)).all()
    failures_by_resource: dict[str, list[ChecklistEntry]] = {}
    for entry in entries:
        if entry.decision == 'fail':
            failures_by_resource.setdefault(entry.resource_id, []).append(entry)

    groups: list[ReportGroup] = []
    for resource in resources:
        failures = [
            ReportFailure(itemId=entry.item_id, label=entry.label, recommendation=entry.recommendation)
            for entry in failures_by_resource.get(resource.id, [])
        ]
        if failures:
            groups.append(ReportGroup(resource=serialize_resource(resource), failures=failures))

    response = GeneratedReportResponse(
        jobId=job_id,
        resourceCount=len(resources),
        failedItemCount=sum(len(group.failures) for group in groups),
        groups=groups,
        generatedAt=utcnow(),
        downloads=_report_downloads(job_id),
    )

    lines = _build_text_lines(response, settings.report_brand_name)
    reports_dir = get_reports_dir(settings, job_id)
    pdf_path = reports_dir / 'accessible-course-report.pdf'
    docx_path = reports_dir / 'accessible-course-report.docx'
    _write_pdf(pdf_path, lines)
    _write_docx(docx_path, lines)

    existing = session.exec(select(ReportRecord).where(ReportRecord.job_id == job_id)).first()
    if existing:
        existing.resource_count = response.resourceCount
        existing.failed_item_count = response.failedItemCount
        existing.generated_at = response.generatedAt
        existing.pdf_path = str(pdf_path)
        existing.docx_path = str(docx_path)
        existing.payload = response.model_dump(mode='json')
        session.add(existing)
    else:
        session.add(
            ReportRecord(
                job_id=job_id,
                resource_count=response.resourceCount,
                failed_item_count=response.failedItemCount,
                generated_at=response.generatedAt,
                pdf_path=str(pdf_path),
                docx_path=str(docx_path),
                payload=response.model_dump(mode='json'),
            )
        )

    record_job_event(
        session,
        settings,
        job_id=job_id,
        event='progress',
        message='Informe regenerado.',
        progress=100,
        details={'failedItemCount': response.failedItemCount},
    )
    session.commit()
    return response
