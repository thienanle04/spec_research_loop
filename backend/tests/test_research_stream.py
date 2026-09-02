"""Research SSE generation tests using deterministic fake providers."""

import json
from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.adapters.storage import MemoryObjectStorage
from app.core.config import get_settings
from app.db.session import get_session_factory
from app.modules.research.adapters.fake_llm import FakeLlmPort
from app.modules.research.adapters.fake_source import (
    FakeCitationVerifier,
    FakeScholarlySourcePort,
)
from app.modules.research.models import Citation, RelatedWorkFinding
from app.modules.research.ports import DocumentText, ScholarlyRecord, VerificationResult
from app.modules.research.schemas import (
    ResearchGenerateRequest,
    ResearchNode,
    VerificationStatus,
)
from app.modules.research.service import ResearchService
from tests.test_loop_api import (
    _auth_client,
    _confirm,
    _create_card,
    _create_session,
    _interpret,
    _patch_working_draft,
    _prepare,
)
from tests.test_research_api import _prepare_related_work


def _events(body: str) -> list[dict]:
    return [
        json.loads(line.removeprefix("data: "))
        for line in body.splitlines()
        if line.startswith("data: ")
    ]


class _SelectiveDocumentSource:
    async def fetch_text(self, *, record: ScholarlyRecord) -> DocumentText | None:
        if record.provider_source_id == "blocked":
            return None
        return DocumentText(
            text=(record.abstract or record.title) * 8,
            source_url=f"https://example.org/{record.provider_source_id}.pdf",
            source_kind="full_text_pdf",
            original_content_type="application/pdf",
        )


class _MetadataAwareDocumentSource:
    def __init__(self) -> None:
        self.seen_full_text_urls: list[str | None] = []

    async def fetch_text(self, *, record: ScholarlyRecord) -> DocumentText | None:
        full_text_url = record.metadata.get("full_text_url")
        self.seen_full_text_urls.append(
            str(full_text_url) if full_text_url else None
        )
        if not full_text_url:
            return None
        return DocumentText(
            text=(record.abstract or record.title) * 8,
            source_url=str(full_text_url),
            source_kind="full_text_pdf",
            original_content_type="application/pdf",
        )


class _FullTextEnrichingVerifier:
    @staticmethod
    def _result(record: ScholarlyRecord) -> VerificationResult:
        resolved = ScholarlyRecord(
            title=record.title,
            abstract=record.abstract,
            provider="openalex",
            provider_source_id=record.provider_source_id,
            metadata={"full_text_url": "https://example.org/resolved-paper.pdf"},
        )
        return VerificationResult(
            status=VerificationStatus.VERIFIED,
            record=resolved,
        )

    async def verify(self, *, citation: ScholarlyRecord) -> VerificationResult:
        return self._result(citation)

    async def verify_many(
        self,
        *,
        citations: list[ScholarlyRecord],
    ) -> list[VerificationResult]:
        return [self._result(citation) for citation in citations]


@pytest.mark.asyncio
async def test_research_inputs_stream_updates_working_narrative(
    client: AsyncClient,
) -> None:
    await _auth_client(client)
    created = await _create_session(client)
    interpreted = await _interpret(client, created["id"], created["version"])
    decomposed = await _confirm(
        client,
        created["id"],
        "idea_decomposition",
        interpreted["version"],
    )
    draft = await _prepare(
        client,
        created["id"],
        "related_work",
        decomposed["version"],
    )
    response = await client.post(
        f"/api/research/sessions/{created['id']}/nodes/research_inputs/generate",
        json={"expected_version": draft["version"]},
    )
    assert response.status_code == 200, response.text
    events = _events(response.text)
    patch = next(event for event in events if event["type"] == "draft_patch")
    assert patch["narrative"]["keywords"]
    assert events[-1]["type"] == "done"
    fetched = await client.get(f"/api/loop/sessions/{created['id']}")
    assert fetched.json()["working_draft_narrative"] == patch["narrative"]


