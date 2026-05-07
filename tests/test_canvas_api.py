from __future__ import annotations

from typing import Any

import httpx
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.services.canvas_api import CanvasAPIClient, CanvasAPIError
from tests.conftest import build_sample_imscc
from tests.test_online_api import StubCanvasClient, StubUrlChecker


def canvas_settings() -> Settings:
    return Settings(
        canvas_base_url="https://canvas.example.edu",
        canvas_api_prefix="/api/v1",
        canvas_token="secret-token",
        canvas_per_page=2,
        canvas_timeout_seconds=3,
    )


def configure_token_encryption(client) -> None:
    client.app.state.settings.token_encryption_key = Fernet.generate_key().decode("ascii")
    client.app.state.settings.session_secret = "test-session-secret"


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


def test_canvas_api_client_accepts_token_pasted_with_bearer_prefix() -> None:
    seen: dict[str, Any] = {}
    settings = canvas_settings()
    settings.canvas_token = "  Bearer pasted-token  "

    def handler(request: httpx.Request) -> httpx.Response:
        seen["authorization"] = request.headers.get("Authorization")
        return httpx.Response(200, json={"id": 1}, request=request)

    client = CanvasAPIClient(settings, transport=httpx.MockTransport(handler))
    client.get_json("/users/self/profile")

    assert seen["authorization"] == "Bearer pasted-token"


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
    client.app.state.settings.canvas_base_url = "https://canvas.example.edu"
    client.app.state.settings.canvas_token = "secret-token"

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

    activate_response = client.post("/api/token/activate-demo")
    assert activate_response.status_code == 200, activate_response.text
    assert activate_response.json() == {"ok": True, "tokenConfigured": True, "mode": "demo"}

    health_response = client.get("/api/canvas/health")
    assert health_response.status_code == 200, health_response.text
    assert health_response.json() == {
        "ok": True,
        "tokenConfigured": True,
        "demoTokenAvailable": True,
        "mode": "demo",
    }

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


def test_canvas_courses_requires_active_demo_token(client, monkeypatch) -> None:
    client.app.state.settings.canvas_base_url = "https://canvas.example.edu"
    client.app.state.settings.canvas_token = "secret-token"

    def fail_if_called(settings):
        raise AssertionError("CanvasAPIClient should not be built without an active token.")

    monkeypatch.setattr("app.api.routes.canvas.CanvasAPIClient", fail_if_called)

    status_response = client.get("/api/token/status")
    assert status_response.status_code == 200, status_response.text
    assert status_response.json() == {
        "tokenConfigured": False,
        "demoTokenAvailable": True,
        "mode": "none",
    }

    courses_response = client.get("/api/canvas/courses")

    assert courses_response.status_code == 428, courses_response.text
    payload = courses_response.json()
    assert payload["code"] == "canvas_token_required"
    assert payload["message"] == "Configura tu token de acceso para consultar tus cursos de Canvas."
    assert payload["demoTokenAvailable"] is True
    assert payload["tokenConfigured"] is False
    assert payload["mode"] == "none"


def test_user_token_can_be_configured_and_used_without_exposure(client, monkeypatch) -> None:
    client.app.state.settings.canvas_base_url = "https://canvas.example.edu"
    client.app.state.settings.canvas_token = "demo-token"
    configure_token_encryption(client)
    seen_tokens: list[str | None] = []

    class FakeCanvasAPIClient:
        def __init__(self, settings):
            self.settings = settings

        def get_json(self, path):
            assert path == "/users/self/profile"
            seen_tokens.append(self.settings.canvas_token)
            return {"id": 99}

        def get_paginated_json(self, path, *, params, max_pages):
            seen_tokens.append(self.settings.canvas_token)
            return [{"id": 77, "name": "Curso usuario", "course_code": "USER", "workflow_state": "available"}]

    monkeypatch.setattr("app.api.routes.token.CanvasAPIClient", FakeCanvasAPIClient)
    monkeypatch.setattr("app.api.routes.canvas.CanvasAPIClient", FakeCanvasAPIClient)

    configure_response = client.post("/api/token/configure", json={"token": "user-secret-token"})
    assert configure_response.status_code == 200, configure_response.text
    assert configure_response.json() == {"ok": True, "tokenConfigured": True, "mode": "user"}
    assert "user-secret-token" not in configure_response.text

    status_response = client.get("/api/token/status")
    assert status_response.status_code == 200, status_response.text
    assert status_response.json() == {
        "tokenConfigured": True,
        "demoTokenAvailable": True,
        "mode": "user",
    }

    courses_response = client.get("/api/canvas/courses")
    assert courses_response.status_code == 200, courses_response.text
    assert courses_response.json()[0]["id"] == 77
    assert seen_tokens == ["user-secret-token", "user-secret-token"]

    session_files = list((client.app.state.settings.storage_root / "sessions").glob("*.json"))
    assert len(session_files) == 1
    assert "user-secret-token" not in session_files[0].read_text(encoding="utf-8")


