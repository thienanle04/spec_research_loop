"""Research read-contract tests."""

from typing import Any

import pytest
from httpx import AsyncClient

from tests.test_loop_api import (
    _auth_client,
    _confirm,
    _create_session,
    _patch_working_draft,
    _prepare,
    _register,
)


async def _prepare_related_work(client: AsyncClient) -> dict[str, Any]:
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
            "keywords": ["claim verification", "prompt optimization"],
            "preferred_sources": {
                "peer_reviewed_papers": True,
                "official_proceedings": True,
                "author_materials": True,
                "sourced_surveys": True,
            },
        },
    )
    confirmed = await _confirm(
        client,
        session_id,
        "research_inputs",
        inputs.json()["version"],
    )
    return await _prepare(
        client,
        session_id,
        "related_work",
        confirmed["version"],
    )


@pytest.mark.asyncio
async def test_other_account_cannot_read_research_data(client: AsyncClient) -> None:
    await _auth_client(client)
    draft = await _prepare_related_work(client)
    token = await _register(client, email="other@example.com")
    client.headers["Authorization"] = f"Bearer {token}"
    response = await client.get(f"/api/research/sessions/{draft['id']}/citations")
    assert response.status_code == 404

    findings = await client.get(f"/api/research/sessions/{draft['id']}/findings")
    assert findings.status_code == 404
