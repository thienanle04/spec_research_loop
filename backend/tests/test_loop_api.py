"""HTTP seam tests for /api/loop (ADR 0020)."""

import json
from uuid import uuid4

import pytest
from httpx import AsyncClient, Response

from app.adapters.llm import FakeLlm, bind_llm_ports, get_llm_port
from app.modules.loop.catalog import WORKFLOW_NODES, WorkflowNode

CATALOG = [
    "idea_interpretation",
    "idea_decomposition",
    "research_inputs",
    "related_work",
    "gap",
    "contribution",
    "claims",
    "evidence",
    "experiment_plan",
    "feasibility",
    "gap_judge",
    "contribution_judge",
    "evidence_judge",
    "experiment_judge",
    "conference_judge",
    "aggregator",
]


def _head(payload: dict, node: str) -> dict:
    return next(item for item in payload["node_heads"] if item["node"] == node)


async def _register(client: AsyncClient, email: str | None = None) -> str:
    response = await client.post(
        "/api/identity/register",
        json={"email": email or f"{uuid4().hex[:12]}@example.com", "password": "password1"},
    )
    assert response.status_code == 201, response.text
    return response.json()["access_token"]


async def _auth_client(client: AsyncClient) -> AsyncClient:
    token = await _register(client)
    client.headers["Authorization"] = f"Bearer {token}"
    return client


async def _create_session(client: AsyncClient, title: str | None = "Latency idea") -> dict:
    response = await client.post("/api/loop/sessions", json={"title": title})
    assert response.status_code == 201, response.text
    return response.json()


IDEA_FRAME = {
    "intent": "You want to cut GPU kernel DRAM traffic by tiling.",
    "problem": "GPU kernel latency is memory bound",
    "research_question": "Can tiling cut DRAM traffic?",
}


def _changed_interpretation_narrative(problem: str = "latency") -> dict:
    return {
        "exhausted": True,
        "frame": {
            "intent": f"You want to study {problem}.",
            "problem": problem,
            "research_question": IDEA_FRAME["research_question"],
        },
        "turns": [
            {"role": "account", "kind": "idea", "text": problem},
            {"role": "model", "preamble": "Done.", "questions": []},
        ],
    }


def _interpretation_done() -> str:
    payload = {
        "exhausted": True,
        "cards": [],
        "questions": [],
        "frame": IDEA_FRAME,
    }
    return "No further questions.\n---json---\n" + json.dumps(payload)


async def _confirm(
    client: AsyncClient,
    session_id: str,
    node: str,
    expected_version: int,
    *,
    stale_reaccept: bool = False,
) -> dict:
    body: dict = {"node": node, "expected_version": expected_version}
    if stale_reaccept:
        body["stale_reaccept"] = True
    response = await client.post(
        f"/api/loop/sessions/{session_id}/confirm",
        json=body,
    )
    assert response.status_code == 200, response.text
    return response.json()


async def _generate_idea(
    client: AsyncClient,
    session_id: str,
    expected_version: int,
    idea: str = "GPU kernel latency",
    response_text: str | None = None,
) -> int:
    fake = FakeLlm(response=response_text or _interpretation_done())
    ports = {node.value: get_llm_port(node.value) for node in WORKFLOW_NODES}
    ports[WorkflowNode.IDEA_INTERPRETATION.value] = fake
    ports[WorkflowNode.IDEA_DECOMPOSITION.value] = fake
    bind_llm_ports(ports)
    response = await client.post(
        f"/api/idea/sessions/{session_id}/generate",
        json={"expected_version": expected_version, "message": idea},
    )
    assert response.status_code == 200, response.text
    version = None
    for block in response.text.split("\n\n"):
        line = next((item for item in block.split("\n") if item.startswith("data:")), None)
        if not line:
            continue
        event = json.loads(line[5:].strip())
        if event.get("type") == "done":
            version = event["version"]
        if event.get("type") == "error":
            raise AssertionError(event)
    assert version is not None
    return version


async def _interpret(
    client: AsyncClient,
    session_id: str,
    expected_version: int,
    idea: str = "GPU kernel latency",
) -> dict:
    version = await _generate_idea(client, session_id, expected_version, idea)
    return await _confirm(client, session_id, "idea_interpretation", version)


async def _prepare(
    client: AsyncClient, session_id: str, stage: str, expected_version: int
) -> dict:
    response = await client.post(
        f"/api/loop/sessions/{session_id}/recompute-prepare",
        json={"stage": stage, "expected_version": expected_version},
    )
    assert response.status_code == 200, response.text
    return response.json()


async def _confirm_through_related_work(client: AsyncClient) -> dict:
    created = await _create_session(client)
    session_id = created["id"]
    interpreted = await _interpret(client, session_id, created["version"])
    decomposed = await _confirm(
        client, session_id, "idea_decomposition", interpreted["version"]
    )
    inputs = await _prepare(client, session_id, "related_work", decomposed["version"])
    inputs_confirmed = await _confirm(
        client, session_id, "research_inputs", inputs["version"]
    )
    related = await _prepare(
        client, session_id, "related_work", inputs_confirmed["version"]
    )
    return await _confirm(client, session_id, "related_work", related["version"])


async def _create_card(
    client: AsyncClient,
    session_id: str,
    *,
    kind: str,
    body: dict,
    expected_version: int,
) -> Response:
    return await client.post(
        f"/api/loop/sessions/{session_id}/cards",
        json={"kind": kind, "body": body, "expected_version": expected_version},
    )


async def _patch_working_draft(
    client: AsyncClient,
    session_id: str,
    *,
    expected_version: int | None = None,
    node: str | None = None,
    narrative: dict | None = None,
) -> Response:
    body: dict = {}
    if expected_version is not None:
        body["expected_version"] = expected_version
    if node is not None:
        body["node"] = node
    if narrative is not None:
        body["narrative"] = narrative
    return await client.patch(f"/api/loop/sessions/{session_id}/working-draft", json=body)


