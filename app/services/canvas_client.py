from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from email.utils import parsedate_to_datetime
from threading import Lock
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx

from app.core.errors import AppError


@dataclass(slots=True, frozen=True)
class CanvasCredentials:
    base_url: str
    token: str = field(repr=False)
    auth_mode: str = "token"

    @classmethod
    def create(cls, *, base_url: str, token: str, auth_mode: str = "token") -> "CanvasCredentials":
        normalized_base_url = normalize_canvas_base_url(base_url)
        cleaned_token = token.strip()
        if cleaned_token.lower().startswith("bearer "):
            cleaned_token = cleaned_token[7:].strip()
        if not cleaned_token:
            raise AppError(
                code="canvas_token_required",
                message="Necesitamos un token de Canvas para acceder a los cursos online.",
                status_code=400,
            )
        if auth_mode != "token":
            raise AppError(
                code="canvas_auth_mode_not_supported",
                message="Este MVP solo admite autenticacion con token de Canvas.",
                status_code=400,
                details={"supportedAuthModes": ["token"]},
            )
        return cls(base_url=normalized_base_url, token=cleaned_token, auth_mode=auth_mode)

    def build_url(self, path: str) -> str:
        return urljoin(self.base_url, path.lstrip("/"))

    def auth_headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/json",
        }

    def normalized_base_url(self) -> str:
        return self.base_url.rstrip("/")

    def api_base_url(self) -> str:
        return urljoin(self.base_url, "api/v1")

    def is_canvas_url(self, url: str) -> bool:
        return urlparse(url).netloc.lower() == urlparse(self.base_url).netloc.lower()


@dataclass(slots=True, frozen=True)
class CanvasCourse:
    id: str
    name: str
    term: str | None
    start_at: datetime | None
    end_at: datetime | None


@dataclass(slots=True, frozen=True)
class CanvasModule:
    id: str
    name: str
    position: int


@dataclass(slots=True, frozen=True)
class CanvasModuleItem:
    id: str
    title: str
    type: str
    position: int
    content_id: str | None
    html_url: str | None
    external_url: str | None
    page_url: str | None
    url: str | None


@dataclass(slots=True, frozen=True)
class CanvasFile:
    id: str
    display_name: str
    filename: str
    content_type: str | None
    folder_full_name: str | None
    url: str | None
    html_url: str | None
    preview_url: str | None


@dataclass(slots=True)
class CanvasDownloadHandle:
    client: httpx.Client = field(repr=False)
    response: httpx.Response = field(repr=False)
    filename: str | None = None
    content_type: str | None = None
    content_length: int | None = None

    def iter_bytes(self):
        try:
            yield from self.response.iter_bytes()
        finally:
            self.close()

    def close(self) -> None:
        self.response.close()
        self.client.close()


@dataclass(slots=True, frozen=True)
class CanvasTextResponse:
    text: str
    status_code: int
    content_type: str | None
    url: str


@dataclass(slots=True)
class OnlineJobContext:
    credentials: CanvasCredentials
    course_id: str
    course_name: str | None = None


class OnlineJobContextStore:
    def __init__(self) -> None:
        self._lock = Lock()
        self._items: dict[str, OnlineJobContext] = {}

    def put(self, job_id: str, context: OnlineJobContext) -> None:
        with self._lock:
            self._items[job_id] = context

    def pop(self, job_id: str) -> OnlineJobContext | None:
        with self._lock:
            return self._items.pop(job_id, None)

    def get(self, job_id: str) -> OnlineJobContext | None:
        with self._lock:
            return self._items.get(job_id)

    def delete(self, job_id: str) -> None:
        with self._lock:
            self._items.pop(job_id, None)


def normalize_canvas_base_url(value: str) -> str:
    cleaned = value.strip()
    parsed = urlparse(cleaned)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise AppError(
            code="canvas_base_url_invalid",
            message="La URL base de Canvas no es valida. Usa un dominio http(s) completo.",
            status_code=400,
        )
    path = parsed.path.rstrip("/")
    normalized = parsed._replace(path=f"{path}/" if path else "/", params="", query="", fragment="")
    return normalized.geturl()


def _parse_datetime(value: Any) -> datetime | None:
    if not value or not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        try:
            return parsedate_to_datetime(value)
        except (TypeError, ValueError):
            return None


