from __future__ import annotations

import httpx

from app.services.url_check import URLCheckService


def test_url_check_marks_404_after_head_fallback_to_get() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.method)
        if request.method == "HEAD":
            return httpx.Response(405, request=request)
        return httpx.Response(404, request=request)

    service = URLCheckService(timeout_seconds=1, max_urls=10, transport=httpx.MockTransport(handler))
    results = service.check([{"id": "res-404", "url": "https://example.com/missing"}])

    result = results["res-404"]
    assert calls == ["HEAD", "GET"]
    assert result.checked is True
    assert result.broken_link is True
    assert result.reason == "404_not_found"
    assert result.status_code == 404
    assert result.url_status == "404"
    assert result.final_url == "https://example.com/missing"
    assert result.checked_at is not None
