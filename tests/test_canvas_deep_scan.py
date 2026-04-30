from __future__ import annotations

from app.services.canvas_deep_scan import extract_canvas_links


def test_extract_canvas_links_finds_downloads_internal_pages_and_dedupes() -> None:
    html = """
    <main>
      <a href="/courses/77/files/99/download">Plantilla accesible</a>
      <a href="https://canvas.example.edu/courses/77/files/99/download?wrap=1">Duplicado</a>
      <a href="/courses/77/pages/rubrica">Rubrica</a>
      <a href="/courses/77/files/metadata.xml">Metadata</a>
      <a href="https://external.example.org/info">Referencia externa</a>
      <a href="/courses/77/files/100/download">Anexo PDF</a>
    </main>
    """

    links = extract_canvas_links(
        html,
        base_url="https://canvas.example.edu/courses/77/pages/bienvenida",
        course_id="77",
        allowed_host="canvas.example.edu",
    )

    assert [link.title for link in links] == [
        "Plantilla accesible",
        "Rubrica",
        "Referencia externa",
        "Anexo PDF",
    ]
    assert links[0].file_id == "99"
    assert links[0].is_downloadable_candidate is True
    assert links[1].page_url == "rubrica"
    assert links[1].is_internal is True
    assert links[2].is_internal is False
    assert all(".xml" not in link.url for link in links)
