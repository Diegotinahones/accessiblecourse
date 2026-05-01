from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from zipfile import ZipFile

from app.services.imscc_parser import IMSCCParser, ParserError, classify_resource

MANIFEST_WITH_NAMESPACE = """<?xml version="1.0" encoding="UTF-8"?>
<manifest
    xmlns="http://www.imsglobal.org/xsd/imsccv1p1/imscp_v1p1"
    xmlns:lom="http://ltsc.ieee.org/xsd/imsccv1p1/LOM/resource"
    identifier="demo-course">
  <metadata>
    <lom:lom>
      <lom:general>
        <lom:title>
          <lom:string>Demo Accessible Course</lom:string>
        </lom:title>
      </lom:general>
    </lom:lom>
  </metadata>
  <organizations>
    <organization identifier="org-1">
      <title>Demo Accessible Course</title>
      <item identifier="module-1">
        <title>Módulo 1</title>
        <item identifier="lesson-1" identifierref="res-html">
          <title>Página HTML</title>
        </item>
        <item identifier="lesson-2" identifierref="res-video">
          <title>Video de apoyo</title>
        </item>
      </item>
    </organization>
  </organizations>
  <resources>
    <resource identifier="res-html" type="webcontent" href="course/module1/page.html">
      <file href="course/module1/page.html" />
    </resource>
    <resource identifier="res-video" type="imswl_xmlv1p1" href="web_resources/video_link.xml">
      <file href="web_resources/video_link.xml" />
    </resource>
  </resources>
</manifest>
"""


WEB_LINK_XML = """<?xml version="1.0" encoding="UTF-8"?>
<webLink xmlns="http://www.imsglobal.org/xsd/imswl_v1p1">
  <title>Video externo</title>
  <url href="https://www.youtube.com/watch?v=demo123" />
</webLink>
"""


MANIFEST_WITH_MISSING_FILE = """<?xml version="1.0" encoding="UTF-8"?>
<manifest xmlns="http://www.imsglobal.org/xsd/imsccv1p1/imscp_v1p1" identifier="missing-file">
  <organizations>
    <organization identifier="org-1">
      <title>Missing file course</title>
      <item identifier="item-1" identifierref="res-pdf">
        <title>PDF inexistente</title>
      </item>
    </organization>
  </organizations>
  <resources>
    <resource identifier="res-pdf" type="webcontent" href="docs/missing.pdf">
      <file href="docs/missing.pdf" />
    </resource>
  </resources>
</manifest>
"""


MANIFEST_WITH_METADATA_RESOURCE = """<?xml version="1.0" encoding="UTF-8"?>
<manifest xmlns="http://www.imsglobal.org/xsd/imsccv1p1/imscp_v1p1" identifier="metadata-only">
  <organizations>
    <organization identifier="org-1">
      <title>Metadata only</title>
      <item identifier="item-1" identifierref="res-metadata">
        <title>Metadata XML</title>
      </item>
    </organization>
  </organizations>
  <resources>
    <resource identifier="res-metadata" type="webcontent" href="metadata/resource.xml">
      <file href="metadata/resource.xml" />
    </resource>
  </resources>
</manifest>
"""


MANIFEST_WITH_LTI_RESOURCE = """<?xml version="1.0" encoding="UTF-8"?>
<manifest xmlns="http://www.imsglobal.org/xsd/imsccv1p1/imscp_v1p1" identifier="lti-course">
  <organizations>
    <organization identifier="org-1">
      <title>Curso con LTI</title>
      <item identifier="module-1">
        <title>Módulo 1</title>
        <item identifier="item-lti" identifierref="res-lti">
          <title>Learning Tools</title>
        </item>
        <item identifier="item-pdf" identifierref="res-pdf">
          <title>Apunte PDF</title>
        </item>
      </item>
    </organization>
  </organizations>
  <resources>
    <resource identifier="res-lti" type="associatedcontent/imscc_xmlv1p1/learning-application-resource" href="lti_resource_links/tool.xml">
      <file href="lti_resource_links/tool.xml" />
    </resource>
    <resource identifier="res-pdf" type="webcontent" href="docs/apunte.pdf">
      <file href="docs/apunte.pdf" />
    </resource>
  </resources>
</manifest>
"""


