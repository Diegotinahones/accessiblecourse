from __future__ import annotations

from fastapi.testclient import TestClient

from server import app as server_app


def test_combined_server_exposes_api_without_double_prefix() -> None:
    client = TestClient(server_app)

    health_response = client.get("/api/health")
    assert health_response.status_code == 200, health_response.text
    assert health_response.json()["status"] == "ok"

    upload_response = client.post("/api/jobs")
    assert upload_response.status_code == 422, upload_response.text

    double_prefixed_response = client.post("/api/api/jobs")
    assert double_prefixed_response.status_code == 404, double_prefixed_response.text


def test_wrapper_health_endpoint_returns_json() -> None:
    client = TestClient(server_app)

    response = client.get("/health")

    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("application/json")
    assert response.json()["status"] == "ok"
