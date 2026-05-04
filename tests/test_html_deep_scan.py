from __future__ import annotations

import tempfile
from pathlib import Path

from app.services.course_structure import augment_course_structure, build_section_key
from app.services.imscc_parser import IMSCCParser


def _write(path: Path, content: str | bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, bytes):
        path.write_bytes(content)
        return
    path.write_text(content, encoding="utf-8")


def test_resolve_html_reference_handles_relative_segments_and_rejects_escape() -> None:
    parser = IMSCCParser()

    with tempfile.TemporaryDirectory() as temp_dir:
        extracted_root = Path(temp_dir) / "extract"
        html_path = extracted_root / "course" / "module" / "page.html"
        pdf_path = extracted_root / "course" / "downloads" / "guide.pdf"

        _write(html_path, "<html><body>Page</body></html>")
        _write(pdf_path, b"%PDF-1.4\n")

        resolved = parser.resolve_html_reference(
            "../downloads/guide.pdf?download=1#page=2",
            html_path,
            extracted_root,
        )

        assert resolved == pdf_path
        assert parser.resolve_html_reference("../../../../etc/passwd", html_path, extracted_root) is None


def test_discover_html_linked_resources_extracts_and_dedupes_nested_links() -> None:
    parser = IMSCCParser()

    with tempfile.TemporaryDirectory() as temp_dir:
        extracted_root = Path(temp_dir) / "extract"
        page_one = extracted_root / "course" / "module" / "page.html"
        page_two = extracted_root / "course" / "module" / "nested" / "page2.html"
        guide_pdf = extracted_root / "course" / "downloads" / "guide.pdf"
        slides_pptx = extracted_root / "course" / "downloads" / "slides.pptx"
        chart_png = extracted_root / "course" / "images" / "chart.png"
        metadata_xml = extracted_root / "course" / "metadata" / "item.xml"

        _write(
            page_one,
            """
            <html><body>
              <a href="../downloads/guide.pdf">Guía descargable</a>
              <a href="../downloads/guide.pdf#again">Guía descargable</a>
              <img src="../images/chart.png" alt="Gráfico resumen" />
              <a href="https://example.com/resource">Recurso web</a>
              <iframe src="https://www.youtube.com/watch?v=demo123"></iframe>
              <a href="nested/page2.html">Siguiente página</a>
              <a href="../metadata/item.xml">Metadata</a>
            </body></html>
            """,
        )
        _write(
            page_two,
            """
            <html><body>
              <a href="../../downloads/slides.pptx">Presentación final</a>
            </body></html>
            """,
        )
        _write(guide_pdf, b"%PDF-1.4\n")
        _write(slides_pptx, b"PPTX")
        _write(chart_png, b"PNG")
        _write(metadata_xml, "<metadata />")

        inventory = [
            {
                "id": "html-1",
                "title": "Página 1",
                "type": "WEB",
                "path": "course/module/page.html",
                "filePath": "course/module/page.html",
                "localPath": "course/module/page.html",
                "coursePath": "Módulo 1",
                "modulePath": "Módulo 1",
                "moduleTitle": "Módulo 1",
                "sectionTitle": "Módulo 1",
                "itemPath": "Módulo 1 > Página 1",
                "status": "OK",
                "details": {},
            },
            {
                "id": "html-2",
                "title": "Página 2",
                "type": "WEB",
                "path": "course/module/nested/page2.html",
                "filePath": "course/module/nested/page2.html",
                "localPath": "course/module/nested/page2.html",
                "coursePath": "Módulo 1",
                "modulePath": "Módulo 1",
                "moduleTitle": "Módulo 1",
                "sectionTitle": "Módulo 1",
                "itemPath": "Módulo 1 > Página 2",
                "status": "OK",
                "details": {},
            },
        ]

        discovered = parser.discover_html_linked_resources(
            inventory,
            extracted_root,
            excluded_extensions={".xml"},
        )

        references = {resource.get("path") or resource.get("url"): resource for resource in discovered}

        assert set(references) == {
            "course/downloads/guide.pdf",
            "course/images/chart.png",
            "course/downloads/slides.pptx",
            "https://example.com/resource",
            "https://www.youtube.com/watch?v=demo123",
        }
        assert references["course/downloads/guide.pdf"]["type"] == "PDF"
        assert references["course/images/chart.png"]["type"] == "IMAGE"
        assert references["course/downloads/slides.pptx"]["type"] == "OTHER"
        assert references["https://example.com/resource"]["type"] == "WEB"
        assert references["https://www.youtube.com/watch?v=demo123"]["type"] == "VIDEO"
        assert references["course/downloads/guide.pdf"]["title"] == "Guía descargable"
        assert references["course/images/chart.png"]["title"] == "Gráfico resumen"
        assert references["course/downloads/guide.pdf"]["parentResourceId"] == "html-1"
        assert references["course/downloads/guide.pdf"]["parentId"] == "html-1"
        assert references["course/downloads/guide.pdf"]["coursePath"] == "Módulo 1"
        assert references["course/downloads/guide.pdf"]["moduleTitle"] == "Módulo 1"
        assert references["course/downloads/guide.pdf"]["sectionTitle"] == "Módulo 1"
        assert references["course/downloads/guide.pdf"]["origin"] == "INTERNAL_FILE"
        assert references["course/downloads/guide.pdf"]["contentAvailable"] is True
        assert references["https://example.com/resource"]["origin"] == "EXTERNAL_URL"
        assert references["https://example.com/resource"]["contentAvailable"] is False
        assert inventory[0]["discoveredChildrenCount"] == 4
        assert inventory[1]["discoveredChildrenCount"] == 1


def test_augment_course_structure_merges_equivalent_sections_and_keeps_discovered_under_parent() -> None:
    structure = {
        "title": "Curso demo",
        "organizations": [
            {
                "nodeId": "org-1",
                "title": "Curso demo",
                "children": [
                    {
                        "nodeId": "section-1",
                        "title": "PEC 2: práctica",
                        "resourceId": None,
                        "children": [
                            {
                                "nodeId": "page-1",
                                "title": "Página principal",
                                "resourceId": "res-html",
                                "children": [],
                            }
                        ],
                    },
                    {
                        "nodeId": "section-2",
                        "title": "PEC2 practica",
                        "resourceId": None,
                        "children": [],
                    },
                ],
            }
        ],
        "unplacedResourceIds": [],
    }
    resources = [
        {
            "id": "res-html",
            "title": "Página principal",
            "modulePath": "PEC 2: práctica",
            "itemPath": "PEC 2: práctica > Página principal",
        },
        {
            "id": "discovered-pdf",
            "title": "Guía descargable",
            "modulePath": "PEC2 practica",
            "itemPath": "PEC2 practica > Página principal > Guía descargable",
            "parentResourceId": "res-html",
            "discovered": True,
        },
    ]

    augmented = augment_course_structure(structure, resources)

    assert augmented is not None
    organization = augmented["organizations"][0]
    assert len(organization["children"]) == 1
    assert build_section_key("PEC 2: práctica") == build_section_key("PEC2 practica")
    section = organization["children"][0]
    assert section["title"] == "PEC 2: práctica"
    page = section["children"][0]
    assert page["resourceId"] == "res-html"
    assert page["children"][0]["resourceId"] == "discovered-pdf"