@pytest.mark.asyncio
async def test_related_work_stream_persists_citations_and_findings(
    client: AsyncClient,
) -> None:
    await _auth_client(client)
    draft = await _prepare_related_work(client)
    session_id = draft["id"]
    response = await client.post(
        f"/api/research/sessions/{session_id}/nodes/related_work/generate",
        json={"expected_version": draft["version"], "max_results": 2},
    )
    assert response.status_code == 200, response.text
    events = _events(response.text)
    assert events[0]["type"] == "progress"
    assert events[-1] == {
        "type": "done",
        "node": "related_work",
        "version": draft["version"] + 1,
        "citation_count": 1,
    }
    assert [event["type"] for event in events].count("citation_upsert") == 1
    assert any(event["type"] == "draft_patch" for event in events)

    listed = await client.get(f"/api/research/sessions/{session_id}/citations")
    assert len(listed.json()) == 1
    assert all(item["text_object_key"] for item in listed.json())
    assert all(item["text_checksum"] for item in listed.json())
    assert all(item["text_source_kind"] == "abstract" for item in listed.json())
    listed_findings = await client.get(f"/api/research/sessions/{session_id}/findings")
    assert listed_findings.status_code == 200
    assert len(listed_findings.json()) == 1
    assert all(item["citation_id"] for item in listed_findings.json())
    assert all(item["supporting_passage"] for item in listed_findings.json())
    assert all(item["source_object_key"] for item in listed_findings.json())
    abstract_warnings = [
        event
        for event in events
        if event["type"] == "warning"
        and event.get("code") == "abstract_only_findings"
    ]
    assert abstract_warnings == []
    patch = next(event for event in events if event["type"] == "draft_patch")
    assert patch["narrative"]["abstract_only_finding_count"] == 0

    old_ids = {item["id"] for item in listed.json()}
    old_finding_ids = {item["id"] for item in listed_findings.json()}
    for pinned_id in old_ids:
        pinned = await client.patch(
            f"/api/research/sessions/{session_id}/citations/{pinned_id}/selection",
            json={"pinned": True},
        )
        assert pinned.status_code == 200, pinned.text
        assert pinned.json()["pinned"] is True

    rerun = await client.post(
        f"/api/research/sessions/{session_id}/nodes/related_work/generate",
        json={"expected_version": events[-1]["version"], "max_results": 1},
    )
    assert rerun.status_code == 200, rerun.text
    after_rerun = await client.get(f"/api/research/sessions/{session_id}/citations")
    assert len(after_rerun.json()) == 1
    assert {item["id"] for item in after_rerun.json()}.isdisjoint(old_ids)
    assert all(not item["pinned"] for item in after_rerun.json())
    async with get_session_factory()() as db:
        citations = list(
            (
                await db.scalars(
                    select(Citation).where(
                        Citation.session_id == UUID(session_id),
                        Citation.stage_revision_id.is_(None),
                    )
                )
            ).all()
        )
        findings = list(
            (
                await db.scalars(
                    select(RelatedWorkFinding).where(
                        RelatedWorkFinding.session_id == UUID(session_id),
                        RelatedWorkFinding.stage_revision_id.is_(None),
                    )
                )
            ).all()
        )
        assert len(citations) == 1
        assert len(findings) == 1
        assert {str(item.id) for item in findings}.isdisjoint(old_finding_ids)
        assert all(item.citation_id for item in findings)
        assert all(item.supporting_passage for item in findings)


@pytest.mark.asyncio
async def test_unconfirmed_search_survives_research_inputs_continue(
    client: AsyncClient,
) -> None:
    await _auth_client(client)
    draft = await _prepare_related_work(client)
    session_id = draft["id"]
    generated = await client.post(
        f"/api/research/sessions/{session_id}/nodes/related_work/generate",
        json={"expected_version": draft["version"], "max_results": 2},
    )
    assert generated.status_code == 200, generated.text
    events = _events(generated.text)
    generated_narrative = next(
        event["narrative"] for event in events if event["type"] == "draft_patch"
    )
    generated_citations = (
        await client.get(f"/api/research/sessions/{session_id}/citations")
    ).json()
    generated_findings = (
        await client.get(f"/api/research/sessions/{session_id}/findings")
    ).json()

    reopened_inputs = await _patch_working_draft(
        client,
        session_id,
        expected_version=events[-1]["version"],
        node="research_inputs",
    )
    assert reopened_inputs.status_code == 200, reopened_inputs.text
    reconfirmed_inputs = await _confirm(
        client,
        session_id,
        "research_inputs",
        reopened_inputs.json()["version"],
    )
    continued = await _prepare(
        client,
        session_id,
        "related_work",
        reconfirmed_inputs["version"],
    )

    assert continued["working_draft_node"] == "related_work"
    assert continued["working_draft_narrative"] == generated_narrative
    assert (
        await client.get(f"/api/research/sessions/{session_id}/citations")
    ).json() == generated_citations
    assert (
        await client.get(f"/api/research/sessions/{session_id}/findings")
    ).json() == generated_findings


