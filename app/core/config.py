from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore", enable_decoding=False)

    app_name: str = "AccessibleCourse API"
    version: str = "0.6.0"
    api_prefix: str = "/api"
    environment: Literal["development", "test", "production"] = "development"
    database_url: str = "sqlite:///data/app.db"
    storage_root: Path = Path("data")
    cors_origins: list[str] = Field(
        default_factory=lambda: [
            "http://localhost:5173",
            "http://127.0.0.1:5173",
            "http://localhost:8080",
            "http://127.0.0.1:8080",
        ]
    )
    max_upload_mb: int = 200
    max_extracted_files: int = 2000
    max_extracted_mb: int = 1024
    log_level: str = "INFO"
    log_json: bool = False
    report_brand_name: str = "AccessibleCourse"
    jobs_rate_limit_per_minute: int = 12
    reports_rate_limit_per_minute: int = 30

    @field_validator("cors_origins", mode="before")
    @classmethod
    def validate_cors_origins(cls, value: object) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        raise ValueError("CORS_ORIGINS must be a comma-separated string or a list.")

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024

    @property
    def max_extracted_bytes(self) -> int:
        return self.max_extracted_mb * 1024 * 1024

    @property
    def data_dir(self) -> Path:
        return self.storage_root


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