def test_configure_token_rejects_invalid_canvas_token(client, monkeypatch) -> None:
    client.app.state.settings.canvas_base_url = "https://canvas.example.edu"
    configure_token_encryption(client)

    class FakeCanvasAPIClient:
        def __init__(self, settings):
            self.settings = settings

        def get_json(self, path):
            raise CanvasAPIError("invalid", status=401, detail="invalid")

    monkeypatch.setattr("app.api.routes.token.CanvasAPIClient", FakeCanvasAPIClient)

    response = client.post("/api/token/configure", json={"token": "bad-token"})

    assert response.status_code == 401, response.text
    payload = response.json()
    assert payload["code"] == "invalid_canvas_token"
    assert payload["message"] == "No hemos podido validar el token con Canvas/UOC."
    assert "bad-token" not in response.text


def test_demo_token_can_be_activated_and_deactivated_for_session(client, monkeypatch) -> None:
    client.app.state.settings.canvas_base_url = "https://canvas.example.edu"
    client.app.state.settings.canvas_token = "secret-token"

    class FakeCanvasAPIClient:
        def __init__(self, settings):
            self.settings = settings

        def get_paginated_json(self, path, *, params, max_pages):
            assert self.settings.canvas_token == "secret-token"
            return [{"id": 77, "name": "Curso demo", "course_code": "DEMO", "workflow_state": "available"}]

    monkeypatch.setattr("app.api.routes.canvas.CanvasAPIClient", FakeCanvasAPIClient)

    activate_response = client.post("/api/token/activate-demo")
    assert activate_response.status_code == 200, activate_response.text
    assert activate_response.json() == {"ok": True, "tokenConfigured": True, "mode": "demo"}

    courses_response = client.get("/api/canvas/courses")
    assert courses_response.status_code == 200, courses_response.text
    assert courses_response.json()[0]["id"] == 77

    deactivate_response = client.post("/api/token/deactivate")
    assert deactivate_response.status_code == 200, deactivate_response.text
    assert deactivate_response.json() == {"ok": True, "tokenConfigured": False, "mode": "none"}

    blocked_response = client.get("/api/canvas/courses")
    assert blocked_response.status_code == 428, blocked_response.text
    assert blocked_response.json()["code"] == "canvas_token_required"


def test_user_tokens_are_isolated_between_sessions(client, monkeypatch) -> None:
    client.app.state.settings.canvas_base_url = "https://canvas.example.edu"
    configure_token_encryption(client)
    seen_tokens: list[str | None] = []

    class FakeCanvasAPIClient:
        def __init__(self, settings):
            self.settings = settings

        def get_json(self, path):
            return {"id": 1}

        def get_paginated_json(self, path, *, params, max_pages):
            seen_tokens.append(self.settings.canvas_token)
            return []

    monkeypatch.setattr("app.api.routes.token.CanvasAPIClient", FakeCanvasAPIClient)
    monkeypatch.setattr("app.api.routes.canvas.CanvasAPIClient", FakeCanvasAPIClient)

    second_client = TestClient(client.app)

    assert client.post("/api/token/configure", json={"token": "token-user-a"}).status_code == 200
    assert second_client.post("/api/token/configure", json={"token": "token-user-b"}).status_code == 200

    assert client.get("/api/canvas/courses").status_code == 200
    assert second_client.get("/api/canvas/courses").status_code == 200
    assert seen_tokens == ["token-user-a", "token-user-b"]


def test_activate_demo_token_requires_backend_canvas_token(client) -> None:
    response = client.post("/api/token/activate-demo")

    assert response.status_code == 409, response.text
    assert response.json()["code"] == "token_not_configured"