@pytest.mark.asyncio
async def test_related_work_skips_inaccessible_source_and_backfills(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _auth_client(client)
    account = (await client.get("/api/identity/me")).json()
    draft = await _prepare_related_work(client)
    records = [
        ScholarlyRecord(
            title=f"Claim verification {identifier}",
            abstract="Evaluates claim evidence verification with a benchmark.",
            provider="fixture",
            provider_source_id=identifier,
        )
        for identifier in ("blocked", "accessible-1", "accessible-2")
    ]
    monkeypatch.setenv("RESEARCH_REQUIRE_DOWNLOADABLE_FULL_TEXT", "true")
    get_settings.cache_clear()
    try:
        async with get_session_factory()() as db:
            service = ResearchService(
                db,
                source=FakeScholarlySourcePort(records),
                verifier=FakeCitationVerifier(),
                llm=FakeLlmPort(),
                document_text_source=_SelectiveDocumentSource(),
                object_storage=MemoryObjectStorage(),
            )
            run = await service.begin_generation(
                session_id=UUID(draft["id"]),
                account_id=UUID(account["id"]),
                node=ResearchNode.RELATED_WORK,
                body=ResearchGenerateRequest(
                    expected_version=draft["version"],
                    max_results=2,
                ),
            )
            events = [event async for event in service.generate(run)]
    finally:
        get_settings.cache_clear()

    citations = [
        event["citation"] for event in events if event["type"] == "citation_upsert"
    ]
    assert [item["provider_source_id"] for item in citations] == [
        "accessible-1",
        "accessible-2",
    ]
    patch = next(event for event in events if event["type"] == "draft_patch")
    assert patch["narrative"]["citation_count"] == 2
    assert patch["narrative"]["skipped_inaccessible_count"] == 1
    skip_warning = next(
        event
        for event in events
        if event["type"] == "warning" and event.get("code") == "full_text_unavailable"
    )
    assert "Skipped 1 scholarly candidate" in skip_warning["message"]
    assert "strict full-text mode" in skip_warning["message"]
    assert patch["narrative"]["selection_rule"].startswith(
        "one_best_citation_per_discovered_tool_"
    )
    assert events[-1]["citation_count"] == 2


@pytest.mark.asyncio
async def test_related_work_resolves_full_text_metadata_before_download(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _auth_client(client)
    account = (await client.get("/api/identity/me")).json()
    draft = await _prepare_related_work(client)
    document_source = _MetadataAwareDocumentSource()
    record = ScholarlyRecord(
        title="Claim verification prompt optimization method",
        abstract="Evaluates claim verification and iterative prompt optimization.",
        provider="semantic_scholar",
        provider_source_id="resolved-before-download",
    )
    monkeypatch.setenv("RESEARCH_REQUIRE_DOWNLOADABLE_FULL_TEXT", "true")
    get_settings.cache_clear()
    try:
        async with get_session_factory()() as db:
            service = ResearchService(
                db,
                source=FakeScholarlySourcePort([record]),
                verifier=_FullTextEnrichingVerifier(),
                llm=FakeLlmPort(),
                document_text_source=document_source,
                object_storage=MemoryObjectStorage(),
            )
            run = await service.begin_generation(
                session_id=UUID(draft["id"]),
                account_id=UUID(account["id"]),
                node=ResearchNode.RELATED_WORK,
                body=ResearchGenerateRequest(
                    expected_version=draft["version"],
                    max_results=1,
                ),
            )
            events = [event async for event in service.generate(run)]
    finally:
        get_settings.cache_clear()

    assert document_source.seen_full_text_urls == [
        "https://example.org/resolved-paper.pdf"
    ]
    citation = next(
        event["citation"] for event in events if event["type"] == "citation_upsert"
    )
    assert citation["text_source_kind"] == "full_text_pdf"
    assert events[-1]["citation_count"] == 1


@pytest.mark.asyncio
async def test_related_work_citation_count_follows_discovered_tool_count(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _auth_client(client)
    account = (await client.get("/api/identity/me")).json()
    draft = await _prepare_related_work(client)
    records = [
        ScholarlyRecord(
            title=f"Claim verification prompt optimization method {index}",
            abstract=(
                "Evaluates claim verification and iterative prompt optimization "
                f"with benchmark protocol {index}."
            ),
            provider="fixture",
            provider_source_id=f"citation-{index}",
        )
        for index in range(8)
    ]
    monkeypatch.setenv("RESEARCH_REQUIRE_DOWNLOADABLE_FULL_TEXT", "true")
    get_settings.cache_clear()
    try:
        async with get_session_factory()() as db:
            service = ResearchService(
                db,
                source=FakeScholarlySourcePort(records),
                verifier=FakeCitationVerifier(),
                llm=FakeLlmPort(),
                document_text_source=_SelectiveDocumentSource(),
                object_storage=MemoryObjectStorage(),
            )
            run = await service.begin_generation(
                session_id=UUID(draft["id"]),
                account_id=UUID(account["id"]),
                node=ResearchNode.RELATED_WORK,
                body=ResearchGenerateRequest(expected_version=draft["version"]),
            )
            events = [event async for event in service.generate(run)]
    finally:
        get_settings.cache_clear()

    citations = [
        event["citation"] for event in events if event["type"] == "citation_upsert"
    ]
    assert len(citations) == 4
    assert events[-1]["citation_count"] == 4
    patch = next(event for event in events if event["type"] == "draft_patch")
    assert patch["narrative"]["citation_count"] == 4
    assert patch["narrative"]["citation_target"] == 4
    assert len(patch["narrative"]["search_queries"]) == 4
    assert len(patch["narrative"]["query_plan"]["facets"]) >= 2
    assert patch["narrative"]["discovery_leads_status"] == (
        "unverified_search_leads"
    )
    assert "DSPy" in patch["narrative"]["discovery_leads"][
        "tools_and_frameworks"
    ]
    tool_coverage = patch["narrative"]["tool_coverage"]
    assert [item["tool"] for item in tool_coverage] == [
        "DSPy",
        "TextGrad",
        "OPRO",
        "ProTeGi",
    ]
    assert all(item["status"] == "matched_citation" for item in tool_coverage)
    progress_messages = [
        event["message"] for event in events if event["type"] == "progress"
    ]
    assert any("Expanding confirmed keywords" in message for message in progress_messages)
    assert any("named research leads" in message for message in progress_messages)


@pytest.mark.asyncio
async def test_gap_stream_strict_mode_does_not_promote_abstract_only_support(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _auth_client(client)
    monkeypatch.setenv("RESEARCH_REQUIRE_DOWNLOADABLE_FULL_TEXT", "true")
    get_settings.cache_clear()
    draft = await _prepare_related_work(client)
    session_id = draft["id"]
    related = await client.post(
        f"/api/research/sessions/{session_id}/nodes/related_work/generate",
        json={"expected_version": draft["version"], "max_results": 5},
    )
    related_events = _events(related.text)
    related_version = related_events[-1]["version"]
    confirmed = await _confirm(
        client,
        session_id,
        "related_work",
        related_version,
    )
    gap_draft = await _prepare(
        client,
        session_id,
        "gap",
        confirmed["version"],
    )
    response = await client.post(
        f"/api/research/sessions/{session_id}/nodes/gap/generate",
        json={"expected_version": gap_draft["version"]},
    )
    assert response.status_code == 200, response.text
    events = _events(response.text)
    progress_messages = [
        event["message"] for event in events if event["type"] == "progress"
    ]
    assert "Checking whether Related Work limitations are source-supported" in (
        progress_messages
    )
    patch = next(event for event in events if event["type"] == "draft_patch")
    candidate = patch["narrative"]["candidate"]
    assert candidate["statement"]
    assert candidate["supporting_citation_keys"] == []
    assert candidate["status"] == "insufficient_evidence"
    assert len(candidate["search_audit"]["related_work_queries"]) >= 4
    assert candidate["search_audit"]["counter_evidence_queries"] == []
    assert candidate["evidence_check"]["ready"] is False
    assert "prior_work" not in candidate
    assert events[-1]["type"] == "done"


@pytest.mark.asyncio
async def test_gap_regeneration_replaces_saved_gap_without_confirming(
    client: AsyncClient,
) -> None:
    await _auth_client(client)
    draft = await _prepare_related_work(client)
    session_id = draft["id"]
    related = await client.post(
        f"/api/research/sessions/{session_id}/nodes/related_work/generate",
        json={"expected_version": draft["version"], "max_results": 1},
    )
    related_version = _events(related.text)[-1]["version"]
    confirmed = await _confirm(client, session_id, "related_work", related_version)
    gap_draft = await _prepare(
        client,
        session_id,
        "gap",
        confirmed["version"],
    )
    first = await client.post(
        f"/api/research/sessions/{session_id}/nodes/gap/generate",
        json={"expected_version": gap_draft["version"]},
    )
    first_events = _events(first.text)
    first_candidate = next(
        event["narrative"]["candidate"]
        for event in first_events
        if event["type"] == "draft_patch"
    )
    first_candidate["statement"] = "Saved Gap that should be replaced."
    saved = await _create_card(
        client,
        session_id,
        kind="gap",
        body=first_candidate,
        expected_version=first_events[-1]["version"],
    )
    assert saved.status_code == 201, saved.text

    regenerated = await client.post(
        f"/api/research/sessions/{session_id}/nodes/gap/generate",
        json={"expected_version": saved.json()["version"]},
    )
    assert regenerated.status_code == 200, regenerated.text
    regenerated_events = _events(regenerated.text)
    regenerated_candidate = next(
        event["narrative"]["candidate"]
        for event in regenerated_events
        if event["type"] == "draft_patch"
    )

    fetched = await client.get(f"/api/loop/sessions/{session_id}")
    payload = fetched.json()
    assert payload["working_draft_narrative"]["candidate"] == regenerated_candidate
    assert not any(card["kind"] == "gap" for card in payload["cards"])


@pytest.mark.asyncio
async def test_generate_rejects_non_research_node_and_stale_version(
    client: AsyncClient,
) -> None:
    await _auth_client(client)
    draft = await _prepare_related_work(client)
    invalid = await client.post(
        f"/api/research/sessions/{draft['id']}/nodes/contribution/generate",
        json={"expected_version": draft["version"]},
    )
    assert invalid.status_code == 422

    stale = await client.post(
        f"/api/research/sessions/{draft['id']}/nodes/related_work/generate",
        json={"expected_version": draft["version"] - 1},
    )
    assert stale.status_code == 409
    assert stale.json()["code"] == "version_conflict"


@pytest.mark.asyncio
async def test_all_provider_queries_failing_stops_generation(
    client: AsyncClient,
) -> None:
    await _auth_client(client)
    account = (await client.get("/api/identity/me")).json()
    draft = await _prepare_related_work(client)
    initial = await client.post(
        f"/api/research/sessions/{draft['id']}/nodes/related_work/generate",
        json={"expected_version": draft["version"], "max_results": 1},
    )
    initial_events = _events(initial.text)
    initial_version = initial_events[-1]["version"]
    assert len(
        (await client.get(f"/api/research/sessions/{draft['id']}/citations")).json()
    ) == 1

    async with get_session_factory()() as db:
        service = ResearchService(
            db,
            source=FakeScholarlySourcePort(error=TimeoutError()),
            verifier=FakeCitationVerifier(),
            llm=FakeLlmPort(),
        )
        run = await service.begin_generation(
            session_id=UUID(draft["id"]),
            account_id=UUID(account["id"]),
            node=ResearchNode.RELATED_WORK,
            body=ResearchGenerateRequest(expected_version=initial_version),
        )
        events = [event async for event in service.generate(run)]
    assert events[-1] == {
        "type": "error",
        "node": "related_work",
        "code": "generation_failed",
        "message": "Scholarly provider failed: TimeoutError",
    }
    assert not any(event["type"] == "done" for event in events)
    assert (
        await client.get(f"/api/research/sessions/{draft['id']}/citations")
    ).json() == []
    assert (
        await client.get(f"/api/research/sessions/{draft['id']}/findings")
    ).json() == []
    session = (await client.get(f"/api/loop/sessions/{draft['id']}")).json()
    assert session["working_draft_narrative"] == {}
    assert session["version"] == initial_version + 1
