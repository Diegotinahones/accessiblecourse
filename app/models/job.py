from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class JobStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    ERROR = "error"


@dataclass(slots=True)
class Job:
    id: str
    filename: str
    archive_path: str
    status: str = JobStatus.PENDING.value
    progress: int = 0
    message: str = "Pendiente de procesamiento."
    error_detail: str | None = None
    resources_count: int = 0
    structure_available: bool = False
    manifest_path: str | None = None
    created_at: str = ""
    updated_at: str = ""

    def __post_init__(self) -> None:
        now = datetime.now(timezone.utc).isoformat()
        if not self.created_at:
            self.created_at = now
        if not self.updated_at:
            self.updated_at = now

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "Job":
        return cls(**payload)
