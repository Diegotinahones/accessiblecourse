from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any
from urllib.parse import urljoin

import httpx

from app.core.config import Settings

logger = logging.getLogger("accessiblecourse.canvas_api")


@dataclass(slots=True)
class CanvasAPIError(Exception):
    message: str
    status: int | None = None
    detail: str | None = None
    method: str | None = None
    url: str | None = None

    def as_debug_payload(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "detail": self.detail or self.message,
            "method": self.method,
            "url": self.url,
        }


class CanvasAPIClient:
    def __init__(
        self,
        settings: Settings,
        *,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        if not settings.canvas_base_url:
            raise CanvasAPIError("CANVAS_BASE_URL no está configurado.")
        if not settings.canvas_token:
            raise CanvasAPIError("CANVAS_TOKEN no está configurado.")

        self.base_url = settings.canvas_base_url.rstrip("/")
        self.api_prefix = _normalize_api_prefix(settings.canvas_api_prefix)
        self.token = settings.canvas_token
        self.timeout_seconds = settings.canvas_timeout_seconds
        self.transport = transport

    def get_json(self, path: str, *, params: dict[str, Any] | None = None) -> Any:
        payload, _ = self.get_json_with_response(path, params=params)
        return payload

    def get_json_with_response(
        self,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        absolute_url: bool = False,
    ) -> tuple[Any, httpx.Response]:
        method = "GET"
        url = path if absolute_url else self.build_url(path)
        try:
            with httpx.Client(
                timeout=httpx.Timeout(self.timeout_seconds),
                follow_redirects=True,
                transport=self.transport,
            ) as client:
                response = client.request(method, url, headers=self._headers(), params=params)
        except httpx.TimeoutException as exc:
            raise CanvasAPIError(
                "Canvas API timeout.",
                status=None,
                detail=str(exc) or "timeout",
                method=method,
                url=url,
            ) from exc
        except httpx.HTTPError as exc:
            raise CanvasAPIError(
                "No se pudo conectar con Canvas API.",
                status=None,
                detail=str(exc),
                method=method,
                url=url,
            ) from exc

        logger.info(
            "canvas_api_request",
            extra={
                "event": "canvas_api_request",
                "method": method,
                "url": str(response.url),
                "status_code": response.status_code,
            },
        )

        if response.status_code >= 400:
            raise CanvasAPIError(
                "Canvas API devolvió un error.",
                status=response.status_code,
                detail=response.text,
                method=method,
                url=str(response.url),
            )

        try:
            return response.json(), response
        except ValueError as exc:
            raise CanvasAPIError(
                "Canvas API no devolvió JSON válido.",
                status=response.status_code,
                detail=response.text,
                method=method,
                url=str(response.url),
            ) from exc

    def get_paginated_json(
        self,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        max_pages: int = 3,
    ) -> list[Any]:
        payload, response = self.get_json_with_response(path, params=params)
        items = _ensure_list(payload)

        pages_read = 1
        next_url = _next_link(response)
        while next_url and pages_read < max_pages:
            payload, response = self.get_json_with_response(next_url, absolute_url=True)
            items.extend(_ensure_list(payload))
            pages_read += 1
            next_url = _next_link(response)

        return items

    def build_url(self, path: str) -> str:
        normalized_path = path if path.startswith("/") else f"/{path}"
        return f"{self.base_url}{self.api_prefix}{normalized_path}"

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/json",
        }


def _normalize_api_prefix(value: str) -> str:
    cleaned = (value or "/api/v1").strip()
    if not cleaned.startswith("/"):
        cleaned = f"/{cleaned}"
    return cleaned.rstrip("/")


def _ensure_list(payload: Any) -> list[Any]:
    if isinstance(payload, list):
        return payload
    raise CanvasAPIError(
        "Canvas API devolvió un formato inesperado.",
        detail="Se esperaba una lista JSON.",
    )


def _next_link(response: httpx.Response) -> str | None:
    link = response.links.get("next")
    if not link:
        return None
    url = link.get("url")
    if not url:
        return None
    return urljoin(str(response.url), url)
