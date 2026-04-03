from __future__ import annotations

import json
import shutil
import subprocess
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path, PurePosixPath
from uuid import uuid4

from docx import Document
from docx.oxml.ns import qn
from docx.shared import Inches, Pt
from fastapi import status
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from sqlmodel import Session, select

from app.core.config import Settings
from app.core.errors import AppError
from app.models import Job as ProcessingJob
from app.models.entities import (
    ChecklistResponse,
    ChecklistValue,
    ReportRecord,
    Resource,
    ResourceHealthStatus,
    ResourceType,
    utcnow,
)
from app.models.entities import (
    Job as ReviewJob,
)
from app.schemas import (
    GeneratedReportResponse,
    ReportDownloads,
    ReportFailure,
    ReportGroup,
    ResourceResponse,
)
from app.services.catalog import SEVERITY_ORDER, get_item_severity
from app.services.review_service import (
    ensure_job_inventory,
    ensure_review_rollups,
    get_templates_by_type,
)
from app.services.storage import get_reports_dir

TYPE_LABELS = {
    ResourceType.WEB: "Web",
    ResourceType.PDF: "PDF",
    ResourceType.VIDEO: "Video",
    ResourceType.NOTEBOOK: "Notebook",
    ResourceType.IMAGE: "Imagen",
    ResourceType.OTHER: "Otro",
}

STATUS_LABELS = {
    ResourceHealthStatus.OK: "OK",
    ResourceHealthStatus.WARN: "AVISO",
    ResourceHealthStatus.ERROR: "ERROR",
}

MEDIA_TYPES = {
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "json": "application/json",
}


def _download_urls(job_id: str) -> dict[str, str]:
    return {
        "pdfUrl": f"/api/jobs/{job_id}/report/download?format=pdf",
        "docxUrl": f"/api/jobs/{job_id}/report/download?format=docx",
        "jsonUrl": f"/api/jobs/{job_id}/report/download?format=json",
    }


def _legacy_downloads(job_id: str) -> ReportDownloads:
    return ReportDownloads(
        pdfUrl=f"/api/reports/{job_id}/download/pdf",
        docxUrl=f"/api/reports/{job_id}/download/docx",
    )


def _canonical_paths(settings: Settings, job_id: str) -> tuple[Path, Path, Path]:
    reports_dir = get_reports_dir(settings, job_id)
    return reports_dir / "report.json", reports_dir / "report.docx", reports_dir / "report.pdf"


def _resource_sort_key(resource: dict) -> tuple[int, int, str]:
    return (-resource["stats"]["fails"], -resource["stats"]["pending"], resource["title"].lower())


def _issue_sort_key(issue: dict) -> tuple[int, str]:
    return (SEVERITY_ORDER.get(issue["severity"], 9), issue["label"].lower())


def _format_report_date(value: str | datetime) -> str:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(value)
    return parsed.strftime("%Y-%m-%d %H:%M UTC")


def _stable_filename(job_id: str, created_at: str | datetime, extension: str) -> str:
    parsed = created_at if isinstance(created_at, datetime) else datetime.fromisoformat(created_at)
    return f"AccessibleCourse_Report_{job_id}_{parsed.strftime('%Y%m%d')}.{extension}"


def _resolve_course_title(session: Session, job_id: str) -> str | None:
    processing_job = session.get(ProcessingJob, job_id)
    if processing_job and getattr(processing_job, "original_filename", None):
        stem = Path(processing_job.original_filename).stem.strip()
        if stem:
            return stem

    review_job = session.get(ReviewJob, job_id)
    if review_job and review_job.name:
        candidate = review_job.name.strip()
        if candidate:
            return candidate

    return None


def _assert_job_ready(session: Session, job_id: str) -> None:
    processing_job = session.get(ProcessingJob, job_id)
    if processing_job is None:
        return

    if processing_job.status in {"created", "processing"}:
        raise AppError(
            code="job_not_ready",
            message="Job aun en proceso.",
            status_code=status.HTTP_409_CONFLICT,
            job_id=job_id,
        )
    if processing_job.status != "done":
        raise AppError(
            code="job_not_ready",
            message="El job no esta listo para generar el informe.",
            status_code=status.HTTP_409_CONFLICT,
            job_id=job_id,
        )


