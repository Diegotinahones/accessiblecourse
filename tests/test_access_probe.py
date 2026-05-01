from __future__ import annotations

import httpx

from app.services.access_probe import (
    REASON_AUTH_REQUIRED,
    REASON_FORBIDDEN,
    REASON_NOT_FOUND,
    REASON_OK,
    REASON_TIMEOUT,
    AccessProbe,
)


def test_access_probe_marks_200_ok_with_downloadable_guess() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "application/pdf"},
            request=request,
        )

    probe = AccessProbe(timeout_seconds=1, transport=httpx.MockTransport(handler))
    result = probe.probe("https://example.com/guide.pdf")

    assert result.ok is True
    assert result.http_status == 200
    assert result.reason_code == REASON_OK
    assert result.final_url == "https://example.com/guide.pdf"
    assert result.content_type == "application/pdf"
    assert result.downloadable_guess is True


def test_access_probe_follows_301_redirects() -> None:
    calls: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, str(request.url)))
        if str(request.url) == "https://example.com/old":
            return httpx.Response(
                301,
                headers={"location": "https://example.com/new.pdf"},
                request=request,
            )
        return httpx.Response(
            200,
            headers={"content-type": "application/pdf"},
            request=request,
        )

    probe = AccessProbe(timeout_seconds=1, transport=httpx.MockTransport(handler))
    result = probe.probe("https://example.com/old")

    assert calls == [("HEAD", "https://example.com/old"), ("HEAD", "https://example.com/new.pdf")]
    assert result.ok is True
    assert result.http_status == 200
    assert result.reason_code == REASON_OK
    assert result.final_url == "https://example.com/new.pdf"
    assert result.redirected is True


def test_access_probe_marks_401_as_auth_required() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, request=request)

    probe = AccessProbe(timeout_seconds=1, transport=httpx.MockTransport(handler))
    result = probe.probe("https://example.com/private")

    assert result.ok is False
    assert result.http_status == 401
    assert result.reason_code == REASON_AUTH_REQUIRED
    assert result.reason_detail == "La URL requiere autenticacion."


def test_access_probe_marks_403_as_forbidden() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, request=request)

    probe = AccessProbe(timeout_seconds=1, transport=httpx.MockTransport(handler))
    result = probe.probe("https://example.com/forbidden")

    assert result.ok is False
    assert result.http_status == 403
    assert result.reason_code == REASON_FORBIDDEN
    assert result.reason_detail == "La URL devolvió 403."


def test_access_probe_marks_404_as_not_found() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.method)
        if request.method == "HEAD":
            return httpx.Response(405, request=request)
        return httpx.Response(404, request=request)

    probe = AccessProbe(timeout_seconds=1, transport=httpx.MockTransport(handler))
    result = probe.probe("https://example.com/missing")

    assert calls == ["HEAD", "GET"]
    assert result.ok is False
    assert result.http_status == 404
    assert result.reason_code == REASON_NOT_FOUND
    assert result.reason_detail == "La URL devolvió 404."


def test_access_probe_marks_timeout() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("too slow", request=request)

    probe = AccessProbe(timeout_seconds=1, transport=httpx.MockTransport(handler))
    result = probe.probe("https://example.com/slow")

    assert result.ok is False
    assert result.http_status is None
    assert result.reason_code == REASON_TIMEOUT
    assert result.reason_detail == "La URL ha excedido el tiempo de espera."


def test_access_probe_marks_login_html_as_auth_required() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.method)
        if request.method == "HEAD":
            return httpx.Response(
                200,
                headers={"content-type": "text/html; charset=utf-8"},
                request=request,
            )
        return httpx.Response(
            200,
            headers={"content-type": "text/html; charset=utf-8"},
            text="<html><head><title>Login</title></head><body><input type=\"password\"></body></html>",
            request=request,
        )

    probe = AccessProbe(timeout_seconds=1, transport=httpx.MockTransport(handler))
    result = probe.probe("https://example.com/session")

    assert calls == ["HEAD", "GET"]
    assert result.ok is False
    assert result.http_status == 200
    assert result.reason_code == REASON_AUTH_REQUIRED
    assert result.reason_detail == "La URL responde con una pantalla de login."
