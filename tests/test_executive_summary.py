from __future__ import annotations

from app.services.executive_summary import build_executive_summary
from app.services.html_accessibility import (
    AccessibilityCheckResult,
    AccessibilityModuleResult,
    AccessibilityReport,
    AccessibilityResourceResult,
    AccessibilitySummary,
)


def _check(check_id: str, status: str) -> AccessibilityCheckResult:
    return AccessibilityCheckResult(
        checkId=check_id,
        checkTitle=f"Check {check_id}",
        status=status,
        evidence="Evidencia breve.",
        recommendation=f"Recomendacion {check_id}",
    )


def _report(*resources: AccessibilityResourceResult) -> AccessibilityReport:
    return AccessibilityReport(
        jobId="job-exec",
        summary=AccessibilitySummary(),
        modules=[AccessibilityModuleResult(title="Modulo 1", resources=list(resources))],
    )


def _resource(
    resource_id: str,
    *,
    title: str = "Recurso",
    resource_type: str = "WEB",
    access_status: str = "OK",
    can_download: bool = False,
) -> dict[str, object]:
    return {
        "id": resource_id,
        "title": title,
        "type": resource_type,
        "origin": "INTERNAL_PAGE" if resource_type == "WEB" else "INTERNAL_FILE",
        "modulePath": "Modulo 1",
        "coursePath": "Modulo 1",
        "accessStatus": access_status,
        "canAccess": access_status == "OK",
        "canDownload": can_download,
        "contentAvailable": True,
        "path": f"{resource_id}.html",
    }


def _analyzed_resource(
    resource_id: str,
    checks: list[AccessibilityCheckResult],
    *,
    resource_type: str = "WEB",
) -> AccessibilityResourceResult:
    return AccessibilityResourceResult(
        resourceId=resource_id,
        title="Recurso",
        type=resource_type,
        analysisType="HTML" if resource_type == "WEB" else resource_type,
        accessStatus="OK",
        checks=checks,
    )


def test_resource_with_all_pass_scores_100() -> None:
    summary = build_executive_summary(
        job_id="job-exec",
        mode="OFFLINE_IMSCC",
        course_title="Curso",
        inventory_items=[_resource("r1")],
        accessibility_report=_report(_analyzed_resource("r1", [_check("html.lang", "PASS"), _check("html.h1", "PASS")])),
    )

    resource = summary["modules"][0]["resources"][0]
    assert summary["accessibilityScore"] == 100
    assert summary["priority"] == "LOW"
    assert resource["score"] == 100
    assert resource["priority"] == "LOW"


def test_resource_with_fail_and_warning_scores_lower() -> None:
    summary = build_executive_summary(
        job_id="job-exec",
        mode="OFFLINE_IMSCC",
        course_title="Curso",
        inventory_items=[_resource("r1")],
        accessibility_report=_report(
            _analyzed_resource(
                "r1",
                [_check("html.lang", "PASS"), _check("html.h1", "WARNING"), _check("html.images_alt", "FAIL")],
            )
        ),
    )

    resource = summary["modules"][0]["resources"][0]
    assert resource["score"] == 50
    assert resource["priority"] == "HIGH"
    assert summary["summary"]["highPriorityResources"] == 1


def test_not_applicable_checks_do_not_penalize_score() -> None:
    summary = build_executive_summary(
        job_id="job-exec",
        mode="OFFLINE_IMSCC",
        course_title="Curso",
        inventory_items=[_resource("r1")],
        accessibility_report=_report(
            _analyzed_resource("r1", [_check("html.lang", "PASS"), _check("html.table_headers", "NOT_APPLICABLE")])
        ),
    )

    assert summary["accessibilityScore"] == 100
    assert summary["modules"][0]["resources"][0]["score"] == 100


def test_module_and_global_scores_average_scored_resources() -> None:
    summary = build_executive_summary(
        job_id="job-exec",
        mode="OFFLINE_IMSCC",
        course_title="Curso",
        inventory_items=[_resource("r1"), _resource("r2", resource_type="PDF")],
        accessibility_report=_report(
            _analyzed_resource("r1", [_check("html.lang", "PASS"), _check("html.h1", "PASS")]),
            _analyzed_resource("r2", [_check("pdf.text_extractable", "PASS"), _check("pdf.tagged", "FAIL")], resource_type="PDF"),
        ),
    )

    assert summary["accessibilityScore"] == 75
    assert summary["summary"]["resourcesAnalyzed"] == 2
    assert summary["modules"][0]["score"] == 75
    assert summary["modules"][0]["analyzedCount"] == 2


def test_non_analyzable_resources_are_not_scored() -> None:
    summary = build_executive_summary(
        job_id="job-exec",
        mode="ONLINE_CANVAS",
        course_title="Curso",
        inventory_items=[
            {
                **_resource("sso", title="RALTI", access_status="REQUIERE_SSO"),
                "origin": "RALTI",
                "contentAvailable": False,
            }
        ],
        accessibility_report=_report(),
    )

    resource = summary["modules"][0]["resources"][0]
    assert summary["accessibilityScore"] is None
    assert summary["priority"] == "NOT_SCORED"
    assert summary["summary"]["notScoredResources"] == 1
    assert resource["score"] is None
    assert resource["priority"] == "NOT_SCORED"
