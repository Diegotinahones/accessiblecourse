from __future__ import annotations

from dataclasses import dataclass

from app.services.canvas_client import CanvasCourse, CanvasFile, CanvasModule, CanvasModuleItem
from app.services.url_check import UrlCheckResult


def canvas_headers() -> dict[str, str]:
    return {
        "X-Canvas-Base-Url": "https://canvas.example.edu",
        "X-Canvas-Token": "secret-token",
    }


class StubCanvasClient:
    def __init__(self, credentials) -> None:
        self.credentials = credentials

    def verify_auth(self) -> None:
        return None

    def list_courses(self) -> list[CanvasCourse]:
        return [
            CanvasCourse(
                id="77",
                name="Accesibilidad Digital",
                term="2025/26",
                start_at=None,
                end_at=None,
            )
        ]

    def get_course(self, course_id: str) -> CanvasCourse:
        return CanvasCourse(
            id=course_id,
            name="Accesibilidad Digital",
            term="2025/26",
            start_at=None,
            end_at=None,
        )

    def list_modules(self, course_id: str) -> list[CanvasModule]:
        return [
            CanvasModule(id="m-1", name="Modulo 1", position=1),
            CanvasModule(id="m-2", name="Modulo 2", position=2),
        ]

    def list_module_items(self, course_id: str, module_id: str) -> list[CanvasModuleItem]:
        if module_id == "m-1":
            return [
                CanvasModuleItem(
                    id="sub-1",
                    title="Recursos principales",
                    type="SubHeader",
                    position=1,
                    content_id=None,
                    html_url=None,
                    external_url=None,
                    page_url=None,
                    url=None,
                ),
                CanvasModuleItem(
                    id="file-1",
                    title="Guia docente",
                    type="File",
                    position=2,
                    content_id="f-1",
                    html_url="https://canvas.example.edu/files/1",
                    external_url=None,
                    page_url=None,
                    url=None,
                ),
                CanvasModuleItem(
                    id="external-1",
                    title="Video externo",
                    type="ExternalUrl",
                    position=3,
                    content_id=None,
                    html_url=None,
                    external_url="https://broken.example.com/video",
                    page_url=None,
                    url=None,
                ),
            ]
        return [
            CanvasModuleItem(
                id="page-1",
                title="Bienvenida",
                type="Page",
                position=1,
                content_id=None,
                html_url="https://canvas.example.edu/courses/77/pages/bienvenida",
                external_url=None,
                page_url="bienvenida",
                url=None,
            )
        ]

    def get_file(self, course_id: str, file_id: str) -> CanvasFile:
        if file_id == "99":
            return CanvasFile(
                id=file_id,
                display_name="Plantilla accesible.docx",
                filename="plantilla-accesible.docx",
                content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                folder_full_name="course files/modulo-2",
                url="https://canvas.example.edu/files/99/download",
                html_url="https://canvas.example.edu/courses/77/files/99",
                preview_url=None,
            )
        return CanvasFile(
            id=file_id,
            display_name="Guia docente.pdf",
            filename="guia-docente.pdf",
            content_type="application/pdf",
            folder_full_name="course files/modulo-1",
            url="https://canvas.example.edu/files/1/download",
            html_url="https://canvas.example.edu/files/1",
            preview_url=None,
        )

    def get_page(self, course_id: str, page_url: str) -> dict[str, str]:
        if page_url == "rubrica":
            return {
                "url": f"https://canvas.example.edu/api/v1/courses/{course_id}/pages/{page_url}",
                "updated_at": "2026-04-30T09:45:00Z",
                "body": '<p><a href="/courses/77/files/99/download">Plantilla duplicada</a></p>',
            }
        return {
            "url": f"https://canvas.example.edu/api/v1/courses/{course_id}/pages/{page_url}",
            "updated_at": "2026-04-30T09:30:00Z",
            "body": """
                <p><a href="/courses/77/files/99/download">Plantilla accesible</a></p>
                <p><a href="/courses/77/pages/rubrica">Rubrica de evaluacion</a></p>
                <p><a href="/courses/77/files/metadata.xml">Metadata XML</a></p>
            """,
        }

    def get_text(self, url: str):
        raise AssertionError(f"Unexpected HTML request: {url}")

    def stream_download(self, url: str, *, filename: str | None = None):
        return StubDownloadHandle(
            payload=b"%PDF-1.4 test canvas pdf",
            filename=filename or "guia-docente.pdf",
            content_type="application/pdf",
        )


@dataclass
class StubDownloadHandle:
    payload: bytes
    filename: str
    content_type: str
    content_length: int | None = None

    def __post_init__(self) -> None:
        if self.content_length is None:
            self.content_length = len(self.payload)

    def iter_bytes(self):
        yield self.payload