@pytest.mark.asyncio
async def test_loop_health_is_public(client: AsyncClient) -> None:
    response = await client.get("/api/loop/health")
    assert response.status_code == 200
    assert response.json() == {"module": "loop", "status": "ok"}


@pytest.mark.asyncio
async def test_create_session_requires_bearer(client: AsyncClient) -> None:
    response = await client.post("/api/loop/sessions", json={})
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_create_session_has_empty_catalog_heads(client: AsyncClient) -> None:
    await _auth_client(client)
    payload = await _create_session(client)
    assert payload["version"] == 1
    assert payload["working_draft_node"] == "idea_interpretation"
    assert payload["working_draft_narrative"] == {}
    assert payload["cards"] == []
    assert payload["produced_spec_version"] is None
    assert payload["valid_spec_version_id"] is None
    nodes = [item["node"] for item in payload["node_heads"]]
    assert nodes == CATALOG
    assert [item["status"] for item in payload["node_heads"]] == ["empty"] * 16
    assert len(WORKFLOW_NODES) == 16


@pytest.mark.asyncio
async def test_list_and_get_and_patch_title(client: AsyncClient) -> None:
    await _auth_client(client)
    created = await _create_session(client, title=None)
    session_id = created["id"]
    listed = await client.get("/api/loop/sessions")
    assert listed.status_code == 200
    assert listed.json()[0]["id"] == session_id
    assert listed.json()[0]["version"] == 1
    assert listed.json()[0]["updated_at"] == created["updated_at"]
    patched = await client.patch(
        f"/api/loop/sessions/{session_id}",
        json={"title": "GPU budget"},
    )
    assert patched.status_code == 200
    assert patched.json()["title"] == "GPU budget"
    assert patched.json()["version"] == 1
    fetched = await client.get(f"/api/loop/sessions/{session_id}")
    assert fetched.json()["title"] == "GPU budget"
    assert fetched.json()["version"] == 1


@pytest.mark.asyncio
async def test_list_sessions_orders_by_recent_activity(client: AsyncClient) -> None:
    await _auth_client(client)
    first = await _create_session(client, title="First")
    second = await _create_session(client, title="Second")

    renamed = await client.patch(
        f"/api/loop/sessions/{first['id']}",
        json={"title": "Most recent"},
    )
    assert renamed.status_code == 200

    listed = await client.get("/api/loop/sessions")
    assert listed.status_code == 200
    rows = listed.json()
    assert [row["id"] for row in rows] == [first["id"], second["id"]]
    assert rows[0]["updated_at"] == renamed.json()["updated_at"]


@pytest.mark.asyncio
async def test_patch_title_last_write_wins_without_bumping_version(client: AsyncClient) -> None:
    await _auth_client(client)
    created = await _create_session(client, title="Original")
    first = await client.patch(
        f"/api/loop/sessions/{created['id']}",
        json={"title": "Accepted"},
    )
    assert first.status_code == 200
    assert first.json()["version"] == created["version"]

    second = await client.patch(
        f"/api/loop/sessions/{created['id']}",
        json={"title": "Stale overwrite"},
    )
    assert second.status_code == 200
    assert second.json()["title"] == "Stale overwrite"
    assert second.json()["version"] == created["version"]
    fetched = await client.get(f"/api/loop/sessions/{created['id']}")
    assert fetched.json()["title"] == "Stale overwrite"
    assert fetched.json()["version"] == created["version"]


@pytest.mark.asyncio
async def test_patch_title_does_not_change_working_draft_version(client: AsyncClient) -> None:
    await _auth_client(client)
    created = await _create_session(client)
    draft = await _patch_working_draft(
        client,
        created["id"],
        expected_version=created["version"],
        narrative={"text": "GPU kernels"},
    )
    assert draft.status_code == 200
    assert draft.json()["version"] == 2

    patched = await client.patch(
        f"/api/loop/sessions/{created['id']}",
        json={"title": "GPU budget"},
    )
    assert patched.status_code == 200
    assert patched.json()["title"] == "GPU budget"
    assert patched.json()["version"] == 2
    assert patched.json()["working_draft_narrative"] == draft.json()["working_draft_narrative"]


@pytest.mark.asyncio
async def test_foreign_session_is_not_found(client: AsyncClient) -> None:
    await _auth_client(client)
    created = await _create_session(client)
    other_token = await _register(client)
    client.headers["Authorization"] = f"Bearer {other_token}"
    response = await client.get(f"/api/loop/sessions/{created['id']}")
    assert response.status_code == 404
    missing = await client.get(f"/api/loop/sessions/{uuid4()}")
    assert missing.status_code == 404


