"""Contribution-direction generation contract tests."""

import json

import pytest
from fastapi import HTTPException
from httpx import AsyncClient

from app.modules.spec.service import SpecService
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
    assert directions[0]["title"] == "Đối chiếu từng luận điểm với nguồn học thuật"
    assert not any(item["title"].startswith("Tập trung vào") for item in directions)
    for item in directions[:3]:
        assert "Cơ chế:" in item["description"]
        assert "Liên hệ Gap:" in item["description"]
        assert "Điểm mới:" in item["description"]
        assert "Kiểm chứng:" in item["description"]
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


class _ScriptedContributionLlm:
    def __init__(self, responses: list[str]) -> None:
        self.responses = responses
        self.calls = 0
        self.prompts: list[str] = []
        self.systems: list[str] = []

    async def complete(self, **kwargs: object) -> str:
        self.prompts.append(str(kwargs["prompt"]))
        self.systems.append(str(kwargs["system"]))
        response = self.responses[min(self.calls, len(self.responses) - 1)]
        self.calls += 1
        return response


@pytest.mark.asyncio
async def test_repairs_a_generic_direction_once() -> None:
    valid = json.dumps(
        {"directions": [
            {
                "title": "Bản đồ luận điểm–bằng chứng",
                "mechanism": "Liên kết từng luận điểm với đoạn bằng chứng học thuật hỗ trợ hoặc phản bác.",
                "gap_link": "Cơ chế xử lý trực tiếp việc Gap chưa kiểm chứng kết quả ở cấp từng luận điểm.",
                "novelty": "Khác với danh sách nguồn tổng hợp, quan hệ hỗ trợ được biểu diễn cho từng luận điểm.",
                "validation": "So sánh với danh sách nguồn, đo độ chính xác truy vết và bác bỏ nếu không tốt hơn.",
            }
        ]},
        ensure_ascii=False,
    )
    llm = _ScriptedContributionLlm(
        [
            '[{"title":"Tập trung vào kiểm chứng","description":"Kiểm chứng tốt hơn."}]',
            valid,
        ]
    )
    service = SpecService(None, llm=llm)  # type: ignore[arg-type]

    directions = await service._propose_directions(
        {
            "upstream": {
                "gap": {
                    "card_snapshot": [
                        {
                            "kind": "gap",
                            "body": {
                                "statement": "Các phương pháp chưa kiểm chứng từng luận điểm."
                            },
                        }
                    ]
                }
            }
        },
        "Vietnamese",
    )

    assert llm.calls == 2
    assert directions[0].title == "Bản đồ luận điểm–bằng chứng"


@pytest.mark.asyncio
async def test_does_not_save_a_generic_fallback_after_repair_fails() -> None:
    llm = _ScriptedContributionLlm(["not-json"])
    service = SpecService(None, llm=llm)  # type: ignore[arg-type]

    with pytest.raises(HTTPException) as caught:
        await service._propose_directions(
            {"upstream": {"gap": {"card_snapshot": []}}},
            "English",
        )

    assert llm.calls == 2
    assert caught.value.status_code == 502
    assert "no generic fallback was saved" in caught.value.detail


