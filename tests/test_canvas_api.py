from __future__ import annotations

from typing import Any

import httpx

from app.core.config import Settings
from app.services.canvas_api import CanvasAPIClient, CanvasAPIError


def canvas_settings() -> Settings:
    return Settings(
        canvas_base_url="https://canvas.example.edu",
        canvas_api_prefix="/api/v1",
        canvas_token="secret-token",
        canvas_per_page=2,
        canvas_timeout_seconds=3,
    )


def test_canvas_api_client_builds_url_and_sends_bearer_token() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["authorization"] = request.headers.get("Authorization")
        return httpx.Response(200, json={"id": 1}, request=request)

    client = CanvasAPIClient(canvas_settings(), transport=httpx.MockTransport(handler))
    payload = client.get_json("/users/self/profile")

    assert payload == {"id": 1}
    assert seen["url"] == "https://canvas.example.edu/api/v1/users/self/profile"
    assert seen["authorization"] == "Bearer secret-token"


def test_canvas_api_client_exposes_status_and_response_text_on_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text="invalid token", request=request)

    client = CanvasAPIClient(canvas_settings(), transport=httpx.MockTransport(handler))

    try:
        client.get_json("/users/self/profile")
    except CanvasAPIError as exc:
        assert exc.status == 401
        assert exc.detail == "invalid token"
        assert exc.method == "GET"
        assert exc.url == "https://canvas.example.edu/api/v1/users/self/profile"
    else:  # pragma: no cover
        raise AssertionError("CanvasAPIError was not raised")


def test_canvas_routes_profile_courses_and_health(client, monkeypatch) -> None:
    class FakeCanvasAPIClient:
        def __init__(self, settings):
            self.settings = settings

        def get_json(self, path):
            assert path == "/users/self/profile"
            return {"id": 7, "name": "Docente Demo"}

        def get_paginated_json(self, path, *, params, max_pages):
            assert path == "/courses"
            assert params["enrollment_state"] == "active"
            assert params["per_page"] == 100
            assert max_pages == 3
            return [
                {
                    "id": 10,
                    "name": "Accesibilidad",
                    "course_code": "ACC-101",
                    "workflow_state": "available",
                    "ignored": True,
                }
            ]

    monkeypatch.setattr("app.api.routes.canvas.CanvasAPIClient", FakeCanvasAPIClient)

    health_response = client.get("/api/canvas/health")
    assert health_response.status_code == 200, health_response.text
    assert health_response.json() == {"ok": True}

    profile_response = client.get("/api/canvas/profile")
    assert profile_response.status_code == 200, profile_response.text
    assert profile_response.json() == {"id": 7, "name": "Docente Demo"}

    courses_response = client.get("/api/canvas/courses")
    assert courses_response.status_code == 200, courses_response.text
    assert courses_response.json() == [
        {
            "id": 10,
            "name": "Accesibilidad",
            "course_code": "ACC-101",
            "workflow_state": "available",
        }
    ]


def test_canvas_health_returns_false_when_env_is_missing(client) -> None:
    response = client.get("/api/canvas/health")

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["ok"] is False
    assert payload["status"] is None
    assert "CANVAS_BASE_URL" in payload["detail"]
