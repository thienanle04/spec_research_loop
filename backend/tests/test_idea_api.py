"""HTTP seam tests for /api/idea generate (ADR 0012, 0024)."""

import asyncio
import json
from collections.abc import AsyncIterator
from uuid import uuid4

import pytest
from httpx import AsyncClient

from app.adapters.llm import FakeLlm, bind_llm_ports
from app.modules.loop.catalog import WORKFLOW_NODES
from tests.test_loop_api import (
    IDEA_FRAME,
    _auth_client,
    _create_session,
    _interpret,
    _register,
)

_FRAME = json.dumps(IDEA_FRAME)
INTERPRETATION = (
    "What is the compute budget?\n"
    "---json---\n"
    '{"exhausted": false, "cards": [], "questions": ['
    '{"text": "What is the compute budget?", "options": ["<8GB", "8-24GB", ">24GB"]}'
    f'], "frame": {_FRAME}}}'
)

EXHAUSTED = (
    "No further questions.\n"
    "---json---\n"
    f'{{"exhausted": true, "cards": [], "questions": [], "frame": {_FRAME}}}'
)

DECOMPOSITION = (
    "Kernels are memory bound.\n"
    "---json---\n"
    '{"exhausted": false, "cards": ['
    '{"kind": "problem", "text": "Memory bandwidth limits kernel latency"},'
    '{"kind": "research_question", "text": "Can tiling cut DRAM traffic?"},'
    '{"kind": "constraint", "text": "8GB VRAM"},'
    '{"kind": "open_question", "text": "Which GPU generation?"}'
    "]}"
)


def _bind_fake(*, response: str | None = None, chunks: list[str] | None = None) -> FakeLlm:
    fake = FakeLlm(response=response or INTERPRETATION, chunks=chunks)
    bind_llm_ports({node.value: fake for node in WORKFLOW_NODES})
    return fake


def _events(text: str) -> list[dict]:
    events: list[dict] = []
    for block in text.split("\n\n"):
        line = next((item for item in block.split("\n") if item.startswith("data:")), None)
        if line:
            events.append(json.loads(line[5:].strip()))
    return events


@pytest.mark.asyncio
async def test_idea_health_is_public(client: AsyncClient) -> None:
    response = await client.get("/api/idea/health")
    assert response.status_code == 200
    assert response.json() == {"module": "idea", "status": "ok"}


