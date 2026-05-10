from __future__ import annotations

from typing import Any, Literal

from app.services.accessibility_metrics import calculate_accessibility_metrics
from app.services.html_accessibility import AccessibilityReport

ExecutivePriority = Literal["HIGH", "MEDIUM", "LOW", "NOT_SCORED"]


def build_executive_summary(
    *,
    job_id: str,
    mode: str,
    course_title: str,
    course_name: str | None = None,
    course_code: str | None = None,
    course_id: str | None = None,
    inventory_items: list[Any],
    accessibility_report: AccessibilityReport,
) -> dict[str, Any]:
    metrics = calculate_accessibility_metrics(
        job_id=job_id,
        inventory_items=inventory_items,
        accessibility_report=accessibility_report,
    )
    modules = metrics["executiveModules"]

    return {
        "jobId": job_id,
        "mode": mode,
        "courseTitle": course_title,
        "courseName": course_name or course_title,
        "courseCode": course_code,
        "courseId": course_id,
        "accessibilityScore": metrics["accessibilityScore"],
        "priority": metrics["priority"],
        "metricsSource": metrics["metricsSource"],
        "metricsVersion": metrics["metricsVersion"],
        "summary": {
            "resourcesDetected": metrics["resourcesDetected"],
            "resourcesAccessed": metrics["resourcesAccessed"],
            "resourcesAnalyzed": metrics["resourcesAnalyzed"],
            "downloadableResources": metrics["downloadableResources"],
            "incidentCount": metrics["incidentCount"],
            "failCount": metrics["failCount"],
            "warningCount": metrics["warningCount"],
            "errorCount": metrics["errorCount"],
            "passCount": metrics["passCount"],
            "notApplicableCount": metrics["notApplicableCount"],
            "notAnalyzableResources": metrics["notAnalyzableResources"],
            "resourcesByType": metrics["resourcesByType"],
            "analyzedByType": metrics["analyzedByType"],
            "highPriorityResources": sum(module["highPriorityCount"] for module in modules),
            "mediumPriorityResources": sum(module["mediumPriorityCount"] for module in modules),
            "lowPriorityResources": sum(module["lowPriorityCount"] for module in modules),
            "notScoredResources": sum(
                1
                for module in modules
                for resource in module["resources"]
                if resource["priority"] == "NOT_SCORED"
            ),
        },
        "topIssues": metrics["topIssues"],
        "topRecommendations": metrics["topRecommendations"],
        "modules": modules,
    }
