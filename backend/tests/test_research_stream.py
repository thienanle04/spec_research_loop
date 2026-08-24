"""Research SSE generation tests using deterministic fake providers."""

import json
from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.db.session import get_session_factory
from app.modules.research.adapters.fake_llm import FakeLlmPort
from app.modules.research.adapters.fake_source import (
    FakeCitationVerifier,
    FakeScholarlySourcePort,
)
from app.modules.research.models import RelatedWorkFinding
from app.modules.research.schemas import ResearchGenerateRequest, ResearchNode
from app.modules.research.service import ResearchService
from tests.test_loop_api import _auth_client, _confirm, _create_session, _prepare
from tests.test_research_api import _prepare_related_work


def _events(body: str) -> list[dict]:
    return [
        json.loads(line.removeprefix("data: "))
        for line in body.splitlines()
        if line.startswith("data: ")
    ]


@pytest.mark.asyncio
async def test_research_inputs_stream_updates_working_narrative(
    client: AsyncClient,
) -> None:
    await _auth_client(client)
    created = await _create_session(client)
    interpreted = await _confirm(
        client,
        created["id"],
        "idea_interpretation",
        created["version"],
    )
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
        "citation_count": 2,
    }
    assert [event["type"] for event in events].count("citation_upsert") == 2
    assert any(event["type"] == "draft_patch" for event in events)

    listed = await client.get(f"/api/research/sessions/{session_id}/citations")
    assert len(listed.json()) == 2
    assert all(item["text_object_key"] for item in listed.json())
    assert all(item["text_checksum"] for item in listed.json())
    assert all(item["text_source_kind"] == "abstract" for item in listed.json())
    listed_findings = await client.get(f"/api/research/sessions/{session_id}/findings")
    assert listed_findings.status_code == 200
    assert len(listed_findings.json()) == 2
    assert all(item["citation_id"] for item in listed_findings.json())
    assert all(item["supporting_passage"] for item in listed_findings.json())
    assert all(item["source_object_key"] for item in listed_findings.json())

    pinned_ids = {item["id"] for item in listed.json()}
    for pinned_id in pinned_ids:
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
    assert len(after_rerun.json()) == 2
    assert {item["id"] for item in after_rerun.json()} == pinned_ids
    assert all(item["pinned"] for item in after_rerun.json())
    async with get_session_factory()() as db:
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
        assert len(findings) == 2
        assert all(item.citation_id for item in findings)
        assert all(item.supporting_passage for item in findings)


@pytest.mark.asyncio
async def test_gap_stream_uses_confirmed_citation_support(client: AsyncClient) -> None:
    await _auth_client(client)
    draft = await _prepare_related_work(client)
    session_id = draft["id"]
    related = await client.post(
        f"/api/research/sessions/{session_id}/nodes/related_work/generate",
        json={"expected_version": draft["version"], "max_results": 1},
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
        "related_work",
        confirmed["version"],
    )
    response = await client.post(
        f"/api/research/sessions/{session_id}/nodes/gap/generate",
        json={"expected_version": gap_draft["version"]},
    )
    assert response.status_code == 200, response.text
    events = _events(response.text)
    patch = next(event for event in events if event["type"] == "draft_patch")
    candidate = patch["narrative"]["candidate"]
    assert candidate["statement"]
    assert candidate["supporting_citation_keys"]
    assert candidate["status"] == "candidate"
    assert candidate["search_audit"]["complete"] is True
    assert len(candidate["search_audit"]["related_work_queries"]) >= 4
    assert len(candidate["search_audit"]["counter_evidence_queries"]) >= 3
    assert candidate["evidence_check"]["ready"] is True
    assert "prior_work" not in candidate
    assert events[-1]["type"] == "done"


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
            body=ResearchGenerateRequest(expected_version=draft["version"]),
        )
        events = [event async for event in service.generate(run)]
    assert events[-1] == {
        "type": "error",
        "node": "related_work",
        "code": "generation_failed",
        "message": "Scholarly provider failed: TimeoutError",
    }
    assert not any(event["type"] == "done" for event in events)
