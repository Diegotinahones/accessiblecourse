from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping
from urllib.parse import urlparse

import httpx


REASON_OK = "OK"
REASON_NOT_FOUND = "NOT_FOUND"
REASON_AUTH_REQUIRED = "AUTH_REQUIRED"
REASON_FORBIDDEN = "FORBIDDEN"
REASON_TIMEOUT = "TIMEOUT"
REASON_DNS_ERROR = "DNS_ERROR"
REASON_SSL_ERROR = "SSL_ERROR"
REASON_NETWORK_ERROR = "NETWORK_ERROR"
REASON_UNSUPPORTED = "UNSUPPORTED"
REASON_UNKNOWN = "UNKNOWN"

DOWNLOADABLE_EXTENSIONS = {
    ".csv",
    ".doc",
    ".docx",
    ".gif",
    ".ipynb",
    ".jpeg",
    ".jpg",
    ".md",
    ".mov",
    ".mp4",
    ".pdf",
    ".png",
    ".ppt",
    ".pptx",
    ".rtf",
    ".svg",
    ".txt",
    ".webm",
    ".xls",
    ".xlsx",
    ".zip",
}
DOWNLOADABLE_CONTENT_PREFIXES = ("application/", "audio/", "image/", "video/")
NON_DOWNLOADABLE_CONTENT_TYPES = ("text/html", "application/json", "text/json")
LOGIN_KEYWORDS = (
    "<title>login",
    "<title>sign in",
    "<title>iniciar",
    "name=\"password\"",
    "type=\"password\"",
    "single sign-on",
    "sso",
    "saml",
    "oauth",
    "cas/login",
    "inicia sessio",
    "iniciar sesion",
    "identificacion",
    "autenticacion",
)


@dataclass(slots=True, frozen=True)
class AccessProbeResult:
    ok: bool
    http_status: int | None
    reason_code: str
    reason_detail: str | None
    final_url: str | None
    content_type: str | None
    downloadable_guess: bool
    content_disposition: str | None = None
    redirected: bool = False
    redirect_location: str | None = None


@dataclass(slots=True, frozen=True)
class _ProbeHTTPResponse:
    status_code: int
    final_url: str
    content_type: str | None
    content_disposition: str | None
    redirect_location: str | None
    body_preview: str


