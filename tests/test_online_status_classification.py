from __future__ import annotations

from app.services.access_analysis import OnlineAccessAdapter, analyze_access
from app.services.canvas_client import CanvasCredentials
from app.services.url_check import UrlCheckResult


SSO_DETAIL = "Requiere autenticación externa o capa SSO no accesible mediante API Canvas."
INTERACTION_DETAIL = "Recurso interactivo o entrega que no se analiza como contenido descargable."


class ClassificationCanvasClient:
    def get_assignment(self, course_id: str, assignment_id: str) -> dict[str, str]:
        assert course_id == "77"
        assert assignment_id == "a-1"
        return {"id": assignment_id, "description": "<p>Entrega final</p>"}


class ClassificationUrlChecker:
    def check_url(self, url: str, *, credentials=None) -> UrlCheckResult:
        if "ralti.uoc.edu" in url:
            return UrlCheckResult(
                url=url,
                checked=True,
                broken_link=True,
                reason="auth_required",
                status_code=401,
                url_status="401",
                final_url=url,
            )
        if "biblioteca.uoc.edu" in url:
            return UrlCheckResult(
                url=url,
                checked=True,
                broken_link=True,
                reason="auth_required",
                status_code=401,
                url_status="401",
                final_url=url,
            )
        return UrlCheckResult(
            url=url,
            checked=True,
            broken_link=True,
            reason="404_not_found",
            status_code=404,
            url_status="404",
            final_url=url,
            error_message="La URL devolvió 404.",
        )


def test_online_auth_required_resources_are_reclassified() -> None:
    credentials = CanvasCredentials.create(base_url="https://canvas.example.edu", token="secret-token")
    adapter = OnlineAccessAdapter(
        client=ClassificationCanvasClient(),
        credentials=credentials,
        course_id="77",
        url_checker=ClassificationUrlChecker(),
        max_depth=0,
    )

    analysis = analyze_access(
        job_id="online-classification",
        resources=[
            {
                "id": "ralti",
                "title": "RALTI",
                "type": "WEB",
                "sourceUrl": "https://ralti.uoc.edu/launch",
            },
            {
                "id": "library",
                "title": "Libro biblioteca",
                "type": "WEB",
                "sourceUrl": "https://biblioteca.uoc.edu/books/protected",
            },
            {
                "id": "assignment",
                "title": "Entrega final",
                "type": "WEB",
                "details": {"canvasType": "Assignment", "contentId": "a-1"},
            },
            {
                "id": "broken",
                "title": "Enlace roto",
                "type": "WEB",
                "sourceUrl": "https://broken.example.com/missing",
            },
        ],
        adapter=adapter,
    )

    by_id = {resource["id"]: resource for resource in analysis.resources}

    assert by_id["ralti"]["accessStatus"] == "REQUIERE_SSO"
    assert by_id["ralti"]["reasonCode"] == "AUTH_REQUIRED"
    assert by_id["ralti"]["reasonDetail"] == SSO_DETAIL
    assert by_id["library"]["accessStatus"] == "REQUIERE_SSO"
    assert by_id["library"]["reasonCode"] == "AUTH_REQUIRED"
    assert by_id["library"]["reasonDetail"] == SSO_DETAIL

    assert by_id["assignment"]["accessStatus"] == "REQUIERE_INTERACCION"
    assert by_id["assignment"]["reasonDetail"] == INTERACTION_DETAIL
    assert by_id["assignment"]["contentAvailable"] is True

    assert by_id["broken"]["accessStatus"] == "NO_ACCEDE"
    assert by_id["broken"]["reasonCode"] == "NOT_FOUND"

    summary = analysis.summary
    assert summary["total"] == 4
    assert summary["ok_count"] == 0
    assert summary["no_accede_count"] == 1
    assert summary["requires_sso_count"] == 2
    assert summary["requires_interaction_count"] == 1
    assert (
        summary["ok_count"]
        + summary["no_accede_count"]
        + summary["requires_sso_count"]
        + summary["requires_interaction_count"]
    ) == summary["total"]
