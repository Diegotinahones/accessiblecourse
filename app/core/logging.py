from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.core.config import Settings

job_id_context: ContextVar[str | None] = ContextVar("job_id", default=None)


class StructuredFormatter(logging.Formatter):
    def __init__(self, *, json_output: bool) -> None:
        super().__init__()
        self.json_output = json_output

    def format(self, record: logging.LogRecord) -> str:
        job_id = getattr(record, "job_id", None) or job_id_context.get()
        details = getattr(record, "details", None)
        payload: dict[str, Any] = {
            "time": datetime.now(tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "event": getattr(record, "event", None),
            "jobId": job_id,
        }
        if details is not None:
            payload["details"] = details

        if self.json_output:
            return json.dumps(payload, ensure_ascii=True, default=str)

        text = (
            f"{payload['time']} level={payload['level']} logger={payload['logger']} "
            f"event={payload.get('event') or '-'} jobId={payload.get('jobId') or '-'} "
            f"message={payload['message']}"
        )
        if details is not None:
            text = f"{text} details={json.dumps(details, ensure_ascii=True, default=str)}"
        return text


def configure_logging(settings: Settings) -> None:
    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    handler = logging.StreamHandler()
    handler.setFormatter(StructuredFormatter(json_output=settings.log_json))
    root_logger.addHandler(handler)
    root_logger.setLevel(settings.log_level.upper())

    logging.getLogger("uvicorn").handlers.clear()
    logging.getLogger("uvicorn.access").handlers.clear()


@contextmanager
def job_logging_context(job_id: str | None) -> Iterator[None]:
    token = job_id_context.set(job_id)
    try:
        yield
    finally:
        job_id_context.reset(token)


def append_job_log(log_path: Path, *, event: str, message: str, details: dict[str, Any] | None = None) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "time": datetime.now(tz=UTC).isoformat(),
        "event": event,
        "message": message,
        "details": details or {},
    }
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=True, default=str))
        handle.write("\n")