def _ensure_report_ready(session: Session, settings: Settings, job_id: str) -> None:
    _assert_job_ready(session, job_id)
    try:
        ensure_job_inventory(session, settings, job_id)
        ensure_review_rollups(session, job_id)
    except FileNotFoundError as exc:
        raise AppError(
            code="inventory_not_found",
            message="No hemos encontrado el inventario del curso para este job.",
            status_code=status.HTTP_404_NOT_FOUND,
            details={"reason": str(exc)},
            job_id=job_id,
        ) from exc
    except ValueError as exc:
        raise AppError(
            code="invalid_inventory",
            message="El inventario del curso no tiene un formato valido.",
            status_code=status.HTTP_409_CONFLICT,
            details={"reason": str(exc)},
            job_id=job_id,
        ) from exc


def _origin_label(resource: Resource) -> str:
    value = (resource.origin or "").lower()
    if resource.url or "extern" in value:
        return "externo"
    return "interno"


def _source_label(resource: Resource) -> str | None:
    return resource.path or resource.url or None


def _course_path(resource: Resource) -> str:
    if resource.course_path:
        return resource.course_path
    source = resource.path or resource.url or ""
    if source.startswith(("http://", "https://")):
        return "Enlaces externos"
    parent = PurePosixPath(source).parent.as_posix().strip(".")
    return parent or "Raiz del curso"


def _resource_response(resource: Resource) -> ResourceResponse:
    return ResourceResponse(
        id=resource.id,
        title=resource.title,
        type=TYPE_LABELS[resource.type],
        origin=_origin_label(resource),
        status=STATUS_LABELS[resource.status],
        href=_source_label(resource),
    )


def _recommendations(resources: list[dict]) -> list[str]:
    issue_counter = Counter()
    severity_counter = Counter()
    for resource in resources:
        for issue in resource["fails"] + resource["pending"]:
            issue_counter[issue["itemKey"]] += 1
            severity_counter[issue["severity"]] += 1

    recommendations = [
        "Prioriza primero los FAIL de severidad HIGH en los recursos con mayor uso docente.",
        "Convierte cada PENDING en una comprobacion verificable antes de publicar el curso.",
        "Agrupa la correccion por ruta del curso para reducir retrabajo entre equipos.",
    ]

    if issue_counter["captions"] or issue_counter["transcript"]:
        recommendations.append("Completa subtitulos y transcripciones en los videos antes de revisar mejoras menores.")
    if issue_counter["tagged"] or issue_counter["reading_order"] or issue_counter["ocr_scan"]:
        recommendations.append("Reexporta los PDF con etiquetado, orden de lectura y OCR revisados.")
    if issue_counter["alt_text"] or issue_counter["alt_images"] or issue_counter["alternative_text"]:
        recommendations.append("Añade alternativas textuales a imagenes, figuras y salidas visuales clave.")
    if issue_counter["keyboard"] or issue_counter["focus"] or issue_counter["player_controls"]:
        recommendations.append(
            "Revisa teclado y foco visible en los recursos interactivos con mayor frecuencia de uso."
        )
    if severity_counter["HIGH"] == 0 and len(recommendations) < 4:
        recommendations.append("Empieza por los recursos con mas FAIL acumulados para ganar impacto rapidamente.")

    return recommendations[:6]