MANIFEST_WITH_TITLE_FALLBACKS = """<?xml version="1.0" encoding="UTF-8"?>
<manifest xmlns="http://www.imsglobal.org/xsd/imsccv1p1/imscp_v1p1" identifier="title-fallbacks">
  <metadata>
    <title>Curso con títulos heredados</title>
  </metadata>
  <organizations>
    <organization identifier="org-1">
      <item identifier="module-1">
        <title>Untitled item</title>
        <item identifier="lesson-1" identifierref="res-guide">
          <title>Untitled item</title>
        </item>
        <item identifier="group-1">
          <item identifier="lesson-2" identifierref="res-link">
            <title>Tema práctico</title>
          </item>
        </item>
      </item>
    </organization>
  </organizations>
  <resources>
    <resource identifier="res-guide" type="webcontent" href="docs/Guia_docente.pdf">
      <file href="docs/Guia_docente.pdf" />
    </resource>
    <resource identifier="res-link" type="webcontent" href="docs/practica.html">
      <file href="docs/practica.html" />
    </resource>
    <resource identifier="res-orphan" type="webcontent" href="docs/orphan.html">
      <file href="docs/orphan.html" />
    </resource>
  </resources>
</manifest>
"""


class IMSCCParserTests(unittest.TestCase):
    def setUp(self) -> None:
        self.parser = IMSCCParser()

    def test_safe_extract_archive_blocks_zip_slip(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            archive_path = temp_path / "bad.imscc"
            destination = temp_path / "extract"
            with ZipFile(archive_path, "w") as archive:
                archive.writestr("../escape.txt", "malicious")

            with self.assertRaises(ParserError):
                self.parser.safe_extract_archive(archive_path, destination)

    def test_parse_manifest_with_namespace_and_external_link(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            archive_path = temp_path / "sample.imscc"
            destination = temp_path / "extract"
            self._build_archive(
                archive_path,
                {
                    "imsmanifest.xml": MANIFEST_WITH_NAMESPACE,
                    "course/module1/page.html": "<html><body>Lesson</body></html>",
                    "web_resources/video_link.xml": WEB_LINK_XML,
                },
            )

            self.parser.safe_extract_archive(archive_path, destination)
            manifest_path = self.parser.find_manifest(destination)
            parsed_manifest = self.parser.parse_manifest(manifest_path, destination)
            resources = self.parser.build_resource_inventory(parsed_manifest, manifest_path, destination)

            self.assertEqual(parsed_manifest.course_title, "Demo Accessible Course")
            self.assertEqual(len(resources), 2)

            by_identifier = {resource["identifier"]: resource for resource in resources}
            self.assertEqual(by_identifier["res-html"]["type"], "WEB")
            self.assertEqual(by_identifier["res-html"]["origin"], "internal_page")
            self.assertEqual(by_identifier["res-html"]["path"], "course/module1/page.html")
            self.assertEqual(by_identifier["res-html"]["coursePath"], "Módulo 1")
            self.assertEqual(by_identifier["res-html"]["modulePath"], "Módulo 1")
            self.assertEqual(by_identifier["res-html"]["itemPath"], "Módulo 1 > Página HTML")
            self.assertEqual(by_identifier["res-video"]["origin"], "external_url")
            self.assertEqual(by_identifier["res-video"]["url"], "https://www.youtube.com/watch?v=demo123")
            self.assertEqual(by_identifier["res-video"]["modulePath"], "Módulo 1")
            self.assertEqual(by_identifier["res-video"]["type"], "VIDEO")

    def test_classify_resource_types(self) -> None:
        self.assertEqual(classify_resource("https://www.youtube.com/watch?v=abc", is_external=True), "VIDEO")
        self.assertEqual(classify_resource("https://example.com/guide", is_external=True), "WEB")
        self.assertEqual(classify_resource("slides/week1.ipynb"), "NOTEBOOK")
        self.assertEqual(classify_resource("docs/manual.pdf"), "PDF")
        self.assertEqual(classify_resource("media/diagram.svg"), "IMAGE")
        self.assertEqual(classify_resource("files/archive.docx"), "OTHER")

    def test_marks_missing_internal_file_as_warning(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            archive_path = temp_path / "missing.imscc"
            destination = temp_path / "extract"
            self._build_archive(archive_path, {"imsmanifest.xml": MANIFEST_WITH_MISSING_FILE})

            self.parser.safe_extract_archive(archive_path, destination)
            manifest_path = self.parser.find_manifest(destination)
            parsed_manifest = self.parser.parse_manifest(manifest_path, destination)
            resources = self.parser.build_resource_inventory(parsed_manifest, manifest_path, destination)

            self.assertEqual(len(resources), 1)
            resource = resources[0]
            self.assertEqual(resource["status"], "WARN")
            self.assertEqual(resource["path"], "docs/missing.pdf")
            self.assertIn("no existe dentro del paquete", resource["notes"][0])

    def test_excludes_internal_metadata_xml_resources(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            archive_path = temp_path / "metadata.imscc"
            destination = temp_path / "extract"
            self._build_archive(
                archive_path,
                {
                    "imsmanifest.xml": MANIFEST_WITH_METADATA_RESOURCE,
                    "metadata/resource.xml": "<metadata />",
                },
            )

            self.parser.safe_extract_archive(archive_path, destination)
            manifest_path = self.parser.find_manifest(destination)
            parsed_manifest = self.parser.parse_manifest(manifest_path, destination)
            resources = self.parser.build_resource_inventory(parsed_manifest, manifest_path, destination)

            self.assertEqual(resources, [])

    def test_ignores_lti_resources_and_learning_tools_nodes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            archive_path = temp_path / "lti.imscc"
            destination = temp_path / "extract"
            self._build_archive(
                archive_path,
                {
                    "imsmanifest.xml": MANIFEST_WITH_LTI_RESOURCE,
                    "lti_resource_links/tool.xml": "<tool />",
                    "docs/apunte.pdf": b"%PDF-1.4\n",
                },
            )

            self.parser.safe_extract_archive(archive_path, destination)
            manifest_path = self.parser.find_manifest(destination)
            parsed_manifest = self.parser.parse_manifest(manifest_path, destination)
            resources = self.parser.build_resource_inventory(parsed_manifest, manifest_path, destination)

            self.assertEqual([resource["identifier"] for resource in resources], ["res-pdf"])
            organization = parsed_manifest.structure["organizations"][0]
            self.assertEqual(organization["children"][0]["title"], "Módulo 1")
            self.assertEqual([child["resourceId"] for child in organization["children"][0]["children"]], ["res-pdf"])

    def test_resolves_titles_from_resource_or_child_and_keeps_unmapped_resources_outside_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            archive_path = temp_path / "fallbacks.imscc"
            destination = temp_path / "extract"
            self._build_archive(
                archive_path,
                {
                    "imsmanifest.xml": MANIFEST_WITH_TITLE_FALLBACKS,
                    "docs/Guia_docente.pdf": "%PDF-1.4\n",
                    "docs/practica.html": "<html><body>Practica</body></html>",
                    "docs/orphan.html": "<html><body>Orphan</body></html>",
                },
            )

            self.parser.safe_extract_archive(archive_path, destination)
            manifest_path = self.parser.find_manifest(destination)
            parsed_manifest = self.parser.parse_manifest(manifest_path, destination)
            resources = self.parser.build_resource_inventory(parsed_manifest, manifest_path, destination)

            organizations = parsed_manifest.structure["organizations"]
            self.assertEqual(len(organizations), 1)
            organization = organizations[0]
            self.assertEqual(organization["title"], "Curso con títulos heredados")
            self.assertEqual([child["title"] for child in organization["children"]], ["Guia docente", "Tema práctico"])
            self.assertEqual(organization["children"][0]["resourceId"], "res-guide")
            self.assertEqual(organization["children"][0]["children"], [])
            self.assertEqual(organization["children"][1]["resourceId"], "res-link")
            self.assertEqual(parsed_manifest.structure["unplacedResourceIds"], ["res-orphan"])
            self.assertNotIn("Untitled item", str(parsed_manifest.structure))

            by_identifier = {resource["identifier"]: resource for resource in resources}
            self.assertEqual(by_identifier["res-guide"]["title"], "Guia docente")
            self.assertEqual(by_identifier["res-guide"]["itemPath"], "Guia docente")
            self.assertEqual(by_identifier["res-link"]["itemPath"], "Tema práctico")
            self.assertIsNone(by_identifier["res-orphan"]["coursePath"])
            self.assertIsNone(by_identifier["res-orphan"]["modulePath"])
            self.assertIsNone(by_identifier["res-orphan"]["itemPath"])

    def _build_archive(self, archive_path: Path, files: dict[str, str]) -> None:
        with ZipFile(archive_path, "w") as archive:
            for relative_path, content in files.items():
                archive.writestr(relative_path, content)


if __name__ == "__main__":
    unittest.main()
