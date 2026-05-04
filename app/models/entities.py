from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from uuid import uuid4

from sqlalchemy import JSON, Column, Enum as SAEnum, String, Text, UniqueConstraint
from sqlmodel import Field, SQLModel


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def generate_id() -> str:
    return str(uuid4())


class ResourceType(str, Enum):
    WEB = "WEB"
    PDF = "PDF"
    VIDEO = "VIDEO"
    NOTEBOOK = "NOTEBOOK"
    IMAGE = "IMAGE"
    FILE = "FILE"
    OTHER = "OTHER"


class ResourceHealthStatus(str, Enum):
    OK = "OK"
    WARN = "WARN"
    ERROR = "ERROR"


class ResourceAccessStatus(str, Enum):
    OK = "OK"
    NO_ACCEDE = "NO_ACCEDE"
    REQUIERE_INTERACCION = "REQUIERE_INTERACCION"
    REQUIERE_SSO = "REQUIERE_SSO"
    NO_ANALIZABLE = "NO_ANALIZABLE"
    # Legacy values are kept so older persisted jobs remain readable.
    NOT_FOUND = "NOT_FOUND"
    FORBIDDEN = "FORBIDDEN"
    TIMEOUT = "TIMEOUT"
    ERROR = "ERROR"


class ReviewState(str, Enum):
    OK = "OK"
    IN_REVIEW = "IN_REVIEW"
    NEEDS_FIX = "NEEDS_FIX"


class ChecklistValue(str, Enum):
    PENDING = "PENDING"
    PASS = "PASS"
    FAIL = "FAIL"


class ReviewSessionStatus(str, Enum):
    NOT_STARTED = "NOT_STARTED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETE = "COMPLETE"


class Job(SQLModel, table=True):
    __tablename__ = "jobs"

    id: str = Field(primary_key=True)
    name: str | None = Field(default=None, index=True, max_length=255)
    created_at: datetime = Field(default_factory=utcnow, nullable=False)
    updated_at: datetime = Field(default_factory=utcnow, nullable=False)


class Resource(SQLModel, table=True):
    __tablename__ = "resources"

    id: str = Field(primary_key=True)
    job_id: str = Field(foreign_key="jobs.id", index=True)
    title: str = Field(max_length=500)
    type: ResourceType = Field(sa_column=Column(SAEnum(ResourceType), nullable=False))
    origin: str | None = Field(default=None, max_length=255)
    url: str | None = Field(default=None, max_length=2000)
    download_url: str | None = Field(default=None, max_length=2000)
    final_url: str | None = Field(default=None, max_length=2000)
    path: str | None = Field(default=None, max_length=2000)
    course_path: str | None = Field(default=None, max_length=2000)
    status: ResourceHealthStatus = Field(
        default=ResourceHealthStatus.OK,
        sa_column=Column(SAEnum(ResourceHealthStatus), nullable=False),
    )
    can_access: bool = Field(default=False, nullable=False)
    access_status: ResourceAccessStatus = Field(
        default=ResourceAccessStatus.NO_ACCEDE,
        sa_column=Column(SAEnum(ResourceAccessStatus), nullable=False),
    )
    http_status: int | None = Field(default=None, nullable=True)
    access_status_code: int | None = Field(default=None, nullable=True)
    can_download: bool = Field(default=False, nullable=False)
    download_status: str | None = Field(default=None, max_length=64)
    download_status_code: int | None = Field(default=None, nullable=True)
    discovered_children_count: int = Field(default=0, nullable=False)
    parent_resource_id: str | None = Field(default=None, max_length=255)
    discovered: bool = Field(default=False, nullable=False)
    reason_code: str | None = Field(default=None, max_length=64)
    reason_detail: str | None = Field(default=None, sa_column=Column(Text, nullable=True))
    content_available: bool = Field(default=False, nullable=False)
    access_note: str | None = Field(default=None, sa_column=Column(Text, nullable=True))
    error_message: str | None = Field(default=None, sa_column=Column(Text, nullable=True))
    notes: str | None = Field(default=None, sa_column=Column(Text, nullable=True))
    review_state: ReviewState = Field(
        default=ReviewState.IN_REVIEW,
        sa_column=Column(SAEnum(ReviewState), nullable=False),
    )
    created_at: datetime = Field(default_factory=utcnow, nullable=False)
    updated_at: datetime = Field(default_factory=utcnow, nullable=False)