def _build_report_payload(
    session: Session,
    settings: Settings,
    job_id: str,
    *,
    include_pending: bool = True,
    only_fails: bool = False,
) -> dict:
    _ensure_report_ready(session, settings, job_id)
    include_pending = include_pending and not only_fails

    template_map = get_templates_by_type(session)
    resources = session.exec(select(Resource).where(Resource.job_id == job_id).order_by(Resource.title)).all()
    responses = session.exec(select(ChecklistResponse).where(ChecklistResponse.job_id == job_id)).all()

    responses_by_resource: dict[str, list[ChecklistResponse]] = defaultdict(list)
    for response in responses:
        responses_by_resource[response.resource_id].append(response)

    created_at = utcnow()
    course_title = _resolve_course_title(session, job_id)
    report_id = f"report-{uuid4().hex[:12]}"
    resource_sections: list[dict] = []
    total_fails = 0
    total_pending = 0

    for resource in resources:
        template_bundle = template_map.get(resource.type) or template_map.get(ResourceType.OTHER)
        if template_bundle is None:
            continue

        responses_by_key = {response.item_key: response for response in responses_by_resource.get(resource.id, [])}
        fails: list[dict] = []
        pending: list[dict] = []

        for template_item in template_bundle.items:
            response = responses_by_key.get(template_item.key)
            value = response.value if response is not None else ChecklistValue.PENDING
            issue = {
                "itemKey": template_item.key,
                "label": template_item.label,
                "description": template_item.description or template_item.label,
                "recommendation": template_item.recommendation,
                "severity": get_item_severity(template_item.key),
                "comment": response.comment if response is not None else None,
            }

            if value == ChecklistValue.FAIL:
                fails.append({**issue, "status": "FAIL"})
            elif value == ChecklistValue.PENDING and include_pending:
                pending.append({**issue, "status": "PENDING"})

        fails.sort(key=_issue_sort_key)
        pending.sort(key=_issue_sort_key)
        total_fails += len(fails)
        total_pending += len(pending)

        if not fails and not pending:
            continue

        resource_sections.append(
            {
                "resourceId": resource.id,
                "title": resource.title,
                "type": TYPE_LABELS[resource.type],
                "origin": _origin_label(resource),
                "status": STATUS_LABELS[resource.status],
                "source": _source_label(resource),
                "coursePath": _course_path(resource),
                "stats": {"resources": 1, "fails": len(fails), "pending": len(pending)},
                "fails": fails,
                "pending": pending,
            }
        )

    route_groups: dict[str, list[dict]] = defaultdict(list)
    for resource in resource_sections:
        route_groups[resource["coursePath"]].append(resource)

    routes = []
    for course_path in sorted(route_groups):
        grouped_resources = sorted(route_groups[course_path], key=_resource_sort_key)
        routes.append(
            {
                "coursePath": course_path,
                "stats": {
                    "resources": len(grouped_resources),
                    "fails": sum(item["stats"]["fails"] for item in grouped_resources),
                    "pending": sum(item["stats"]["pending"] for item in grouped_resources),
                },
                "resources": grouped_resources,
            }
        )

    top_resources = sorted(
        [
            {
                "resourceId": resource["resourceId"],
                "title": resource["title"],
                "coursePath": resource["coursePath"],
                "failCount": resource["stats"]["fails"],
            }
            for resource in resource_sections
            if resource["stats"]["fails"] > 0
        ],
        key=lambda item: (-item["failCount"], item["title"].lower()),
    )[:5]

    created_at_iso = created_at.isoformat()
    return {
        "reportId": report_id,
        "createdAt": created_at_iso,
        "files": _download_urls(job_id),
        "stats": {"resources": len(resources), "fails": total_fails, "pending": total_pending},
        "meta": {
            "reportId": report_id,
            "createdAt": created_at_iso,
            "courseTitle": course_title,
            "jobId": job_id,
            "includePending": include_pending,
            "onlyFails": only_fails,
            "systemVersion": settings.version,
        },
        "summary": {
            "resources": len(resources),
            "fails": total_fails,
            "pending": total_pending,
            "topResources": top_resources,
            "recommendations": _recommendations(resource_sections),
        },
        "routes": routes,
        "resources": sorted(resource_sections, key=_resource_sort_key),
        "appendix": {
            "statusDefinitions": {
                "PENDING": "Pendiente de revisar o sin evidencia suficiente todavia.",
                "PASS": "Cumple el criterio revisado.",
                "FAIL": "No cumple el criterio y requiere accion correctiva.",
            },
            "createdAt": created_at_iso,
            "systemVersion": settings.version,
        },
    }


def _configure_docx_styles(document: Document) -> None:
    def set_style_font(style_name: str, size: int) -> None:
        style = document.styles[style_name]
        style.font.name = "Calibri"
        style.font.size = Pt(size)
        style._element.get_or_add_rPr().get_or_add_rFonts().set(qn("w:eastAsia"), "Calibri")

    for section in document.sections:
        section.top_margin = Inches(1)
        section.bottom_margin = Inches(1)
        section.left_margin = Inches(1)
        section.right_margin = Inches(1)

    set_style_font("Normal", 11)
    set_style_font("Heading 1", 16)
    set_style_font("Heading 2", 13)


