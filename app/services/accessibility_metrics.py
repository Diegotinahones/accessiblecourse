from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlparse

from app.services.access_analysis import build_access_summary
from app.services.html_accessibility import AccessibilityCheckResult, AccessibilityReport
from app.services.resource_core import normalize_resource

METRICS_SOURCE = "centralized"
METRICS_VERSION = "1.0"

ExecutivePriority = Literal["HIGH", "MEDIUM", "LOW", "NOT_SCORED"]

ANALYSIS_TYPES = ("HTML", "PDF", "DOCX", "VIDEO", "NOTEBOOK")
APPLICABLE_STATUSES = {"PASS", "FAIL", "WARNING", "ERROR"}
COUNTED_STATUSES = APPLICABLE_STATUSES | {"NOT_APPLICABLE"}
REPORT_TYPE_BY_ANALYSIS = {
    "HTML": "HTML",
    "PDF": "PDF",
    "DOCX": "WORD",
    "VIDEO": "VIDEO",
    "NOTEBOOK": "NOTEBOOK",
}
REPORT_PRIORITY_BY_EXECUTIVE = {
    "HIGH": "alta",
    "MEDIUM": "media",
    "LOW": "baja",
    "NOT_SCORED": "sin_puntuar",
}
REPORT_PRIORITY_ORDER = {"alta": 0, "media": 1, "baja": 2, "sin_puntuar": 3}

IMPORTANT_WARNING_CHECKS = {
    "html.heading_hierarchy",
    "pdf.title",
    "pdf.headings",
    "pdf.images_alt",
    "docx.title",
    "docx.headings",
    "docx.heading_hierarchy",
    "video.captions",
    "video.transcript",
    "video.controls",
    "notebook.intro_markdown",
    "notebook.title",
    "notebook.heading_hierarchy",
    "notebook.markdown_explanation",
    "notebook.visual_outputs",
    "notebook.execution_order",
    "notebook.markdown_tables",
}
CRITICAL_FAIL_CHECKS = {
    "html.lang",
    "html.images_alt",
    "html.links_descriptive",
    "html.form_labels",
    "pdf.readable",
    "pdf.text_extractable",
    "pdf.tagged",
    "docx.readable",
    "docx.text_extractable",
    "video.accessible",
    "video.captions",
    "video.controls",
    "notebook.readable",
    "notebook.markdown_explanation",
    "notebook.image_alt",
    "notebook.links",
    "notebook.execution_errors",
}


@dataclass(slots=True, frozen=True)
class ResourceScore:
    score: int | None
    priority: ExecutivePriority
    not_scored: bool
    weight: int
    main_issue: str | None
    has_critical_fail: bool


