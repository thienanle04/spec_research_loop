"""In-process Context Projection seam (ADR 0009, Q9)."""

from uuid import UUID

import pytest
from httpx import AsyncClient

from app.db.session import get_session_factory
from app.modules.loop.catalog import WorkflowNode
from app.modules.loop.service import LoopService
from tests.test_loop_api import _auth_client, _create_session, _interpret


@pytest.mark.asyncio
async def test_project_context_uses_working_draft_and_empty_projectors(
    client: AsyncClient,
) -> None:
    await _auth_client(client)
    created = await _create_session(client)
    session_id = UUID(created["id"])
    me = await client.get("/api/identity/me")
    account_id = UUID(me.json()["id"])
    await _interpret(client, str(session_id), created["version"])

    factory = get_session_factory()
    async with factory() as db:
        context = await LoopService(db).project_context(
            session_id=session_id,
            account_id=account_id,
            node=WorkflowNode.IDEA_DECOMPOSITION,
        )
    assert context["working_draft"]["node"] == "idea_decomposition"
    assert context["projected"] == {}
    assert "idea_interpretation" in context["upstream"]
