from __future__ import annotations

import json

import httpx
import pytest

from app.core.errors import AppError
from app.services.canvas_client import CanvasClient, CanvasCredentials


def build_transport(handler):
    return httpx.MockTransport(handler)


def test_list_courses_follows_pagination_and_sends_auth_header() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)

        if request.url.path == "/api/v1/courses" and request.url.params.get("page") is None:
            return httpx.Response(
                200,
                json=[
                    {
                        "id": 22,
                        "name": "Biologia",
                        "term": {"name": "B"},
                        "start_at": "2026-01-01T09:00:00Z",
                        "end_at": "2026-06-30T18:00:00Z",
                    }
                ],
                headers={"Link": '<https://canvas.example.edu/api/v1/courses?page=2>; rel="next"'},
            )

        if request.url.path == "/api/v1/courses" and request.url.params.get("page") == "2":
            return httpx.Response(
                200,
                json=[
                    {
                        "id": 11,
                        "name": "Algebra",
                        "term": {"name": "A"},
                        "start_at": "2025-09-01T09:00:00Z",
                        "end_at": "2026-01-31T18:00:00Z",
                    }
                ],
            )

        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    credentials = CanvasCredentials.create(base_url="https://canvas.example.edu", token="secret-token")
    client = CanvasClient(credentials, transport=build_transport(handler))

    courses = client.list_courses()

    assert [course.name for course in courses] == ["Algebra", "Biologia"]
    assert requests[0].headers["Authorization"] == "Bearer secret-token"
    assert requests[0].url.params["enrollment_type"] == "teacher"


def test_get_course_raises_auth_error_on_401() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"errors": [{"message": "Unauthorized"}]})

    credentials = CanvasCredentials.create(base_url="https://canvas.example.edu", token="bad-token")
    client = CanvasClient(credentials, transport=build_transport(handler))

    with pytest.raises(AppError) as exc_info:
        client.get_course("99")

    assert exc_info.value.code == "canvas_auth_failed"
    assert exc_info.value.status_code == 401