def test_canvas_job_uses_server_side_token(client, monkeypatch) -> None:
    client.app.state.settings.canvas_base_url = "https://canvas.example.edu"
    client.app.state.settings.canvas_token = "secret-token"

    monkeypatch.setattr(
        "app.api.routes.canvas._build_canvas_client",
        lambda credentials, settings: StubCanvasClient(credentials),
    )
    monkeypatch.setattr(
        "app.api.routes.canvas._build_url_checker",
        lambda settings: StubUrlChecker(),
    )

    activate_response = client.post("/api/token/activate-demo")
    assert activate_response.status_code == 200, activate_response.text

    create_response = client.post("/api/canvas/jobs", json={"courseId": "77"})

    assert create_response.status_code == 201, create_response.text
    job_id = create_response.json()["jobId"]

    status_response = client.get(f"/api/jobs/{job_id}")
    assert status_response.status_code == 200, status_response.text
    assert status_response.json()["status"] == "done"

    resources_response = client.get(f"/api/jobs/{job_id}/resources")
    assert resources_response.status_code == 200, resources_response.text
    assert len(resources_response.json()["resources"]) == 9


def test_canvas_access_summary_groups_resources_by_module(client, monkeypatch) -> None:
    client.app.state.settings.canvas_base_url = "https://canvas.example.edu"
    client.app.state.settings.canvas_token = "secret-token"

    monkeypatch.setattr(
        "app.api.routes.canvas._build_canvas_client",
        lambda credentials, settings: StubCanvasClient(credentials),
    )
    monkeypatch.setattr(
        "app.api.routes.canvas._build_url_checker",
        lambda settings: StubUrlChecker(),
    )

    activate_response = client.post("/api/token/activate-demo")
    assert activate_response.status_code == 200, activate_response.text

    response = client.get("/api/canvas/courses/77/access-summary")

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["courseId"] == "77"
    assert payload["total"] == 9
    assert payload["accessible"] == 5
    assert payload["requiere_interaccion_count"] == 2
    assert payload["requiere_sso_count"] == 1
    assert payload["downloadable"] == 3
    assert payload["downloadableAccessible"] == 3
    assert payload["byStatus"]["OK"] == 5
    assert payload["byStatus"]["NO_ACCEDE"] == 1
    assert payload["byStatus"]["REQUIERE_INTERACCION"] == 2
    assert payload["byStatus"]["REQUIERE_SSO"] == 1
    assert payload["deepScan"]["scannedPages"] == 3
    assert len(payload["modules"]) == 4
    assert payload["modules"][0]["moduleName"] == "Modulo 1 > Recursos principales"
    assert payload["modules"][0]["resources"][0]["title"] == "Guia docente.pdf"


def test_canvas_download_streams_file_with_backend_proxy(client, monkeypatch) -> None:
    client.app.state.settings.canvas_base_url = "https://canvas.example.edu"
    client.app.state.settings.canvas_token = "secret-token"

    monkeypatch.setattr(
        "app.api.routes.canvas._build_canvas_client",
        lambda credentials, settings: StubCanvasClient(credentials),
    )
    monkeypatch.setattr(
        "app.api.routes.canvas._build_url_checker",
        lambda settings: StubUrlChecker(),
    )

    activate_response = client.post("/api/token/activate-demo")
    assert activate_response.status_code == 200, activate_response.text

    summary_response = client.get("/api/canvas/courses/77/access-summary")
    assert summary_response.status_code == 200, summary_response.text
    first_resource_id = summary_response.json()["modules"][0]["resources"][0]["id"]

    download_response = client.get(f"/api/canvas/courses/77/resources/{first_resource_id}/download")

    assert download_response.status_code == 200, download_response.text
    assert download_response.content == b"%PDF-1.4 test canvas pdf"
    assert download_response.headers["content-type"].startswith("application/pdf")
    assert "attachment;" in download_response.headers["content-disposition"]


def test_canvas_health_returns_false_when_env_is_missing(client) -> None:
    response = client.get("/api/canvas/health")

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["ok"] is False
    assert payload["demoTokenAvailable"] is False
    assert payload["tokenConfigured"] is False
    assert payload["mode"] == "none"
    assert payload["status"] is None
    assert "token de acceso" in payload["detail"]


def test_offline_upload_does_not_require_active_canvas_token(client) -> None:
    client.app.state.settings.canvas_base_url = "https://canvas.example.edu"
    client.app.state.settings.canvas_token = "secret-token"

    token_status_response = client.get("/api/token/status")
    assert token_status_response.status_code == 200, token_status_response.text
    assert token_status_response.json()["tokenConfigured"] is False

    create_response = client.post(
        "/api/jobs",
        files={"file": ("course.imscc", build_sample_imscc(), "application/octet-stream")},
    )

    assert create_response.status_code == 201, create_response.text
