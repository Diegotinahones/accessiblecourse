from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.models.entities import (
    ChecklistValue as ReviewChecklistValue,
)
from app.models.entities import (
    ResourceAccessStatus as ReviewResourceAccessStatus,
)
from app.models.entities import (
    ResourceHealthStatus as ReviewResourceHealthStatus,
)
from app.models.entities import (
    ResourceType as ReviewResourceType,
)
from app.models.entities import (
    ReviewSessionStatus as ReviewSessionStatusEnum,
)
from app.models.entities import (
    ReviewState as ReviewStateEnum,
)
from app.services.resource_core import ResourceCore, ResourceContentResult


class JobLifecycleStatus(str, Enum):
    CREATED = "created"
    PROCESSING = "processing"
    DONE = "done"
    ERROR = "error"


class JobPhase(str, Enum):
    UPLOAD = "UPLOAD"
    INVENTORY = "INVENTORY"
    ACCESS_SCAN = "ACCESS_SCAN"
    HTML_ACCESSIBILITY_SCAN = "HTML_ACCESSIBILITY_SCAN"
    PDF_ACCESSIBILITY_SCAN = "PDF_ACCESSIBILITY_SCAN"
    DONE = "DONE"
    ERROR = "ERROR"


class ResourceType(str, Enum):
    PDF = "PDF"
    WEB = "Web"
    VIDEO = "Video"
    NOTEBOOK = "Notebook"
    OTHER = "Other"


class ResourceOrigin(str, Enum):
    INTERNO = "interno"
    EXTERNO = "externo"


class ResourceState(str, Enum):
    OK = "OK"
    WARNING = "AVISO"
    ERROR = "ERROR"


class ChecklistDecision(str, Enum):
    PENDING = "pending"
    PASS = "pass"
    FAIL = "fail"


class AnalysisCategory(str, Enum):
    MAIN_ANALYZABLE = "MAIN_ANALYZABLE"
    NON_ANALYZABLE_EXTERNAL = "NON_ANALYZABLE_EXTERNAL"
    TECHNICAL_IGNORED = "TECHNICAL_IGNORED"


class ChecklistItem(BaseModel):
    id: str
    label: str
    recommendation: str


class ResourceResponse(BaseModel):
    id: str
    title: str
    type: ResourceType
    origin: ResourceOrigin
    status: ResourceState
    href: str | None = None


class JobCreatedResponse(BaseModel):
    jobId: str


class JobStatusResponse(BaseModel):
    jobId: str
    status: JobLifecycleStatus
    phase: JobPhase = JobPhase.UPLOAD
    progress: int
    message: str
    currentStep: int
    totalSteps: int
    errorCode: str | None = None


class ChecklistStateResponse(BaseModel):
    jobId: str
    state: dict[str, dict[str, ChecklistDecision]]


class ChecklistUpdateRequest(BaseModel):
    items: dict[str, ChecklistDecision] = Field(default_factory=dict)


class ReportFailure(BaseModel):
    itemId: str
    label: str
    recommendation: str


class ReportGroup(BaseModel):
    resource: ResourceResponse
    failures: list[ReportFailure]


class ReportDownloads(BaseModel):
    pdfUrl: str
    docxUrl: str


class GeneratedReportResponse(BaseModel):
    jobId: str
    resourceCount: int
    failedItemCount: int
    groups: list[ReportGroup]
    generatedAt: datetime
    downloads: ReportDownloads


class HealthResponse(BaseModel):
    status: str
    version: str
    time: datetime


class ProblemDetails(BaseModel):
    model_config = ConfigDict(extra="allow")

    type: str = "about:blank"
    title: str
    status: int
    code: str
    message: str
    details: Any | None = None
    jobId: str | None = None
    path: str


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class OnlineCourseRead(StrictModel):
    id: str
    name: str
    term: str | None = None
    start_at: datetime | None = None
    end_at: datetime | None = None


class OnlineJobCreateRequest(StrictModel):
    courseId: str
    courseName: str | None = None


class ReviewSessionRead(StrictModel):
    jobId: str
    status: ReviewSessionStatusEnum
    startedAt: datetime | None = None
    updatedAt: datetime


