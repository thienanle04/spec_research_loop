"""Research typed snapshots integrated through LoopService StagePort."""

from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.db.session import get_session_factory
from app.modules.loop.catalog import NodeHeadStatus, WorkflowNode
from app.modules.loop.service import LoopService
from app.modules.research.models import Citation, RelatedWorkFinding
from app.modules.research.stage_port import ResearchStagePort
from tests.test_loop_api import (
    _auth_client,
    _confirm,
    _create_card,
    _create_session,
    _head,
    _patch_working_draft,
    _prepare,
)


@pytest.mark.asyncio
async def test_citation_changes_create_revision_and_project_confirmed_rows(
    client: AsyncClient,
) -> None:
    await _auth_client(client)
    account = (await client.get("/api/identity/me")).json()
    created = await _create_session(client)
    session_id = created["id"]

    interpreted = await _confirm(
        client,
        session_id,
        "idea_interpretation",
        created["version"],
    )
    decomposed = await _confirm(
        client,
        session_id,
        "idea_decomposition",
        interpreted["version"],
    )
    inputs_draft = await _prepare(
        client,
        session_id,
        "related_work",
        decomposed["version"],
    )
    inputs = await _patch_working_draft(
        client,
        session_id,
        expected_version=inputs_draft["version"],
        narrative={
            "keywords": ["claim verification"],
            "preferred_sources": {
                "peer_reviewed_papers": True,
                "official_proceedings": True,
                "author_materials": True,
                "sourced_surveys": True,
            },
        },
    )
    inputs_confirmed = await _confirm(
        client,
        session_id,
        "research_inputs",
        inputs.json()["version"],
    )
    related_draft = await _prepare(
        client,
        session_id,
        "related_work",
        inputs_confirmed["version"],
    )

    citation_id: UUID
    factory = get_session_factory()
    async with factory() as db:
        citation = Citation(
            citation_key="opro-2023",
            session_id=UUID(session_id),
            title="Large Language Models as Optimizers",
            authors=["Yang et al."],
            year=2023,
            doi="10.48550/arXiv.2309.03409",
            provider="fixture",
            provider_source_id="opro",
            verification_status="verified",
            source_metadata={"fixture": True},
        )
        db.add(citation)
        await db.flush()
        citation_id = citation.id
        db.add(
            RelatedWorkFinding(
                session_id=UUID(session_id),
                citation_id=citation.id,
                what_was_done="Uses an LLM to propose optimized prompts.",
                method_or_feedback="Scalar task score",
                limitation="Does not analyze errors per claim.",
                relevance="Directly relevant to prompt optimization.",
                supporting_passage="The optimizer receives prior prompts and scores.",
                confidence=0.9,
                grounding_status="grounded",
            )
        )
        await db.commit()

    related_confirmed = await _confirm(
        client,
        session_id,
        "related_work",
        related_draft["version"],
    )
    first_revision_id = _head(related_confirmed, "related_work")["stage_revision_id"]
    gap_draft = await _prepare(
        client,
        session_id,
        "related_work",
        related_confirmed["version"],
    )
    gap_card = await _create_card(
        client,
        session_id,
        kind="gap",
        body={
            "statement": "Claim-level feedback remains underexplored.",
            "supporting_citation_keys": ["opro-2023"],
            "status": "proposed",
        },
        expected_version=gap_draft["version"],
    )
    assert gap_card.status_code == 201, gap_card.text
    gap_confirmed = await _confirm(
        client,
        session_id,
        "gap",
        gap_card.json()["version"],
    )

    async with factory() as db:
        context = await LoopService(db).project_context(
            session_id=UUID(session_id),
            account_id=UUID(account["id"]),
            node=WorkflowNode.CONTRIBUTION,
        )
        research_projection = context["upstream"]["related_work"]["projected"]
        assert research_projection["citations"][0]["id"] == str(citation_id)
        assert research_projection["citations"][0]["title"] == (
            "Large Language Models as Optimizers"
        )
        assert research_projection["related_work"][0]["citation_id"] == str(citation_id)

    reopened = await _patch_working_draft(
        client,
        session_id,
        expected_version=gap_confirmed["version"],
        node="related_work",
    )
    assert reopened.status_code == 200, reopened.text
    async with factory() as db:
        citation = await db.scalar(
            select(Citation).where(
                Citation.session_id == UUID(session_id),
                Citation.stage_revision_id.is_(None),
                Citation.id == citation_id,
            )
        )
        assert citation is not None
        citation.title = "OPRO: Large Language Models as Optimizers"
        await db.commit()

    changed = await _confirm(
        client,
        session_id,
        "related_work",
        reopened.json()["version"],
    )
    assert _head(changed, "related_work")["stage_revision_id"] != first_revision_id
    assert _head(changed, "gap")["status"] == NodeHeadStatus.STALE.value

    async with factory() as db:
        snapshots = list(
            (
                await db.scalars(
                    select(Citation)
                    .where(
                        Citation.session_id == UUID(session_id),
                        Citation.stage_revision_id.is_not(None),
                        Citation.id == citation_id,
                    )
                    .order_by(Citation.created_at)
                )
            ).all()
        )
        assert [row.title for row in snapshots] == [
            "Large Language Models as Optimizers",
            "OPRO: Large Language Models as Optimizers",
        ]

        await ResearchStagePort(db).reset_working(
            session_id=UUID(session_id),
            node=WorkflowNode.RELATED_WORK.value,
            from_revision_id=UUID(first_revision_id),
        )
        restored = await db.scalar(
            select(Citation).where(
                Citation.session_id == UUID(session_id),
                Citation.stage_revision_id.is_(None),
                Citation.id == citation_id,
            )
        )
        assert restored is not None
        assert restored.title == "Large Language Models as Optimizers"