def calculate_accessibility_metrics(
    *,
    job_id: str,
    inventory_items: list[Any],
    accessibility_report: AccessibilityReport,
) -> dict[str, Any]:
    """Build the single source of truth for automatic accessibility metrics."""

    inventory_payloads = [_as_mapping(item) for item in inventory_items]
    main_items = [item for item in inventory_payloads if _is_main_item(item)]
    scoped_items = [item for item in inventory_payloads if not _is_technical_ignored(item)]
    access_resources = [_access_summary_resource(item) for item in main_items]
    access_summary = build_access_summary(
        job_id=job_id,
        resources=access_resources,
        progress=100,
        status="done",
    )
    detected_by_type = _detected_by_analysis_type(main_items)
    resources_by_type = Counter(normalize_resource(item).type for item in main_items)
    unique_checks, checks_by_resource, report_resources = _unique_checks(accessibility_report)

    status_counts = Counter(entry["status"] for entry in unique_checks)
    type_status_counts: dict[str, Counter[str]] = {analysis_type: Counter() for analysis_type in ANALYSIS_TYPES}
    for entry in unique_checks:
        type_status_counts[entry["analysisType"]][entry["status"]] += 1

    score_by_resource_id = {
        resource_id: _score_resource(checks)
        for resource_id, checks in checks_by_resource.items()
    }
    analyzed_by_type = Counter(resource["analysisType"] for resource in report_resources.values())
    resource_score_rows = _resource_score_rows(
        report_resources=report_resources,
        score_by_resource_id=score_by_resource_id,
    )
    global_score = _weighted_score(score_by_resource_id.values())
    global_priority = _overall_priority(global_score, list(score_by_resource_id.values()))

    executive_modules = _executive_modules(
        main_items=main_items,
        report_resources=report_resources,
        score_by_resource_id=score_by_resource_id,
    )
    report_module_scores = _report_module_scores(resource_score_rows)
    public_resource_score_rows = [_public_resource_payload(row) for row in resource_score_rows]
    top_issues = _top_issues(unique_checks)
    top_recommendations = _top_recommendations(top_issues)
    analyzed_ids = set(report_resources)
    not_analyzable_resources = _not_analyzable_resource_count(scoped_items, analyzed_ids)

    base_counts = _base_counts(status_counts)
    type_summaries = {
        analysis_type: {
            "resourcesTotal": detected_by_type[analysis_type],
            "resourcesAnalyzed": analyzed_by_type[analysis_type],
            **_base_counts(type_status_counts[analysis_type]),
        }
        for analysis_type in ANALYSIS_TYPES
    }

    metrics = {
        "metricsSource": METRICS_SOURCE,
        "metricsVersion": METRICS_VERSION,
        "jobId": job_id,
        **base_counts,
        "resourcesDetected": int(access_summary["total"]),
        "resourcesAccessed": int(access_summary["accessible"]),
        "downloadableResources": int(access_summary["downloadable"]),
        "resourcesAnalyzed": len(report_resources),
        "analyzedResourceIds": sorted(analyzed_ids),
        "notAnalyzableResources": not_analyzable_resources,
        "resourcesByType": dict(sorted(resources_by_type.items())),
        "analyzedByType": dict(sorted(analyzed_by_type.items())),
        "detectedByType": {analysis_type: detected_by_type[analysis_type] for analysis_type in ANALYSIS_TYPES},
        "typeSummaries": type_summaries,
        "accessibilityScore": global_score,
        "priority": global_priority,
        "topIssues": top_issues,
        "topRecommendations": top_recommendations,
        "executiveModules": executive_modules,
        "reportResourceScores": public_resource_score_rows,
        "reportResourceScoreById": {row["resourceId"]: row for row in public_resource_score_rows},
        "reportModuleScores": report_module_scores,
    }
    metrics["accessSummary"] = build_report_access_summary_payload(metrics, access_summary)
    metrics["accessibilitySummary"] = build_accessibility_summary_payload(metrics)
    metrics["automaticSummary"] = build_automatic_summary_payload(metrics)
    metrics["reportTypeSummaries"] = build_report_type_summaries(metrics)
    return metrics


def build_report_access_summary_payload(metrics: dict[str, Any], access_summary: dict[str, Any]) -> dict[str, int]:
    return {
        "resourcesDetected": metrics["resourcesDetected"],
        "resourcesAccessed": metrics["resourcesAccessed"],
        "downloadable": metrics["downloadableResources"],
        "noAccessible": int(access_summary["no_accede_count"]),
        "requiresSSO": int(access_summary["requires_sso_count"]),
        "requiresInteraction": int(access_summary["requires_interaction_count"]),
    }