class ResourceListItemRead(StrictModel):
    id: str
    jobId: str
    title: str
    type: ReviewResourceType
    origin: str | None = None
    analysisCategory: AnalysisCategory = AnalysisCategory.MAIN_ANALYZABLE
    url: str | None = None
    sourceUrl: str | None = None
    downloadUrl: str | None = None
    path: str | None = None
    htmlPath: str | None = None
    localPath: str | None = None
    filePath: str | None = None
    coursePath: str | None = None
    modulePath: str | None = None
    moduleTitle: str | None = None
    sectionTitle: str | None = None
    sectionKey: str | None = None
    sectionType: str | None = None
    itemPath: str | None = None
    status: ReviewResourceHealthStatus
    urlStatus: str | None = None
    finalUrl: str | None = None
    checkedAt: datetime | None = None
    canAccess: bool = False
    accessStatus: ReviewResourceAccessStatus = ReviewResourceAccessStatus.NO_ACCEDE
    httpStatus: int | None = None
    accessStatusCode: int | None = None
    canDownload: bool = False
    downloadStatus: str | None = None
    downloadStatusCode: int | None = None
    contentAvailable: bool = False
    discoveredChildrenCount: int = 0
    parentResourceId: str | None = None
    parentId: str | None = None
    discovered: bool = False
    accessNote: str | None = None
    errorMessage: str | None = None
    reasonCode: str | None = None
    reasonDetail: str | None = None
    notes: str | None = None
    reviewState: ReviewStateEnum
    failCount: int
    updatedAt: datetime
    core: ResourceCore


class ResourceContentRead(ResourceContentResult):
    pass


class ResourceContentCheckRead(StrictModel):
    ok: bool
    resourceId: str
    title: str
    type: str
    origin: str | None = None
    contentKind: str
    contentAvailable: bool = False
    downloadable: bool = False
    mimeType: str | None = None
    filename: str | None = None
    errorCode: str | None = None
    errorDetail: str | None = None


class AccessSummaryResourceRead(StrictModel):
    id: str
    title: str
    type: str
    accessStatus: ReviewResourceAccessStatus
    canAccess: bool
    canDownload: bool
    downloadStatus: str | None = None
    accessStatusCode: int | None = None
    downloadStatusCode: int | None = None
    discovered: bool = False
    accessNote: str | None = None
    badge: dict[str, str]


class AccessSummaryGroupRead(StrictModel):
    modulePath: str
    total: int
    accessible: int
    downloadable: int
    downloadableAccessible: int = 0
    ok_count: int = 0
    no_accede_count: int = 0
    requires_interaction_count: int = 0
    requires_sso_count: int = 0
    requiere_interaccion_count: int = 0
    requiere_sso_count: int = 0
    downloadables_total: int = 0
    downloadables_ok: int = 0
    byStatus: dict[str, int]
    resources: list[AccessSummaryResourceRead] = Field(default_factory=list)


class AccessSummaryRead(StrictModel):
    jobId: str
    status: str
    progress: int
    total: int
    totalAnalizables: int | None = None
    accessible: int
    downloadable: int
    downloadableAccessible: int = 0
    ok_count: int = 0
    no_accede_count: int = 0
    requires_interaction_count: int = 0
    requires_sso_count: int = 0
    requiere_interaccion_count: int = 0
    requiere_sso_count: int = 0
    downloadables_total: int = 0
    downloadables_ok: int = 0
    byStatus: dict[str, int]
    groups: list[AccessSummaryGroupRead] = Field(default_factory=list)
    noAnalizablesExternos: int = 0
    tecnicosIgnorados: int = 0
    globalUnplacedCount: int = 0
    noAccessCount: int = 0
    noAccessByReason: dict[str, int] = Field(default_factory=dict)
    discovered: int = 0
    deepScan: dict[str, Any] | None = None