def _write_docx(destination: Path, report: dict, brand_name: str) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    document = Document()
    _configure_docx_styles(document)

    document.add_heading(f"{brand_name} - Informe de accesibilidad", level=1)
    document.add_paragraph(f"Curso: {report['meta']['courseTitle'] or 'No disponible'}")
    document.add_paragraph(f"Fecha: {_format_report_date(report['createdAt'])}")
    document.add_paragraph(f"Job ID: {report['meta']['jobId']}")
    document.add_page_break()

    document.add_heading("Resumen ejecutivo", level=1)
    summary_table = document.add_table(rows=1, cols=2)
    summary_table.style = "Table Grid"
    summary_header = summary_table.rows[0].cells
    summary_header[0].text = "Indicador"
    summary_header[1].text = "Valor"
    for label, value in (
        ("Recursos analizados", str(report["summary"]["resources"])),
        ("Items FAIL", str(report["summary"]["fails"])),
        ("Items PENDING", str(report["summary"]["pending"])),
    ):
        row = summary_table.add_row().cells
        row[0].text = label
        row[1].text = value

    document.add_heading("Top 5 recursos con mas FAIL", level=2)
    if report["summary"]["topResources"]:
        for resource in report["summary"]["topResources"]:
            document.add_paragraph(
                f"{resource['title']} ({resource['coursePath']}) - {resource['failCount']} FAIL",
                style="List Bullet",
            )
    else:
        document.add_paragraph("No hay recursos con FAIL registrados.")

    document.add_heading("Recomendaciones generales", level=2)
    for recommendation in report["summary"]["recommendations"]:
        document.add_paragraph(recommendation, style="List Bullet")

    document.add_page_break()
    document.add_heading("Detalle por recurso", level=1)
    if not report["routes"]:
        document.add_paragraph("No hay hallazgos FAIL o PENDING para incluir en el informe.")
    else:
        for route in report["routes"]:
            document.add_heading(f"Ruta: {route['coursePath']}", level=1)
            for resource in route["resources"]:
                document.add_heading(resource["title"], level=2)
                document.add_paragraph(
                    f"Tipo: {resource['type']} | Origen: {resource['origin']} | "
                    f"Ruta: {resource['coursePath']} | Fuente: {resource['source'] or 'No disponible'}"
                )
                detail_table = document.add_table(rows=1, cols=5)
                detail_table.style = "Table Grid"
                headers = detail_table.rows[0].cells
                headers[0].text = "Estado"
                headers[1].text = "Severidad"
                headers[2].text = "Descripcion breve"
                headers[3].text = "Como arreglarlo"
                headers[4].text = "Notas del revisor"

                for issue in resource["fails"] + resource["pending"]:
                    row = detail_table.add_row().cells
                    row[0].text = issue["status"]
                    row[1].text = issue["severity"]
                    row[2].text = issue["description"]
                    row[3].text = issue["recommendation"] or "Sin recomendacion disponible."
                    row[4].text = issue.get("comment") or "-"

    document.add_heading("Apendice", level=1)
    for key, value in report["appendix"]["statusDefinitions"].items():
        document.add_paragraph(f"{key}: {value}", style="List Bullet")
    document.add_paragraph(f"Fecha: {_format_report_date(report['appendix']['createdAt'])}")
    document.add_paragraph(f"Version del sistema: {report['appendix']['systemVersion']}")
    document.save(destination)


