from __future__ import annotations

import json
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.core.config import JOBS_DIR, UPLOADS_DIR, ensure_runtime_directories
from app.models.job import Job


class JobStore:
    def __init__(self, jobs_dir: Path = JOBS_DIR, uploads_dir: Path = UPLOADS_DIR) -> None:
        self.jobs_dir = jobs_dir
        self.uploads_dir = uploads_dir
        self._lock = threading.RLock()
        ensure_runtime_directories()

    def create_job(self, filename: str, archive_path: str = "") -> Job:
        job_id = uuid.uuid4().hex
        job = Job(id=job_id, filename=filename, archive_path=archive_path)
        self.job_dir(job_id).mkdir(parents=True, exist_ok=True)
        self._write_json(self._job_file(job_id), job.to_dict())
        return job

    def get_job(self, job_id: str) -> Job:
        return Job.from_dict(self._read_json(self._job_file(job_id)))

    def has_job(self, job_id: str) -> bool:
        return self._job_file(job_id).exists()

    def update_job(self, job_id: str, **changes: Any) -> Job:
        with self._lock:
            job = self.get_job(job_id)
            for key, value in changes.items():
                if hasattr(job, key):
                    setattr(job, key, value)
            job.updated_at = datetime.now(timezone.utc).isoformat()
            self._write_json(self._job_file(job_id), job.to_dict())
            return job

    def save_resources(self, job_id: str, resources: list[dict[str, Any]]) -> None:
        self._write_json(self.job_dir(job_id) / "resources.json", resources)

    def load_resources(self, job_id: str) -> list[dict[str, Any]]:
        path = self.job_dir(job_id) / "resources.json"
        if not path.exists():
            return []
        payload = self._read_json(path)
        return payload if isinstance(payload, list) else []

    def save_structure(self, job_id: str, structure: dict[str, Any]) -> None:
        self._write_json(self.job_dir(job_id) / "course_structure.json", structure)

    def load_structure(self, job_id: str) -> dict[str, Any] | None:
        path = self.job_dir(job_id) / "course_structure.json"
        if not path.exists():
            return None
        payload = self._read_json(path)
        return payload if isinstance(payload, dict) else None

    def append_log(self, job_id: str, *, event: str, message: str, details: dict[str, Any] | None = None) -> None:
        log_path = self.job_dir(job_id) / "job.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        entry = {
            "time": datetime.now(timezone.utc).isoformat(),
            "event": event,
            "message": message,
            "details": details or {},
        }
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, ensure_ascii=False))
            handle.write("\n")

    def upload_path(self, job_id: str, suffix: str) -> Path:
        normalized = suffix if suffix.startswith(".") else f".{suffix}"
        self.uploads_dir.mkdir(parents=True, exist_ok=True)
        return self.uploads_dir / f"{job_id}{normalized.lower()}"

    def job_dir(self, job_id: str) -> Path:
        return self.jobs_dir / job_id

    def _job_file(self, job_id: str) -> Path:
        return self.job_dir(job_id) / "job.json"

    def _read_json(self, path: Path) -> Any:
        if not path.exists():
            raise FileNotFoundError(f"No existe el job solicitado: {path}")
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)

    def _write_json(self, path: Path, payload: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = path.with_suffix(f"{path.suffix}.tmp")
        with temp_path.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
        temp_path.replace(path)
