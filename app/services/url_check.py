from __future__ import annotations

from dataclasses import dataclass
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

    def check(self, resources: list[dict[str, Any]], *, credentials: CanvasCredentials) -> dict[str, UrlCheckResult]:
        urls_by_resource = {
            str(resource["id"]): str(resource["url"]).strip()
            for resource in resources
            if resource.get("url") and str(resource["url"]).startswith(("http://", "https://"))
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

    def _check_url(self, url: str, *, credentials: CanvasCredentials) -> UrlCheckResult:
        headers: dict[str, str] = {}
        if self._shares_canvas_host(url, credentials.base_url):
            headers.update(credentials.auth_headers())

        with httpx.Client(
            transport=self.transport,
            timeout=httpx.Timeout(self.timeout_seconds),
            follow_redirects=True,
        ) as client:
            try:
                with client.stream("GET", url, headers=headers) as response:
                    status_code = response.status_code
            except httpx.TimeoutException:
                return UrlCheckResult(
                    url=url,
                    checked=True,
                    broken_link=True,
                    reason="timeout",
                )
            except httpx.HTTPError:
                return UrlCheckResult(
                    url=url,
                    checked=True,
                    broken_link=False,
                    reason="request_error",
                )

        if status_code == 404:
            return UrlCheckResult(
                url=url,
                checked=True,
                broken_link=True,
                reason="404_not_found",
                status_code=status_code,
            )

        if status_code in {401, 403} and self._shares_canvas_host(url, credentials.base_url):
            return UrlCheckResult(
                url=url,
                checked=True,
                broken_link=False,
                reason="canvas_auth_required",
                status_code=status_code,
            )

        return UrlCheckResult(
            url=url,
            checked=True,
            broken_link=False,
            status_code=status_code,
        )

    @staticmethod
    def _shares_canvas_host(url: str, base_url: str) -> bool:
        return urlparse(url).netloc.lower() == urlparse(base_url).netloc.lower()