@pytest.mark.asyncio
async def test_patch_working_draft_requires_expected_version(client: AsyncClient) -> None:
    await _auth_client(client)
    created = await _create_session(client)
    response = await _patch_working_draft(
        client,
        created["id"],
        narrative={"text": "GPU kernels"},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_patch_working_draft_narrative_increments_version(client: AsyncClient) -> None:
    await _auth_client(client)
    created = await _create_session(client)
    session_id = created["id"]

    response = await _patch_working_draft(
        client,
        session_id,
        expected_version=created["version"],
        narrative={"text": "GPU kernels", "schema": "keep-me"},
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["version"] == 2
    assert payload["working_draft_node"] == "idea_interpretation"
    assert payload["working_draft_narrative"] == {"schema": "keep-me", "text": "GPU kernels"}
    fetched = await client.get(f"/api/loop/sessions/{session_id}")
    assert fetched.json()["working_draft_narrative"] == {"schema": "keep-me", "text": "GPU kernels"}
    assert fetched.json()["version"] == 2


@pytest.mark.asyncio
async def test_stale_working_draft_patch_preserves_server_narrative(client: AsyncClient) -> None:
    await _auth_client(client)
    created = await _create_session(client)
    session_id = created["id"]
    accepted = await _patch_working_draft(
        client,
        session_id,
        expected_version=created["version"],
        narrative={"text": "Accepted idea"},
    )
    assert accepted.status_code == 200
    assert accepted.json()["version"] == 2

    stale = await _patch_working_draft(
        client,
        session_id,
        expected_version=created["version"],
        narrative={"text": "Stale overwrite"},
    )

    assert stale.status_code == 409
    assert stale.json() == {
        "code": "version_conflict",
        "detail": "Loop Session was changed by another request",
        "current_version": 2,
    }
    fetched = await client.get(f"/api/loop/sessions/{session_id}")
    assert fetched.json()["working_draft_narrative"] == {"text": "Accepted idea"}
    assert fetched.json()["version"] == 2


@pytest.mark.asyncio
async def test_stale_working_draft_reopen_is_version_conflict(client: AsyncClient) -> None:
    await _auth_client(client)
    created = await _create_session(client)
    response = await _patch_working_draft(
        client,
        created["id"],
        expected_version=created["version"] + 5,
        node="idea_decomposition",
    )
    assert response.status_code == 409
    assert response.json() == {
        "code": "version_conflict",
        "detail": "Loop Session was changed by another request",
        "current_version": 1,
    }
    fetched = await client.get(f"/api/loop/sessions/{created['id']}")
    assert fetched.json()["working_draft_node"] == "idea_interpretation"
    assert fetched.json()["version"] == 1


@pytest.mark.asyncio
async def test_reopening_empty_workflow_node_is_invalid_working_draft_target(
    client: AsyncClient,
) -> None:
    await _auth_client(client)
    created = await _create_session(client)
    session_id = created["id"]
    interpreted = await _interpret(client, session_id, created["version"])
    confirmed = await _confirm(client, session_id, "idea_decomposition", interpreted["version"])
    response = await _patch_working_draft(
        client,
        session_id,
        expected_version=confirmed["version"],
        node="research_inputs",
    )
    assert response.status_code == 409
    assert response.json()["code"] == "invalid_working_draft_target"
    fetched = await client.get(f"/api/loop/sessions/{session_id}")
    assert fetched.json()["working_draft_node"] == "idea_decomposition"
    assert fetched.json()["version"] == confirmed["version"]


@pytest.mark.asyncio
async def test_reopening_without_current_upstream_is_upstream_not_current(
    client: AsyncClient,
) -> None:
    await _auth_client(client)
    created = await _create_session(client)
    response = await _patch_working_draft(
        client,
        created["id"],
        expected_version=created["version"],
        node="idea_decomposition",
    )
    assert response.status_code == 409
    assert response.json()["code"] == "upstream_not_current"
    fetched = await client.get(f"/api/loop/sessions/{created['id']}")
    assert fetched.json()["working_draft_node"] == "idea_interpretation"
    assert fetched.json()["working_draft_narrative"] == {}
    assert fetched.json()["version"] == 1


@pytest.mark.asyncio
async def test_reopening_current_workflow_node_increments_version(client: AsyncClient) -> None:
    await _auth_client(client)
    created = await _create_session(client)
    session_id = created["id"]
    confirmed = await _interpret(client, session_id, created["version"])
    response = await _patch_working_draft(
        client,
        session_id,
        expected_version=confirmed["version"],
        node="idea_interpretation",
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["working_draft_node"] == "idea_interpretation"
    assert payload["version"] == confirmed["version"] + 1
    fetched = await client.get(f"/api/loop/sessions/{session_id}")
    assert fetched.json()["working_draft_node"] == "idea_interpretation"
    assert fetched.json()["version"] == confirmed["version"] + 1


@pytest.mark.asyncio
async def test_reopening_research_inputs_restores_confirmed_narrative(
    client: AsyncClient,
) -> None:
    await _auth_client(client)
    created = await _create_session(client)
    session_id = created["id"]
    interpreted = await _interpret(client, session_id, created["version"])
    decomposed = await _confirm(
        client, session_id, "idea_decomposition", interpreted["version"]
    )
    research_draft = await _prepare(
        client, session_id, "related_work", decomposed["version"]
    )
    saved_inputs = {
        "keywords": ["claim-level verification", "evidence-grounded feedback"],
        "preferred_sources": {
            "peer_reviewed": True,
            "official_proceedings": True,
        },
    }
    patched = await _patch_working_draft(
        client,
        session_id,
        expected_version=research_draft["version"],
        narrative=saved_inputs,
    )
    confirmed = await _confirm(
        client, session_id, "research_inputs", patched.json()["version"]
    )
    related_work = await _prepare(
        client, session_id, "related_work", confirmed["version"]
    )
    assert related_work["working_draft_narrative"] == {}

    reopened = await _patch_working_draft(
        client,
        session_id,
        expected_version=related_work["version"],
        node="research_inputs",
    )

    assert reopened.status_code == 200, reopened.text
    assert reopened.json()["working_draft_node"] == "research_inputs"
    assert reopened.json()["working_draft_narrative"] == saved_inputs


@pytest.mark.asyncio
async def test_confirm_requires_expected_version(client: AsyncClient) -> None:
    await _auth_client(client)
    created = await _create_session(client)
    response = await client.post(
        f"/api/loop/sessions/{created['id']}/confirm",
        json={"node": "idea_interpretation"},
    )
    assert response.status_code == 422
    fetched = await client.get(f"/api/loop/sessions/{created['id']}")
    assert fetched.json()["working_draft_node"] == "idea_interpretation"
    assert fetched.json()["version"] == 1
    assert _head(fetched.json(), "idea_interpretation")["status"] == "empty"
    decisions = await client.get(f"/api/loop/sessions/{created['id']}/decisions")
    assert decisions.json() == []


@pytest.mark.asyncio
async def test_confirm_wrong_node_conflicts(client: AsyncClient) -> None:
    await _auth_client(client)
    created = await _create_session(client)
    response = await client.post(
        f"/api/loop/sessions/{created['id']}/confirm",
        json={"node": "idea_decomposition", "expected_version": created["version"]},
    )
    assert response.status_code == 409
    assert response.json() == {
        "code": "invalid_working_draft_target",
        "detail": "confirm must target the Working Draft Workflow Node",
        "current_version": None,
    }
    fetched = await client.get(f"/api/loop/sessions/{created['id']}")
    assert fetched.json()["working_draft_node"] == "idea_interpretation"
    assert fetched.json()["version"] == 1
    decisions = await client.get(f"/api/loop/sessions/{created['id']}/decisions")
    assert decisions.json() == []


@pytest.mark.asyncio
async def test_confirm_empty_interpretation_conflicts(client: AsyncClient) -> None:
    await _auth_client(client)
    created = await _create_session(client)
    response = await client.post(
        f"/api/loop/sessions/{created['id']}/confirm",
        json={"node": "idea_interpretation", "expected_version": created["version"]},
    )
    assert response.status_code == 409
    assert response.json()["code"] == "interpretation_not_confirmable"


@pytest.mark.asyncio
async def test_confirm_interpretation_allows_open_cluster(client: AsyncClient) -> None:
    await _auth_client(client)
    created = await _create_session(client)
    open_cluster = (
        "Need the budget.\n---json---\n"
        + json.dumps(
            {
                "exhausted": False,
                "cards": [],
                "questions": [
                    {"text": "Training or inference?", "options": ["Training", "Inference"]}
                ],
                "frame": IDEA_FRAME,
            }
        )
    )
    version = await _generate_idea(
        client, created["id"], created["version"], response_text=open_cluster
    )
    payload = await _confirm(client, created["id"], "idea_interpretation", version)
    assert payload["working_draft_node"] == "idea_decomposition"


@pytest.mark.asyncio
async def test_confirm_interpretation_rejects_frame_without_intent(client: AsyncClient) -> None:
    await _auth_client(client)
    created = await _create_session(client)
    two_field = (
        "Need the budget.\n---json---\n"
        + json.dumps(
            {
                "exhausted": True,
                "cards": [],
                "questions": [],
                "frame": {
                    "problem": IDEA_FRAME["problem"],
                    "research_question": IDEA_FRAME["research_question"],
                },
            }
        )
    )
    version = await _generate_idea(
        client, created["id"], created["version"], response_text=two_field
    )
    response = await client.post(
        f"/api/loop/sessions/{created['id']}/confirm",
        json={"node": "idea_interpretation", "expected_version": version},
    )
    assert response.status_code == 409
    assert response.json()["code"] == "interpretation_not_confirmable"


@pytest.mark.asyncio
async def test_confirm_interpretation_moves_working_draft(client: AsyncClient) -> None:
    await _auth_client(client)
    created = await _create_session(client)
    session_id = created["id"]
    payload = await _interpret(client, session_id, created["version"])
    assert payload["working_draft_node"] == "idea_decomposition"
    assert _head(payload, "idea_interpretation")["status"] == "current"
    assert _head(payload, "idea_interpretation")["stage_revision_id"] is not None
    assert _head(payload, "idea_interpretation")["head_revision"]["narrative"]["frame"]["intent"]
    assert _head(payload, "idea_decomposition")["status"] == "empty"
    assert _head(payload, "idea_decomposition")["head_revision"] is None
    decisions = await client.get(f"/api/loop/sessions/{session_id}/decisions")
    assert decisions.status_code == 200
    rows = decisions.json()
    assert len(rows) == 1
    assert rows[0]["kind"] == "confirm"
    assert rows[0]["node"] == "idea_interpretation"
    assert payload["version"] == created["version"] + 2


@pytest.mark.asyncio
async def test_confirm_increments_version_in_the_freeze_transaction(client: AsyncClient) -> None:
    await _auth_client(client)
    created = await _create_session(client)
    session_id = created["id"]
    payload = await _interpret(client, session_id, created["version"])
    assert payload["version"] == created["version"] + 2
    assert payload["working_draft_node"] == "idea_decomposition"
    assert _head(payload, "idea_interpretation")["status"] == "current"
    fetched = await client.get(f"/api/loop/sessions/{session_id}")
    assert fetched.json()["version"] == created["version"] + 2
    assert fetched.json()["working_draft_node"] == "idea_decomposition"


@pytest.mark.asyncio
async def test_stale_confirm_creates_no_revision_decision_or_handoff(client: AsyncClient) -> None:
    await _auth_client(client)
    created = await _create_session(client)
    bumped = await _patch_working_draft(
        client,
        created["id"],
        expected_version=created["version"],
        narrative={"text": "Accepted idea"},
    )
    assert bumped.status_code == 200
    assert bumped.json()["version"] == 2

    stale = await client.post(
        f"/api/loop/sessions/{created['id']}/confirm",
        json={"node": "idea_interpretation", "expected_version": created["version"]},
    )
    assert stale.status_code == 409
    assert stale.json() == {
        "code": "version_conflict",
        "detail": "Loop Session was changed by another request",
        "current_version": 2,
    }
    fetched = await client.get(f"/api/loop/sessions/{created['id']}")
    payload = fetched.json()
    assert payload["version"] == 2
    assert payload["working_draft_narrative"]["text"] == "Accepted idea"
    assert payload["working_draft_node"] == "idea_interpretation"
    assert payload["produced_spec_version"] is None
    assert payload["valid_spec_version_id"] is None
    assert _head(payload, "idea_interpretation") == {
        "node": "idea_interpretation",
        "status": "empty",
        "stage_revision_id": None,
        "generated_since_prepare": False,
        "head_revision": None,
    }
    decisions = await client.get(f"/api/loop/sessions/{created['id']}/decisions")
    assert decisions.json() == []


@pytest.mark.asyncio
async def test_identical_confirm_is_noop(client: AsyncClient) -> None:
    await _auth_client(client)
    created = await _create_session(client)
    session_id = created["id"]
    first = await _interpret(client, session_id, created["version"])
    revision = _head(first, "idea_interpretation")["stage_revision_id"]
    reopened = await _patch_working_draft(
        client,
        session_id,
        expected_version=first["version"],
        node="idea_interpretation",
    )
    assert reopened.status_code == 200
    second = await _confirm(client, session_id, "idea_interpretation", reopened.json()["version"])
    assert _head(second, "idea_interpretation")["stage_revision_id"] == revision
    decisions = await client.get(f"/api/loop/sessions/{session_id}/decisions")
    assert len(decisions.json()) == 1


@pytest.mark.asyncio
async def test_card_write_requires_owning_working_draft(client: AsyncClient) -> None:
    await _auth_client(client)
    created = await _create_session(client)
    session_id = created["id"]
    denied = await _create_card(
        client,
        session_id,
        kind="problem",
        body={"text": "too soon"},
        expected_version=created["version"],
    )
    assert denied.status_code == 409
    assert denied.json() == {
        "code": "card_owner_mismatch",
        "detail": "Card writes require the Working Draft to be the owning Workflow Node",
        "current_version": None,
    }
    confirmed = await _interpret(client, session_id, created["version"])
    created_card = await _create_card(
        client,
        session_id,
        kind="problem",
        body={"text": "LLM latency"},
        expected_version=confirmed["version"],
    )
    assert created_card.status_code == 201, created_card.text
    assert created_card.json()["kind"] == "problem"
    constraint = await _create_card(
        client,
        session_id,
        kind="constraint",
        body={"text": "one 16GB GPU"},
        expected_version=created_card.json()["version"],
    )
    assert constraint.status_code == 201


@pytest.mark.asyncio
async def test_create_card_requires_expected_version(client: AsyncClient) -> None:
    await _auth_client(client)
    created = await _create_session(client)
    session_id = created["id"]
    await _interpret(client, session_id, created["version"])

    response = await client.post(
        f"/api/loop/sessions/{session_id}/cards",
        json={"kind": "problem", "body": {"text": "LLM latency"}},
    )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_create_and_patch_card_increment_session_version(client: AsyncClient) -> None:
    await _auth_client(client)
    created = await _create_session(client)
    session_id = created["id"]
    confirmed = await _interpret(client, session_id, created["version"])

    created_card = await _create_card(
        client,
        session_id,
        kind="problem",
        body={"schema": "keep-me", "text": "LLM latency"},
        expected_version=confirmed["version"],
    )
    assert created_card.status_code == 201, created_card.text
    payload = created_card.json()
    assert payload["kind"] == "problem"
    assert payload["body"] == {"schema": "keep-me", "text": "LLM latency"}
    assert payload["version"] == confirmed["version"] + 1

    patched = await client.patch(
        f"/api/loop/sessions/{session_id}/cards/{payload['id']}",
        json={
            "expected_version": payload["version"],
            "body": {"schema": "keep-me", "extra": 7, "text": "GPU kernels"},
        },
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["version"] == confirmed["version"] + 2
    assert patched.json()["body"] == {"schema": "keep-me", "extra": 7, "text": "GPU kernels"}

    fetched = await client.get(f"/api/loop/sessions/{session_id}")
    assert fetched.json()["version"] == confirmed["version"] + 2
    assert fetched.json()["cards"][0]["body"] == {
        "schema": "keep-me",
        "extra": 7,
        "text": "GPU kernels",
    }


@pytest.mark.asyncio
async def test_stale_card_write_makes_no_partial_change(client: AsyncClient) -> None:
    await _auth_client(client)
    created = await _create_session(client)
    session_id = created["id"]
    confirmed = await _interpret(client, session_id, created["version"])

    accepted = await _create_card(
        client,
        session_id,
        kind="problem",
        body={"text": "Accepted problem"},
        expected_version=confirmed["version"],
    )
    assert accepted.status_code == 201, accepted.text
    card_id = accepted.json()["id"]

    stale_create = await _create_card(
        client,
        session_id,
        kind="constraint",
        body={"text": "stale constraint"},
        expected_version=created["version"],
    )
    assert stale_create.status_code == 409
    assert stale_create.json() == {
        "code": "version_conflict",
        "detail": "Loop Session was changed by another request",
        "current_version": confirmed["version"] + 1,
    }

    stale_patch = await client.patch(
        f"/api/loop/sessions/{session_id}/cards/{card_id}",
        json={"expected_version": created["version"], "body": {"text": "Stale overwrite"}},
    )
    assert stale_patch.status_code == 409
    assert stale_patch.json() == {
        "code": "version_conflict",
        "detail": "Loop Session was changed by another request",
        "current_version": confirmed["version"] + 1,
    }

    fetched = await client.get(f"/api/loop/sessions/{session_id}")
    assert fetched.json()["version"] == confirmed["version"] + 1
    assert fetched.json()["cards"] == [
        {
            "id": card_id,
            "kind": "problem",
            "body": {"text": "Accepted problem"},
            "created_at": accepted.json()["created_at"],
            "updated_at": accepted.json()["updated_at"],
        }
    ]


@pytest.mark.asyncio
async def test_changed_interpretation_marks_decomposition_stale(client: AsyncClient) -> None:
    await _auth_client(client)
    created = await _create_session(client)
    session_id = created["id"]
    interpreted = await _interpret(client, session_id, created["version"])
    card = await _create_card(
        client,
        session_id,
        kind="problem",
        body={"text": "accuracy"},
        expected_version=interpreted["version"],
    )
    assert card.status_code == 201
    decomposed = await _confirm(client, session_id, "idea_decomposition", card.json()["version"])
    reopened = await _patch_working_draft(
        client,
        session_id,
        expected_version=decomposed["version"],
        node="idea_interpretation",
        narrative=_changed_interpretation_narrative(),
    )
    assert reopened.status_code == 200
    payload = await _confirm(
        client, session_id, "idea_interpretation", reopened.json()["version"]
    )
    assert _head(payload, "idea_decomposition")["status"] == "stale"
    assert payload["valid_spec_version_id"] is None


@pytest.mark.asyncio
async def test_prepare_requires_expected_version(client: AsyncClient) -> None:
    await _auth_client(client)
    created = await _create_session(client)
    response = await client.post(
        f"/api/loop/sessions/{created['id']}/recompute-prepare",
        json={"stage": "grilling"},
    )
    assert response.status_code == 422
    fetched = await client.get(f"/api/loop/sessions/{created['id']}")
    assert fetched.json()["working_draft_node"] == "idea_interpretation"
    assert fetched.json()["version"] == 1


@pytest.mark.asyncio
async def test_prepare_increments_version_and_returns_session(client: AsyncClient) -> None:
    await _auth_client(client)
    created = await _create_session(client)
    payload = await _prepare(client, created["id"], "grilling", created["version"])
    assert payload["version"] == 2
    assert payload["working_draft_node"] == "idea_interpretation"
    assert payload["working_draft_narrative"] == {}
    assert _head(payload, "idea_interpretation")["status"] == "empty"
    fetched = await client.get(f"/api/loop/sessions/{created['id']}")
    assert fetched.json()["version"] == 2
    assert fetched.json()["working_draft_node"] == "idea_interpretation"


@pytest.mark.asyncio
async def test_stale_prepare_is_version_conflict(client: AsyncClient) -> None:
    await _auth_client(client)
    created = await _create_session(client)
    bumped = await _patch_working_draft(
        client,
        created["id"],
        expected_version=created["version"],
        narrative={"text": "Accepted idea"},
    )
    assert bumped.status_code == 200
    assert bumped.json()["version"] == 2

    stale = await client.post(
        f"/api/loop/sessions/{created['id']}/recompute-prepare",
        json={"stage": "grilling", "expected_version": created["version"]},
    )
    assert stale.status_code == 409
    assert stale.json() == {
        "code": "version_conflict",
        "detail": "Loop Session was changed by another request",
        "current_version": 2,
    }
    fetched = await client.get(f"/api/loop/sessions/{created['id']}")
    assert fetched.json()["working_draft_narrative"]["text"] == "Accepted idea"
    assert fetched.json()["version"] == 2
    assert fetched.json()["working_draft_node"] == "idea_interpretation"


@pytest.mark.asyncio
async def test_prepare_grilling_lands_on_stale_decomposition(client: AsyncClient) -> None:
    await _auth_client(client)
    created = await _create_session(client)
    session_id = created["id"]
    interpreted = await _interpret(client, session_id, created["version"])
    card = await _create_card(
        client,
        session_id,
        kind="problem",
        body={"text": "accuracy"},
        expected_version=interpreted["version"],
    )
    assert card.status_code == 201
    decomposed = await _confirm(client, session_id, "idea_decomposition", card.json()["version"])
    reopened = await _patch_working_draft(
        client,
        session_id,
        expected_version=decomposed["version"],
        node="idea_interpretation",
        narrative=_changed_interpretation_narrative(),
    )
    assert reopened.status_code == 200
    changed = await _confirm(
        client, session_id, "idea_interpretation", reopened.json()["version"]
    )
    payload = await _prepare(client, session_id, "grilling", changed["version"])
    assert payload["working_draft_node"] == "idea_decomposition"
    assert payload["version"] == changed["version"] + 1
    assert _head(payload, "idea_interpretation")["status"] == "current"
    assert _head(payload, "idea_decomposition")["status"] == "stale"
    assert payload["working_draft_narrative"] == {}
    fetched = await client.get(f"/api/loop/sessions/{session_id}")
    problem = next(item for item in fetched.json()["cards"] if item["kind"] == "problem")
    assert problem["body"] == {"text": "accuracy"}


@pytest.mark.asyncio
async def test_prepare_grilling_conflicts_when_current(client: AsyncClient) -> None:
    await _auth_client(client)
    created = await _create_session(client)
    session_id = created["id"]
    interpreted = await _interpret(client, session_id, created["version"])
    confirmed = await _confirm(client, session_id, "idea_decomposition", interpreted["version"])
    response = await client.post(
        f"/api/loop/sessions/{session_id}/recompute-prepare",
        json={"stage": "grilling", "expected_version": confirmed["version"]},
    )
    assert response.status_code == 409
    assert response.json()["code"] == "stage_already_current"
    fetched = await client.get(f"/api/loop/sessions/{session_id}")
    assert fetched.json()["working_draft_node"] == "idea_decomposition"
    assert fetched.json()["version"] == confirmed["version"]


@pytest.mark.asyncio
async def test_prepare_readiness_conflicts(client: AsyncClient) -> None:
    await _auth_client(client)
    created = await _create_session(client)
    response = await client.post(
        f"/api/loop/sessions/{created['id']}/recompute-prepare",
        json={"stage": "readiness", "expected_version": created["version"]},
    )
    assert response.status_code == 409
    assert response.json()["code"] == "stage_already_current"
    fetched = await client.get(f"/api/loop/sessions/{created['id']}")
    assert fetched.json()["version"] == 1


@pytest.mark.asyncio
async def test_prepare_related_work_requires_grilling(client: AsyncClient) -> None:
    await _auth_client(client)
    created = await _create_session(client)
    response = await client.post(
        f"/api/loop/sessions/{created['id']}/recompute-prepare",
        json={"stage": "related_work", "expected_version": created["version"]},
    )
    assert response.status_code == 409
    assert response.json()["code"] == "upstream_not_current"
    fetched = await client.get(f"/api/loop/sessions/{created['id']}")
    assert fetched.json()["working_draft_node"] == "idea_interpretation"
    assert fetched.json()["version"] == 1


@pytest.mark.asyncio
async def test_prepare_accepts_gap_contribution_and_spec_draft_stages(
    client: AsyncClient,
) -> None:
    await _auth_client(client)
    created = await _create_session(client)
    for stage in ("gap", "contribution", "spec_draft"):
        response = await client.post(
            f"/api/loop/sessions/{created['id']}/recompute-prepare",
            json={"stage": stage, "expected_version": created["version"]},
        )
        assert response.status_code != 422, response.text


@pytest.mark.asyncio
async def test_prepare_spec_draft_conflicts_like_readiness(client: AsyncClient) -> None:
    await _auth_client(client)
    created = await _create_session(client)
    response = await client.post(
        f"/api/loop/sessions/{created['id']}/recompute-prepare",
        json={"stage": "spec_draft", "expected_version": created["version"]},
    )
    assert response.status_code == 409
    assert response.json()["code"] == "stage_already_current"
    fetched = await client.get(f"/api/loop/sessions/{created['id']}")
    assert fetched.json()["version"] == 1
    assert fetched.json()["working_draft_node"] == "idea_interpretation"


@pytest.mark.asyncio
async def test_prepare_related_work_does_not_reset_gap_or_contribution(
    client: AsyncClient,
) -> None:
    await _auth_client(client)
    related = await _confirm_through_related_work(client)
    session_id = related["id"]
    response = await client.post(
        f"/api/loop/sessions/{session_id}/recompute-prepare",
        json={"stage": "related_work", "expected_version": related["version"]},
    )
    assert response.status_code == 409
    assert response.json()["code"] == "stage_already_current"
    fetched = await client.get(f"/api/loop/sessions/{session_id}")
    payload = fetched.json()
    assert payload["version"] == related["version"]
    assert payload["working_draft_node"] == "related_work"
    assert _head(payload, "research_inputs")["status"] == "current"
    assert _head(payload, "related_work")["status"] == "current"
    assert _head(payload, "gap")["status"] == "empty"
    assert _head(payload, "contribution")["status"] == "empty"


@pytest.mark.asyncio
async def test_prepare_gap_only_considers_gap(client: AsyncClient) -> None:
    await _auth_client(client)
    related = await _confirm_through_related_work(client)
    session_id = related["id"]
    payload = await _prepare(client, session_id, "gap", related["version"])
    assert payload["working_draft_node"] == "gap"
    assert payload["version"] == related["version"] + 1
    assert _head(payload, "research_inputs")["status"] == "current"
    assert _head(payload, "related_work")["status"] == "current"
    assert _head(payload, "gap")["status"] == "empty"
    assert _head(payload, "contribution")["status"] == "empty"


@pytest.mark.asyncio
async def test_prepare_contribution_only_considers_contribution(
    client: AsyncClient,
) -> None:
    await _auth_client(client)
    related = await _confirm_through_related_work(client)
    session_id = related["id"]
    gap = await _prepare(client, session_id, "gap", related["version"])
    gap_card = await _create_card(
        client,
        session_id,
        kind="gap",
        body={
            "statement": "Claim-level feedback remains underexplored.",
            "supporting_citation_keys": ["opro-2023"],
            "status": "insufficient_evidence",
        },
        expected_version=gap["version"],
    )
    assert gap_card.status_code == 201, gap_card.text
    gap_confirmed = await _confirm(
        client, session_id, "gap", gap_card.json()["version"]
    )
    payload = await _prepare(
        client, session_id, "contribution", gap_confirmed["version"]
    )
    assert payload["working_draft_node"] == "contribution"
    assert _head(payload, "gap")["status"] == "current"
    assert _head(payload, "related_work")["status"] == "current"
    assert _head(payload, "contribution")["status"] == "empty"


@pytest.mark.asyncio
async def test_prepare_gap_requires_related_work(client: AsyncClient) -> None:
    await _auth_client(client)
    created = await _create_session(client)
    interpreted = await _interpret(client, created["id"], created["version"])
    decomposed = await _confirm(
        client, created["id"], "idea_decomposition", interpreted["version"]
    )
    response = await client.post(
        f"/api/loop/sessions/{created['id']}/recompute-prepare",
        json={"stage": "gap", "expected_version": decomposed["version"]},
    )
    assert response.status_code == 409
    assert response.json()["code"] == "upstream_not_current"
    fetched = await client.get(f"/api/loop/sessions/{created['id']}")
    assert fetched.json()["working_draft_node"] == "idea_decomposition"
    assert fetched.json()["version"] == decomposed["version"]


@pytest.mark.asyncio
async def test_prepare_contribution_requires_gap(client: AsyncClient) -> None:
    await _auth_client(client)
    related = await _confirm_through_related_work(client)
    response = await client.post(
        f"/api/loop/sessions/{related['id']}/recompute-prepare",
        json={"stage": "contribution", "expected_version": related["version"]},
    )
    assert response.status_code == 409
    assert response.json()["code"] == "upstream_not_current"
    fetched = await client.get(f"/api/loop/sessions/{related['id']}")
    assert fetched.json()["working_draft_node"] == "related_work"
    assert fetched.json()["version"] == related["version"]
    assert _head(fetched.json(), "gap")["status"] == "empty"


@pytest.mark.asyncio
async def test_feasibility_confirm_mints_spec_version(client: AsyncClient) -> None:
    await _auth_client(client)
    created = await _create_session(client)
    session_id = created["id"]
    interpreted = await _interpret(client, session_id, created["version"])
    decomposed = await _confirm(client, session_id, "idea_decomposition", interpreted["version"])
    inputs = await _prepare(client, session_id, "related_work", decomposed["version"])
    inputs_confirmed = await _confirm(
        client, session_id, "research_inputs", inputs["version"]
    )
    related = await _prepare(
        client, session_id, "related_work", inputs_confirmed["version"]
    )
    related_generation = await client.post(
        f"/api/research/sessions/{session_id}/nodes/related_work/generate",
        json={"expected_version": related["version"], "max_results": 5},
    )
    related_events = [
        json.loads(line.removeprefix("data: "))
        for line in related_generation.text.splitlines()
        if line.startswith("data: ")
    ]
    related_confirmed = await _confirm(
        client, session_id, "related_work", related_events[-1]["version"]
    )
    gap = await _prepare(client, session_id, "gap", related_confirmed["version"])
    gap_generation = await client.post(
        f"/api/research/sessions/{session_id}/nodes/gap/generate",
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
    card = await client.post(
        f"/api/loop/sessions/{session_id}/cards",
        json={
            "kind": "gap",
            "body": candidate,
            "expected_version": gap_events[-1]["version"],
        },
    )
    assert card.status_code == 201, card.text
    gap_confirmed = await _confirm(
        client, session_id, "gap", card.json()["version"]
    )
    expected_version = gap_confirmed["version"]
    for stage, node in (
        ("contribution", "contribution"),
        ("claims_evidence", "claims"),
        ("claims_evidence", "evidence"),
        ("experiment_planning", "experiment_plan"),
        ("experiment_planning", "feasibility"),
    ):
        prepared = await _prepare(client, session_id, stage, expected_version)
        assert prepared["working_draft_node"] == node
        confirmed = await _confirm(client, session_id, node, prepared["version"])
        expected_version = confirmed["version"]
    fetched = await client.get(f"/api/loop/sessions/{session_id}")
    payload = fetched.json()
    assert payload["produced_spec_version"] is not None
    assert payload["valid_spec_version_id"] == payload["produced_spec_version"]["id"]
    assert "idea_interpretation" in payload["produced_spec_version"]["document"]["nodes"]
    assert "feasibility" in payload["produced_spec_version"]["document"]["nodes"]
    nodes = payload["produced_spec_version"]["document"]["nodes"]
    for node_name, node_document in nodes.items():
        assert node_document["stage_revision_id"] == _head(payload, node_name)[
            "stage_revision_id"
        ]
    gap_document = nodes["gap"]
    assert "candidate" not in gap_document["narrative"]
    assert gap_document["card_snapshot"] == [
        {
            "id": card.json()["id"],
            "kind": "gap",
            "body": candidate,
        }
    ]
    related_revision_id = nodes["related_work"]["stage_revision_id"]
    frozen_citations = await client.get(
        f"/api/research/sessions/{session_id}/citations",
        params={"stage_revision_id": related_revision_id},
    )
    assert frozen_citations.status_code == 200, frozen_citations.text
    assert len(frozen_citations.json()) >= 1
    frozen_findings = await client.get(
        f"/api/research/sessions/{session_id}/findings",
        params={"stage_revision_id": related_revision_id},
    )
    assert frozen_findings.status_code == 200, frozen_findings.text
    assert len(frozen_findings.json()) >= 1


async def _stale_decomposition_prepared(client: AsyncClient) -> dict:
    created = await _create_session(client)
    session_id = created["id"]
    interpreted = await _interpret(client, session_id, created["version"])
    card = await _create_card(
        client,
        session_id,
        kind="problem",
        body={"text": "accuracy"},
        expected_version=interpreted["version"],
    )
    assert card.status_code == 201
    decomposed = await _confirm(
        client, session_id, "idea_decomposition", card.json()["version"]
    )
    reopened = await _patch_working_draft(
        client,
        session_id,
        expected_version=decomposed["version"],
        node="idea_interpretation",
        narrative=_changed_interpretation_narrative(),
    )
    assert reopened.status_code == 200
    changed = await _confirm(
        client, session_id, "idea_interpretation", reopened.json()["version"]
    )
    assert _head(changed, "idea_decomposition")["status"] == "stale"
    assert _head(changed, "idea_decomposition")["generated_since_prepare"] is False
    return await _prepare(client, session_id, "grilling", changed["version"])


@pytest.mark.asyncio
async def test_stale_confirm_without_generate_requires_reaccept(
    client: AsyncClient,
) -> None:
    await _auth_client(client)
    prepared = await _stale_decomposition_prepared(client)
    session_id = prepared["id"]
    assert _head(prepared, "idea_decomposition")["status"] == "stale"
    assert _head(prepared, "idea_decomposition")["generated_since_prepare"] is False

    denied = await client.post(
        f"/api/loop/sessions/{session_id}/confirm",
        json={
            "node": "idea_decomposition",
            "expected_version": prepared["version"],
        },
    )
    assert denied.status_code == 409
    assert denied.json()["code"] == "stale_reaccept_required"

    accepted = await _confirm(
        client,
        session_id,
        "idea_decomposition",
        prepared["version"],
        stale_reaccept=True,
    )
    assert _head(accepted, "idea_decomposition")["status"] == "current"
    assert _head(accepted, "idea_decomposition")["generated_since_prepare"] is False


@pytest.mark.asyncio
async def test_stale_confirm_after_generate_skips_reaccept(
    client: AsyncClient,
) -> None:
    await _auth_client(client)
    prepared = await _stale_decomposition_prepared(client)
    session_id = prepared["id"]
    version = await _generate_idea(
        client,
        session_id,
        prepared["version"],
        idea="accuracy",
        response_text=(
            "Cards ready.\n---json---\n"
            + json.dumps(
                {
                    "exhausted": True,
                    "cards": [
                        {"kind": "problem", "text": "accuracy"},
                        {
                            "kind": "research_question",
                            "text": IDEA_FRAME["research_question"],
                        },
                    ],
                }
            )
        ),
    )
    fetched = await client.get(f"/api/loop/sessions/{session_id}")
    assert _head(fetched.json(), "idea_decomposition")["generated_since_prepare"] is True
    confirmed = await _confirm(client, session_id, "idea_decomposition", version)
    assert _head(confirmed, "idea_decomposition")["status"] == "current"
    assert _head(confirmed, "idea_decomposition")["generated_since_prepare"] is False