def _write_pdf(destination: Path, report: dict, brand_name: str) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="Section", parent=styles["Heading1"], fontSize=15))

    story = [
        Paragraph(f"{brand_name} - Informe de accesibilidad", styles["Title"]),
        Spacer(1, 0.4 * cm),
        Paragraph(f"Curso: {report['meta']['courseTitle'] or 'No disponible'}", styles["Normal"]),
        Paragraph(f"Fecha: {_format_report_date(report['createdAt'])}", styles["Normal"]),
        Paragraph(f"Job ID: {report['meta']['jobId']}", styles["Normal"]),
        PageBreak(),
        Paragraph("Resumen ejecutivo", styles["Section"]),
    ]

    summary_table = Table(
        [
            ["Indicador", "Valor"],
            ["Recursos analizados", str(report["summary"]["resources"])],
            ["Items FAIL", str(report["summary"]["fails"])],
            ["Items PENDING", str(report["summary"]["pending"])],
        ],
        colWidths=[8 * cm, 5 * cm],
    )
    summary_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E2E8F0")),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E1")),
                ("PADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    story.extend(
        [
            summary_table,
            Spacer(1, 0.25 * cm),
            Paragraph("Top 5 recursos con mas FAIL", styles["Heading2"]),
        ]
    )

    if report["summary"]["topResources"]:
        for resource in report["summary"]["topResources"]:
            story.append(
                Paragraph(
                    f"- {resource['title']} ({resource['coursePath']}) - {resource['failCount']} FAIL",
                    styles["Normal"],
                )
            )
    else:
        story.append(Paragraph("No hay recursos con FAIL registrados.", styles["Normal"]))

    story.extend([Spacer(1, 0.25 * cm), Paragraph("Recomendaciones generales", styles["Heading2"])])
    for recommendation in report["summary"]["recommendations"]:
        story.append(Paragraph(f"- {recommendation}", styles["Normal"]))

    story.extend([PageBreak(), Paragraph("Detalle por recurso", styles["Section"])])
    if not report["routes"]:
        story.append(Paragraph("No hay hallazgos FAIL o PENDING para incluir en el informe.", styles["Normal"]))
    else:
        for route in report["routes"]:
            story.append(Paragraph(f"Ruta: {route['coursePath']}", styles["Heading2"]))
            for resource in route["resources"]:
                story.append(Paragraph(resource["title"], styles["Heading3"]))
                story.append(
                    Paragraph(
                        f"Tipo: {resource['type']} | Origen: {resource['origin']} | "
                        f"Ruta: {resource['coursePath']} | Fuente: {resource['source'] or 'No disponible'}",
                        styles["Normal"],
                    )
                )
                rows = [["Estado", "Severidad", "Descripcion", "Como arreglarlo", "Notas"]]
                for issue in resource["fails"] + resource["pending"]:
                    rows.append(
                        [
                            issue["status"],
                            issue["severity"],
                            issue["description"],
                            issue["recommendation"] or "Sin recomendacion disponible.",
                            issue.get("comment") or "-",
                        ]
                    )
                detail_table = Table(rows, colWidths=[2 * cm, 2.2 * cm, 4 * cm, 6 * cm, 2.8 * cm])
                detail_table.setStyle(
                    TableStyle(
                        [
                            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E2E8F0")),
                            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E1")),
                            ("PADDING", (0, 0), (-1, -1), 4),
                            ("VALIGN", (0, 0), (-1, -1), "TOP"),
                        ]
                    )
                )
                story.extend([Spacer(1, 0.15 * cm), detail_table, Spacer(1, 0.35 * cm)])

    story.extend([PageBreak(), Paragraph("Apendice", styles["Section"])])
    for key, value in report["appendix"]["statusDefinitions"].items():
        story.append(Paragraph(f"- {key}: {value}", styles["Normal"]))
    story.append(Paragraph(f"Fecha: {_format_report_date(report['appendix']['createdAt'])}", styles["Normal"]))
    story.append(Paragraph(f"Version del sistema: {report['appendix']['systemVersion']}", styles["Normal"]))

    document = SimpleDocTemplate(str(destination), pagesize=A4, leftMargin=2 * cm, rightMargin=2 * cm)
    document.build(story)


