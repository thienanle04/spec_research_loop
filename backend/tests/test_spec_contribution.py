"""Contribution-direction generation contract tests."""

import pytest
from httpx import AsyncClient

from tests.test_loop_api import (
    _auth_client,
    _confirm,
    _create_session,
    _prepare,
)


async def _prepare_contribution(client: AsyncClient) -> dict:
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
    inputs = await _prepare(
        client,
        created["id"],
        "related_work",
        decomposed["version"],
    )
    inputs_confirmed = await _confirm(
        client,
        created["id"],
        "research_inputs",
        inputs["version"],
    )
    related = await _prepare(
        client,
        created["id"],
        "related_work",
        inputs_confirmed["version"],
    )
    related_confirmed = await _confirm(
        client,
        created["id"],
        "related_work",
        related["version"],
    )
    gap = await _prepare(
        client,
        created["id"],
        "related_work",
        related_confirmed["version"],
    )
    gap_confirmed = await _confirm(
        client,
        created["id"],
        "gap",
        gap["version"],
    )
    prepared = await _prepare(
        client,
        created["id"],
        "related_work",
        gap_confirmed["version"],
    )
    assert prepared["working_draft_node"] == "contribution"
    return prepared


@pytest.mark.asyncio
async def test_generates_contextual_directions_with_fixed_combine_and_other(
    client: AsyncClient,
) -> None:
    await _auth_client(client)
    contribution = await _prepare_contribution(client)

    response = await client.post(
        f"/api/spec/sessions/{contribution['id']}/contribution-directions/generate",
        json={"expected_version": contribution["version"]},
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert len(payload["directions"]) == 5
    assert [item["kind"] for item in payload["directions"][-2:]] == [
        "combine",
        "other",
    ]
    assert payload["version"] == contribution["version"] + 1

    saved = await client.get(f"/api/loop/sessions/{contribution['id']}")
    assert saved.status_code == 200
    assert (
        saved.json()["working_draft_narrative"]["directions"] == payload["directions"]
    )


@pytest.mark.asyncio
async def test_rejects_direction_generation_outside_contribution_draft(
    client: AsyncClient,
) -> None:
    await _auth_client(client)
    created = await _create_session(client)

    response = await client.post(
        f"/api/spec/sessions/{created['id']}/contribution-directions/generate",
        json={"expected_version": created["version"]},
    )

    assert response.status_code == 409
    assert response.json()["code"] == "invalid_working_draft_target"