def build_accessibility_summary_payload(metrics: dict[str, Any]) -> dict[str, Any]:
    type_summaries = metrics["typeSummaries"]
    return {
        "htmlResourcesTotal": type_summaries["HTML"]["resourcesTotal"],
        "htmlResourcesAnalyzed": type_summaries["HTML"]["resourcesAnalyzed"],
        "pdfResourcesTotal": type_summaries["PDF"]["resourcesTotal"],
        "pdfResourcesAnalyzed": type_summaries["PDF"]["resourcesAnalyzed"],
        "docxResourcesTotal": type_summaries["DOCX"]["resourcesTotal"],
        "docxResourcesAnalyzed": type_summaries["DOCX"]["resourcesAnalyzed"],
        "videoResourcesTotal": type_summaries["VIDEO"]["resourcesTotal"],
        "videoResourcesAnalyzed": type_summaries["VIDEO"]["resourcesAnalyzed"],
        "notebookResourcesTotal": type_summaries["NOTEBOOK"]["resourcesTotal"],
        "notebookResourcesAnalyzed": type_summaries["NOTEBOOK"]["resourcesAnalyzed"],
        "passCount": metrics["passCount"],
        "failCount": metrics["failCount"],
        "warningCount": metrics["warningCount"],
        "notApplicableCount": metrics["notApplicableCount"],
        "errorCount": metrics["errorCount"],
        "incidentCount": metrics["incidentCount"],
        "resourcesDetected": metrics["resourcesDetected"],
        "resourcesAccessed": metrics["resourcesAccessed"],
        "resourcesAnalyzed": metrics["resourcesAnalyzed"],
        "downloadableResources": metrics["downloadableResources"],
        "notAnalyzableResources": metrics["notAnalyzableResources"],
        "resourcesByType": metrics["resourcesByType"],
        "analyzedByType": metrics["analyzedByType"],
        "accessibilityScore": metrics["accessibilityScore"],
        "metricsSource": metrics["metricsSource"],
        "metricsVersion": metrics["metricsVersion"],
        "byType": type_summaries,
    }


def build_automatic_summary_payload(metrics: dict[str, Any]) -> dict[str, Any]:
    type_summaries = metrics["typeSummaries"]
    return {
        "htmlResourcesDetected": type_summaries["HTML"]["resourcesTotal"],
        "htmlResourcesAnalyzed": type_summaries["HTML"]["resourcesAnalyzed"],
        "pdfResourcesDetected": type_summaries["PDF"]["resourcesTotal"],
        "pdfResourcesAnalyzed": type_summaries["PDF"]["resourcesAnalyzed"],
        "wordResourcesDetected": type_summaries["DOCX"]["resourcesTotal"],
        "wordResourcesAnalyzed": type_summaries["DOCX"]["resourcesAnalyzed"],
        "videoResourcesDetected": type_summaries["VIDEO"]["resourcesTotal"],
        "videoResourcesAnalyzed": type_summaries["VIDEO"]["resourcesAnalyzed"],
        "notebookResourcesDetected": type_summaries["NOTEBOOK"]["resourcesTotal"],
        "notebookResourcesAnalyzed": type_summaries["NOTEBOOK"]["resourcesAnalyzed"],
        "passCount": metrics["passCount"],
        "failCount": metrics["failCount"],
        "warningCount": metrics["warningCount"],
        "notApplicableCount": metrics["notApplicableCount"],
        "errorCount": metrics["errorCount"],
        "incidentCount": metrics["incidentCount"],
        "resourcesDetected": metrics["resourcesDetected"],
        "resourcesAccessed": metrics["resourcesAccessed"],
        "resourcesAnalyzed": metrics["resourcesAnalyzed"],
        "notAnalyzableResources": metrics["notAnalyzableResources"],
        "resourcesByType": metrics["resourcesByType"],
        "analyzedByType": metrics["analyzedByType"],
        "accessibilityScore": metrics["accessibilityScore"],
        "metricsSource": metrics["metricsSource"],
        "metricsVersion": metrics["metricsVersion"],
    }


def build_report_type_summaries(metrics: dict[str, Any]) -> dict[str, dict[str, Any]]:
    type_summaries = metrics["typeSummaries"]
    return {
        REPORT_TYPE_BY_ANALYSIS[analysis_type]: {
            "resourcesDetected": summary["resourcesTotal"],
            "resourcesAnalyzed": summary["resourcesAnalyzed"],
            "passCount": summary["passCount"],
            "failCount": summary["failCount"],
            "warningCount": summary["warningCount"],
            "notApplicableCount": summary["notApplicableCount"],
            "errorCount": summary["errorCount"],
            "incidentCount": summary["incidentCount"],
            "metricsSource": metrics["metricsSource"],
            "metricsVersion": metrics["metricsVersion"],
        }
        for analysis_type, summary in type_summaries.items()
    }


