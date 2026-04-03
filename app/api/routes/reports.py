from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import FileResponse
from sqlmodel import Session

from app.api.deps import get_rate_limiter, get_session, get_settings
from app.core.config import Settings
from app.core.rate_limit import MemoryRateLimiter, get_client_ip
from app.schemas import GeneratedReportResponse
from app.services.reports import generate_report, get_report_file_info, load_report

router = APIRouter(prefix="/reports", tags=["reports"])


@router.post("/{job_id}", response_model=GeneratedReportResponse)
def create_report(
    job_id: str,
    request: Request,
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
    rate_limiter: MemoryRateLimiter = Depends(get_rate_limiter),
) -> GeneratedReportResponse:
    rate_limiter.hit(
        bucket="reports:create",
        key=get_client_ip(request),
        limit=settings.reports_rate_limit_per_minute,
    )
    return generate_report(session, settings, job_id)


@router.get("/{job_id}", response_model=GeneratedReportResponse)
def get_report(job_id: str, session: Session = Depends(get_session)) -> GeneratedReportResponse:
    return load_report(session, job_id)


@router.get("/{job_id}/download/{fmt}")
def download_report(
    job_id: str,
    fmt: str,
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> FileResponse:
    file_path, media_type, filename = get_report_file_info(session, settings, job_id, fmt)
    return FileResponse(
        path=file_path,
        media_type=media_type,
        filename=filename,
        headers={"Cache-Control": "no-store, max-age=0", "Pragma": "no-cache", "Expires": "0"},
    )