def _convert_docx_to_pdf(docx_path: Path, pdf_path: Path) -> bool:
    soffice = shutil.which("soffice") or shutil.which("libreoffice")
    if not soffice:
        return False

    try:
        subprocess.run(
            [
                soffice,
                "--headless",
                "--convert-to",
                "pdf:writer_pdf_Export",
                "--outdir",
                str(pdf_path.parent),
                str(docx_path),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return False

    generated_pdf = docx_path.with_suffix(".pdf")
    if generated_pdf.exists() and generated_pdf != pdf_path:
        generated_pdf.replace(pdf_path)
    return pdf_path.exists()


def _persist_files(settings: Settings, job_id: str, report: dict) -> tuple[Path, Path, Path]:
    json_path, docx_path, pdf_path = _canonical_paths(settings, job_id)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    _write_docx(docx_path, report, settings.report_brand_name)
    if not _convert_docx_to_pdf(docx_path, pdf_path):
        _write_pdf(pdf_path, report, settings.report_brand_name)
    return json_path, docx_path, pdf_path


def get_report_or_404(session: Session, job_id: str) -> ReportRecord:
    report = session.exec(select(ReportRecord).where(ReportRecord.job_id == job_id)).first()
    if report is None or report.payload is None:
        raise AppError(
            code="report_not_found",
            message="Todavia no existe un informe generado para este job.",
            status_code=status.HTTP_404_NOT_FOUND,
            job_id=job_id,
        )
    return report


def generate_job_report(
    session: Session,
    settings: Settings,
    job_id: str,
    *,
    include_pending: bool = True,
    only_fails: bool = False,
) -> dict:
    payload = _build_report_payload(
        session,
        settings,
        job_id,
        include_pending=include_pending,
        only_fails=only_fails,
    )
    _, docx_path, pdf_path = _persist_files(settings, job_id, payload)
    generated_at = datetime.fromisoformat(payload["createdAt"])
    record = session.exec(select(ReportRecord).where(ReportRecord.job_id == job_id)).first()

    if record is None:
        record = ReportRecord(job_id=job_id)

    record.resource_count = payload["stats"]["resources"]
    record.failed_item_count = payload["stats"]["fails"]
    record.generated_at = generated_at
    record.pdf_path = str(pdf_path)
    record.docx_path = str(docx_path)
    record.payload = payload
    session.add(record)
    session.commit()
    return payload


def load_job_report(session: Session, job_id: str) -> dict:
    return get_report_or_404(session, job_id).payload


def get_report_file_info(session: Session, settings: Settings, job_id: str, fmt: str) -> tuple[Path, str, str]:
    if fmt not in MEDIA_TYPES:
        raise AppError(
            code="invalid_format",
            message="Formato de descarga no soportado.",
            status_code=status.HTTP_404_NOT_FOUND,
            job_id=job_id,
        )

    record = get_report_or_404(session, job_id)
    json_path, canonical_docx, canonical_pdf = _canonical_paths(settings, job_id)

    if fmt == "json":
        file_path = json_path
    elif fmt == "docx":
        file_path = Path(record.docx_path) if record.docx_path else canonical_docx
    else:
        file_path = Path(record.pdf_path) if record.pdf_path else canonical_pdf

    if not file_path.exists():
        raise AppError(
            code="report_file_missing",
            message="El archivo solicitado del informe no esta disponible.",
            status_code=status.HTTP_404_NOT_FOUND,
            job_id=job_id,
        )

    download_name = _stable_filename(job_id, record.generated_at, fmt)
    return file_path, MEDIA_TYPES[fmt], download_name


def _legacy_groups_from_payload(session: Session, payload: dict) -> list[ReportGroup]:
    groups: list[ReportGroup] = []
    for resource in payload["resources"]:
        if not resource["fails"]:
            continue
        review_resource = session.get(Resource, resource["resourceId"])
        if review_resource is None:
            continue
        groups.append(
            ReportGroup(
                resource=_resource_response(review_resource),
                failures=[
                    ReportFailure(
                        itemId=item["itemKey"],
                        label=item["label"],
                        recommendation=item["recommendation"] or "Sin recomendacion disponible.",
                    )
                    for item in resource["fails"]
                ],
            )
        )
    return groups


def generate_report(session: Session, settings: Settings, job_id: str) -> GeneratedReportResponse:
    payload = generate_job_report(session, settings, job_id, include_pending=False, only_fails=True)
    return GeneratedReportResponse(
        jobId=job_id,
        resourceCount=payload["stats"]["resources"],
        failedItemCount=payload["stats"]["fails"],
        groups=_legacy_groups_from_payload(session, payload),
        generatedAt=datetime.fromisoformat(payload["createdAt"]),
        downloads=_legacy_downloads(job_id),
    )


def load_report(session: Session, job_id: str) -> GeneratedReportResponse:
    payload = load_job_report(session, job_id)
    return GeneratedReportResponse(
        jobId=job_id,
        resourceCount=payload["stats"]["resources"],
        failedItemCount=payload["stats"]["fails"],
        groups=_legacy_groups_from_payload(session, payload),
        generatedAt=datetime.fromisoformat(payload["createdAt"]),
        downloads=_legacy_downloads(job_id),
    )