def _extract_next_link(link_header: str | None) -> str | None:
    if not link_header:
        return None
    for chunk in link_header.split(","):
        parts = [part.strip() for part in chunk.split(";") if part.strip()]
        if len(parts) < 2:
            continue
        target, *attributes = parts
        if 'rel="next"' not in attributes:
            continue
        if target.startswith("<") and target.endswith(">"):
            return target[1:-1]
    return None


def _require_string(payload: dict[str, Any], key: str, *, fallback: str | None = None) -> str:
    value = payload.get(key, fallback)
    if value is None:
        return ""
    return str(value).strip()


class CanvasClient:
    def __init__(
        self,
        credentials: CanvasCredentials,
        *,
        timeout_seconds: float = 10.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.credentials = credentials
        self.timeout_seconds = timeout_seconds
        self.transport = transport

    def verify_auth(self) -> None:
        self._request_json("GET", "api/v1/users/self")

    def list_courses(self) -> list[CanvasCourse]:
        payload = self._paginate("api/v1/courses", params={"enrollment_type": "teacher", "include[]": "term"})
        courses = [self._parse_course(item) for item in payload]
        return sorted(
            courses,
            key=lambda course: (
                course.term.lower() if course.term else "zzz",
                course.name.lower(),
                course.id,
            ),
        )

    def get_course(self, course_id: str) -> CanvasCourse:
        payload = self._request_json("GET", f"api/v1/courses/{course_id}", params={"include[]": "term"})
        if not isinstance(payload, dict):
            raise AppError(
                code="canvas_course_invalid",
                message="Canvas ha devuelto un curso en un formato inesperado.",
                status_code=502,
            )
        return self._parse_course(payload)

    def list_modules(self, course_id: str) -> list[CanvasModule]:
        payload = self._paginate(f"api/v1/courses/{course_id}/modules", params={"per_page": 100})
        modules = [
            CanvasModule(
                id=_require_string(item, "id"),
                name=_require_string(item, "name", fallback="Modulo sin titulo") or "Modulo sin titulo",
                position=int(item.get("position") or 0),
            )
            for item in payload
        ]
        return sorted(modules, key=lambda module: (module.position, module.name.lower(), module.id))

    def list_module_items(self, course_id: str, module_id: str) -> list[CanvasModuleItem]:
        payload = self._paginate(
            f"api/v1/courses/{course_id}/modules/{module_id}/items",
            params={"per_page": 100},
        )
        items = [
            CanvasModuleItem(
                id=_require_string(item, "id"),
                title=_require_string(item, "title", fallback="Elemento sin titulo") or "Elemento sin titulo",
                type=_require_string(item, "type", fallback="Unknown") or "Unknown",
                position=int(item.get("position") or 0),
                content_id=str(item["content_id"]) if item.get("content_id") is not None else None,
                html_url=item.get("html_url"),
                external_url=item.get("external_url"),
                page_url=item.get("page_url"),
                url=item.get("url"),
            )
            for item in payload
        ]
        return sorted(items, key=lambda item: (item.position, item.title.lower(), item.id))

    def get_file(self, course_id: str, file_id: str) -> CanvasFile:
        payload = self._request_json("GET", f"api/v1/courses/{course_id}/files/{file_id}")
        return self._parse_file(payload)

    def get_file_by_id(self, file_id: str) -> CanvasFile:
        payload = self._request_json("GET", f"api/v1/files/{file_id}")
        return self._parse_file(payload)

    def _parse_file(self, payload: Any) -> CanvasFile:
        if not isinstance(payload, dict):
            raise AppError(
                code="canvas_file_invalid",
                message="Canvas ha devuelto un fichero en un formato inesperado.",
                status_code=502,
            )
        return CanvasFile(
            id=_require_string(payload, "id"),
            display_name=_require_string(payload, "display_name", fallback="Fichero sin titulo") or "Fichero sin titulo",
            filename=_require_string(payload, "filename", fallback="file") or "file",
            content_type=_require_string(payload, "content-type") or _require_string(payload, "content_type") or None,
            folder_full_name=_require_string(payload, "folder_full_name") or None,
            url=payload.get("url"),
            html_url=payload.get("html_url"),
            preview_url=payload.get("preview_url"),
        )

    def get_assignment(self, course_id: str, assignment_id: str) -> dict[str, Any]:
        return self.get_json(f"api/v1/courses/{course_id}/assignments/{assignment_id}")

    def get_discussion_topic(self, course_id: str, topic_id: str) -> dict[str, Any]:
        return self.get_json(f"api/v1/courses/{course_id}/discussion_topics/{topic_id}")

    def get_quiz(self, course_id: str, quiz_id: str) -> dict[str, Any]:
        return self.get_json(f"api/v1/courses/{course_id}/quizzes/{quiz_id}")

    def get_folder(self, folder_id: str | int) -> dict[str, Any]:
        payload = self._request_json("GET", f"api/v1/folders/{folder_id}")
        if not isinstance(payload, dict):
            raise AppError(
                code="canvas_folder_invalid",
                message="Canvas ha devuelto una carpeta en un formato inesperado.",
                status_code=502,
            )
        return payload

    def get_page(self, course_id: str, page_url: str) -> dict[str, Any]:
        payload = self._request_json("GET", f"api/v1/courses/{course_id}/pages/{page_url}")
        if not isinstance(payload, dict):
            raise AppError(
                code="canvas_page_invalid",
                message="Canvas ha devuelto una pagina en un formato inesperado.",
                status_code=502,
            )
        return payload

    def get_json(self, path_or_url: str, *, params: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = self._request_json(
            "GET",
            path_or_url,
            params=params,
            allow_absolute_url=path_or_url.startswith(("http://", "https://")),
        )
        if not isinstance(payload, dict):
            raise AppError(
                code="canvas_response_invalid",
                message="Canvas ha devuelto una respuesta inesperada.",
                status_code=502,
            )
        return payload

    def get_text(self, path_or_url: str, *, accept: str = "text/html") -> CanvasTextResponse:
        url = path_or_url if path_or_url.startswith(("http://", "https://")) else self.credentials.build_url(path_or_url)
        timeout = httpx.Timeout(self.timeout_seconds)
        headers = {**self.credentials.auth_headers(), "Accept": accept}

        with httpx.Client(
            transport=self.transport,
            timeout=timeout,
            headers=headers,
            follow_redirects=False,
        ) as client:
            try:
                response = client.get(url)
            except httpx.TimeoutException as exc:
                raise AppError(
                    code="canvas_timeout",
                    message="Canvas no ha respondido a tiempo. Intentalo de nuevo.",
                    status_code=504,
                ) from exc
            except httpx.HTTPError as exc:
                raise AppError(
                    code="canvas_unreachable",
                    message="No hemos podido conectar con Canvas usando la URL indicada.",
                    status_code=502,
                ) from exc

        if 300 <= response.status_code < 400:
            raise AppError(
                code="canvas_redirect_required",
                message="Canvas ha redirigido la peticion HTML antes de devolver contenido.",
                status_code=response.status_code,
                details={"location": response.headers.get("location")},
            )
        if response.status_code in {401, 403}:
            raise AppError(
                code="canvas_auth_failed",
                message="Canvas ha rechazado el acceso al contenido HTML con el token configurado.",
                status_code=response.status_code,
            )
        if response.status_code == 404:
            raise AppError(
                code="canvas_not_found",
                message="No hemos encontrado el contenido HTML solicitado en Canvas.",
                status_code=404,
            )
        if response.status_code == 429:
            raise AppError(
                code="canvas_rate_limited",
                message="Canvas ha limitado temporalmente las peticiones. Intentalo de nuevo en unos segundos.",
                status_code=429,
            )
        if response.status_code >= 400:
            raise AppError(
                code="canvas_request_failed",
                message="Canvas ha rechazado la peticion HTML necesaria para profundizar el inventario.",
                status_code=502,
                details={"statusCode": response.status_code},
            )

        return CanvasTextResponse(
            text=response.text,
            status_code=response.status_code,
            content_type=response.headers.get("content-type"),
            url=str(response.url),
        )

    def stream_download(self, url: str, *, filename: str | None = None) -> CanvasDownloadHandle:
        timeout = httpx.Timeout(self.timeout_seconds)
        client = httpx.Client(
            transport=self.transport,
            timeout=timeout,
            headers=self.credentials.auth_headers(),
            follow_redirects=True,
        )
        try:
            request = client.build_request("GET", url)
            response = client.send(request, stream=True)
        except httpx.TimeoutException as exc:
            client.close()
            raise AppError(
                code="canvas_timeout",
                message="Canvas no ha respondido a tiempo. Intentalo de nuevo.",
                status_code=504,
            ) from exc
        except httpx.HTTPError as exc:
            client.close()
            raise AppError(
                code="canvas_unreachable",
                message="No hemos podido conectar con Canvas usando la URL indicada.",
                status_code=502,
            ) from exc

        if response.status_code in {401, 403}:
            response.close()
            client.close()
            raise AppError(
                code="canvas_auth_failed",
                message="No hemos podido autenticar la sesion de Canvas. Revisa la URL base y el token.",
                status_code=401,
            )
        if response.status_code == 404:
            response.close()
            client.close()
            raise AppError(
                code="canvas_not_found",
                message="No hemos encontrado el recurso solicitado en Canvas.",
                status_code=404,
            )
        if response.status_code == 429:
            response.close()
            client.close()
            raise AppError(
                code="canvas_rate_limited",
                message="Canvas ha limitado temporalmente las peticiones. Intentalo de nuevo en unos segundos.",
                status_code=429,
            )
        if response.status_code >= 400:
            response.close()
            client.close()
            raise AppError(
                code="canvas_request_failed",
                message="Canvas ha rechazado la descarga solicitada.",
                status_code=502,
                details={"statusCode": response.status_code},
            )

        content_length = response.headers.get("content-length")
        return CanvasDownloadHandle(
            client=client,
            response=response,
            filename=filename,
            content_type=response.headers.get("content-type"),
            content_length=int(content_length) if content_length and content_length.isdigit() else None,
        )

    def _parse_course(self, payload: dict[str, Any]) -> CanvasCourse:
        term_payload = payload.get("term") if isinstance(payload.get("term"), dict) else {}
        return CanvasCourse(
            id=_require_string(payload, "id"),
            name=_require_string(payload, "name", fallback="Curso sin titulo") or "Curso sin titulo",
            term=_require_string(term_payload, "name") or None,
            start_at=_parse_datetime(payload.get("start_at")),
            end_at=_parse_datetime(payload.get("end_at")),
        )

    def _paginate(self, path: str, *, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        url = self.credentials.build_url(path)
        current_params = dict(params or {})
        results: list[dict[str, Any]] = []

        while url:
            payload, headers = self._request_json("GET", url, params=current_params, allow_absolute_url=True, with_headers=True)
            current_params = None
            if not isinstance(payload, list):
                raise AppError(
                    code="canvas_response_invalid",
                    message="Canvas ha devuelto una respuesta inesperada.",
                    status_code=502,
                )
            results.extend(item for item in payload if isinstance(item, dict))
            url = _extract_next_link(headers.get("link"))

        return results

    def _request_json(
        self,
        method: str,
        path_or_url: str,
        *,
        params: dict[str, Any] | None = None,
        allow_absolute_url: bool = False,
        with_headers: bool = False,
    ) -> Any | tuple[Any, httpx.Headers]:
        url = path_or_url if allow_absolute_url else self.credentials.build_url(path_or_url)
        timeout = httpx.Timeout(self.timeout_seconds)

        with httpx.Client(transport=self.transport, timeout=timeout, headers=self.credentials.auth_headers()) as client:
            try:
                response = client.request(method, url, params=params)
            except httpx.TimeoutException as exc:
                raise AppError(
                    code="canvas_timeout",
                    message="Canvas no ha respondido a tiempo. Intentalo de nuevo.",
                    status_code=504,
                ) from exc
            except httpx.HTTPError as exc:
                raise AppError(
                    code="canvas_unreachable",
                    message="No hemos podido conectar con Canvas usando la URL indicada.",
                    status_code=502,
                ) from exc

        if response.status_code in {401, 403}:
            raise AppError(
                code="canvas_auth_failed",
                message="No hemos podido autenticar la sesion de Canvas. Revisa la URL base y el token.",
                status_code=401,
            )
        if response.status_code == 404:
            raise AppError(
                code="canvas_not_found",
                message="No hemos encontrado el recurso solicitado en Canvas.",
                status_code=404,
            )
        if response.status_code == 429:
            raise AppError(
                code="canvas_rate_limited",
                message="Canvas ha limitado temporalmente las peticiones. Intentalo de nuevo en unos segundos.",
                status_code=429,
            )
        if response.status_code >= 400:
            raise AppError(
                code="canvas_request_failed",
                message="Canvas ha rechazado una de las peticiones necesarias para construir el inventario.",
                status_code=502,
                details={"statusCode": response.status_code},
            )

        try:
            payload = response.json()
        except ValueError as exc:
            raise AppError(
                code="canvas_response_invalid",
                message="Canvas ha devuelto una respuesta no valida.",
                status_code=502,
            ) from exc

        if with_headers:
            return payload, response.headers
        return payload


CanvasAuthConfig = CanvasCredentials
CanvasApiError = AppError