@pytest.mark.asyncio
async def test_repairs_a_truncated_tail_before_falling_back_to_complete_items() -> None:
    complete = {
        "title": "Claim-level evidence routing",
        "mechanism": "Route each unsupported claim to the scholarly passage needed to assess it.",
        "gap_link": "This directly addresses the inability to verify results at individual claim level.",
        "novelty": "Unlike aggregate checking, the method preserves each failed claim and its evidence link.",
        "validation": "Compare with aggregate checking and reject if unsupported claims do not decrease.",
    }
    truncated = (
        '{"directions":['
        + json.dumps(complete)
        + ',{"title":"Second direction","mechanism":"This response was cut'
    )
    repaired = json.dumps(
        {
            "directions": [
                complete,
                {
                    "title": "Traceable evidence map",
                    "mechanism": "Link each claim to its supporting or contradicting scholarly passage.",
                    "gap_link": "This makes claim-level evidence observable instead of relying on aggregate checks.",
                    "novelty": "Unlike an unlinked bibliography, it records support relationships for each claim.",
                    "validation": "Compare trace accuracy with a source list and reject if auditors are not more accurate.",
                },
                {
                    "title": "Unsupported-claim confirmation gate",
                    "mechanism": "Block confirmation until material unsupported claims are resolved.",
                    "gap_link": "This prevents unverified claims from entering the confirmed Research Spec.",
                    "novelty": "Unlike passive warnings, evidence status becomes an editable confirmation condition.",
                    "validation": "Compare with warnings alone and reject if residual unsupported claims do not decrease.",
                },
            ]
        }
    )
    llm = _ScriptedContributionLlm([truncated, repaired])
    service = SpecService(None, llm=llm)  # type: ignore[arg-type]

    directions = await service._propose_directions(
        {
            "upstream": {
                "gap": {
                    "card_snapshot": [
                        {
                            "kind": "gap",
                            "body": {
                                "statement": "Existing methods do not verify individual claims."
                            },
                        }
                    ]
                }
            }
        },
        "English",
    )

    assert llm.calls == 2
    assert len(directions) == 3
    assert [item.title for item in directions] == [
        "Claim-level evidence routing",
        "Traceable evidence map",
        "Unsupported-claim confirmation gate",
    ]
    assert "mechanism to one short, direct sentence" in llm.systems[0]


@pytest.mark.asyncio
async def test_compacts_related_work_before_direction_generation() -> None:
    valid = json.dumps(
        {
            "directions": [
                {
                    "title": "Claim-level evidence routing",
                    "mechanism": "Route each unsupported claim to the scholarly passage needed to assess it.",
                    "gap_link": "This directly addresses the inability to verify results at individual claim level.",
                    "novelty": "Unlike aggregate checking, the method preserves the failed claim and its evidence link.",
                    "validation": "Compare with aggregate checking and reject the direction if unsupported claims do not decrease.",
                }
            ]
        }
    )
    llm = _ScriptedContributionLlm([valid])
    service = SpecService(None, llm=llm)  # type: ignore[arg-type]
    oversized = "RAW_METADATA_SHOULD_NOT_REACH_MODEL " * 10_000
    context = {
        "upstream": {
            "idea_decomposition": {
                "card_snapshot": [
                    {"kind": "problem", "body": {"text": "Unsupported claims"}},
                    {
                        "kind": "research_question",
                        "body": {"text": "Can claim-level checks reduce unsupported claims?"},
                    },
                ]
            },
            "research_inputs": {
                "narrative": {"keywords": ["claim evidence verification"]}
            },
            "related_work": {
                "narrative": {"candidate_count": 20, "ranked_candidate_count": 6},
                "projected": {
                    "citations": [
                        {
                            "id": "citation-1",
                            "citation_key": "smith-2025",
                            "title": "Aggregate Claim Checking",
                            "year": 2025,
                            "abstract": oversized,
                            "metadata": {"raw": oversized},
                        }
                    ],
                    "related_work": [
                        {
                            "citation_id": "citation-1",
                            "what_was_done": "Scores the result as a whole.",
                            "limitation": "Does not localize unsupported claims.",
                            "relevance": "Provides the closest aggregate baseline.",
                            "supporting_passage": oversized,
                            "evidence": {"raw": oversized},
                        }
                    ],
                },
            },
            "gap": {
                "card_snapshot": [
                    {
                        "kind": "gap",
                        "body": {
                            "statement": "Existing methods do not verify each claim against scholarly evidence."
                        },
                    }
                ]
            },
        }
    }

    directions = await service._propose_directions(context, "English")

    request = json.loads(llm.prompts[0])
    serialized = json.dumps(request)
    assert len(serialized) < 30_000
    assert "RAW_METADATA_SHOULD_NOT_REACH_MODEL" not in serialized
    assert "context_projection" not in request
    assert request["contribution_brief"]["related_work"]["studies"][0][
        "source"
    ]["title"] == "Aggregate Claim Checking"
    assert directions[0].title == "Claim-level evidence routing"


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