class AccessProbe:
    def __init__(
        self,
        *,
        timeout_seconds: float = 5.0,
        user_agent: str = "AccessibleCourse/1.0 (+access-probe)",
        transport: httpx.BaseTransport | None = None,
        max_body_bytes: int = 64 * 1024,
    ) -> None:
        self.timeout_seconds = timeout_seconds
        self.user_agent = user_agent
        self.transport = transport
        self.max_body_bytes = max_body_bytes

    def probe(
        self,
        url: str,
        headers: Mapping[str, str] | None = None,
        *,
        follow_redirects: bool = True,
    ) -> AccessProbeResult:
        parsed = urlparse(url)
        if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
            return AccessProbeResult(
                ok=False,
                http_status=None,
                reason_code=REASON_UNSUPPORTED,
                reason_detail="Solo se pueden comprobar URLs http(s).",
                final_url=url,
                content_type=None,
                downloadable_guess=False,
            )

        request_headers = {"User-Agent": self.user_agent, "Accept": "*/*"}
        if headers:
            request_headers.update(dict(headers))

        try:
            with httpx.Client(
                transport=self.transport,
                timeout=httpx.Timeout(self.timeout_seconds),
                follow_redirects=follow_redirects,
            ) as client:
                response = self._request(client, "HEAD", url, headers=request_headers)
                if response.status_code in {405, 501} or self._needs_body_probe(response):
                    response = self._request(client, "GET", url, headers=request_headers)
        except httpx.UnsupportedProtocol as exc:
            return self._error_result(url, REASON_UNSUPPORTED, "URL no soportada.", exc)
        except httpx.TimeoutException as exc:
            return self._error_result(url, REASON_TIMEOUT, "La URL ha excedido el tiempo de espera.", exc)
        except httpx.TransportError as exc:
            reason_code = self._network_reason_code(exc)
            return self._error_result(url, reason_code, self._network_reason_detail(reason_code, exc), exc)

        return self._result_from_response(url, response)

    def _request(
        self,
        client: httpx.Client,
        method: str,
        url: str,
        *,
        headers: dict[str, str],
    ) -> _ProbeHTTPResponse:
        body = b""
        with client.stream(method, url, headers=headers) as response:
            if method == "GET":
                for chunk in response.iter_bytes():
                    body += chunk
                    if len(body) >= self.max_body_bytes:
                        break
            body_preview = body.decode(response.encoding or "utf-8", errors="ignore")
            return _ProbeHTTPResponse(
                status_code=response.status_code,
                final_url=str(response.url),
                content_type=response.headers.get("content-type"),
                content_disposition=response.headers.get("content-disposition"),
                redirect_location=response.headers.get("location"),
                body_preview=body_preview,
            )

    def _result_from_response(self, original_url: str, response: _ProbeHTTPResponse) -> AccessProbeResult:
        status_code = response.status_code
        reason_code = REASON_OK
        reason_detail: str | None = None

        if status_code == 404:
            reason_code = REASON_NOT_FOUND
            reason_detail = "La URL devolvió 404."
        elif status_code == 401:
            reason_code = REASON_AUTH_REQUIRED
            reason_detail = "La URL requiere autenticacion."
        elif status_code == 403:
            reason_code = REASON_FORBIDDEN
            reason_detail = "La URL devolvió 403."
        elif status_code >= 400:
            reason_code = REASON_UNKNOWN
            reason_detail = f"La URL devolvió {status_code}."
        elif self._looks_like_login(response):
            reason_code = REASON_AUTH_REQUIRED
            reason_detail = "La URL responde con una pantalla de login."

        return AccessProbeResult(
            ok=reason_code == REASON_OK,
            http_status=status_code,
            reason_code=reason_code,
            reason_detail=reason_detail,
            final_url=response.final_url,
            content_type=response.content_type,
            content_disposition=response.content_disposition,
            downloadable_guess=self._downloadable_guess(response),
            redirected=response.final_url.rstrip("/") != original_url.rstrip("/") or 300 <= status_code < 400,
            redirect_location=response.redirect_location,
        )

    def _needs_body_probe(self, response: _ProbeHTTPResponse) -> bool:
        if response.status_code >= 400 or 300 <= response.status_code < 400:
            return False
        content_type = (response.content_type or "").lower()
        return not content_type or "html" in content_type

    def _looks_like_login(self, response: _ProbeHTTPResponse) -> bool:
        content_type = (response.content_type or "").lower()
        if content_type and "html" not in content_type:
            return False
        body = response.body_preview.lower()
        if not body:
            return False
        return any(keyword in body for keyword in LOGIN_KEYWORDS)

    def _downloadable_guess(self, response: _ProbeHTTPResponse) -> bool:
        disposition = (response.content_disposition or "").lower()
        if "attachment" in disposition or "filename=" in disposition:
            return True

        content_type = (response.content_type or "").split(";", 1)[0].strip().lower()
        if content_type in NON_DOWNLOADABLE_CONTENT_TYPES:
            return False
        if content_type and content_type.startswith(DOWNLOADABLE_CONTENT_PREFIXES):
            return True

        suffix = Path(urlparse(response.final_url).path).suffix.lower()
        if suffix in DOWNLOADABLE_EXTENSIONS:
            return True
        return "download" in urlparse(response.final_url).path.lower()

    def _error_result(
        self,
        url: str,
        reason_code: str,
        reason_detail: str,
        exc: Exception,
    ) -> AccessProbeResult:
        detail = reason_detail if reason_code == REASON_TIMEOUT else f"{reason_detail} ({exc})"
        return AccessProbeResult(
            ok=False,
            http_status=None,
            reason_code=reason_code,
            reason_detail=detail,
            final_url=url,
            content_type=None,
            downloadable_guess=False,
        )

    def _network_reason_code(self, exc: httpx.TransportError) -> str:
        message = str(exc).lower()
        if "certificate" in message or "ssl" in message:
            return REASON_SSL_ERROR
        if "name or service" in message or "nodename" in message or "dns" in message:
            return REASON_DNS_ERROR
        return REASON_NETWORK_ERROR

    def _network_reason_detail(self, reason_code: str, exc: httpx.TransportError) -> str:
        if reason_code == REASON_SSL_ERROR:
            return "Error SSL al comprobar la URL."
        if reason_code == REASON_DNS_ERROR:
            return "No se ha podido resolver el dominio de la URL."
        return f"Error de red al comprobar la URL: {exc}"