@pytest.mark.asyncio
async def test_generate_requires_bearer(client: AsyncClient) -> None:
    response = await client.post(
        f"/api/idea/sessions/{uuid4()}/generate",
        json={"expected_version": 1, "message": "hi"},
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_generate_other_account_session_is_404(client: AsyncClient) -> None:
    await _auth_client(client)
    created = await _create_session(client)
    token = await _register(client)
    client.headers["Authorization"] = f"Bearer {token}"
    _bind_fake()
    response = await client.post(
        f"/api/idea/sessions/{created['id']}/generate",
        json={"expected_version": 1, "message": "hi"},
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_interpretation_generate_requires_message(client: AsyncClient) -> None:
    await _auth_client(client)
    created = await _create_session(client)
    _bind_fake()
    response = await client.post(
        f"/api/idea/sessions/{created['id']}/generate",
        json={"expected_version": 1},
    )
    assert response.status_code == 409
    assert response.json()["code"] == "empty_generate_message"


@pytest.mark.asyncio
async def test_interpretation_generate_streams_and_appends_transcript(client: AsyncClient) -> None:
    await _auth_client(client)
    created = await _create_session(client)
    session_id = created["id"]
    fake = _bind_fake(
        chunks=[
            "What is ",
            "X?\n--",
            "-json",
            '---\n{"exhausted": true, "cards": [], "questions": []}',
        ]
    )
    response = await client.post(
        f"/api/idea/sessions/{session_id}/generate",
        json={"expected_version": 1, "message": "GPU kernel latency"},
    )
    assert response.status_code == 200
    events = _events(response.text)
    types = [item["type"] for item in events]
    assert types[0] == "progress"
    assert "token" in types
    token_text = "".join(item["text"] for item in events if item["type"] == "token")
    assert "---json---" not in token_text
    assert "What is X?" in token_text
    assert events[-2]["type"] == "result"
    assert events[-2]["exhausted"] is True
    assert events[-2]["questions"] == []
    assert events[-2]["preamble"] == "What is X?"
    assert events[-1] == {"type": "done", "version": 2}
    assert fake.calls
    fetched = await client.get(f"/api/loop/sessions/{session_id}")
    body = fetched.json()
    assert body["version"] == 2
    narrative = body["working_draft_narrative"]
    assert narrative["exhausted"] is True
    assert narrative["turns"][0] == {
        "role": "account",
        "kind": "idea",
        "text": "GPU kernel latency",
    }
    assert narrative["turns"][1]["role"] == "model"
    assert narrative["turns"][1]["preamble"] == "What is X?"
    assert narrative["turns"][1]["questions"] == []
    assert body["cards"] == []


@pytest.mark.asyncio
async def test_parse_error_does_not_mutate(client: AsyncClient) -> None:
    await _auth_client(client)
    created = await _create_session(client)
    session_id = created["id"]
    _bind_fake(response="no trailer here")
    response = await client.post(
        f"/api/idea/sessions/{session_id}/generate",
        json={"expected_version": 1, "message": "hello"},
    )
    assert response.status_code == 200
    events = _events(response.text)
    assert events[-1]["type"] == "error"
    assert events[-1]["code"] == "generate_parse_error"
    fetched = await client.get(f"/api/loop/sessions/{session_id}")
    assert fetched.json()["version"] == 1
    assert fetched.json()["working_draft_narrative"] == {}


@pytest.mark.asyncio
async def test_decomposition_generate_upserts_cards(client: AsyncClient) -> None:
    await _auth_client(client)
    created = await _create_session(client)
    session_id = created["id"]
    confirmed = await _interpret(client, session_id, created["version"])
    _bind_fake(response=DECOMPOSITION)
    response = await client.post(
        f"/api/idea/sessions/{session_id}/generate",
        json={"expected_version": confirmed["version"]},
    )
    assert response.status_code == 200
    events = _events(response.text)
    assert events[-1]["type"] == "done"
    fetched = await client.get(f"/api/loop/sessions/{session_id}")
    body = fetched.json()
    assert body["working_draft_node"] == "idea_decomposition"
    kinds = {card["kind"]: card["body"]["text"] for card in body["cards"]}
    assert kinds["problem"] == IDEA_FRAME["problem"]
    assert kinds["research_question"] == IDEA_FRAME["research_question"]
    assert kinds["constraint"] == "8GB VRAM"
    assert kinds["open_question"] == "Which GPU generation?"
    first_ids = {card["kind"]: card["id"] for card in body["cards"]}

    _bind_fake(
        response=(
            "Updated restatement.\n---json---\n"
            '{"exhausted": false, "cards": ['
            '{"kind": "problem", "text": "Updated problem"},'
            '{"kind": "research_question", "text": "Updated RQ"},'
            '{"kind": "constraint", "text": "16GB VRAM"},'
            '{"kind": "constraint", "text": "No cloud"},'
            '{"kind": "open_question", "text": "Dataset?"}'
            "]}"
        )
    )
    again = await client.post(
        f"/api/idea/sessions/{session_id}/generate",
        json={"expected_version": body["version"], "message": "prefer 16GB"},
    )
    assert again.status_code == 200
    refreshed = (await client.get(f"/api/loop/sessions/{session_id}")).json()
    by_kind: dict[str, list[dict]] = {}
    for card in refreshed["cards"]:
        by_kind.setdefault(card["kind"], []).append(card)
    assert by_kind["problem"][0]["id"] == first_ids["problem"]
    assert by_kind["problem"][0]["body"]["text"] == IDEA_FRAME["problem"]
    assert [card["body"]["text"] for card in by_kind["constraint"]] == ["16GB VRAM", "No cloud"]


@pytest.mark.asyncio
async def test_second_generate_conflicts_when_in_flight(client: AsyncClient) -> None:
    await _auth_client(client)
    created = await _create_session(client)
    session_id = created["id"]
    started = asyncio.Event()
    release = asyncio.Event()

    class SlowLlm:
        calls: list = []

        async def stream(self, *, system: str, prompt: str, model: str | None = None) -> AsyncIterator[str]:
            self.calls.append((system, prompt, model))
            started.set()
            await release.wait()
            yield INTERPRETATION

        async def complete(self, *, system: str, prompt: str, model: str | None = None) -> str:
            parts: list[str] = []
            async for token in self.stream(system=system, prompt=prompt, model=model):
                parts.append(token)
            return "".join(parts)

    bind_llm_ports({node.value: SlowLlm() for node in WORKFLOW_NODES})

    async def first() -> object:
        return await client.post(
            f"/api/idea/sessions/{session_id}/generate",
            json={"expected_version": 1, "message": "hello"},
        )

    task = asyncio.create_task(first())
    await asyncio.wait_for(started.wait(), timeout=5)
    second = await client.post(
        f"/api/idea/sessions/{session_id}/generate",
        json={"expected_version": 1, "message": "hello"},
    )
    assert second.status_code == 409
    assert second.json()["code"] == "generate_in_flight"
    release.set()
    first_response = await task
    assert first_response.status_code == 200
    assert _events(first_response.text)[-1]["type"] == "done"


@pytest.mark.asyncio
async def test_cluster_send_appends_answers_and_next_cluster(client: AsyncClient) -> None:
    await _auth_client(client)
    created = await _create_session(client)
    session_id = created["id"]
    _bind_fake()
    first = await client.post(
        f"/api/idea/sessions/{session_id}/generate",
        json={"expected_version": 1, "message": "GPU kernel latency"},
    )
    assert first.status_code == 200
    version = _events(first.text)[-1]["version"]
    message_again = await client.post(
        f"/api/idea/sessions/{session_id}/generate",
        json={"expected_version": version, "message": "8GB"},
    )
    assert message_again.status_code == 409
    assert message_again.json()["code"] == "unexpected_generate_message"

    _bind_fake(response=EXHAUSTED)
    second = await client.post(
        f"/api/idea/sessions/{session_id}/generate",
        json={
            "expected_version": version,
            "answers": [{"option": "<8GB"}],
        },
    )
    assert second.status_code == 200
    events = _events(second.text)
    assert events[-2]["exhausted"] is True
    assert events[-2]["questions"] == []
    body = (await client.get(f"/api/loop/sessions/{session_id}")).json()
    turns = body["working_draft_narrative"]["turns"]
    assert turns[2] == {"role": "account", "kind": "answers", "answers": [{"option": "<8GB"}]}
    assert turns[3]["questions"] == []
    assert body["working_draft_narrative"]["exhausted"] is True


@pytest.mark.asyncio
async def test_patch_earlier_idea_truncates_later_turns(client: AsyncClient) -> None:
    await _auth_client(client)
    created = await _create_session(client)
    session_id = created["id"]
    _bind_fake()
    first = await client.post(
        f"/api/idea/sessions/{session_id}/generate",
        json={"expected_version": 1, "message": "GPU kernel latency"},
    )
    version = _events(first.text)[-1]["version"]
    patched = await client.patch(
        f"/api/loop/sessions/{session_id}/working-draft",
        json={
            "expected_version": version,
            "narrative": {
                "turns": [
                    {"role": "account", "kind": "idea", "text": "corrected idea"},
                    {
                        "role": "model",
                        "preamble": "What is the compute budget?",
                        "questions": [
                            {
                                "text": "What is the compute budget?",
                                "options": ["<8GB", "8-24GB", ">24GB"],
                            }
                        ],
                    },
                ]
            },
        },
    )
    assert patched.status_code == 200, patched.text
    narrative = patched.json()["working_draft_narrative"]
    assert narrative["exhausted"] is False
    assert narrative["turns"] == [{"role": "account", "kind": "idea", "text": "corrected idea"}]
    assert narrative["frame"] == IDEA_FRAME


@pytest.mark.asyncio
async def test_cluster_note_skips_unanswered_questions(client: AsyncClient) -> None:
    await _auth_client(client)
    created = await _create_session(client)
    session_id = created["id"]
    _bind_fake()
    first = await client.post(
        f"/api/idea/sessions/{session_id}/generate",
        json={"expected_version": 1, "message": "GPU kernel latency"},
    )
    version = _events(first.text)[-1]["version"]
    _bind_fake(response=EXHAUSTED)
    skipped = await client.post(
        f"/api/idea/sessions/{session_id}/generate",
        json={"expected_version": version, "note": "Skip budget. Focus on tiling."},
    )
    assert skipped.status_code == 200, skipped.text
    turns = (await client.get(f"/api/loop/sessions/{session_id}")).json()["working_draft_narrative"][
        "turns"
    ]
    assert turns[1]["questions"]
    assert turns[2] == {
        "role": "account",
        "kind": "note",
        "text": "Skip budget. Focus on tiling.",
    }
    assert turns[3]["questions"] == []