class ChecklistTemplate(SQLModel, table=True):
    __tablename__ = "checklist_templates"

    __table_args__ = (UniqueConstraint("resource_type", name="uq_checklist_template_resource_type"),)

    id: str = Field(primary_key=True)
    resource_type: ResourceType = Field(sa_column=Column(SAEnum(ResourceType), nullable=False))
    created_at: datetime = Field(default_factory=utcnow, nullable=False)
    updated_at: datetime = Field(default_factory=utcnow, nullable=False)


class ChecklistItem(SQLModel, table=True):
    __tablename__ = "checklist_items"

    __table_args__ = (UniqueConstraint("template_id", "key", name="uq_checklist_item_template_key"),)

    id: str = Field(default_factory=generate_id, primary_key=True)
    template_id: str = Field(foreign_key="checklist_templates.id", index=True)
    key: str = Field(sa_column=Column(String(120), nullable=False))
    label: str = Field(max_length=255)
    description: str | None = Field(default=None, sa_column=Column(Text, nullable=True))
    recommendation: str | None = Field(default=None, sa_column=Column(Text, nullable=True))
    display_order: int = Field(default=0, nullable=False)
    created_at: datetime = Field(default_factory=utcnow, nullable=False)
    updated_at: datetime = Field(default_factory=utcnow, nullable=False)


class ChecklistResponse(SQLModel, table=True):
    __tablename__ = "checklist_responses"

    __table_args__ = (UniqueConstraint("job_id", "resource_id", "item_key", name="uq_checklist_response_item"),)

    id: str = Field(default_factory=generate_id, primary_key=True)
    job_id: str = Field(foreign_key="jobs.id", index=True)
    resource_id: str = Field(foreign_key="resources.id", index=True)
    item_key: str = Field(sa_column=Column(String(120), nullable=False))
    value: ChecklistValue = Field(
        default=ChecklistValue.PENDING,
        sa_column=Column(SAEnum(ChecklistValue), nullable=False),
    )
    comment: str | None = Field(default=None, sa_column=Column(Text, nullable=True))
    updated_at: datetime = Field(default_factory=utcnow, nullable=False)


class ReviewSummary(SQLModel, table=True):
    __tablename__ = "review_summaries"

    job_id: str = Field(primary_key=True, foreign_key="jobs.id")
    total_resources: int = Field(default=0, nullable=False)
    total_fail_items: int = Field(default=0, nullable=False)
    accessible_resources: int = Field(default=0, nullable=False)
    downloadable_resources: int = Field(default=0, nullable=False)
    last_updated: datetime = Field(default_factory=utcnow, nullable=False)


class ReviewSession(SQLModel, table=True):
    __tablename__ = "review_sessions"

    job_id: str = Field(primary_key=True, foreign_key="jobs.id")
    status: ReviewSessionStatus = Field(
        default=ReviewSessionStatus.NOT_STARTED,
        sa_column=Column(SAEnum(ReviewSessionStatus), nullable=False),
    )
    started_at: datetime | None = Field(default=None, nullable=True)
    updated_at: datetime = Field(default_factory=utcnow, nullable=False)


class JobEvent(SQLModel, table=True):
    __tablename__ = "job_events"

    id: str = Field(default_factory=generate_id, primary_key=True)
    job_id: str = Field(foreign_key="jobs.id", index=True)
    event: str = Field(max_length=120)
    message: str = Field(max_length=500)
    progress: int | None = Field(default=None)
    details: dict | None = Field(default=None, sa_column=Column(JSON, nullable=True))
    created_at: datetime = Field(default_factory=utcnow, nullable=False)


class ReportRecord(SQLModel, table=True):
    __tablename__ = "report_records"

    id: str = Field(default_factory=generate_id, primary_key=True)
    job_id: str = Field(foreign_key="jobs.id", index=True, unique=True)
    resource_count: int = Field(default=0)
    failed_item_count: int = Field(default=0)
    generated_at: datetime = Field(default_factory=utcnow)
    pdf_path: str | None = Field(default=None, max_length=2000)
    docx_path: str | None = Field(default=None, max_length=2000)
    payload: dict | None = Field(default=None, sa_column=Column(JSON, nullable=True))


ChecklistEntry = ChecklistResponse
ResourceRecord = Resource
