from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, Column
from sqlmodel import Field, SQLModel


def utcnow() -> datetime:
    return datetime.now(tz=UTC)


class Job(SQLModel, table=True):
    id: str = Field(primary_key=True, index=True)
    original_filename: str
    stored_filename: str
    size_bytes: int
    storage_dir: str
    status: str = Field(default='created', index=True)
    progress: int = Field(default=0)
    current_step: int = Field(default=1)
    total_steps: int = Field(default=4)
    message: str = Field(default='Analisis en cola.')
    error_code: str | None = Field(default=None)
    error_message: str | None = Field(default=None)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
    finished_at: datetime | None = Field(default=None)


class ResourceRecord(SQLModel, table=True):
    id: str = Field(primary_key=True, index=True)
    job_id: str = Field(index=True, foreign_key='job.id')
    title: str
    type: str
    origin: str
    status: str
    href: str | None = None
    extracted_path: str | None = None


class ChecklistEntry(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    job_id: str = Field(index=True, foreign_key='job.id')
    resource_id: str = Field(index=True, foreign_key='resourcerecord.id')
    item_id: str = Field(index=True)
    label: str
    recommendation: str
    decision: str = Field(default='pending')


class JobEvent(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    job_id: str = Field(index=True, foreign_key='job.id')
    event: str = Field(index=True)
    message: str
    progress: int | None = None
    details: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON, nullable=True))
    created_at: datetime = Field(default_factory=utcnow, index=True)


class ReportRecord(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    job_id: str = Field(index=True, foreign_key='job.id', unique=True)
    resource_count: int
    failed_item_count: int
    generated_at: datetime = Field(default_factory=utcnow)
    pdf_path: str
    docx_path: str
    payload: dict[str, Any] = Field(sa_column=Column(JSON, nullable=False))
