from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.models import ChecklistValue, ResourceHealthStatus, ResourceType, ReviewSessionStatus, ReviewState


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True, use_enum_values=True)


class JobCreatedResponse(StrictModel):
    job_id: str = Field(alias="jobId")


class JobLifecycleStatus(str, Enum):
    CREATED = "created"
    PROCESSING = "processing"
    DONE = "done"
    ERROR = "error"


class JobStatusResponse(StrictModel):
    job_id: str = Field(alias="jobId")
    status: str
    progress: int
    message: str | None = None
    error_detail: str | None = Field(default=None, alias="errorDetail")


class HealthResponse(StrictModel):
    status: str
    version: str
    time: datetime


class ReviewSessionRead(StrictModel):
    job_id: str = Field(alias="jobId")
    status: ReviewSessionStatus
    started_at: datetime | None = Field(default=None, alias="startedAt")
    updated_at: datetime = Field(alias="updatedAt")


class ResourceListItemRead(StrictModel):
    id: str
    job_id: str = Field(alias="jobId")
    title: str
    type: ResourceType
    origin: str | None = None
    url: str | None = None
    path: str | None = None
    course_path: str | None = Field(default=None, alias="coursePath")
    status: ResourceHealthStatus
    notes: str | None = None
    review_state: ReviewState = Field(alias="reviewState")
    fail_count: int = Field(alias="failCount")
    updated_at: datetime = Field(alias="updatedAt")


class ResourceListResponse(StrictModel):
    job_id: str = Field(alias="jobId")
    resources: list[ResourceListItemRead]
    review_session: ReviewSessionRead = Field(alias="reviewSession")


class ChecklistTemplateItemRead(StrictModel):
    item_key: str = Field(alias="itemKey")
    label: str
    description: str | None = None
    recommendation: str | None = None


class ChecklistTemplateRead(StrictModel):
    template_id: str = Field(alias="templateId")
    resource_type: ResourceType = Field(alias="resourceType")
    items: list[ChecklistTemplateItemRead]


class ChecklistTemplatesResponse(StrictModel):
    templates: dict[ResourceType, ChecklistTemplateRead]


class ChecklistItemRead(StrictModel):
    item_key: str = Field(alias="itemKey")
    label: str
    description: str | None = None
    recommendation: str | None = None
    value: ChecklistValue
    comment: str | None = None


class ChecklistDetailRead(StrictModel):
    template_id: str = Field(alias="templateId")
    resource_type: ResourceType = Field(alias="resourceType")
    items: list[ChecklistItemRead]


class ChecklistDetailResponse(StrictModel):
    resource: ResourceListItemRead
    checklist: ChecklistDetailRead
    review_session: ReviewSessionRead = Field(alias="reviewSession")


class ChecklistResponseInput(StrictModel):
    item_key: str = Field(alias="itemKey")
    value: ChecklistValue
    comment: str | None = None


class ChecklistSaveRequest(StrictModel):
    responses: list[ChecklistResponseInput]


class ChecklistSaveResult(StrictModel):
    resource_id: str = Field(alias="resourceId")
    review_state: ReviewState = Field(alias="reviewState")
    fail_count: int = Field(alias="failCount")
    updated_at: datetime = Field(alias="updatedAt")


class ChecklistDecision(str, Enum):
    PENDING = "pending"
    PASS = "pass"
    FAIL = "fail"


class ChecklistStateResponse(StrictModel):
    job_id: str = Field(alias="jobId")
    state: dict[str, dict[str, ChecklistDecision]]


class ChecklistUpdateRequest(StrictModel):
    items: dict[str, ChecklistDecision] = Field(default_factory=dict)


class ReviewFailItemRead(StrictModel):
    item_key: str = Field(alias="itemKey")
    label: str
    recommendation: str | None = None
    comment: str | None = None


class ReviewFailResourceRead(StrictModel):
    resource_id: str = Field(alias="resourceId")
    title: str
    resource_type: ResourceType = Field(alias="resourceType")
    review_state: ReviewState = Field(alias="reviewState")
    fail_count: int = Field(alias="failCount")
    recommendations: list[ReviewFailItemRead]


class ReviewSummaryRead(StrictModel):
    job_id: str = Field(alias="jobId")
    total_resources: int = Field(alias="totalResources")
    total_fail_items: int = Field(alias="totalFailItems")
    last_updated: datetime = Field(alias="lastUpdated")
    review_session: ReviewSessionRead = Field(alias="reviewSession")
    resources: list[ReviewFailResourceRead]


class ResourceResponse(StrictModel):
    id: str
    title: str
    type: ResourceType
    origin: str | None = None
    status: ResourceHealthStatus
    href: str | None = None


class ReportDownloads(StrictModel):
    pdf_url: str = Field(alias="pdfUrl")
    docx_url: str = Field(alias="docxUrl")


class ReportFailure(StrictModel):
    item_id: str = Field(alias="itemId")
    label: str
    recommendation: str


class ReportGroup(StrictModel):
    resource: ResourceResponse
    failures: list[ReportFailure]


class GeneratedReportResponse(StrictModel):
    job_id: str = Field(alias="jobId")
    resource_count: int = Field(alias="resourceCount")
    failed_item_count: int = Field(alias="failedItemCount")
    groups: list[ReportGroup]
    generated_at: datetime = Field(alias="generatedAt")
    downloads: ReportDownloads


class ProblemDetails(StrictModel):
    model_config = ConfigDict(extra="allow")

    type: str = "about:blank"
    title: str
    status: int
    code: str
    message: str
    details: Any | None = None
    job_id: str | None = Field(default=None, alias="jobId")
    path: str
