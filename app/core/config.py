from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(slots=True)
class Settings:
    base_dir: Path = field(default_factory=lambda: Path(__file__).resolve().parents[2])
    environment: str = "development"
    data_dir: Path | None = None
    storage_root: Path | None = None
    db_url: str = "sqlite:///./data/app.db"
    database_url: str | None = None
    version: str = "0.6.0"
    app_name: str = "AccessibleCourse API"
    api_prefix: str = "/api"
    cors_origins: list[str] = field(
        default_factory=lambda: [
            "http://localhost:5173",
            "http://127.0.0.1:5173",
            "http://localhost:8080",
            "http://127.0.0.1:8080",
        ]
    )
    log_json: bool = False
    log_level: str = "INFO"
    report_brand_name: str = "AccessibleCourse"
    max_upload_bytes: int = 128 * 1024 * 1024
    max_upload_mb: int | None = None
    max_extracted_files: int = 5000
    max_extracted_bytes: int = 512 * 1024 * 1024
    max_extracted_mb: int | None = None
    jobs_rate_limit_per_minute: int = 30
    reports_rate_limit_per_minute: int = 30

    def __post_init__(self) -> None:
        self.base_dir = Path(self.base_dir).resolve()
        preferred_root = self.data_dir or self.storage_root
        self.data_dir = Path(preferred_root).resolve() if preferred_root else self.base_dir / "data"
        self.storage_root = self.data_dir
        if self.database_url:
            self.db_url = self.database_url
        self.database_url = self.db_url
        if self.max_upload_mb is not None:
            self.max_upload_bytes = self.max_upload_mb * 1024 * 1024
        else:
            self.max_upload_mb = self.max_upload_bytes // (1024 * 1024)
        if self.max_extracted_mb is not None:
            self.max_extracted_bytes = self.max_extracted_mb * 1024 * 1024
        else:
            self.max_extracted_mb = self.max_extracted_bytes // (1024 * 1024)


BASE_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = BASE_DIR / "data"
UPLOADS_DIR = DATA_DIR / "uploads"
JOBS_DIR = DATA_DIR / "jobs"
ALLOWED_ARCHIVE_EXTENSIONS = {".imscc", ".zip"}
MAX_ARCHIVE_MEMBERS = 5000
MAX_ARCHIVE_MEMBER_SIZE = 128 * 1024 * 1024
MAX_ARCHIVE_TOTAL_SIZE = 512 * 1024 * 1024


def get_settings() -> Settings:
    data_dir = os.getenv("ACCESSIBLE_COURSE_DATA_DIR")
    database_url = os.getenv("ACCESSIBLE_COURSE_DB_URL")
    return Settings(
        data_dir=Path(data_dir).expanduser().resolve() if data_dir else None,
        database_url=database_url,
    )


def ensure_runtime_directories(settings: Settings | None = None) -> Settings:
    resolved = settings or get_settings()
    os.environ["ACCESSIBLE_COURSE_DATA_DIR"] = str(resolved.data_dir)
    for path in (resolved.data_dir, resolved.data_dir / "jobs", resolved.data_dir / "uploads"):
        path.mkdir(parents=True, exist_ok=True)
    return resolved
