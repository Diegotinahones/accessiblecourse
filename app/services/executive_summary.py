from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Any, Literal

from app.services.access_analysis import build_access_summary
from app.services.html_accessibility import AccessibilityCheckResult, AccessibilityReport
from app.services.resource_core import normalize_resource

ExecutivePriority = Literal["HIGH", "MEDIUM", "LOW", "NOT_SCORED"]
APPLICABLE_STATUSES = {"PASS", "FAIL", "WARNING", "ERROR"}
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


def build_executive_summary(
    *,
    job_id: str,
    mode: str,
    course_title: str,
    inventory_items: list[Any],
    accessibility_report: AccessibilityReport,
) -> dict[str, Any]:
    analyzed_by_id = _flatten_accessibility_resources(accessibility_report)
    inventory_payloads = [_as_mapping(item) for item in inventory_items if not _is_technical_ignored(item)]
    module_groups: dict[str, dict[str, Any]] = {}
    resource_scores: list[tuple[dict[str, Any], ResourceScore]] = []
    not_scored_count = 0

    for item in inventory_payloads:
        core = normalize_resource(item)
        module_title = _module_title(core)
        analyzed_resource = analyzed_by_id.get(core.id)
        score = _score_resource(analyzed_resource.checks if analyzed_resource is not None else [])
        if score.not_scored:
            not_scored_count += 1

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
        group = module_groups.setdefault(module_title, {"title": module_title, "resources": []})
        group["resources"].append(resource_payload)
        resource_scores.append((resource_payload, score))

    module_payloads = [_module_payload(group) for group in module_groups.values()]
    global_score = _weighted_score(score for _resource, score in resource_scores)
    global_priority = _overall_priority(global_score, [score for _resource, score in resource_scores])
    top_issues = _top_issues(accessibility_report)
    top_recommendations = _top_recommendations(top_issues)
    access_summary = build_access_summary(
        job_id=job_id,
        resources=inventory_payloads,
        progress=100,
        status="done",
    )

    return {
        "jobId": job_id,
        "mode": mode,
        "courseTitle": course_title,
        "accessibilityScore": global_score,
        "priority": global_priority,
        "summary": {
            "resourcesDetected": access_summary["total"],
            "resourcesAccessed": access_summary["accessible"],
            "resourcesAnalyzed": sum(1 for _resource, score in resource_scores if not score.not_scored),
            "downloadableResources": access_summary["downloadable"],
            "highPriorityResources": sum(
                1 for _resource, score in resource_scores if score.priority == "HIGH"
            ),
            "mediumPriorityResources": sum(
                1 for _resource, score in resource_scores if score.priority == "MEDIUM"
            ),
            "lowPriorityResources": sum(
                1 for _resource, score in resource_scores if score.priority == "LOW"
            ),
            "notScoredResources": not_scored_count,
        },
        "topIssues": top_issues,
        "topRecommendations": top_recommendations,
        "modules": sorted(module_payloads, key=lambda module: str(module["title"]).lower()),
    }


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
    has_critical_fail = any(check.status in {"FAIL", "ERROR"} and check.checkId in CRITICAL_FAIL_CHECKS for check in applicable)
    has_important_warning = any(
        check.status == "WARNING" and check.checkId in IMPORTANT_WARNING_CHECKS for check in applicable
    )
    return ResourceScore(
        score=score,
        priority=_resource_priority(score, has_critical_fail=has_critical_fail, has_important_warning=has_important_warning),
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


def _module_payload(group: dict[str, Any]) -> dict[str, Any]:
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


def _weighted_score_from_resources(resources: list[dict[str, Any]]) -> int | None:
    total_weight = sum(int(resource.get("_scoreWeight") or 0) for resource in resources)
    if total_weight <= 0:
        return None
    weighted_total = sum(int(resource["score"]) * int(resource.get("_scoreWeight") or 0) for resource in resources)
    return round(weighted_total / total_weight)


def _public_resource_payload(resource: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in resource.items() if not key.startswith("_")}


def _overall_priority(score: int | None, scores: list[ResourceScore]) -> ExecutivePriority:
    if score is None:
        return "NOT_SCORED"
    if score < 60 or any(item.priority == "HIGH" for item in scores):
        return "HIGH"
    if score < 80 or any(item.priority == "MEDIUM" for item in scores):
        return "MEDIUM"
    return "LOW"


def _module_priority(score: int | None, resources: list[dict[str, Any]]) -> ExecutivePriority:
    if score is None:
        return "NOT_SCORED"
    if score < 60 or any(resource["priority"] == "HIGH" for resource in resources):
        return "HIGH"
    if score < 80 or any(resource["priority"] == "MEDIUM" for resource in resources):
        return "MEDIUM"
    return "LOW"


def _main_issue(checks: list[AccessibilityCheckResult]) -> str | None:
    for status in ("FAIL", "ERROR", "WARNING"):
        issue = next((check for check in checks if check.status == status), None)
        if issue is not None:
            return issue.checkTitle
    return None


def _top_issues(report: AccessibilityReport, *, limit: int = 5) -> list[dict[str, Any]]:
    issues: Counter[tuple[str, str, str]] = Counter()
    recommendations: dict[tuple[str, str, str], str] = {}
    for resource in _flatten_accessibility_resources(report).values():
        issue_type = resource.analysisType or resource.type
        for check in resource.checks:
            if check.status not in {"FAIL", "ERROR", "WARNING"}:
                continue
            key = (str(issue_type), check.checkTitle, check.recommendation)
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


def _flatten_accessibility_resources(report: AccessibilityReport) -> dict[str, Any]:
    resources: dict[str, Any] = {}
    for module in report.modules:
        for resource in module.resources:
            resources[resource.resourceId] = resource
    return resources


def _module_title(core: Any) -> str:
    if core.modulePath:
        return " > ".join(core.modulePath)
    return core.sectionTitle or "Modulo general"


def _is_technical_ignored(item: Any) -> bool:
    payload = _as_mapping(item)
    return str(payload.get("analysis_category") or payload.get("analysisCategory") or "").upper() == "TECHNICAL_IGNORED"


def _as_mapping(item: Any) -> dict[str, Any]:
    if hasattr(item, "model_dump"):
        payload = item.model_dump(mode="python")
        return payload if isinstance(payload, dict) else {}
    return item if isinstance(item, dict) else {}
