from __future__ import annotations

import json
from pathlib import Path

from app.services.notebook_accessibility import analyze_notebook_accessibility, run_notebook_accessibility_scan
from app.services.storage import get_extracted_dir


def _write_notebook(path: Path, cells: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "nbformat": 4,
                "nbformat_minor": 5,
                "metadata": {},
                "cells": cells,
            }
        ),
        encoding="utf-8",
    )


def _markdown(source: str) -> dict[str, object]:
    return {"cell_type": "markdown", "metadata": {}, "source": source}


def _code(
    source: str,
    *,
    execution_count: int | None = None,
    outputs: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    return {
        "cell_type": "code",
        "metadata": {},
        "source": source,
        "execution_count": execution_count,
        "outputs": outputs or [],
    }


def _status_by_check(path: Path) -> dict[str, str]:
    checks = analyze_notebook_accessibility(
        {"id": "notebook", "title": "Practica accesible", "type": "NOTEBOOK"},
        path,
    )
    return {check.checkId: check.status for check in checks}


def test_notebook_accessibility_passes_intro_title_and_markdown(tmp_path) -> None:
    notebook_path = tmp_path / "intro.ipynb"
    _write_notebook(
        notebook_path,
        [
            _markdown(
                "# Practica de analisis\n\n"
                "Este notebook explica el objetivo, los requisitos y el flujo principal de trabajo."
            ),
            _code("print('hola')", execution_count=1),
        ],
    )

    statuses = _status_by_check(notebook_path)

    assert statuses["notebook.readable"] == "PASS"
    assert statuses["notebook.intro_markdown"] == "PASS"
    assert statuses["notebook.title"] == "PASS"
    assert statuses["notebook.markdown_explanation"] == "PASS"


def test_notebook_accessibility_flags_notebook_without_markdown(tmp_path) -> None:
    notebook_path = tmp_path / "code-only.ipynb"
    _write_notebook(notebook_path, [_code("print('sin explicacion')", execution_count=1)])

    statuses = _status_by_check(notebook_path)

    assert statuses["notebook.intro_markdown"] == "FAIL"
    assert statuses["notebook.markdown_explanation"] == "FAIL"


def test_notebook_accessibility_warns_when_it_starts_with_code(tmp_path) -> None:
    notebook_path = tmp_path / "starts-code.ipynb"
    _write_notebook(
        notebook_path,
        [
            _code("x = 1", execution_count=1),
            _markdown("## Explicacion\n\nSe incluye contexto, pero llega despues del codigo inicial."),
        ],
    )

    statuses = _status_by_check(notebook_path)

    assert statuses["notebook.intro_markdown"] == "WARNING"


def test_notebook_accessibility_fails_markdown_image_without_alt(tmp_path) -> None:
    notebook_path = tmp_path / "image.ipynb"
    _write_notebook(
        notebook_path,
        [_markdown("# Imagen\n\n![](plot.png)\n\nTexto suficiente para explicar el notebook.")],
    )

    statuses = _status_by_check(notebook_path)

    assert statuses["notebook.image_alt"] == "FAIL"


def test_notebook_accessibility_fails_generic_link_text(tmp_path) -> None:
    notebook_path = tmp_path / "link.ipynb"
    _write_notebook(
        notebook_path,
        [_markdown("# Enlaces\n\nConsulta [aquí](https://example.com) para ampliar la informacion.")],
    )

    statuses = _status_by_check(notebook_path)

    assert statuses["notebook.links"] == "FAIL"


def test_notebook_accessibility_fails_saved_error_output(tmp_path) -> None:
    notebook_path = tmp_path / "error-output.ipynb"
    _write_notebook(
        notebook_path,
        [
            _markdown("# Error\n\nNotebook con contexto suficiente antes del codigo."),
            _code(
                "1 / 0",
                execution_count=1,
                outputs=[
                    {
                        "output_type": "error",
                        "ename": "ZeroDivisionError",
                        "evalue": "division by zero",
                        "traceback": [],
                    }
                ],
            ),
        ],
    )

    statuses = _status_by_check(notebook_path)

    assert statuses["notebook.execution_errors"] == "FAIL"


def test_notebook_accessibility_warns_unordered_execution(tmp_path) -> None:
    notebook_path = tmp_path / "unordered.ipynb"
    _write_notebook(
        notebook_path,
        [
            _markdown("# Orden\n\nNotebook con contexto suficiente para revisar la ejecucion."),
            _code("x = 1", execution_count=2),
            _code("y = 2", execution_count=1),
        ],
    )

    statuses = _status_by_check(notebook_path)

    assert statuses["notebook.execution_order"] == "WARNING"


def test_notebook_accessibility_job_scan_treats_other_ipynb_as_notebook(test_settings) -> None:
    job_id = "88888888-8888-8888-8888-888888888888"
    notebook_path = get_extracted_dir(test_settings, job_id) / "notebooks" / "lab.ipynb"
    _write_notebook(
        notebook_path,
        [
            _markdown(
                "# Laboratorio guiado\n\n"
                "Este notebook describe los pasos principales antes de ejecutar codigo."
            ),
            _code("print('ok')", execution_count=1),
        ],
    )

    report = run_notebook_accessibility_scan(
        settings=test_settings,
        job_id=job_id,
        resources=[
            {
                "id": "lab-notebook",
                "title": "Laboratorio Notebook",
                "type": "OTHER",
                "origin": "INTERNAL_FILE",
                "localPath": "notebooks/lab.ipynb",
                "accessStatus": "OK",
                "canAccess": True,
                "canDownload": True,
                "contentAvailable": True,
            }
        ],
    )

    assert report.summary.notebookResourcesTotal == 1
    assert report.summary.notebookResourcesAnalyzed == 1
    assert report.modules[0].resources[0].analysisType == "NOTEBOOK"


def test_notebook_accessibility_job_scan_skips_non_notebook_resources(test_settings) -> None:
    report = run_notebook_accessibility_scan(
        settings=test_settings,
        job_id="99999999-9999-9999-9999-999999999999",
        resources=[
            {
                "id": "pdf-guide",
                "title": "Guia PDF",
                "type": "PDF",
                "origin": "INTERNAL_FILE",
                "localPath": "docs/guide.pdf",
                "accessStatus": "OK",
                "contentAvailable": True,
            }
        ],
    )

    assert report.summary.notebookResourcesTotal == 0
    assert report.modules == []
