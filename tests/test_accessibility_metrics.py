from __future__ import annotations

from app.services.accessibility_metrics import calculate_accessibility_metrics
from app.services.executive_summary import build_executive_summary
from app.services.html_accessibility import (
    AccessibilityCheckResult,
    AccessibilityModuleResult,
    AccessibilityReport,
    AccessibilityResourceResult,
    AccessibilitySummary,
)
from app.services.reports import _build_report_executive_summary


def _check(check_id: str, status: str) -> AccessibilityCheckResult:
    return AccessibilityCheckResult(
        checkId=check_id,
        checkTitle=f"Check {check_id}",
        status=status,
        evidence="Evidencia.",
        recommendation=f"Recomendacion {check_id}",
    )


def _resource(
    resource_id: str,
    analysis_type: str,
    checks: list[AccessibilityCheckResult],
) -> AccessibilityResourceResult:
    resource_type = "WEB" if analysis_type == "HTML" else analysis_type
    return AccessibilityResourceResult(
        resourceId=resource_id,
        title=f"Recurso {resource_id}",
        type=resource_type,
        analysisType=analysis_type,
        accessStatus="OK",
        checks=checks,
    )


def _inventory_resource(resource_id: str, resource_type: str, path: str) -> dict[str, object]:
    return {
        "id": resource_id,
        "title": f"Recurso {resource_id}",
        "type": resource_type,
        "origin": "INTERNAL_PAGE" if resource_type == "WEB" else "INTERNAL_FILE",
        "analysisCategory": "MAIN_ANALYZABLE",
        "modulePath": "Modulo comun",
        "coursePath": "Modulo comun",
        "accessStatus": "OK",
        "canAccess": True,
        "canDownload": resource_type != "WEB",
        "contentAvailable": True,
        "path": path,
    }


def _fixture() -> tuple[list[dict[str, object]], AccessibilityReport]:
    inventory = [
        _inventory_resource("html", "WEB", "html.html"),
        _inventory_resource("pdf", "PDF", "pdf.pdf"),
        _inventory_resource("docx", "DOCX", "docx.docx"),
        {
            **_inventory_resource("video", "VIDEO", "video.mp4"),
            "origin": "EXTERNAL_URL",
            "sourceUrl": "https://example.com/video",
            "contentAvailable": False,
            "canDownload": False,
        },
        _inventory_resource("notebook", "NOTEBOOK", "notebook.ipynb"),
        {
            **_inventory_resource("sso", "WEB", "sso.html"),
            "origin": "RALTI",
            "accessStatus": "REQUIERE_SSO",
            "canAccess": False,
            "canDownload": False,
            "contentAvailable": False,
        },
    ]
    report = AccessibilityReport(
        jobId="job-metrics",
        summary=AccessibilitySummary(),
        modules=[
            AccessibilityModuleResult(
                title="Modulo comun",
                resources=[
                    _resource(
                        "html",
                        "HTML",
                        [
                            _check("html.lang", "PASS"),
                            _check("html.lang", "PASS"),
                            _check("html.images_alt", "FAIL"),
                            _check("html.tables", "NOT_APPLICABLE"),
                        ],
                    ),
                    _resource(
                        "pdf",
                        "PDF",
                        [
                            _check("pdf.text_extractable", "PASS"),
                            _check("pdf.title", "WARNING"),
                            _check("pdf.links", "NOT_APPLICABLE"),
                        ],
                    ),
                    _resource(
                        "docx",
                        "DOCX",
                        [
                            _check("docx.readable", "PASS"),
                            _check("docx.headings", "WARNING"),
                            _check("docx.tables", "NOT_APPLICABLE"),
                        ],
                    ),
                    _resource(
                        "video",
                        "VIDEO",
                        [
                            _check("video.accessible", "PASS"),
                            _check("video.controls", "FAIL"),
                            _check("video.local_metadata", "NOT_APPLICABLE"),
                        ],
                    ),
                    _resource(
                        "notebook",
                        "NOTEBOOK",
                        [
                            _check("notebook.intro_markdown", "WARNING"),
                            _check("notebook.execution_errors", "ERROR"),
                            _check("notebook.tables", "NOT_APPLICABLE"),
                        ],
                    ),
                ],
            )
        ],
    )
    return inventory, report


def test_central_metrics_dedupe_and_count_incidents_consistently() -> None:
    inventory, report = _fixture()

    metrics = calculate_accessibility_metrics(
        job_id="job-metrics",
        inventory_items=inventory,
        accessibility_report=report,
    )

    assert metrics["passCount"] == 4
    assert metrics["failCount"] == 2
    assert metrics["warningCount"] == 3
    assert metrics["notApplicableCount"] == 5
    assert metrics["errorCount"] == 1
    assert metrics["incidentCount"] == 3
    assert metrics["resourcesDetected"] == 6
    assert metrics["resourcesAnalyzed"] == 5
    assert set(metrics["analyzedResourceIds"]) == {"html", "pdf", "docx", "video", "notebook"}
    assert metrics["notAnalyzableResources"] == 1
    assert metrics["metricsSource"] == "centralized"
    assert metrics["metricsVersion"] == "1.0"
    assert "sso" not in metrics["reportResourceScoreById"]


def test_accessibility_executive_and_report_models_share_central_metrics() -> None:
    inventory, report = _fixture()
    metrics = calculate_accessibility_metrics(
        job_id="job-metrics",
        inventory_items=inventory,
        accessibility_report=report,
    )
    executive = build_executive_summary(
        job_id="job-metrics",
        mode="OFFLINE_IMSCC",
        course_title="Curso",
        inventory_items=inventory,
        accessibility_report=report,
    )
    report_executive = _build_report_executive_summary(metrics)

    accessibility_summary = metrics["accessibilitySummary"]
    automatic_summary = metrics["automaticSummary"]
    assert accessibility_summary["incidentCount"] == automatic_summary["incidentCount"] == 3
    assert accessibility_summary["warningCount"] == automatic_summary["warningCount"] == 3
    assert executive["summary"]["incidentCount"] == report_executive["incidentCount"] == 3
    assert executive["summary"]["resourcesAnalyzed"] == report_executive["resourcesAnalyzed"] == 5
    assert executive["accessibilityScore"] == report_executive["score"]
    assert metrics["reportModuleScores"][0]["resourcesAnalyzed"] == 5
    assert len(metrics["reportResourceScores"]) == 5