def report_priority(value: ExecutivePriority | str | None) -> str:
    return REPORT_PRIORITY_BY_EXECUTIVE.get(str(value or "NOT_SCORED"), "sin_puntuar")


def _base_counts(counts: Counter[str]) -> dict[str, int]:
    fail_count = int(counts["FAIL"])
    error_count = int(counts["ERROR"])
    return {
        "passCount": int(counts["PASS"]),
        "failCount": fail_count,
        "warningCount": int(counts["WARNING"]),
        "notApplicableCount": int(counts["NOT_APPLICABLE"]),
        "errorCount": error_count,
        "incidentCount": fail_count + error_count,
    }


def _unique_checks(
    report: AccessibilityReport,
) -> tuple[list[dict[str, Any]], dict[str, list[AccessibilityCheckResult]], dict[str, dict[str, Any]]]:
    seen: set[tuple[str, str, str]] = set()
    entries: list[dict[str, Any]] = []
    checks_by_resource: dict[str, list[AccessibilityCheckResult]] = defaultdict(list)
    report_resources: dict[str, dict[str, Any]] = {}

    for module in report.modules:
        for resource in module.resources:
            resource_id = str(resource.resourceId)
            analysis_type = _resource_analysis_type(resource)
            report_resources.setdefault(
                resource_id,
                {
                    "resourceId": resource_id,
                    "title": resource.title,
                    "type": resource.type,
                    "analysisType": analysis_type,
                    "accessStatus": resource.accessStatus,
                    "moduleTitle": module.title,
                    "checks": [],
                },
            )
            for check in resource.checks:
                status = str(check.status)
                if status not in COUNTED_STATUSES:
                    continue
                dedupe_key = (resource_id, str(check.checkId), status)
                if dedupe_key in seen:
                    continue
                seen.add(dedupe_key)
                checks_by_resource[resource_id].append(check)
                report_resources[resource_id]["checks"].append(check)
                entries.append(
                    {
                        "resourceId": resource_id,
                        "analysisType": analysis_type,
                        "status": status,
                        "check": check,
                    }
                )
    return entries, checks_by_resource, report_resources


def _score_resource(checks: list[AccessibilityCheckResult]) -> ResourceScore:
    applicable = [check for check in checks if check.status in APPLICABLE_STATUSES]
    if not applicable:
        return ResourceScore(
            score=None,
            priority="NOT_SCORED",
            not_scored=True,
            weight=0,
            main_issue=None,
            has_critical_fail=False,
        )
    obtained = sum(_status_points(check.status) for check in applicable)
    score = round((obtained / len(applicable)) * 100)
    has_critical_fail = any(
        check.status in {"FAIL", "ERROR"} and check.checkId in CRITICAL_FAIL_CHECKS for check in applicable
    )
    has_important_warning = any(
        check.status == "WARNING" and check.checkId in IMPORTANT_WARNING_CHECKS for check in applicable
    )
    return ResourceScore(
        score=score,
        priority=_resource_priority(
            score,
            has_critical_fail=has_critical_fail,
            has_important_warning=has_important_warning,
        ),
        not_scored=False,
        weight=len(applicable),
        main_issue=_main_issue(applicable),
        has_critical_fail=has_critical_fail,
    )


def _status_points(status: str) -> float:
    if status == "PASS":
        return 1.0
    if status == "WARNING":
        return 0.5
    return 0.0


def _resource_priority(
    score: int,
    *,
    has_critical_fail: bool,
    has_important_warning: bool,
) -> ExecutivePriority:
    if score < 60 or has_critical_fail:
        return "HIGH"
    if score < 80 or has_important_warning:
        return "MEDIUM"
    return "LOW"


