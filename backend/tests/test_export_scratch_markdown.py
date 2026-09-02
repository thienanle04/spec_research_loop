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
    assert "## 6. Claims and Evidence" in document["markdown"]
    assert "## 7. Experiment Plan" in document["markdown"]
    assert "## 7. Evidence" not in document["markdown"]


def test_projection_pairs_claim_and_evidence_and_labels_experiment() -> None:
    document = project_export_scratch_document(
        {
            "nodes": {
                "claims": {
                    "card_snapshot": [
                        {
                            "kind": "claim",
                            "body": {
                                "text": "Claim: blob\nBaseline: ignored blob",
                                "metadata": {
                                    "id": "gen-1",
                                    "claim": "Tiling cuts DRAM traffic",
                                    "baseline": "Untiled kernel",
                                    "metric": "DRAM bytes",
                                    "evidence": "do not use this copy",
                                    "rejection_condition": "No 20% cut",
                                },
                            },
                        },
                        {
                            "kind": "evidence",
                            "body": {
                                "text": "Held-out traces",
                                "metadata": {"source_claim_id": "gen-1"},
                            },
                        },
                        {
                            "kind": "evidence",
                            "body": {"text": "Orphan measurement"},
                        },
                    ]
                },
                "experiment_plan": {
                    "narrative": {
                        "plan": {
                            "experiments": [
                                {
                                    "claim": "Tiling cuts DRAM traffic",
                                    "action": "Run tiled vs untiled kernels",
                                    "objective": "Measure DRAM traffic",
                                    "significance": "Tests the claim",
                                }
                            ]
                        }
                    }
                },
            }
        },
        spec_version_id="spec-1",
        spec_version_is_valid=True,
        readiness_blocked=False,
    )
    body = document["markdown"]
    claims = body.split("## 6. Claims and Evidence", 1)[1].split(
        "## 7. Experiment Plan", 1
    )[0]
    experiment = body.split("## 7. Experiment Plan", 1)[1].split("## 8.", 1)[0]
    assert "### Tiling cuts DRAM traffic" in claims
    assert "**Baseline:**\nUntiled kernel" in claims
    assert "**Metric:**\nDRAM bytes" in claims
    assert "**Expected Evidence:**\nHeld-out traces" in claims
    assert "**Rejection Condition:**\nNo 20% cut" in claims
    assert "do not use this copy" not in claims
    assert "ignored blob" not in claims
    assert "### Unpaired evidence" in claims
    assert "Orphan measurement" in claims
    assert "**Action:**\nRun tiled vs untiled kernels" in experiment
    assert "**Objective:**\nMeasure DRAM traffic" in experiment
    assert "**Significance:**\nTests the claim" in experiment


def test_projection_unpaired_claim_uses_statement_without_parsing_blob() -> None:
    document = project_export_scratch_document(
        {
            "nodes": {
                "claims": {
                    "card_snapshot": [
                        {
                            "kind": "claim",
                            "body": {"statement": "A statement-only claim"},
                        },
                        {
                            "kind": "evidence",
                            "body": {"text": "Loose evidence"},
                        },
                    ]
                }
            }
        },
        spec_version_id="spec-1",
        spec_version_is_valid=True,
        readiness_blocked=False,
    )
    claims = document["markdown"].split("## 6. Claims and Evidence", 1)[1]
    assert "### A statement-only claim" in claims
    assert "**Baseline:**" not in claims
    assert "### Unpaired evidence" in claims
    assert "Loose evidence" in claims


def test_legacy_sections_fold_evidence_into_claims_heading() -> None:
    migrated = migrate_sections_document(
        {
            "sections": [
                {"id": "claims", "title": "Claims", "body": "Claim dump"},
                {"id": "evidence", "title": "Evidence", "body": "Evidence dump"},
            ]
        },
        spec_version_id="spec-9",
    )
    body = migrated["markdown"]
    claims = body.split("## 6. Claims and Evidence", 1)[1].split(
        "## 7. Experiment Plan", 1
    )[0]
    assert "Claim dump" in claims
    assert "Evidence dump" in claims
    assert "## 7. Evidence" not in body


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
