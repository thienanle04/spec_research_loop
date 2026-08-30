"""Contribution-direction generation contract tests."""

import json

import pytest
from httpx import AsyncClient

from tests.test_loop_api import (
    _auth_client,
    _confirm,
    _create_session,
    _interpret,
    _prepare,
)

_VIETNAMESE_TEST_CHARACTERS = frozenset("ăâđêôơưàáạảãèéẹẻẽìíịỉĩòóọỏõùúụủũỳýỵỷỹ")


async def _prepare_contribution(
    client: AsyncClient, *, gap_statement: str | None = None
) -> dict:
    created = await _create_session(client)
    interpreted = await _interpret(client, created["id"], created["version"])
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
    related_generation = await client.post(
        f"/api/research/sessions/{created['id']}/nodes/related_work/generate",
        json={"expected_version": related["version"], "max_results": 5},
    )
    related_events = [
        json.loads(line.removeprefix("data: "))
        for line in related_generation.text.splitlines()
        if line.startswith("data: ")
    ]
    related_confirmed = await _confirm(
        client,
        created["id"],
        "related_work",
        related_events[-1]["version"],
    )
    gap = await _prepare(
        client,
        created["id"],
        "gap",
        related_confirmed["version"],
    )
    gap_generation = await client.post(
        f"/api/research/sessions/{created['id']}/nodes/gap/generate",
        json={"expected_version": gap["version"]},
    )
    gap_events = [
        json.loads(line.removeprefix("data: "))
        for line in gap_generation.text.splitlines()
        if line.startswith("data: ")
    ]
    candidate = next(
        event["narrative"]["candidate"]
        for event in gap_events
        if event["type"] == "draft_patch"
    )
    if gap_statement is not None:
        candidate = {**candidate, "statement": gap_statement}
    card = await client.post(
        f"/api/loop/sessions/{created['id']}/cards",
        json={
            "kind": "gap",
            "body": candidate,
            "expected_version": gap_events[-1]["version"],
        },
    )
    assert card.status_code == 201, card.text
    gap_confirmed = await _confirm(
        client,
        created["id"],
        "gap",
        card.json()["version"],
    )
    prepared = await _prepare(
        client,
        created["id"],
        "contribution",
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
    assert [item["title"] for item in payload["directions"][-2:]] == [
        "Combine directions",
        "Other",
    ]
    assert payload["version"] == contribution["version"] + 1

    saved = await client.get(f"/api/loop/sessions/{contribution['id']}")
    assert saved.status_code == 200
    assert (
        saved.json()["working_draft_narrative"]["directions"] == payload["directions"]
    )
    contribution_head = next(
        head
        for head in saved.json()["node_heads"]
        if head["node"] == "contribution"
    )
    assert contribution_head["generated_since_prepare"] is True


@pytest.mark.asyncio
async def test_generates_vietnamese_directions_for_a_vietnamese_gap(
    client: AsyncClient,
) -> None:
    await _auth_client(client)
    contribution = await _prepare_contribution(
        client,
        gap_statement=(
            "Các phương pháp hiện tại chưa kiểm chứng từng luận điểm bằng nguồn học thuật."
        ),
    )

    response = await client.post(
        f"/api/spec/sessions/{contribution['id']}/contribution-directions/generate",
        json={"expected_version": contribution["version"]},
    )

    assert response.status_code == 200, response.text
    directions = response.json()["directions"]
    assert directions[0]["title"] == "Tập trung vào phương pháp cốt lõi"
    assert [item["title"] for item in directions[-2:]] == [
        "Kết hợp các hướng",
        "Khác",
    ]
    assert all(
        any(
            character in _VIETNAMESE_TEST_CHARACTERS
            for character in item["description"].casefold()
        )
        for item in directions
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


@pytest.mark.asyncio
async def test_replaces_contribution_cards_without_accumulating(
    client: AsyncClient,
) -> None:
    await _auth_client(client)
    contribution = await _prepare_contribution(client)
    session_id = contribution["id"]

    first = await client.put(
        f"/api/loop/sessions/{session_id}/cards",
        json={
            "kind": "contribution",
            "bodies": [
                {"text": "Primary", "direction_id": "direction-a", "role": "primary"},
                {
                    "text": "Supporting",
                    "direction_id": "direction-b",
                    "role": "supporting",
                },
            ],
            "expected_version": contribution["version"],
        },
    )
    assert first.status_code == 200, first.text
    first_payload = first.json()
    primary_id = first_payload["cards"][0]["id"]
    assert len(first_payload["cards"]) == 2

    second = await client.put(
        f"/api/loop/sessions/{session_id}/cards",
        json={
            "kind": "contribution",
            "bodies": [
                {"text": "Changed", "direction_id": "direction-c", "role": "primary"}
            ],
            "expected_version": first_payload["version"],
        },
    )
    assert second.status_code == 200, second.text
    second_payload = second.json()
    assert second_payload["version"] == first_payload["version"] + 1
    assert second_payload["cards"] == [
        {
            "id": primary_id,
            "kind": "contribution",
            "body": {
                "text": "Changed",
                "direction_id": "direction-c",
                "role": "primary",
            },
            "created_at": first_payload["cards"][0]["created_at"],
            "updated_at": second_payload["cards"][0]["updated_at"],
        }
    ]

    saved = await client.get(f"/api/loop/sessions/{session_id}")
    contribution_cards = [
        card for card in saved.json()["cards"] if card["kind"] == "contribution"
    ]
    assert contribution_cards == second_payload["cards"]