class AccessModuleRead(StrictModel):
    modulePath: str
    total: int
    accessible: int
    downloadable: int
    downloadableAccessible: int = 0
    ok_count: int = 0
    no_accede_count: int = 0
    requires_interaction_count: int = 0
    requires_sso_count: int = 0
    requiere_interaccion_count: int = 0
    requiere_sso_count: int = 0
    downloadables_total: int = 0
    downloadables_ok: int = 0
    byStatus: dict[str, int]
    resources: list[ResourceListItemRead] = Field(default_factory=list)


class JobAccessRead(StrictModel):
    jobId: str
    status: str
    phase: JobPhase
    progress: int
    summary: AccessSummaryRead
    modules: list[AccessModuleRead] = Field(default_factory=list)
    nonAnalyzableExternalResources: list["AuxiliaryResourceRead"] = Field(default_factory=list)


class AccessibilityCheckRead(StrictModel):
    checkId: str
    checkTitle: str
    status: Literal["PASS", "FAIL", "WARNING", "NOT_APPLICABLE", "ERROR"]
    evidence: str
    recommendation: str
    wcagHint: str | None = None


class AccessibilityResourceRead(StrictModel):
    resourceId: str
    title: str
    type: str
    analysisType: Literal["HTML", "PDF"] | None = None
    accessStatus: str
    checks: list[AccessibilityCheckRead] = Field(default_factory=list)


class AccessibilityModuleRead(StrictModel):
    title: str
    resources: list[AccessibilityResourceRead] = Field(default_factory=list)


class AccessibilityTypeSummaryRead(StrictModel):
    resourcesTotal: int = 0
    resourcesAnalyzed: int = 0
    passCount: int = 0
    failCount: int = 0
    warningCount: int = 0
    notApplicableCount: int = 0
    errorCount: int = 0


class AccessibilitySummaryRead(StrictModel):
    htmlResourcesTotal: int = 0
    htmlResourcesAnalyzed: int = 0
    pdfResourcesTotal: int = 0
    pdfResourcesAnalyzed: int = 0
    passCount: int = 0
    failCount: int = 0
    warningCount: int = 0
    notApplicableCount: int = 0
    errorCount: int = 0
    byType: dict[str, AccessibilityTypeSummaryRead] = Field(default_factory=dict)


class AccessibilityReportRead(StrictModel):
    jobId: str
    generatedAt: datetime | None = None
    summary: AccessibilitySummaryRead
    modules: list[AccessibilityModuleRead] = Field(default_factory=list)
    resources: list[AccessibilityResourceRead] = Field(default_factory=list)


class AuxiliaryResourceRead(StrictModel):
    id: str
    title: str
    type: str
    origin: str | None = None
    analysisCategory: AnalysisCategory
    source: str | None = None
    url: str | None = None
    path: str | None = None
    htmlPath: str | None = None
    coursePath: str | None = None
    modulePath: str | None = None
    moduleTitle: str | None = None
    sectionTitle: str | None = None
    sectionKey: str | None = None
    sectionType: str | None = None
    itemPath: str | None = None
    status: str | None = None
    accessStatus: str | None = None
    finalUrl: str | None = None
    httpStatus: int | None = None
    canAccess: bool = False
    canDownload: bool = False
    contentAvailable: bool = False
    accessNote: str | None = None
    errorMessage: str | None = None
    parentId: str | None = None
    reasonCode: str | None = None
    reasonDetail: str | None = None
    notes: str | None = None


class ResourceListPayload(StrictModel):
    jobId: str
    resources: list[ResourceListItemRead]
    totalAnalizables: int = 0
    noAnalizablesExternos: int = 0
    tecnicosIgnorados: int = 0
    globalUnplacedCount: int = 0
    noAccessCount: int = 0
    noAccessByReason: dict[str, int] = Field(default_factory=dict)
    nonAnalyzableExternalResources: list[AuxiliaryResourceRead] = Field(default_factory=list)
    reviewSession: ReviewSessionRead
    structure: "CourseStructureRead"


class CourseStructureNodeRead(StrictModel):
    nodeId: str
    identifier: str | None = None
    title: str
    resourceId: str | None = None
    children: list["CourseStructureNodeRead"] = Field(default_factory=list)


class CourseStructureOrganizationRead(StrictModel):
    nodeId: str
    identifier: str | None = None
    title: str
    children: list[CourseStructureNodeRead] = Field(default_factory=list)


