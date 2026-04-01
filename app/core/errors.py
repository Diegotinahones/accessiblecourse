from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from fastapi import Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


@dataclass(slots=True)
class AppError(Exception):
    code: str
    message: str
    status_code: int = status.HTTP_400_BAD_REQUEST
    details: Any | None = None
    job_id: str | None = None


def build_problem_response(
    *,
    request: Request,
    status_code: int,
    code: str,
    message: str,
    details: Any | None = None,
    job_id: str | None = None,
) -> JSONResponse:
    payload: dict[str, Any] = {
        "type": "about:blank",
        "title": message,
        "status": status_code,
        "code": code,
        "message": message,
        "details": details,
        "jobId": job_id,
        "path": request.url.path,
    }
    if isinstance(details, dict):
        for key, value in details.items():
            payload.setdefault(key, value)
    return JSONResponse(
        status_code=status_code,
        content=payload,
        media_type="application/problem+json",
    )


async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    return build_problem_response(
        request=request,
        status_code=exc.status_code,
        code=exc.code,
        message=exc.message,
        details=exc.details,
        job_id=exc.job_id,
    )


async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    return build_problem_response(
        request=request,
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        code="validation_error",
        message="La solicitud no cumple el contrato esperado.",
        details=exc.errors(),
    )


async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
    return build_problem_response(
        request=request,
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        code="internal_error",
        message="Ha ocurrido un error interno.",
        details={"exception": exc.__class__.__name__},
    )