class StubUrlChecker:
    def check(self, resources, *, credentials):
        results = {}
        for resource in resources:
            if resource["title"] == "Video externo":
                results[str(resource["id"])] = UrlCheckResult(
                    url=str(resource["url"]),
                    checked=True,
                    broken_link=True,
                    reason="404_not_found",
                    status_code=404,
                )
            else:
                results[str(resource["id"])] = UrlCheckResult(
                    url=str(resource["url"]) if resource.get("url") else "",
                    checked=bool(resource.get("url")),
                    broken_link=False,
                    status_code=200 if resource.get("url") else None,
                )
        return results

    def check_url(self, url: str, *, credentials=None):
        if url == "https://broken.example.com/video":
            return UrlCheckResult(
                url=url,
                checked=True,
                broken_link=True,
                reason="404_not_found",
                status_code=404,
                url_status="404",
                error_message="La URL devolvió 404.",
            )
        if url == "https://canvas.example.edu/files/1/download":
            return UrlCheckResult(
                url=url,
                checked=True,
                broken_link=False,
                status_code=200,
                url_status="200",
                final_url=url,
                content_type="application/pdf",
                content_disposition='attachment; filename="guia-docente.pdf"',
            )
        if url == "https://canvas.example.edu/files/99/download":
            return UrlCheckResult(
                url=url,
                checked=True,
                broken_link=False,
                status_code=200,
                url_status="200",
                final_url=url,
                content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                content_disposition='attachment; filename="plantilla-accesible.docx"',
            )
        return UrlCheckResult(
            url=url,
            checked=True,
            broken_link=False,
            status_code=200,
            url_status="200",
            final_url=url,
        )

    def check_url_no_redirects(self, url: str, *, credentials=None):
        if url == "https://canvas.example.edu/files/99/download":
            return UrlCheckResult(
                url=url,
                checked=True,
                broken_link=False,
                reason="redirect",
                status_code=302,
                url_status="302",
                final_url=url,
                redirected=True,
                redirect_location="https://canvas-cdn.example.edu/files/99",
            )
        if url == "https://canvas.example.edu/files/1/download":
            return UrlCheckResult(
                url=url,
                checked=True,
                broken_link=False,
                status_code=200,
                url_status="200",
                final_url=url,
                content_type="application/pdf",
                content_disposition='attachment; filename="guia-docente.pdf"',
            )
        return UrlCheckResult(
            url=url,
            checked=True,
            broken_link=False,
            status_code=200,
            url_status="200",
            final_url=url,
            content_type="text/html",
        )


def test_online_courses_and_job_flow(client, monkeypatch) -> None:
    monkeypatch.setattr(
        "app.api.routes.online.build_canvas_client",
        lambda credentials, settings: StubCanvasClient(credentials),
    )
    monkeypatch.setattr(
        "app.api.routes.online.build_url_checker",
        lambda settings: StubUrlChecker(),
    )

    courses_response = client.get("/api/online/courses", headers=canvas_headers())
    assert courses_response.status_code == 200, courses_response.text
    assert courses_response.json()[0]["name"] == "Accesibilidad Digital"

    create_response = client.post(
        "/api/online/jobs",
        headers=canvas_headers(),
        json={"courseId": "77", "courseName": "Accesibilidad Digital"},
    )
    assert create_response.status_code == 201, create_response.text
    job_id = create_response.json()["jobId"]

    status_response = client.get(f"/api/jobs/{job_id}")
    assert status_response.status_code == 200, status_response.text
    status_payload = status_response.json()
    assert status_payload["status"] == "done"
    assert status_payload["totalSteps"] == 6

    resources_response = client.get(f"/api/jobs/{job_id}/resources")
    assert resources_response.status_code == 200, resources_response.text
    resources_payload = resources_response.json()
    assert len(resources_payload["resources"]) == 5

    pdf_resource = next(resource for resource in resources_payload["resources"] if resource["title"] == "Guia docente.pdf")
    assert pdf_resource["coursePath"] == "Modulo 1 > Recursos principales"
    assert pdf_resource["localPath"] == "course files/modulo-1/guia-docente.pdf"
    assert pdf_resource["type"] == "PDF"
    assert pdf_resource["canAccess"] is True
    assert pdf_resource["canDownload"] is True
    assert pdf_resource["accessStatus"] == "OK"

    broken_resource = next(resource for resource in resources_payload["resources"] if resource["title"] == "Video externo")
    assert broken_resource["status"] == "ERROR"
    assert "broken_link" in broken_resource["notes"]
    assert broken_resource["accessStatus"] == "NOT_FOUND"

    page_resource = next(resource for resource in resources_payload["resources"] if resource["title"] == "Bienvenida")
    assert page_resource["canAccess"] is True
    assert page_resource["canDownload"] is False
    assert page_resource["discoveredChildrenCount"] == 2

    discovered_file = next(resource for resource in resources_payload["resources"] if resource["title"] == "Plantilla accesible.docx")
    assert discovered_file["canAccess"] is True
    assert discovered_file["canDownload"] is True
    assert discovered_file["downloadStatusCode"] == 302
    assert discovered_file["parentResourceId"] == page_resource["id"]

    detail_response = client.get(f"/api/jobs/{job_id}/resources/{pdf_resource['id']}")
    assert detail_response.status_code == 200, detail_response.text
    assert detail_response.json()["resource"]["type"] == "PDF"

    save_response = client.put(
        f"/api/jobs/{job_id}/resources/{pdf_resource['id']}/checklist",
        json={
            "responses": [
                {"itemKey": "tagged", "value": "FAIL", "comment": "Falta etiquetado PDF."},
                {"itemKey": "lang", "value": "PASS"},
            ]
        },
    )
    assert save_response.status_code == 200, save_response.text
    assert save_response.json()["reviewState"] == "NEEDS_FIX"

    report_response = client.post(f"/api/jobs/{job_id}/report")
    assert report_response.status_code == 200, report_response.text
    assert report_response.json()["stats"]["resources"] == 5
