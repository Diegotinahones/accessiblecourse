from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

import httpx

from app.services.access_probe import (
    REASON_AUTH_REQUIRED,
    REASON_DNS_ERROR,
    REASON_FORBIDDEN,
    REASON_NETWORK_ERROR,
    REASON_NOT_FOUND,
    REASON_OK,
    REASON_SSL_ERROR,
    REASON_TIMEOUT,
    REASON_UNSUPPORTED,
    AccessProbe,
    AccessProbeResult,
)
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
    content_type: str | None = None
    content_disposition: str | None = None
    error_message: str | None = None
    redirected: bool = False
    redirect_location: str | None = None
    reason_code: str | None = None
    reason_detail: str | None = None
    downloadable_guess: bool = False


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
            checked_results[resource_id] = self.check_url(url, credentials=credentials)

        return checked_results

    def check_url(self, url: str, *, credentials: CanvasCredentials | None = None) -> UrlCheckResult:
        return self._check_url(url, credentials=credentials, follow_redirects=True)

    def check_url_no_redirects(self, url: str, *, credentials: CanvasCredentials | None = None) -> UrlCheckResult:
        return self._check_url(url, credentials=credentials, follow_redirects=False)

    def _check_url(
        self,
        url: str,
        *,
        credentials: CanvasCredentials | None = None,
        follow_redirects: bool,
    ) -> UrlCheckResult:
        headers: dict[str, str] = {}
        if credentials and self._shares_canvas_host(url, credentials.base_url):
            headers.update(credentials.auth_headers())

        probe = AccessProbe(
            timeout_seconds=self.timeout_seconds,
            transport=self.transport,
        )
        result = probe.probe(url, headers=headers, follow_redirects=follow_redirects)
        checked_at = datetime.now(timezone.utc)
        shared_canvas_host = credentials is not None and self._shares_canvas_host(url, credentials.base_url)
        return _url_check_from_probe_result(url, result, checked_at=checked_at, shared_canvas_host=shared_canvas_host)

    @staticmethod
    def _shares_canvas_host(url: str, base_url: str) -> bool:
        return urlparse(url).netloc.lower() == urlparse(base_url).netloc.lower()


def _url_check_from_probe_result(
    url: str,
    result: AccessProbeResult,
    *,
    checked_at: datetime,
    shared_canvas_host: bool,
) -> UrlCheckResult:
    reason = _legacy_reason(result, shared_canvas_host=shared_canvas_host)
    return UrlCheckResult(
        url=url,
        checked=True,
        broken_link=not result.ok,
        reason=reason,
        status_code=result.http_status,
        url_status=str(result.http_status) if result.http_status is not None else _url_status_for_reason(result),
        final_url=result.final_url,
        checked_at=checked_at,
        content_type=result.content_type,
        content_disposition=result.content_disposition,
        error_message=None if result.ok else result.reason_detail,
        redirected=result.redirected,
        redirect_location=result.redirect_location,
        reason_code=result.reason_code,
        reason_detail=result.reason_detail,
        downloadable_guess=result.downloadable_guess,
    )


def _legacy_reason(result: AccessProbeResult, *, shared_canvas_host: bool) -> str | None:
    if result.reason_code == REASON_OK:
        return "redirect" if result.redirected and result.http_status and 300 <= result.http_status < 400 else None
    if result.reason_code == REASON_NOT_FOUND:
        return "404_not_found"
    if result.reason_code == REASON_AUTH_REQUIRED:
        return "canvas_auth_required" if shared_canvas_host else "auth_required"
    if result.reason_code == REASON_FORBIDDEN:
        return "forbidden"
    if result.reason_code == REASON_TIMEOUT:
        return "timeout"
    if result.reason_code == REASON_DNS_ERROR:
        return "dns_error"
    if result.reason_code == REASON_SSL_ERROR:
        return "ssl_error"
    if result.reason_code == REASON_NETWORK_ERROR:
        return "network_error"
    if result.reason_code == REASON_UNSUPPORTED:
        return "unsupported"
    if result.http_status is not None and result.http_status >= 400:
        return f"http_{result.http_status}"
    return "unknown"


def _url_status_for_reason(result: AccessProbeResult) -> str | None:
    if result.reason_code == REASON_TIMEOUT:
        return "timeout"
    if result.reason_code in {REASON_DNS_ERROR, REASON_SSL_ERROR, REASON_NETWORK_ERROR}:
        return "error"
    return None
