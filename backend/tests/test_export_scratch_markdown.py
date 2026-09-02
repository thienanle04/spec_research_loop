"""Export Scratch markdown projection, migration, and PDF rendering."""

from io import BytesIO

from pypdf import PdfReader

from app.modules.loop.export_scratch import (
    VALIDITY_BANNER,
    markdown_to_html,
    migrate_sections_document,
    project_export_scratch_document,
    render_export_scratch_pdf,
)


def _pdf_text(payload: bytes) -> str:
    return "\n".join(page.extract_text() or "" for page in PdfReader(BytesIO(payload)).pages)


def test_projection_bakes_validity_banner_when_blocked() -> None:
    document = project_export_scratch_document(
        {"nodes": {}},
        spec_version_id="spec-1",
        spec_version_is_valid=True,
        readiness_blocked=True,
    )
    assert document["markdown"].startswith("Source Spec Version: spec-1")
    assert VALIDITY_BANNER in document["markdown"]
    assert "## 1. Problem Statement" in document["markdown"]


def test_projection_omits_banner_when_ready_and_valid() -> None:
    document = project_export_scratch_document(
        {"nodes": {}},
        spec_version_id="spec-1",
        spec_version_is_valid=True,
        readiness_blocked=False,
    )
    assert VALIDITY_BANNER not in document["markdown"]


def test_legacy_sections_migrate_without_validity_banner() -> None:
    migrated = migrate_sections_document(
        {
            "sections": [
                {
                    "id": "problem_statement",
                    "title": "Problem Statement",
                    "body": "Overlay body",
                }
            ]
        },
        spec_version_id="spec-9",
    )
    assert migrated["markdown"].startswith("Source Spec Version: spec-9")
    assert VALIDITY_BANNER not in migrated["markdown"]
    assert "Overlay body" in migrated["markdown"]
    assert "## 1. Problem Statement" in migrated["markdown"]


def test_pdf_renders_gfm_and_math_features() -> None:
    markdown = "\n".join(
        [
            "# Title",
            "",
            "This is **bold** and a list:",
            "",
            "- alpha",
            "",
            "| method | n |",
            "| --- | --- |",
            "| tiling | 12 |",
            "",
            "Inline $F_1$ and",
            "",
            "$$E = mc^2$$",
            "",
        ]
    )
    html = markdown_to_html(markdown)
    assert "<strong>bold</strong>" in html or "<b>bold</b>" in html
    assert "<table>" in html
    assert "F_1" in html
    assert "E = mc^2" in html
    pdf = render_export_scratch_pdf(markdown)
    assert pdf.startswith(b"%PDF")
    text = _pdf_text(pdf)
    assert "bold" in text
    assert "tiling" in text
    assert "F_1" in text or "F1" in text