def _overall_priority(score: int | None, scores: list[ResourceScore]) -> ExecutivePriority:
    if score is None:
        return "NOT_SCORED"
    if score < 60 or any(item.priority == "HIGH" for item in scores):
        return "HIGH"
    if score < 80 or any(item.priority == "MEDIUM" for item in scores):
        return "MEDIUM"
    return "LOW"


def _main_issue(checks: list[AccessibilityCheckResult]) -> str | None:
    for status in ("FAIL", "ERROR", "WARNING"):
        issue = next((check for check in checks if check.status == status), None)
        if issue is not None:
            return issue.checkTitle
    return None


def _weighted_score(scores: Any) -> int | None:
    total_weight = 0
    weighted_total = 0
    for score in scores:
        if score.score is None or score.weight <= 0:
            continue
        total_weight += score.weight
        weighted_total += score.score * score.weight
    if total_weight == 0:
        return None
    return round(weighted_total / total_weight)


def _resource_score_rows(
    *,
    report_resources: dict[str, dict[str, Any]],
    score_by_resource_id: dict[str, ResourceScore],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for resource_id, score in score_by_resource_id.items():
        if score.not_scored or score.score is None:
            continue
        resource = report_resources.get(resource_id)
        if resource is None:
            continue
        analysis_type = str(resource["analysisType"])
        rows.append(
            {
                "resourceId": resource_id,
                "title": resource["title"],
                "type": REPORT_TYPE_BY_ANALYSIS.get(analysis_type, analysis_type),
                "typeLabel": _type_label(analysis_type),
                "moduleTitle": resource["moduleTitle"] or "Raiz del curso",
                "coursePath": resource["moduleTitle"] or "Raiz del curso",
                "score": score.score,
                "_scoreWeight": score.weight,
                "priority": report_priority(score.priority),
                "mainIssue": score.main_issue or "Sin incidencias FAIL/WARNING",
                "failCount": _resource_status_count(resource_id, "FAIL", report_resources),
                "warningCount": _resource_status_count(resource_id, "WARNING", report_resources),
                "errorCount": _resource_status_count(resource_id, "ERROR", report_resources),
            }
        )
    return sorted(
        rows,
        key=lambda item: (
            REPORT_PRIORITY_ORDER.get(str(item["priority"]), 9),
            int(item["score"]),
            str(item["moduleTitle"]).lower(),
            str(item["title"]).lower(),
        ),
    )


def _resource_status_count(resource_id: str, status: str, report_resources: dict[str, dict[str, Any]]) -> int:
    resource = report_resources.get(resource_id)
    checks = resource.get("checks", []) if isinstance(resource, dict) else []
    return sum(1 for check in checks if getattr(check, "status", None) == status)


def _executive_modules(
    *,
    main_items: list[dict[str, Any]],
    report_resources: dict[str, dict[str, Any]],
    score_by_resource_id: dict[str, ResourceScore],
) -> list[dict[str, Any]]:
    module_groups: dict[str, dict[str, Any]] = {}
    for item in main_items:
        core = normalize_resource(item)
        score = score_by_resource_id.get(
            core.id,
            ResourceScore(
                score=None,
                priority="NOT_SCORED",
                not_scored=True,
                weight=0,
                main_issue=None,
                has_critical_fail=False,
            ),
        )
        analyzed = report_resources.get(core.id)
        resource_payload = {
            "resourceId": core.id,
            "title": core.title,
            "type": core.type,
            "score": score.score,
            "_scoreWeight": score.weight,
            "priority": score.priority,
            "accessStatus": core.accessStatus,
            "downloadable": core.downloadable,
            "mainIssue": score.main_issue,
            "reportAnchorId": f"resource-{core.id}",
        }
        if analyzed is not None:
            resource_payload["type"] = core.type or analyzed["type"]
        module_title = _module_title(core)
        module_groups.setdefault(module_title, {"title": module_title, "resources": []})["resources"].append(
            resource_payload
        )
    return sorted(
        [_executive_module_payload(group) for group in module_groups.values()],
        key=lambda module: str(module["title"]).lower(),
    )


def _executive_module_payload(group: dict[str, Any]) -> dict[str, Any]:
    resources = group["resources"]
    scored = [resource for resource in resources if resource["score"] is not None]
    score = _weighted_score_from_resources(scored)
    priority = _module_priority(score, resources)
    return {
        "title": group["title"],
        "score": score,
        "priority": priority,
        "resourceCount": len(resources),
        "analyzedCount": len(scored),
        "highPriorityCount": sum(1 for resource in resources if resource["priority"] == "HIGH"),
        "mediumPriorityCount": sum(1 for resource in resources if resource["priority"] == "MEDIUM"),
        "lowPriorityCount": sum(1 for resource in resources if resource["priority"] == "LOW"),
        "resources": sorted(
            [_public_resource_payload(resource) for resource in resources],
            key=lambda resource: str(resource["title"]).lower(),
        ),
    }


def _weighted_score_from_resources(resources: list[dict[str, Any]]) -> int | None:
    total_weight = sum(int(resource.get("_scoreWeight") or 0) for resource in resources)
    if total_weight <= 0:
        return None
    weighted_total = sum(int(resource["score"]) * int(resource.get("_scoreWeight") or 0) for resource in resources)
    return round(weighted_total / total_weight)


def _module_priority(score: int | None, resources: list[dict[str, Any]]) -> ExecutivePriority:
    if score is None:
        return "NOT_SCORED"
    if score < 60 or any(resource["priority"] == "HIGH" for resource in resources):
        return "HIGH"
    if score < 80 or any(resource["priority"] == "MEDIUM" for resource in resources):
        return "MEDIUM"
    return "LOW"


def _public_resource_payload(resource: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in resource.items() if not key.startswith("_")}


def _report_module_scores(resource_scores: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in resource_scores:
        grouped[str(row["moduleTitle"])].append(row)

    module_rows: list[dict[str, Any]] = []
    for module_title, rows in grouped.items():
        weighted_score = _weighted_score_from_report_rows(rows)
        priority = report_priority(_module_priority_from_report(weighted_score, rows))
        issues = [
            str(row["mainIssue"])
            for row in sorted(rows, key=lambda item: (int(item["score"]), str(item["title"]).lower()))
            if row.get("mainIssue") and row["mainIssue"] != "Sin incidencias FAIL/WARNING"
        ]
        module_rows.append(
            {
                "moduleTitle": module_title,
                "score": weighted_score if weighted_score is not None else 0,
                "priority": priority,
                "resourcesAnalyzed": len(rows),
                "mainIssues": list(dict.fromkeys(issues))[:3] or ["Sin incidencias principales"],
            }
        )

    return sorted(
        module_rows,
        key=lambda item: (
            REPORT_PRIORITY_ORDER.get(str(item["priority"]), 9),
            int(item["score"]),
            str(item["moduleTitle"]).lower(),
        ),
    )


def _weighted_score_from_report_rows(rows: list[dict[str, Any]]) -> int | None:
    total_weight = sum(int(row.get("_scoreWeight") or 0) for row in rows)
    if total_weight <= 0:
        return None
    weighted_total = sum(int(row["score"]) * int(row.get("_scoreWeight") or 0) for row in rows)
    return round(weighted_total / total_weight)


def _module_priority_from_report(score: int | None, rows: list[dict[str, Any]]) -> ExecutivePriority:
    priorities = {str(row.get("priority")) for row in rows}
    if score is None:
        return "NOT_SCORED"
    if score < 60 or "alta" in priorities:
        return "HIGH"
    if score < 80 or "media" in priorities:
        return "MEDIUM"
    return "LOW"


def _top_issues(entries: list[dict[str, Any]], *, limit: int = 5) -> list[dict[str, Any]]:
    issues: Counter[tuple[str, str, str]] = Counter()
    recommendations: dict[tuple[str, str, str], str] = {}
    for entry in entries:
        status = entry["status"]
        if status not in {"FAIL", "ERROR", "WARNING"}:
            continue
        check = entry["check"]
        issue_type = str(entry["analysisType"])
        key = (issue_type, check.checkTitle, check.recommendation)
        issues[key] += 1
        recommendations[key] = check.recommendation
    ordered = sorted(issues.items(), key=lambda item: (-item[1], item[0][0], item[0][1]))
    return [
        {
            "type": issue_type,
            "checkTitle": check_title,
            "count": count,
            "recommendation": recommendations[(issue_type, check_title, recommendation)],
        }
        for (issue_type, check_title, recommendation), count in ordered[:limit]
    ]


def _top_recommendations(top_issues: list[dict[str, Any]], *, limit: int = 5) -> list[str]:
    recommendations: list[str] = []
    for issue in top_issues:
        recommendation = str(issue["recommendation"])
        if recommendation not in recommendations:
            recommendations.append(recommendation)
        if len(recommendations) >= limit:
            break
    return recommendations


def _detected_by_analysis_type(main_items: list[dict[str, Any]]) -> Counter[str]:
    detected: Counter[str] = Counter()
    for item in main_items:
        analysis_type = _candidate_analysis_type(item)
        if analysis_type is not None:
            detected[analysis_type] += 1
    return detected


def _candidate_analysis_type(item: dict[str, Any]) -> str | None:
    core = normalize_resource(item)
    if core.type == "WEB":
        if core.origin in {"RALTI", "LTI", "EXTERNAL_URL"}:
            return None
        if core.accessStatus in {"REQUIERE_SSO", "REQUIERE_INTERACCION", "NO_ANALIZABLE"}:
            return None
        return "HTML" if core.contentAvailable else None
    if core.type == "PDF":
        if core.origin in {"RALTI", "LTI", "EXTERNAL_URL"}:
            return None
        if core.accessStatus in {"REQUIERE_SSO", "REQUIERE_INTERACCION", "NO_ANALIZABLE"}:
            return None
        return "PDF" if core.contentAvailable else None
    if core.type == "DOCX" or _resource_has_suffix(item, ".docx"):
        if core.origin in {"RALTI", "LTI", "EXTERNAL_URL"}:
            return None
        if core.accessStatus in {"REQUIERE_SSO", "REQUIERE_INTERACCION", "NO_ANALIZABLE"}:
            return None
        return "DOCX" if core.contentAvailable else None
    if core.type == "VIDEO" or _resource_has_video_reference(item):
        if core.origin in {"RALTI", "LTI"}:
            return None
        if core.accessStatus in {"REQUIERE_SSO", "REQUIERE_INTERACCION", "NO_ANALIZABLE"}:
            return None
        return "VIDEO"
    if core.type == "NOTEBOOK" or _resource_has_suffix(item, ".ipynb"):
        if core.origin in {"RALTI", "LTI", "EXTERNAL_URL"}:
            return None
        if core.accessStatus in {"REQUIERE_SSO", "REQUIERE_INTERACCION", "NO_ANALIZABLE"}:
            return None
        return "NOTEBOOK" if core.contentAvailable or core.localPath or core.downloadable else None
    return None


def _not_analyzable_resource_count(scoped_items: list[dict[str, Any]], analyzed_ids: set[str]) -> int:
    count = 0
    for item in scoped_items:
        core = normalize_resource(item)
        if core.id in analyzed_ids:
            continue
        if _is_technical_ignored(item):
            continue
        if (
            core.accessStatus in {"REQUIERE_SSO", "REQUIERE_INTERACCION", "NO_ANALIZABLE"}
            or core.origin in {"RALTI", "LTI"}
            or _analysis_category(item) == "NON_ANALYZABLE_EXTERNAL"
            or core.type not in {"WEB", "PDF", "DOCX", "VIDEO", "NOTEBOOK"}
            or _candidate_analysis_type(item) is None
        ):
            count += 1
    return count


def _access_summary_resource(item: dict[str, Any]) -> dict[str, Any]:
    core = normalize_resource(item)
    return {
        "id": core.id,
        "title": core.title,
        "type": core.type,
        "modulePath": " > ".join(core.modulePath) if core.modulePath else None,
        "coursePath": " > ".join(core.modulePath) if core.modulePath else None,
        "accessStatus": core.accessStatus,
        "canAccess": core.accessStatus == "OK",
        "canDownload": core.downloadable,
        "downloadStatus": core.downloadStatus,
        "accessStatusCode": core.httpStatus,
        "downloadStatusCode": 200 if core.downloadStatus == "OK" else None,
        "accessNote": core.reasonDetail,
        "discovered": core.discovered,
    }


def _resource_analysis_type(resource: Any) -> str:
    analysis_type = getattr(resource, "analysisType", None)
    if analysis_type in ANALYSIS_TYPES:
        return str(analysis_type)
    resource_type = str(getattr(resource, "type", "") or "").upper()
    if resource_type in {"NOTEBOOK", "VIDEO", "DOCX", "PDF"}:
        return resource_type
    return "HTML"


def _module_title(core: Any) -> str:
    if core.modulePath:
        return " > ".join(core.modulePath)
    return core.sectionTitle or "Modulo general"


def _type_label(analysis_type: str) -> str:
    return {
        "HTML": "HTML",
        "PDF": "PDF",
        "DOCX": "Word",
        "VIDEO": "Video",
        "NOTEBOOK": "Notebook",
    }.get(analysis_type, analysis_type)


def _resource_has_video_reference(resource: Any) -> bool:
    for value in _resource_reference_values(resource):
        normalized = value.lower()
        suffix = Path(urlparse(normalized).path).suffix.lower()
        if suffix in {".mp4", ".mov", ".m4v", ".webm", ".avi"}:
            return True
        if any(marker in normalized for marker in ("youtube.com", "youtu.be", "vimeo.com", "kaltura")):
            return True
    return False


def _resource_has_suffix(resource: Any, suffix: str) -> bool:
    return any(Path(urlparse(value).path).suffix.lower() == suffix for value in _resource_reference_values(resource))


def _resource_reference_values(resource: Any) -> list[str]:
    mapping = _as_mapping(resource)
    details = mapping.get("details") if isinstance(mapping.get("details"), dict) else {}
    values: list[str] = []
    for source in (mapping, details):
        for key in (
            "localPath",
            "filePath",
            "path",
            "sourceUrl",
            "url",
            "downloadUrl",
            "title",
            "mimeType",
            "contentType",
            "filename",
            "htmlUrl",
        ):
            value = source.get(key)
            if value is not None and str(value).strip():
                values.append(str(value).strip())
    return values


def _is_main_item(item: Any) -> bool:
    return _analysis_category(item) == "MAIN_ANALYZABLE"


def _is_technical_ignored(item: Any) -> bool:
    return _analysis_category(item) == "TECHNICAL_IGNORED"


def _analysis_category(item: Any) -> str:
    value = _string(item, "analysis_category", "analysisCategory")
    return (value or "MAIN_ANALYZABLE").upper()


def _string(value: Any, *keys: str) -> str | None:
    mapping = _as_mapping(value)
    for key in keys:
        item = mapping.get(key)
        if item is None and "_" in key:
            item = mapping.get(_snake_to_camel(key))
        if hasattr(item, "value"):
            item = item.value
        if item is None:
            continue
        cleaned = str(item).strip()
        if cleaned:
            return cleaned
    return None


def _as_mapping(item: Any) -> dict[str, Any]:
    if hasattr(item, "model_dump"):
        payload = item.model_dump(mode="python")
        return payload if isinstance(payload, dict) else {}
    return item if isinstance(item, dict) else {}


def _snake_to_camel(value: str) -> str:
    head, *tail = value.split("_")
    return head + "".join(part.capitalize() for part in tail)
