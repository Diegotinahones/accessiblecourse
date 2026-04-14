from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

import httpx

from app.services.canvas_client import CanvasCredentials


@dataclass(slots=True, frozen=True)
class UrlCheckResult:
    url: str
    checked: bool
    broken_link: bool
    reason: str | None = None
    status_code: int | None = None
    url_status: str | None = None
    final_url: str | None = None
    checked_at: datetime | None = None


class URLCheckService:
    def __init__(
        self,
        *,
        timeout_seconds: float = 5.0,
        max_urls: int = 200,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.timeout_seconds = timeout_seconds
        self.max_urls = max_urls
        self.transport = transport

    def check(
        self,
        resources: list[dict[str, Any]],
        *,
        credentials: CanvasCredentials | None = None,
    ) -> dict[str, UrlCheckResult]:
        urls_by_resource = {
            str(resource["id"]): str(resource.get("sourceUrl") or resource.get("url")).strip()
            for resource in resources
            if (resource.get("sourceUrl") or resource.get("url"))
            and str(resource.get("sourceUrl") or resource.get("url")).startswith(("http://", "https://"))
        }

        if not urls_by_resource:
            return {}

        checked_results: dict[str, UrlCheckResult] = {}
        for index, (resource_id, url) in enumerate(urls_by_resource.items()):
            if index >= self.max_urls:
                checked_results[resource_id] = UrlCheckResult(
                    url=url,
                    checked=False,
                    broken_link=False,
                    reason="limit_not_checked",
                )
                continue
            checked_results[resource_id] = self._check_url(url, credentials=credentials)

        return checked_results

    def _check_url(self, url: str, *, credentials: CanvasCredentials | None = None) -> UrlCheckResult:
        headers: dict[str, str] = {}
        if credentials and self._shares_canvas_host(url, credentials.base_url):
            headers.update(credentials.auth_headers())

        with httpx.Client(
            transport=self.transport,
            timeout=httpx.Timeout(self.timeout_seconds),
            follow_redirects=True,
        ) as client:
            response, method_error = self._request_with_head_fallback(client, url, headers=headers)
            checked_at = datetime.now(timezone.utc)

        if response is None:
            if isinstance(method_error, httpx.TimeoutException):
                return UrlCheckResult(
                    url=url,
                    checked=True,
                    broken_link=True,
                    reason="timeout",
                    url_status="timeout",
                    checked_at=checked_at,
                )
            return UrlCheckResult(
                url=url,
                checked=True,
                broken_link=False,
                reason="request_error",
                checked_at=checked_at,
            )

        status_code = response.status_code
        final_url = str(response.url)
        url_status = str(status_code)
        shared_canvas_host = credentials is not None and self._shares_canvas_host(url, credentials.base_url)

        if status_code in {401, 403} and shared_canvas_host:
            return UrlCheckResult(
                url=url,
                checked=True,
                broken_link=False,
                reason="canvas_auth_required",
                status_code=status_code,
                url_status=url_status,
                final_url=final_url,
                checked_at=checked_at,
            )

        if status_code == 404:
            return UrlCheckResult(
                url=url,
                checked=True,
                broken_link=True,
                reason="404_not_found",
                status_code=status_code,
                url_status=url_status,
                final_url=final_url,
                checked_at=checked_at,
            )

        return UrlCheckResult(
            url=url,
            checked=True,
            broken_link=status_code >= 400,
            status_code=status_code,
            url_status=url_status,
            final_url=final_url,
            checked_at=checked_at,
        )

    @staticmethod
    def _shares_canvas_host(url: str, base_url: str) -> bool:
        return urlparse(url).netloc.lower() == urlparse(base_url).netloc.lower()

    def _request_with_head_fallback(
        self,
        client: httpx.Client,
        url: str,
        *,
        headers: dict[str, str],
    ) -> tuple[httpx.Response | None, Exception | None]:
        response, error = self._request(client, "HEAD", url, headers=headers)
        if response is not None and response.status_code not in {405, 501}:
            return response, None

        return self._request(client, "GET", url, headers=headers)

    def _request(
        self,
        client: httpx.Client,
        method: str,
        url: str,
        *,
        headers: dict[str, str],
    ) -> tuple[httpx.Response | None, Exception | None]:
        try:
            with client.stream(method, url, headers=headers) as response:
                return response, None
        except (httpx.TimeoutException, httpx.HTTPError) as exc:
            return None, exc
