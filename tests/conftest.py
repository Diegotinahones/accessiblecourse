from __future__ import annotations

import io
from pathlib import Path
from zipfile import ZipFile

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app


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


@pytest.fixture()
def test_settings(tmp_path: Path) -> Settings:
    return Settings(
        environment='test',
        database_url=f'sqlite:///{tmp_path / "test.db"}',
        storage_root=tmp_path / 'data',
        cors_origins=['http://localhost:5173'],
        max_upload_mb=10,
        max_extracted_files=50,
        max_extracted_mb=20,
        log_level='DEBUG',
    )


@pytest.fixture()
def client(test_settings: Settings) -> TestClient:
    app = create_app(test_settings)
    return TestClient(app)