class CourseStructureRead(StrictModel):
    title: str
    organizations: list[CourseStructureOrganizationRead] = Field(default_factory=list)
    unplacedResourceIds: list[str] = Field(default_factory=list)


class ChecklistTemplateItemRead(StrictModel):
    itemKey: str
    label: str
    description: str | None = None
    recommendation: str | None = None


class ChecklistTemplateRead(StrictModel):
    templateId: str
    resourceType: ReviewResourceType
    items: list[ChecklistTemplateItemRead]


class ChecklistItemRead(StrictModel):
    itemKey: str
    label: str
    description: str | None = None
    recommendation: str | None = None
    value: ReviewChecklistValue
    comment: str | None = None


class ChecklistDetailRead(StrictModel):
    templateId: str
    resourceType: ReviewResourceType
    items: list[ChecklistItemRead]


class ChecklistTemplatesResponse(StrictModel):
    templates: dict[ReviewResourceType, ChecklistTemplateRead]


class ResourceDetailPayload(StrictModel):
    resource: ResourceListItemRead
    checklist: ChecklistDetailRead
    reviewSession: ReviewSessionRead


class ChecklistResponseInput(StrictModel):
    itemKey: str
    value: ReviewChecklistValue
    comment: str | None = None


class ChecklistSaveRequest(StrictModel):
    responses: list[ChecklistResponseInput]


class ChecklistSaveResult(StrictModel):
    resourceId: str
    reviewState: ReviewStateEnum
    failCount: int
    updatedAt: datetime


class ReviewFailItemRead(StrictModel):
    itemKey: str
    label: str
    recommendation: str | None = None
    comment: str | None = None


class ReviewFailResourceRead(StrictModel):
    resourceId: str
    title: str
    resourceType: ReviewResourceType
    reviewState: ReviewStateEnum
    failCount: int
    recommendations: list[ReviewFailItemRead]


class ReviewSummaryPayload(StrictModel):
    jobId: str
    totalResources: int
    totalAnalizables: int | None = None
    totalFailItems: int
    accessibleResources: int = 0
    downloadableResources: int = 0
    noAnalizablesExternos: int = 0
    tecnicosIgnorados: int = 0
    lastUpdated: datetime
    reviewSession: ReviewSessionRead
    resources: list[ReviewFailResourceRead]


class ReportPayload(StrictModel):
    jobId: str
    generatedAt: datetime
    summary: ReviewSummaryPayload


class ReportGenerateRequest(StrictModel):
    includePending: bool = True
    onlyFails: bool = False


class ReportFilesRead(StrictModel):
    pdfUrl: str
    docxUrl: str
    jsonUrl: str


class ReportStatsRead(StrictModel):
    resources: int
    fails: int
    pending: int


class ReportMetaRead(StrictModel):
    reportId: str
    createdAt: datetime
    courseTitle: str | None = None
    jobId: str
    includePending: bool
    onlyFails: bool
    systemVersion: str


class ReportModeRead(StrictModel):
    key: Literal["ONLINE_CANVAS", "OFFLINE_IMSCC"]
    label: str


class ReportAccessSummaryRead(StrictModel):
    resourcesDetected: int
    resourcesAccessed: int
    downloadable: int
    noAccessible: int
    requiresSSO: int
    requiresInteraction: int
    globalUnplaced: int = 0
    noAnalyzableExternal: int = 0
    technicalIgnored: int = 0


class ReportHtmlAccessibilitySummaryRead(StrictModel):
    resourcesDetected: int
    resourcesAnalyzed: int
    passCount: int
    failCount: int
    warningCount: int
    notApplicableCount: int
    errorCount: int


class ReportPdfAccessibilitySummaryRead(ReportHtmlAccessibilitySummaryRead):
    pass


class ReportAutomaticAccessibilitySummaryRead(StrictModel):
    htmlResourcesDetected: int
    htmlResourcesAnalyzed: int
    pdfResourcesDetected: int
    pdfResourcesAnalyzed: int
    passCount: int
    failCount: int
    warningCount: int
    notApplicableCount: int
    errorCount: int


