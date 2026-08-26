"""Focused tests for federated retrieval and S3 text persistence."""

from uuid import uuid4

import pytest

from app.adapters.storage import MemoryObjectStorage
from app.modules.research.adapters import (
    CompositeScholarlySource,
    FakeCitationVerifier,
    FakeLlmPort,
    FakeScholarlySourcePort,
)
from app.modules.research.adapters.document_text import _html_text, _normalize_text
from app.modules.research.models import Citation
from app.modules.research.ports import DocumentText, ScholarlyRecord
from app.modules.research.service import (
    ResearchService,
    _deduplicate_records,
    _is_usable_research_document,
)


class _DocumentSource:
    async def fetch_text(self, *, record: ScholarlyRecord) -> DocumentText:
        return DocumentText(
            text=f"Abstract\n\n{record.abstract}\n\nLimitations\nOnly one benchmark.",
            source_url="https://example.org/paper.pdf",
            source_kind="full_text_pdf",
            original_content_type="application/pdf",
        )


def test_html_extraction_prefers_article_content_and_drops_page_chrome() -> None:
    html = b"""
    <html><body>
      <header><form>Username Password Remember me</form></header>
      <nav>Home About Login Search Current Archives Browse By Title</nav>
      <main><article>
        <h2>Abstract</h2>
        <p>This study evaluates reverse-logistics service quality for online shoppers.</p>
        <h2>Research methodology</h2>
        <p>Data were collected from 300 participants using a structured questionnaire.</p>
      </article></main>
      <footer>Journal index and account controls</footer>
    </body></html>
    """

    text = _normalize_text(_html_text(html))

    assert "Username" not in text
    assert "Current Archives" not in text
    assert "Journal index" not in text
    assert "[Section] Abstract" in text
    assert "This study evaluates reverse-logistics" in text


def test_deduplicate_merges_provider_provenance_and_best_text() -> None:
    openalex = ScholarlyRecord(
        title="Grounded Related Work",
        year=2026,
        doi="10.1000/grounded",
        abstract="Short abstract.",
        provider="openalex",
        provider_source_id="W1",
        metadata={
            "provider_ids": {"openalex": "W1"},
            "discovery_queries": ["grounded retrieval"],
        },
    )
    semantic_scholar = ScholarlyRecord(
        title="Grounded Related Work",
        year=2026,
        doi="https://doi.org/10.1000/GROUNDED",
        abstract="A longer abstract with method and limitation details.",
        provider="semantic_scholar",
        provider_source_id="S1",
        metadata={
            "provider_ids": {"semantic_scholar": "S1"},
            "discovery_types": ["references"],
            "full_text_url": "https://example.org/paper.pdf",
        },
    )

    merged = _deduplicate_records([openalex, semantic_scholar])

    assert len(merged) == 1
    assert merged[0].abstract == semantic_scholar.abstract
    assert merged[0].metadata["provider_ids"] == {
        "openalex": "W1",
        "semantic_scholar": "S1",
    }
    assert merged[0].metadata["full_text_url"].endswith("paper.pdf")


def test_full_text_requirement_rejects_missing_or_abstract_only_documents() -> None:
    abstract = DocumentText(text="Provider abstract", source_kind="abstract")
    full_text = DocumentText(text="Downloaded paper text", source_kind="full_text_pdf")

    assert not _is_usable_research_document(
        None,
        require_downloadable_full_text=True,
    )
    assert not _is_usable_research_document(
        abstract,
        require_downloadable_full_text=True,
    )
    assert _is_usable_research_document(
        full_text,
        require_downloadable_full_text=True,
    )
    assert _is_usable_research_document(
        abstract,
        require_downloadable_full_text=False,
    )


@pytest.mark.asyncio
async def test_composite_search_keeps_partial_provider_results() -> None:
    healthy = FakeScholarlySourcePort()
    failing = FakeScholarlySourcePort(error=TimeoutError("offline"))
    source = CompositeScholarlySource([failing, healthy])

    records = await source.search(query="prompt optimization", limit=5)

    assert len(records) == 2


@pytest.mark.asyncio
async def test_retrieved_text_is_stored_by_checksum() -> None:
    storage = MemoryObjectStorage()
    service = ResearchService(
        object(),  # type: ignore[arg-type]
        source=FakeScholarlySourcePort(),
        verifier=FakeCitationVerifier(),
        llm=FakeLlmPort(),
        document_text_source=_DocumentSource(),
        object_storage=storage,
    )
    session_id = uuid4()
    citation = Citation(
        id=uuid4(),
        session_id=session_id,
        citation_key="grounded-2026",
        title="Grounded Related Work",
        authors=[],
        source_metadata={},
    )
    record = ScholarlyRecord(
        title=citation.title,
        abstract="The method retrieves passages by section.",
    )

    document, warnings = await service._persist_document_text(
        session_id=session_id,
        citation=citation,
        record=record,
    )

    assert document is not None
    assert warnings == []
    assert citation.text_object_key is not None
    assert citation.text_object_key.endswith(f"{citation.text_checksum}.txt")
    assert (await storage.get_bytes(key=citation.text_object_key)).decode() == document.text
    assert citation.text_source_kind == "full_text_pdf"
    assert citation.text_char_count == len(document.text)
