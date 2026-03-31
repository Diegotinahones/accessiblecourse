from __future__ import annotations

import io
import json
import time
from pathlib import Path
from zipfile import ZipFile

from fastapi.testclient import TestClient

from app.core.config import Settings
from app.services.imscc import parse_manifest


def build_sample_imscc() -> bytes:
    manifest = """<?xml version="1.0" encoding="UTF-8"?>
<manifest xmlns="http://www.imsglobal.org/xsd/imscp_v1p1">
  <organizations>
    <organization identifier="org-1">
      <item identifier="item-1" identifierref="res-1">
        <title>Guia docente</title>
      </item>
      <item identifier="item-2" identifierref="res-2">
        <title>Plan semanal</title>
      </item>
    </organization>
  </organizations>
  <resources>
    <resource identifier="res-1" type="webcontent" href="module_1/guide.pdf">
      <file href="module_1/guide.pdf" />
    </resource>
    <resource identifier="res-2" type="webcontent" href="module_1/plan.html">
      <file href="module_1/plan.html" />
    </resource>
  </resources>
</manifest>
"""

    buffer = io.BytesIO()
    with ZipFile(buffer, 'w') as archive:
        archive.writestr('imsmanifest.xml', manifest)
        archive.writestr('module_1/guide.pdf', b'%PDF-1.4\n%test pdf\n')
        archive.writestr('module_1/plan.html', '<html><body>Plan semanal</body></html>')
    return buffer.getvalue()


def upload_course(client: TestClient) -> str:
    response = client.post(
        '/api/jobs',
        files={'file': ('sample.imscc', io.BytesIO(build_sample_imscc()), 'application/octet-stream')},
    )
    assert response.status_code == 201, response.text
    return response.json()['jobId']


def wait_for_job_done(client: TestClient, job_id: str) -> dict:
    for _ in range(30):
        response = client.get(f'/api/jobs/{job_id}')
        assert response.status_code == 200, response.text
        payload = response.json()
        if payload['status'] in {'done', 'error'}:
            return payload
        time.sleep(0.05)

    raise AssertionError('Timed out waiting for job completion.')


def test_upload_job_to_done(client: TestClient, test_settings: Settings) -> None:
    job_id = upload_course(client)
    payload = wait_for_job_done(client, job_id)

    assert payload['status'] == 'done', payload
    assert payload['progress'] == 100

    resources_response = client.get(f'/api/jobs/{job_id}/resources')
    assert resources_response.status_code == 200, resources_response.text
    resources = resources_response.json()
    assert len(resources) == 2
    assert {resource['title'] for resource in resources} == {'Guia docente', 'Plan semanal'}

    job_log_path = test_settings.storage_root / 'jobs' / job_id / 'job.log'
    assert job_log_path.exists()
    log_lines = [json.loads(line) for line in job_log_path.read_text(encoding='utf-8').splitlines()]
    assert [line['event'] for line in log_lines][:2] == ['created', 'started']
    assert log_lines[-1]['event'] == 'finished'


def test_parse_basic_manifest(tmp_path: Path) -> None:
    manifest_path = tmp_path / 'imsmanifest.xml'
    manifest_path.write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
<manifest xmlns="http://www.imsglobal.org/xsd/imscp_v1p1">
  <organizations>
    <organization identifier="org-1">
      <item identifier="item-1" identifierref="res-1"><title>Mi PDF</title></item>
    </organization>
  </organizations>
  <resources>
    <resource identifier="res-1" type="webcontent" href="docs/mi-pdf.pdf">
      <file href="docs/mi-pdf.pdf" />
    </resource>
  </resources>
</manifest>
""",
        encoding='utf-8',
    )

    resources = parse_manifest(manifest_path)
    assert resources == [{'identifier': 'res-1', 'title': 'Mi PDF', 'href': 'docs/mi-pdf.pdf'}]


def test_save_checklist(client: TestClient) -> None:
    job_id = upload_course(client)
    wait_for_job_done(client, job_id)

    resources = client.get(f'/api/jobs/{job_id}/resources').json()
    pdf_resource = next(resource for resource in resources if resource['type'] == 'PDF')

    update_response = client.put(
        f'/api/jobs/{job_id}/checklist/{pdf_resource["id"]}',
        json={'items': {'structure': 'fail', 'ocr': 'pass'}},
    )
    assert update_response.status_code == 200, update_response.text

    checklist_response = client.get(f'/api/jobs/{job_id}/checklist')
    assert checklist_response.status_code == 200, checklist_response.text
    state = checklist_response.json()['state']
    assert state[pdf_resource['id']]['structure'] == 'fail'
    assert state[pdf_resource['id']]['ocr'] == 'pass'


def test_generate_report_and_download_files(client: TestClient) -> None:
    job_id = upload_course(client)
    wait_for_job_done(client, job_id)

    resources = client.get(f'/api/jobs/{job_id}/resources').json()
    pdf_resource = next(resource for resource in resources if resource['type'] == 'PDF')
    client.put(
        f'/api/jobs/{job_id}/checklist/{pdf_resource["id"]}',
        json={'items': {'structure': 'fail', 'ocr': 'fail'}},
    )

    report_response = client.post(f'/api/reports/{job_id}')
    assert report_response.status_code == 200, report_response.text
    report = report_response.json()
    assert report['failedItemCount'] == 2
    assert report['downloads']['pdfUrl'].endswith('/download/pdf')
    assert report['downloads']['docxUrl'].endswith('/download/docx')

    get_report_response = client.get(f'/api/reports/{job_id}')
    assert get_report_response.status_code == 200, get_report_response.text
    assert get_report_response.json()['failedItemCount'] == 2

    pdf_download = client.get(f'/api/reports/{job_id}/download/pdf')
    assert pdf_download.status_code == 200
    assert pdf_download.headers['content-type'].startswith('application/pdf')
    assert len(pdf_download.content) > 0

    docx_download = client.get(f'/api/reports/{job_id}/download/docx')
    assert docx_download.status_code == 200
    assert docx_download.headers['content-type'].startswith(
        'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
    )
    assert len(docx_download.content) > 0