class ReportIssueSummaryRead(StrictModel):
    resourceType: Literal["HTML", "PDF"]
    checkId: str
    checkTitle: str
    status: Literal["FAIL", "WARNING"]
    resourceCount: int
    resources: list[str]
    recommendation: str


class ReportKeyIssueRead(StrictModel):
    coursePath: str
    moduleTitle: str | None = None
    resourceId: str
    resourceTitle: str
    resourceType: Literal["HTML", "PDF"]
    checkId: str
    checkTitle: str
    status: Literal["FAIL", "WARNING"]
    evidence: str
    recommendation: str


class ReportHtmlCheckRead(StrictModel):
    checkId: str
    checkTitle: str
    status: Literal["PASS", "FAIL", "WARNING", "NOT_APPLICABLE", "ERROR"]
    evidence: str
    recommendation: str


class ReportHtmlResourceRead(StrictModel):
    resourceId: str
    title: str
    coursePath: str
    moduleTitle: str | None = None
    accessStatus: str
    overallStatus: Literal["PASS", "FAIL", "WARNING", "ERROR"]
    summarized: bool = False
    checks: list[ReportHtmlCheckRead]


class ReportPdfCheckRead(ReportHtmlCheckRead):
    pass


class ReportPdfResourceRead(StrictModel):
    resourceId: str
    title: str
    coursePath: str
    moduleTitle: str | None = None
    accessStatus: str
    overallStatus: Literal["PASS", "FAIL", "WARNING", "ERROR"]
    summarized: bool = False
    checks: list[ReportPdfCheckRead]


class ReportSkippedResourceRead(StrictModel):
    resourceId: str
    title: str
    coursePath: str
    moduleTitle: str | None = None
    type: str
    origin: str | None = None
    accessStatus: str
    reason: str
    explanation: str


class ReportTopResourceRead(StrictModel):
    resourceId: str
    title: str
    coursePath: str
    failCount: int


class ReportSummaryRead(StrictModel):
    resources: int
    fails: int
    pending: int
    topResources: list[ReportTopResourceRead]
    recommendations: list[str]


class ReportIssueRead(StrictModel):
    itemKey: str
    label: str
    description: str
    recommendation: str | None = None
    severity: Literal["HIGH", "MED", "LOW"]
    status: Literal["FAIL", "PENDING"]
    comment: str | None = None


class ReportResourceRead(StrictModel):
    resourceId: str
    title: str
    type: str
    origin: str
    status: str
    source: str | None = None
    coursePath: str
    stats: ReportStatsRead
    fails: list[ReportIssueRead]
    pending: list[ReportIssueRead]


class ReportRouteRead(StrictModel):
    coursePath: str
    stats: ReportStatsRead
    resources: list[ReportResourceRead]


class ReportAppendixRead(StrictModel):
    statusDefinitions: dict[str, str]
    createdAt: datetime
    systemVersion: str


class JobReportRead(StrictModel):
    reportId: str
    createdAt: datetime
    files: ReportFilesRead
    stats: ReportStatsRead
    meta: ReportMetaRead
    mode: ReportModeRead
    accessSummary: ReportAccessSummaryRead
    automaticAccessibilitySummary: ReportAutomaticAccessibilitySummaryRead
    htmlAccessibilitySummary: ReportHtmlAccessibilitySummaryRead
    pdfAccessibilitySummary: ReportPdfAccessibilitySummaryRead
    issueSummary: list[ReportIssueSummaryRead]
    keyIssues: list[ReportKeyIssueRead]
    htmlResources: list[ReportHtmlResourceRead]
    pdfResources: list[ReportPdfResourceRead]
    notAutomaticallyAnalyzable: list[ReportSkippedResourceRead]
    summary: ReportSummaryRead
    routes: list[ReportRouteRead]
    resources: list[ReportResourceRead]
    appendix: ReportAppendixRead


CourseStructureNodeRead.model_rebuild()
CourseStructureOrganizationRead.model_rebuild()
CourseStructureRead.model_rebuild()
ResourceListPayload.model_rebuild()
