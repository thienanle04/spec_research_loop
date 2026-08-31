"""Judgement HTTP seam: Gap Judge generate, floors, Confirm, ownership."""

import json

import pytest
from httpx import AsyncClient

from app.adapters.llm import FakeLlm, bind_llm_ports, get_llm_port
from app.modules.loop.catalog import FIVE_JUDGE_NODES, WORKFLOW_NODES, WorkflowNode
from tests.test_loop_api import (
    _auth_client,
    _confirm,
    _create_session,
    _head,
    _interpret,
    _patch_working_draft,
    _prepare,
    _register,
)

UNSUPPORTED_GAP = (
    "The literature has not measured whether brass instruments improve "
    "soil nitrogen fixation in alpine peat bogs."
)
UNSUPPORTED_CLAIM = (
    "The literature has not measured whether brass instruments improve "
    "soil nitrogen fixation in alpine peat bogs."
)


def _events(body: str) -> list[dict]:
    return [
        json.loads(line.removeprefix("data: "))
        for line in body.splitlines()
        if line.startswith("data: ")
    ]


def _bind_gap_judge_llm(payload: dict) -> FakeLlm:
    fake = FakeLlm(response=json.dumps(payload))
    ports = {node.value: get_llm_port(node.value) for node in WORKFLOW_NODES}
    ports[WorkflowNode.GAP_JUDGE.value] = fake
    bind_llm_ports(ports)
    return fake


def _bind_evidence_judge_llm(payload: dict) -> FakeLlm:
    fake = FakeLlm(response=json.dumps(payload))
    ports = {node.value: get_llm_port(node.value) for node in WORKFLOW_NODES}
    ports[WorkflowNode.EVIDENCE_JUDGE.value] = fake
    bind_llm_ports(ports)
    return fake


async def _mint_valid_spec(
    client: AsyncClient,
    *,
    gap_statement: str | None = None,
    claim_statement: str | None = None,
) -> dict:
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
    related_generation = await client.post(
        f"/api/research/sessions/{session_id}/nodes/related_work/generate",
        json={"expected_version": related["version"], "max_results": 5},
    )
    related_events = _events(related_generation.text)
    citation_keys = [
        event["citation"]["citation_key"]
        for event in related_events
        if event.get("type") == "citation_upsert"
    ]
    related_confirmed = await _confirm(
        client, session_id, "related_work", related_events[-1]["version"]
    )
    gap = await _prepare(client, session_id, "gap", related_confirmed["version"])
    gap_generation = await client.post(
        f"/api/research/sessions/{session_id}/nodes/gap/generate",
        json={"expected_version": gap["version"]},
    )
    gap_events = _events(gap_generation.text)
    candidate = next(
        event["narrative"]["candidate"]
        for event in gap_events
        if event["type"] == "draft_patch"
    )
    if gap_statement is not None:
        candidate = {
            **candidate,
            "statement": gap_statement,
            "supporting_citation_keys": [],
        }
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
        if node == "claims" and claim_statement is not None:
            assert citation_keys, "fixture Related Work must yield a Citation"
            claim = await client.post(
                f"/api/loop/sessions/{session_id}/cards",
                json={
                    "kind": "claim",
                    "body": {
                        "statement": claim_statement,
                        "supporting_citation_keys": [citation_keys[0]],
                    },
                    "expected_version": prepared["version"],
                },
            )
            assert claim.status_code == 201, claim.text
            confirmed = await _confirm(
                client, session_id, node, claim.json()["version"]
            )
        else:
            confirmed = await _confirm(client, session_id, node, prepared["version"])
        expected_version = confirmed["version"]
    fetched = await client.get(f"/api/loop/sessions/{session_id}")
    payload = fetched.json()
    assert payload["valid_spec_version_id"] == payload["produced_spec_version"]["id"]
    return payload


async def _prepare_gap_judge(
    client: AsyncClient,
    *,
    gap_statement: str | None = None,
    claim_statement: str | None = None,
) -> dict:
    minted = await _mint_valid_spec(
        client, gap_statement=gap_statement, claim_statement=claim_statement
    )
    return await _prepare(
        client, minted["id"], "independent_judges", minted["version"]
    )


async def _open_independent_judges_node(
    client: AsyncClient, session: dict, node: str
) -> dict:
    if session["working_draft_node"] == node:
        return session
    patched = await _patch_working_draft(
        client,
        session["id"],
        expected_version=session["version"],
        node=node,
    )
    assert patched.status_code == 200, patched.text
    return patched.json()


async def _prepare_evidence_judge(
    client: AsyncClient,
    *,
    gap_statement: str | None = None,
    claim_statement: str | None = UNSUPPORTED_CLAIM,
) -> dict:
    draft = await _prepare_gap_judge(
        client, gap_statement=gap_statement, claim_statement=claim_statement
    )
    return await _open_independent_judges_node(client, draft, "evidence_judge")


async def _generate_gap_judge(
    client: AsyncClient, session_id: str, expected_version: int, **extra: object
) -> list[dict]:
    body: dict = {"expected_version": expected_version, **extra}
    response = await client.post(
        f"/api/judgement/sessions/{session_id}/nodes/gap_judge/generate",
        json=body,
    )
    assert response.status_code == 200, response.text
    events = _events(response.text)
    assert events[-1]["type"] == "done"
    return events


@pytest.mark.asyncio
async def test_gap_judge_generate_requires_valid_spec_version(
    client: AsyncClient,
) -> None:
    await _auth_client(client)
    created = await _create_session(client)
    response = await client.post(
        f"/api/judgement/sessions/{created['id']}/nodes/gap_judge/generate",
        json={"expected_version": created["version"]},
    )
    assert response.status_code == 409
    assert response.json()["code"] == "valid_spec_version_required"


@pytest.mark.asyncio
async def test_gap_judge_generate_rejects_working_draft_outside_independent_judges(
    client: AsyncClient,
) -> None:
    await _auth_client(client)
    minted = await _mint_valid_spec(client)
    response = await client.post(
        f"/api/judgement/sessions/{minted['id']}/nodes/gap_judge/generate",
        json={"expected_version": minted["version"]},
    )
    assert response.status_code == 409
    assert response.json()["code"] == "invalid_working_draft_target"


@pytest.mark.asyncio
async def test_other_account_cannot_read_or_generate_gap_judge(
    client: AsyncClient,
) -> None:
    await _auth_client(client)
    draft = await _prepare_gap_judge(client)
    token = await _register(client, email="other-judge@example.com")
    client.headers["Authorization"] = f"Bearer {token}"
    listed = await client.get(
        f"/api/judgement/sessions/{draft['id']}/nodes/gap_judge"
    )
    assert listed.status_code == 404
    generated = await client.post(
        f"/api/judgement/sessions/{draft['id']}/nodes/gap_judge/generate",
        json={"expected_version": draft["version"]},
    )
    assert generated.status_code == 404


@pytest.mark.asyncio
async def test_gap_judge_generate_version_conflict(client: AsyncClient) -> None:
    await _auth_client(client)
    draft = await _prepare_gap_judge(client)
    response = await client.post(
        f"/api/judgement/sessions/{draft['id']}/nodes/gap_judge/generate",
        json={"expected_version": draft["version"] - 1},
    )
    assert response.status_code == 409
    assert response.json()["code"] == "version_conflict"


@pytest.mark.asyncio
async def test_gap_verifier_emits_critical_when_llm_omits_issues(
    client: AsyncClient,
) -> None:
    await _auth_client(client)
    draft = await _prepare_gap_judge(client, gap_statement=UNSUPPORTED_GAP)
    events = await _generate_gap_judge(client, draft["id"], draft["version"])
    assert events[0]["type"] == "progress"
    patch = next(event for event in events if event["type"] == "draft_patch")
    kinds = {item["finding_kind"] for item in patch["issues"]}
    assert "gap_unsupported_by_sources" in kinds
    assert all(
        item["severity"] == "CRITICAL"
        for item in patch["issues"]
        if item["finding_kind"] == "gap_unsupported_by_sources"
    )

    listed = await client.get(
        f"/api/judgement/sessions/{draft['id']}/nodes/gap_judge"
    )
    assert listed.status_code == 200, listed.text
    stored = listed.json()["issues"]
    assert any(
        item["finding_kind"] == "gap_unsupported_by_sources"
        and item["severity"] == "CRITICAL"
        for item in stored
    )


@pytest.mark.asyncio
async def test_gap_judge_floors_llm_minor_unsupported_gap_to_critical(
    client: AsyncClient,
) -> None:
    await _auth_client(client)
    draft = await _prepare_gap_judge(client)
    _bind_gap_judge_llm(
        {
            "issues": [
                {
                    "finding_kind": "gap_unsupported_by_sources",
                    "severity": "MINOR",
                    "reason": "The model tried to hide this.",
                    "suggestion": "Ignore it.",
                },
                {
                    "finding_kind": "invented_kind",
                    "severity": "CRITICAL",
                    "reason": "Should be dropped.",
                    "suggestion": "",
                },
                {
                    "finding_kind": "gap_untestable",
                    "severity": "CRITICAL",
                    "reason": "No evaluation protocol exists.",
                    "suggestion": "Add a measurable test.",
                },
            ]
        }
    )
    events = await _generate_gap_judge(client, draft["id"], draft["version"])
    patch = next(event for event in events if event["type"] == "draft_patch")
    by_kind = {item["finding_kind"]: item for item in patch["issues"]}
    assert "invented_kind" not in by_kind
    assert by_kind["gap_unsupported_by_sources"]["severity"] == "CRITICAL"
    assert by_kind["gap_untestable"]["severity"] == "CRITICAL"
    assert (
        sum(
            1
            for item in patch["issues"]
            if item["finding_kind"] == "gap_unsupported_by_sources"
        )
        == 1
    )


async def _session(client: AsyncClient, session_id: str) -> dict:
    response = await client.get(f"/api/loop/sessions/{session_id}")
    assert response.status_code == 200, response.text
    return response.json()


async def _decisions(client: AsyncClient, session_id: str) -> list[dict]:
    response = await client.get(f"/api/loop/sessions/{session_id}/decisions")
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.asyncio
async def test_gap_judge_generate_records_confirm_while_working_draft_is_aggregator(
    client: AsyncClient,
) -> None:
    await _auth_client(client)
    draft = await _prepare_gap_judge(client, gap_statement=UNSUPPORTED_GAP)
    assert draft["working_draft_node"] == "aggregator"
    produced_id = draft["produced_spec_version"]["id"]
    valid_id = draft["valid_spec_version_id"]
    events = await _generate_gap_judge(client, draft["id"], draft["version"])
    assert events[-1]["type"] == "done"
    session = await _session(client, draft["id"])
    assert session["working_draft_node"] == "aggregator"
    assert session["version"] == events[-1]["version"]
    assert _head(session, "gap_judge")["status"] == "current"
    assert session["valid_spec_version_id"] == valid_id
    assert session["produced_spec_version"]["id"] == produced_id
    revision_id = _head(session, "gap_judge")["stage_revision_id"]
    assert revision_id is not None
    frozen = await client.get(
        f"/api/judgement/sessions/{draft['id']}/nodes/gap_judge",
        params={"stage_revision_id": revision_id},
    )
    assert frozen.status_code == 200, frozen.text
    assert any(
        item["finding_kind"] == "gap_unsupported_by_sources"
        and item["severity"] == "CRITICAL"
        for item in frozen.json()["issues"]
    )
    confirms = [
        row
        for row in await _decisions(client, draft["id"])
        if row["kind"] == "confirm" and row["node"] == "gap_judge"
    ]
    assert len(confirms) == 1
    assert confirms[0]["stage_revision_id"] == revision_id

    denied = await client.post(
        f"/api/loop/sessions/{draft['id']}/confirm",
        json={
            "node": "gap_judge",
            "expected_version": session["version"],
        },
    )
    assert denied.status_code == 409
    assert denied.json()["code"] == "invalid_working_draft_target"


@pytest.mark.asyncio
async def test_failed_gap_judge_generate_does_not_confirm(client: AsyncClient) -> None:
    await _auth_client(client)
    draft = await _prepare_gap_judge(client)
    fake = FakeLlm(response="not-json")
    ports = {node.value: get_llm_port(node.value) for node in WORKFLOW_NODES}
    ports[WorkflowNode.GAP_JUDGE.value] = fake
    bind_llm_ports(ports)
    response = await client.post(
        f"/api/judgement/sessions/{draft['id']}/nodes/gap_judge/generate",
        json={"expected_version": draft["version"]},
    )
    assert response.status_code == 200, response.text
    events = _events(response.text)
    assert any(event.get("type") == "error" for event in events)
    assert all(event.get("type") != "done" for event in events)
    session = await _session(client, draft["id"])
    assert session["working_draft_node"] == "aggregator"
    assert _head(session, "gap_judge")["status"] == "empty"
    confirms = [
        row
        for row in await _decisions(client, draft["id"])
        if row["kind"] == "confirm" and row["node"] == "gap_judge"
    ]
    assert confirms == []


@pytest.mark.asyncio
async def test_confirm_aggregator_requires_working_draft_aggregator(
    client: AsyncClient,
) -> None:
    await _auth_client(client)
    draft = await _prepare_gap_judge(client)
    opened = await _open_independent_judges_node(client, draft, "gap_judge")
    assert opened["working_draft_node"] == "gap_judge"
    denied = await client.post(
        f"/api/loop/sessions/{draft['id']}/confirm",
        json={
            "node": "aggregator",
            "expected_version": opened["version"],
        },
    )
    assert denied.status_code == 409
    assert denied.json()["code"] == "invalid_working_draft_target"


INDEPENDENT_JUDGES_NODES = (*FIVE_JUDGE_NODES, WorkflowNode.AGGREGATOR)


@pytest.mark.asyncio
async def test_prepare_independent_judges_lands_working_draft_on_aggregator_when_all_empty(
    client: AsyncClient,
) -> None:
    await _auth_client(client)
    draft = await _prepare_gap_judge(client)
    assert draft["working_draft_node"] == "aggregator"
    for node in INDEPENDENT_JUDGES_NODES:
        head = _head(draft, node.value)
        assert head["status"] == "empty"
        listed = await client.get(
            f"/api/judgement/sessions/{draft['id']}/nodes/{node.value}"
        )
        assert listed.status_code == 200, listed.text
        assert listed.json()["issues"] == []
        assert listed.json().get("scores") is None


@pytest.mark.asyncio
async def test_prepare_independent_judges_does_not_wipe_current_gap_judge(
    client: AsyncClient,
) -> None:
    await _auth_client(client)
    draft = await _prepare_gap_judge(client, gap_statement=UNSUPPORTED_GAP)
    draft = await _open_independent_judges_node(client, draft, "gap_judge")
    await _generate_gap_judge(client, draft["id"], draft["version"])
    confirmed = await _session(client, draft["id"])
    revision_id = _head(confirmed, "gap_judge")["stage_revision_id"]
    prepared = await _prepare(
        client, draft["id"], "independent_judges", confirmed["version"]
    )
    assert prepared["working_draft_node"] == "aggregator"
    assert _head(prepared, "gap_judge")["status"] == "current"
    assert _head(prepared, "gap_judge")["stage_revision_id"] == revision_id
    frozen = await client.get(
        f"/api/judgement/sessions/{draft['id']}/nodes/gap_judge",
        params={"stage_revision_id": revision_id},
    )
    assert any(
        item["finding_kind"] == "gap_unsupported_by_sources"
        for item in frozen.json()["issues"]
    )


@pytest.mark.asyncio
async def test_prepare_independent_judges_lands_aggregator_when_current_judges_and_stale_aggregator(
    client: AsyncClient,
) -> None:
    await _auth_client(client)
    prepared = await _stale_experiment_and_conference(client)
    gap_revision = _head(prepared, "gap_judge")["stage_revision_id"]
    assert prepared["working_draft_node"] == "aggregator"
    assert _head(prepared, "gap_judge")["status"] == "current"
    assert _head(prepared, "aggregator")["status"] == "stale"
    assert _head(prepared, "gap_judge")["stage_revision_id"] == gap_revision


@pytest.mark.asyncio
async def test_prepare_independent_judges_conflicts_when_all_six_heads_current(
    client: AsyncClient,
) -> None:
    await _auth_client(client)
    draft = await _prepare_aggregator(client)
    _bind_aggregator_llm({"options": []})
    generated = await _generate_aggregator(client, draft["id"], draft["version"])
    confirmed = await _confirm(
        client, draft["id"], "aggregator", generated[-1]["version"]
    )
    response = await client.post(
        f"/api/loop/sessions/{confirmed['id']}/recompute-prepare",
        json={
            "stage": "independent_judges",
            "expected_version": confirmed["version"],
        },
    )
    assert response.status_code == 409
    assert response.json()["code"] == "stage_already_current"
    fetched = await client.get(f"/api/loop/sessions/{confirmed['id']}")
    assert fetched.json()["working_draft_node"] == "aggregator"
    assert fetched.json()["version"] == confirmed["version"]


@pytest.mark.asyncio
async def test_gap_judge_generate_allowed_when_working_draft_is_sibling_judge(
    client: AsyncClient,
) -> None:
    await _auth_client(client)
    draft = await _prepare_gap_judge(client, gap_statement=UNSUPPORTED_GAP)
    await _generate_gap_judge(client, draft["id"], draft["version"])
    confirmed = await _session(client, draft["id"])
    prepared = await _prepare(
        client, draft["id"], "independent_judges", confirmed["version"]
    )
    assert prepared["working_draft_node"] == "aggregator"
    sibling = await _generate_gap_judge(
        client, draft["id"], prepared["version"]
    )
    patch = next(event for event in sibling if event["type"] == "draft_patch")
    assert any(
        item["finding_kind"] == "gap_unsupported_by_sources"
        for item in patch["issues"]
    )


@pytest.mark.asyncio
async def test_gap_judge_content_change_stales_aggregator(
    client: AsyncClient,
) -> None:
    await _auth_client(client)
    draft = await _prepare_gap_judge(client, gap_statement=UNSUPPORTED_GAP)
    await _generate_gap_judge(client, draft["id"], draft["version"])
    session = await _session(client, draft["id"])
    session = await _advance_to_aggregator(client, session)
    session = await _confirm(
        client, draft["id"], "aggregator", session["version"]
    )
    assert _head(session, "aggregator")["status"] == "current"

    reopened = await _patch_working_draft(
        client,
        draft["id"],
        expected_version=session["version"],
        node="gap_judge",
    )
    assert reopened.status_code == 200, reopened.text
    _bind_gap_judge_llm(
        {
            "issues": [
                {
                    "finding_kind": "gap_already_addressed",
                    "severity": "MAJOR",
                    "reason": "A prior paper already closed this gap.",
                    "suggestion": "Narrow the claim.",
                }
            ]
        }
    )
    await _generate_gap_judge(
        client, draft["id"], reopened.json()["version"]
    )
    changed = await _session(client, draft["id"])
    assert _head(changed, "aggregator")["status"] == "stale"
    assert changed["valid_spec_version_id"] == changed["produced_spec_version"]["id"]
    listed = await client.get(
        f"/api/judgement/sessions/{draft['id']}/nodes/gap_judge"
    )
    kinds = {item["finding_kind"] for item in listed.json()["issues"]}
    assert "gap_already_addressed" in kinds
    assert all(
        item["severity"] == "CRITICAL"
        for item in listed.json()["issues"]
        if item["finding_kind"] == "gap_already_addressed"
    )


async def _generate_evidence_judge(
    client: AsyncClient, session_id: str, expected_version: int, **extra: object
) -> list[dict]:
    body: dict = {"expected_version": expected_version, **extra}
    response = await client.post(
        f"/api/judgement/sessions/{session_id}/nodes/evidence_judge/generate",
        json=body,
    )
    assert response.status_code == 200, response.text
    events = _events(response.text)
    assert events[-1]["type"] == "done"
    return events


@pytest.mark.asyncio
async def test_evidence_judge_generate_runs_with_valid_spec_version(
    client: AsyncClient,
) -> None:
    await _auth_client(client)
    draft = await _prepare_gap_judge(client)
    events = await _generate_evidence_judge(client, draft["id"], draft["version"])
    assert events[0]["type"] == "progress"
    patch = next(event for event in events if event["type"] == "draft_patch")
    listed = await client.get(
        f"/api/judgement/sessions/{draft['id']}/nodes/evidence_judge"
    )
    assert listed.status_code == 200, listed.text
    assert listed.json()["node"] == "evidence_judge"
    assert patch["issues"] == listed.json()["issues"]


@pytest.mark.asyncio
async def test_evidence_verifier_emits_critical_when_llm_omits_issues(
    client: AsyncClient,
) -> None:
    await _auth_client(client)
    draft = await _prepare_gap_judge(client, claim_statement=UNSUPPORTED_CLAIM)
    events = await _generate_evidence_judge(client, draft["id"], draft["version"])
    patch = next(event for event in events if event["type"] == "draft_patch")
    assert any(
        item["finding_kind"] == "unsupported_citation"
        and item["severity"] == "CRITICAL"
        for item in patch["issues"]
    )
    listed = await client.get(
        f"/api/judgement/sessions/{draft['id']}/nodes/evidence_judge"
    )
    assert listed.status_code == 200, listed.text
    assert any(
        item["finding_kind"] == "unsupported_citation"
        and item["severity"] == "CRITICAL"
        for item in listed.json()["issues"]
    )


@pytest.mark.asyncio
async def test_evidence_judge_floors_llm_minor_unsupported_citation_to_critical(
    client: AsyncClient,
) -> None:
    await _auth_client(client)
    draft = await _prepare_evidence_judge(client)
    _bind_evidence_judge_llm(
        {
            "issues": [
                {
                    "finding_kind": "unsupported_citation",
                    "severity": "MINOR",
                    "reason": "The model tried to hide this.",
                    "suggestion": "Ignore it.",
                },
                {
                    "finding_kind": "invented_kind",
                    "severity": "CRITICAL",
                    "reason": "Should be dropped.",
                    "suggestion": "",
                },
            ]
        }
    )
    events = await _generate_evidence_judge(client, draft["id"], draft["version"])
    patch = next(event for event in events if event["type"] == "draft_patch")
    by_kind = {item["finding_kind"]: item for item in patch["issues"]}
    assert "invented_kind" not in by_kind
    assert by_kind["unsupported_citation"]["severity"] == "CRITICAL"
    assert (
        sum(
            1
            for item in patch["issues"]
            if item["finding_kind"] == "unsupported_citation"
        )
        == 1
    )


@pytest.mark.asyncio
async def test_confirm_evidence_judge_with_critical_keeps_spec_version(
    client: AsyncClient,
) -> None:
    await _auth_client(client)
    draft = await _prepare_evidence_judge(client)
    await _generate_evidence_judge(client, draft["id"], draft["version"])
    confirmed = await _session(client, draft["id"])
    assert _head(confirmed, "evidence_judge")["status"] == "current"
    assert confirmed["valid_spec_version_id"] == confirmed["produced_spec_version"]["id"]
    revision_id = _head(confirmed, "evidence_judge")["stage_revision_id"]
    frozen = await client.get(
        f"/api/judgement/sessions/{draft['id']}/nodes/evidence_judge",
        params={"stage_revision_id": revision_id},
    )
    assert frozen.status_code == 200, frozen.text
    assert any(
        item["finding_kind"] == "unsupported_citation"
        and item["severity"] == "CRITICAL"
        for item in frozen.json()["issues"]
    )


@pytest.mark.asyncio
async def test_evidence_judge_generate_allowed_when_working_draft_is_sibling_judge(
    client: AsyncClient,
) -> None:
    await _auth_client(client)
    draft = await _prepare_gap_judge(client, claim_statement=UNSUPPORTED_CLAIM)
    await _generate_gap_judge(client, draft["id"], draft["version"])
    confirmed = await _session(client, draft["id"])
    prepared = await _prepare(
        client, draft["id"], "independent_judges", confirmed["version"]
    )
    assert prepared["working_draft_node"] == "aggregator"
    sibling = await _generate_evidence_judge(
        client, draft["id"], prepared["version"]
    )
    patch = next(event for event in sibling if event["type"] == "draft_patch")
    assert any(
        item["finding_kind"] == "unsupported_citation"
        for item in patch["issues"]
    )


@pytest.mark.asyncio
async def test_evidence_judge_content_change_stales_aggregator(
    client: AsyncClient,
) -> None:
    await _auth_client(client)
    draft = await _prepare_evidence_judge(client)
    await _generate_evidence_judge(client, draft["id"], draft["version"])
    session = await _session(client, draft["id"])
    session = await _advance_to_aggregator(client, session)
    session = await _confirm(
        client, draft["id"], "aggregator", session["version"]
    )
    assert _head(session, "aggregator")["status"] == "current"

    reopened = await _patch_working_draft(
        client,
        draft["id"],
        expected_version=session["version"],
        node="evidence_judge",
    )
    assert reopened.status_code == 200, reopened.text
    _bind_evidence_judge_llm(
        {
            "issues": [
                {
                    "finding_kind": "claim_broader_than_experiment",
                    "severity": "MAJOR",
                    "reason": "The claim outruns the experiment plan.",
                    "suggestion": "Narrow the claim.",
                }
            ]
        }
    )
    await _generate_evidence_judge(
        client, draft["id"], reopened.json()["version"]
    )
    changed = await _session(client, draft["id"])
    assert _head(changed, "aggregator")["status"] == "stale"
    assert changed["valid_spec_version_id"] == changed["produced_spec_version"]["id"]
    listed = await client.get(
        f"/api/judgement/sessions/{draft['id']}/nodes/evidence_judge"
    )
    assert any(
        item["finding_kind"] == "unsupported_citation"
        and item["severity"] == "CRITICAL"
        for item in listed.json()["issues"]
    )


def _bind_contribution_judge_llm(payload: dict) -> FakeLlm:
    fake = FakeLlm(response=json.dumps(payload))
    ports = {node.value: get_llm_port(node.value) for node in WORKFLOW_NODES}
    ports[WorkflowNode.CONTRIBUTION_JUDGE.value] = fake
    bind_llm_ports(ports)
    return fake


async def _generate_contribution_judge(
    client: AsyncClient, session_id: str, expected_version: int, **extra: object
) -> list[dict]:
    body: dict = {"expected_version": expected_version, **extra}
    response = await client.post(
        f"/api/judgement/sessions/{session_id}/nodes/contribution_judge/generate",
        json=body,
    )
    assert response.status_code == 200, response.text
    events = _events(response.text)
    assert events[-1]["type"] == "done"
    return events


@pytest.mark.asyncio
async def test_contribution_judge_generate_runs_with_valid_spec_version(
    client: AsyncClient,
) -> None:
    await _auth_client(client)
    draft = await _prepare_gap_judge(client)
    events = await _generate_contribution_judge(
        client, draft["id"], draft["version"]
    )
    assert events[0]["type"] == "progress"
    patch = next(event for event in events if event["type"] == "draft_patch")
    listed = await client.get(
        f"/api/judgement/sessions/{draft['id']}/nodes/contribution_judge"
    )
    assert listed.status_code == 200, listed.text
    assert listed.json()["node"] == "contribution_judge"
    assert patch["issues"] == listed.json()["issues"]


def _bind_experiment_judge_llm(payload: dict) -> FakeLlm:
    fake = FakeLlm(response=json.dumps(payload))
    ports = {node.value: get_llm_port(node.value) for node in WORKFLOW_NODES}
    ports[WorkflowNode.EXPERIMENT_JUDGE.value] = fake
    bind_llm_ports(ports)
    return fake


async def _generate_experiment_judge(
    client: AsyncClient, session_id: str, expected_version: int, **extra: object
) -> list[dict]:
    body: dict = {"expected_version": expected_version, **extra}
    response = await client.post(
        f"/api/judgement/sessions/{session_id}/nodes/experiment_judge/generate",
        json=body,
    )
    assert response.status_code == 200, response.text
    events = _events(response.text)
    assert events[-1]["type"] == "done"
    return events


@pytest.mark.asyncio
async def test_experiment_judge_generate_runs_with_valid_spec_version(
    client: AsyncClient,
) -> None:
    await _auth_client(client)
    draft = await _prepare_gap_judge(client)
    events = await _generate_experiment_judge(client, draft["id"], draft["version"])
    assert events[0]["type"] == "progress"
    patch = next(event for event in events if event["type"] == "draft_patch")
    listed = await client.get(
        f"/api/judgement/sessions/{draft['id']}/nodes/experiment_judge"
    )
    assert listed.status_code == 200, listed.text
    assert listed.json()["node"] == "experiment_judge"
    assert patch["issues"] == listed.json()["issues"]


async def _prepare_contribution_judge(client: AsyncClient) -> dict:
    draft = await _prepare_gap_judge(client)
    return await _open_independent_judges_node(client, draft, "contribution_judge")


async def _prepare_experiment_judge(
    client: AsyncClient,
    *,
    gap_statement: str | None = None,
    claim_statement: str | None = None,
) -> dict:
    kwargs: dict = {}
    if gap_statement is not None:
        kwargs["gap_statement"] = gap_statement
    if claim_statement is not None:
        kwargs["claim_statement"] = claim_statement
    draft = await _prepare_gap_judge(client, **kwargs)
    return await _open_independent_judges_node(client, draft, "experiment_judge")


@pytest.mark.asyncio
async def test_contribution_judge_floors_llm_minor_overclaim_to_major(
    client: AsyncClient,
) -> None:
    await _auth_client(client)
    draft = await _prepare_contribution_judge(client)
    _bind_contribution_judge_llm(
        {
            "issues": [
                {
                    "finding_kind": "contribution_not_novel",
                    "severity": "MAJOR",
                    "reason": "Prior work already states this contribution.",
                    "suggestion": "Narrow the novelty claim.",
                },
                {
                    "finding_kind": "contribution_overclaimed",
                    "severity": "MINOR",
                    "reason": "The model tried to hide this.",
                    "suggestion": "Ignore it.",
                },
                {
                    "finding_kind": "invented_kind",
                    "severity": "CRITICAL",
                    "reason": "Should be dropped.",
                    "suggestion": "",
                },
            ]
        }
    )
    events = await _generate_contribution_judge(
        client, draft["id"], draft["version"]
    )
    patch = next(event for event in events if event["type"] == "draft_patch")
    by_kind = {item["finding_kind"]: item for item in patch["issues"]}
    assert "invented_kind" not in by_kind
    assert by_kind["contribution_not_novel"]["severity"] == "MAJOR"
    assert by_kind["contribution_overclaimed"]["severity"] == "MAJOR"


@pytest.mark.asyncio
async def test_experiment_judge_floors_llm_minor_broader_claim_to_major(
    client: AsyncClient,
) -> None:
    await _auth_client(client)
    draft = await _prepare_experiment_judge(client)
    _bind_experiment_judge_llm(
        {
            "issues": [
                {
                    "finding_kind": "experiment_insufficient_for_claim",
                    "severity": "MAJOR",
                    "reason": "The experiment cannot support the claim.",
                    "suggestion": "Add a measurement that matches the claim.",
                },
                {
                    "finding_kind": "claim_broader_than_experiment",
                    "severity": "MINOR",
                    "reason": "The model tried to hide this.",
                    "suggestion": "Ignore it.",
                },
                {
                    "finding_kind": "invented_kind",
                    "severity": "CRITICAL",
                    "reason": "Should be dropped.",
                    "suggestion": "",
                },
            ]
        }
    )
    events = await _generate_experiment_judge(client, draft["id"], draft["version"])
    patch = next(event for event in events if event["type"] == "draft_patch")
    by_kind = {item["finding_kind"]: item for item in patch["issues"]}
    assert "invented_kind" not in by_kind
    assert by_kind["experiment_insufficient_for_claim"]["severity"] == "MAJOR"
    assert by_kind["claim_broader_than_experiment"]["severity"] == "MAJOR"


@pytest.mark.asyncio
async def test_confirm_contribution_judge_with_major_keeps_spec_version(
    client: AsyncClient,
) -> None:
    await _auth_client(client)
    draft = await _prepare_contribution_judge(client)
    _bind_contribution_judge_llm(
        {
            "issues": [
                {
                    "finding_kind": "contribution_not_novel",
                    "severity": "MAJOR",
                    "reason": "Prior work already states this contribution.",
                    "suggestion": "Narrow the novelty claim.",
                }
            ]
        }
    )
    await _generate_contribution_judge(
        client, draft["id"], draft["version"]
    )
    confirmed = await _session(client, draft["id"])
    assert _head(confirmed, "contribution_judge")["status"] == "current"
    assert confirmed["valid_spec_version_id"] == confirmed["produced_spec_version"]["id"]
    revision_id = _head(confirmed, "contribution_judge")["stage_revision_id"]
    frozen = await client.get(
        f"/api/judgement/sessions/{draft['id']}/nodes/contribution_judge",
        params={"stage_revision_id": revision_id},
    )
    assert frozen.status_code == 200, frozen.text
    assert any(
        item["finding_kind"] == "contribution_not_novel"
        and item["severity"] == "MAJOR"
        for item in frozen.json()["issues"]
    )


@pytest.mark.asyncio
async def test_confirm_experiment_judge_with_critical_keeps_spec_version(
    client: AsyncClient,
) -> None:
    await _auth_client(client)
    draft = await _prepare_experiment_judge(client)
    _bind_experiment_judge_llm(
        {
            "issues": [
                {
                    "finding_kind": "claim_broader_than_experiment",
                    "severity": "CRITICAL",
                    "reason": "The claim outruns the experiment plan.",
                    "suggestion": "Narrow the claim.",
                }
            ]
        }
    )
    await _generate_experiment_judge(client, draft["id"], draft["version"])
    confirmed = await _session(client, draft["id"])
    assert _head(confirmed, "experiment_judge")["status"] == "current"
    assert confirmed["valid_spec_version_id"] == confirmed["produced_spec_version"]["id"]
    revision_id = _head(confirmed, "experiment_judge")["stage_revision_id"]
    frozen = await client.get(
        f"/api/judgement/sessions/{draft['id']}/nodes/experiment_judge",
        params={"stage_revision_id": revision_id},
    )
    assert frozen.status_code == 200, frozen.text
    assert any(
        item["finding_kind"] == "claim_broader_than_experiment"
        and item["severity"] == "CRITICAL"
        for item in frozen.json()["issues"]
    )


@pytest.mark.asyncio
async def test_contribution_judge_generate_payload_excludes_peer_judge_runs(
    client: AsyncClient,
) -> None:
    await _auth_client(client)
    draft = await _prepare_gap_judge(client, gap_statement=UNSUPPORTED_GAP)
    await _generate_gap_judge(client, draft["id"], draft["version"])
    confirmed = await _session(client, draft["id"])
    prepared = await _prepare(
        client, draft["id"], "independent_judges", confirmed["version"]
    )
    fake = _bind_contribution_judge_llm({"issues": []})
    await _generate_contribution_judge(client, draft["id"], prepared["version"])
    assert fake.calls
    prompt = fake.calls[0].prompt
    assert "gap_unsupported_by_sources" not in prompt
    assert "gap_judge" not in prompt


CONFERENCE_SCORES = {
    "originality": 7,
    "significance": 8,
    "soundness": 6,
    "clarity": 7,
    "reproducibility": 5,
}


def _bind_conference_judge_llm(payload: dict) -> FakeLlm:
    fake = FakeLlm(response=json.dumps(payload))
    ports = {node.value: get_llm_port(node.value) for node in WORKFLOW_NODES}
    ports[WorkflowNode.CONFERENCE_JUDGE.value] = fake
    bind_llm_ports(ports)
    return fake


async def _generate_conference_judge(
    client: AsyncClient, session_id: str, expected_version: int, **extra: object
) -> list[dict]:
    body: dict = {"expected_version": expected_version, **extra}
    response = await client.post(
        f"/api/judgement/sessions/{session_id}/nodes/conference_judge/generate",
        json=body,
    )
    assert response.status_code == 200, response.text
    events = _events(response.text)
    assert events[-1]["type"] == "done"
    return events


async def _prepare_conference_judge(
    client: AsyncClient,
    *,
    gap_statement: str | None = None,
    claim_statement: str | None = None,
) -> dict:
    draft = await _prepare_gap_judge(
        client, gap_statement=gap_statement, claim_statement=claim_statement
    )
    return await _open_independent_judges_node(client, draft, "conference_judge")


@pytest.mark.asyncio
async def test_conference_judge_generate_requires_valid_spec_version(
    client: AsyncClient,
) -> None:
    await _auth_client(client)
    created = await _create_session(client)
    response = await client.post(
        f"/api/judgement/sessions/{created['id']}/nodes/conference_judge/generate",
        json={"expected_version": created["version"]},
    )
    assert response.status_code == 409
    assert response.json()["code"] == "valid_spec_version_required"


@pytest.mark.asyncio
async def test_conference_judge_generate_runs_with_valid_spec_version(
    client: AsyncClient,
) -> None:
    await _auth_client(client)
    draft = await _prepare_gap_judge(client)
    _bind_conference_judge_llm({"scores": CONFERENCE_SCORES})
    events = await _generate_conference_judge(
        client, draft["id"], draft["version"]
    )
    assert events[0]["type"] == "progress"
    patch = next(event for event in events if event["type"] == "draft_patch")
    assert patch["issues"] == []
    assert patch["scores"] == CONFERENCE_SCORES
    listed = await client.get(
        f"/api/judgement/sessions/{draft['id']}/nodes/conference_judge"
    )
    assert listed.status_code == 200, listed.text
    assert listed.json()["node"] == "conference_judge"
    assert listed.json()["issues"] == []
    assert listed.json()["scores"] == CONFERENCE_SCORES


@pytest.mark.asyncio
async def test_conference_judge_drops_llm_finding_kinds(
    client: AsyncClient,
) -> None:
    await _auth_client(client)
    draft = await _prepare_gap_judge(client)
    _bind_conference_judge_llm(
        {
            "scores": CONFERENCE_SCORES,
            "issues": [
                {
                    "finding_kind": "gap_unsupported_by_sources",
                    "severity": "CRITICAL",
                    "reason": "Conference Judge must not emit Judge Issues.",
                    "suggestion": "Drop this.",
                },
                {
                    "finding_kind": "unsupported_citation",
                    "severity": "CRITICAL",
                    "reason": "Also dropped.",
                    "suggestion": "",
                },
            ],
        }
    )
    events = await _generate_conference_judge(
        client, draft["id"], draft["version"]
    )
    patch = next(event for event in events if event["type"] == "draft_patch")
    assert patch["issues"] == []
    assert patch["scores"] == CONFERENCE_SCORES
    listed = await client.get(
        f"/api/judgement/sessions/{draft['id']}/nodes/conference_judge"
    )
    assert listed.json()["issues"] == []
    assert listed.json()["scores"] == CONFERENCE_SCORES


@pytest.mark.asyncio
async def test_conference_judge_generate_payload_excludes_peer_judge_runs(
    client: AsyncClient,
) -> None:
    await _auth_client(client)
    draft = await _prepare_gap_judge(client, gap_statement=UNSUPPORTED_GAP)
    await _generate_gap_judge(client, draft["id"], draft["version"])
    confirmed = await _session(client, draft["id"])
    prepared = await _prepare(
        client, draft["id"], "independent_judges", confirmed["version"]
    )
    fake = _bind_conference_judge_llm({"scores": CONFERENCE_SCORES})
    await _generate_conference_judge(client, draft["id"], prepared["version"])
    assert fake.calls
    prompt = fake.calls[0].prompt
    view = json.loads(prompt)
    assert view["node"] == "conference_judge"
    assert view["valid_spec_version"]["id"]
    assert "gap_unsupported_by_sources" not in prompt
    assert "gap_judge" not in prompt
    nodes = view["valid_spec_version"]["document"]["nodes"]
    assert "gap" in nodes
    assert "contribution" in nodes
    assert "claims" in nodes
    assert "evidence" in nodes
    assert "experiment_plan" in nodes
    assert view["gap_statement"]


@pytest.mark.asyncio
async def test_confirm_conference_judge_freezes_scores_without_unminting(
    client: AsyncClient,
) -> None:
    await _auth_client(client)
    draft = await _prepare_conference_judge(client)
    produced_id = draft["produced_spec_version"]["id"]
    valid_id = draft["valid_spec_version_id"]
    _bind_conference_judge_llm({"scores": CONFERENCE_SCORES})
    await _generate_conference_judge(
        client, draft["id"], draft["version"]
    )
    confirmed = await _session(client, draft["id"])
    assert _head(confirmed, "conference_judge")["status"] == "current"
    assert confirmed["valid_spec_version_id"] == valid_id
    assert confirmed["produced_spec_version"]["id"] == produced_id
    revision_id = _head(confirmed, "conference_judge")["stage_revision_id"]
    frozen = await client.get(
        f"/api/judgement/sessions/{draft['id']}/nodes/conference_judge",
        params={"stage_revision_id": revision_id},
    )
    assert frozen.status_code == 200, frozen.text
    assert frozen.json()["issues"] == []
    assert frozen.json()["scores"] == CONFERENCE_SCORES


def _bind_aggregator_llm(payload: dict) -> FakeLlm:
    fake = FakeLlm(response=json.dumps(payload))
    ports = {node.value: get_llm_port(node.value) for node in WORKFLOW_NODES}
    ports[WorkflowNode.AGGREGATOR.value] = fake
    bind_llm_ports(ports)
    return fake


async def _generate_aggregator(
    client: AsyncClient, session_id: str, expected_version: int, **extra: object
) -> list[dict]:
    body: dict = {"expected_version": expected_version, **extra}
    response = await client.post(
        f"/api/judgement/sessions/{session_id}/nodes/aggregator/generate",
        json=body,
    )
    assert response.status_code == 200, response.text
    events = _events(response.text)
    assert events[-1]["type"] == "done"
    return events


async def _confirm_five_judge_heads(client: AsyncClient, session: dict) -> dict:
    for node in FIVE_JUDGE_NODES:
        if _head(session, node.value)["status"] == "current":
            continue
        session = await _open_independent_judges_node(client, session, node.value)
        if node is WorkflowNode.CONFERENCE_JUDGE:
            _bind_conference_judge_llm({"scores": CONFERENCE_SCORES})
            await _generate_conference_judge(
                client, session["id"], session["version"]
            )
            session = await _session(client, session["id"])
        else:
            session = await _confirm(
                client, session["id"], node.value, session["version"]
            )
    return session


async def _advance_to_aggregator(client: AsyncClient, session: dict) -> dict:
    session = await _confirm_five_judge_heads(client, session)
    if session["working_draft_node"] == "aggregator":
        return session
    return await _prepare(
        client, session["id"], "independent_judges", session["version"]
    )


async def _prepare_aggregator(
    client: AsyncClient,
    *,
    gap_statement: str | None = None,
    claim_statement: str | None = None,
) -> dict:
    draft = await _prepare_gap_judge(
        client, gap_statement=gap_statement, claim_statement=claim_statement
    )
    return await _advance_to_aggregator(client, draft)


@pytest.mark.asyncio
async def test_aggregator_generate_conflicts_until_five_judge_heads_are_current(
    client: AsyncClient,
) -> None:
    await _auth_client(client)
    draft = await _prepare_gap_judge(client)
    response = await client.post(
        f"/api/judgement/sessions/{draft['id']}/nodes/aggregator/generate",
        json={"expected_version": draft["version"]},
    )
    assert response.status_code == 409
    assert response.json()["code"] == "judge_heads_not_current"


@pytest.mark.asyncio
async def test_aggregator_generate_prompt_view_is_five_current_judge_runs(
    client: AsyncClient,
) -> None:
    await _auth_client(client)
    draft = await _prepare_gap_judge(client, gap_statement=UNSUPPORTED_GAP)
    await _generate_gap_judge(client, draft["id"], draft["version"])
    session = await _session(client, draft["id"])
    session = await _advance_to_aggregator(client, session)
    assert session["working_draft_node"] == "aggregator"
    fake = _bind_aggregator_llm({"options": []})
    await _generate_aggregator(client, draft["id"], session["version"])
    assert fake.calls
    view = json.loads(fake.calls[0].prompt)
    assert view["node"] == "aggregator"
    assert [run["node"] for run in view["judge_runs"]] == [
        "gap_judge",
        "contribution_judge",
        "evidence_judge",
        "experiment_judge",
        "conference_judge",
    ]
    gap_run = view["judge_runs"][0]
    assert any(
        item["finding_kind"] == "gap_unsupported_by_sources"
        and item["severity"] == "CRITICAL"
        for item in gap_run["issues"]
    )
    assert view["judge_runs"][4]["scores"] == CONFERENCE_SCORES
    assert "valid_spec_version" not in view
    assert "cards" not in view
    assert "gap_statement" not in view
    assert "related_work" not in view


@pytest.mark.asyncio
async def test_aggregator_copies_severity_and_ignores_majority_verdict(
    client: AsyncClient,
) -> None:
    await _auth_client(client)
    evidence = await _prepare_evidence_judge(
        client, claim_statement=UNSUPPORTED_CLAIM
    )
    events = await _generate_evidence_judge(
        client, evidence["id"], evidence["version"]
    )
    session = await _session(client, evidence["id"])
    session = await _prepare(
        client, evidence["id"], "independent_judges", session["version"]
    )
    draft = await _advance_to_aggregator(client, session)
    listed = await client.get(
        f"/api/judgement/sessions/{draft['id']}/nodes/evidence_judge"
    )
    assert any(
        item["finding_kind"] == "unsupported_citation"
        and item["severity"] == "CRITICAL"
        for item in listed.json()["issues"]
    )
    _bind_aggregator_llm(
        {
            "verdict": "ACCEPT",
            "issues": [
                {
                    "finding_kind": "unsupported_citation",
                    "severity": "MINOR",
                    "reason": "Majority of Judges accepted.",
                    "suggestion": "Ignore the Evidence Judge.",
                }
            ],
            "options": [],
        }
    )
    events = await _generate_aggregator(client, draft["id"], draft["version"])
    patch = next(event for event in events if event["type"] == "draft_patch")
    assert any(
        item["finding_kind"] == "unsupported_citation"
        and item["severity"] == "CRITICAL"
        and item.get("source_node") == "evidence_judge"
        for item in patch["issues"]
    )
    assert all(item["severity"] != "MINOR" for item in patch["issues"])
    assert "verdict" not in patch
    stored = await client.get(
        f"/api/judgement/sessions/{draft['id']}/nodes/aggregator"
    )
    assert stored.status_code == 200, stored.text
    assert any(
        item["finding_kind"] == "unsupported_citation"
        and item["severity"] == "CRITICAL"
        for item in stored.json()["issues"]
    )
    disagreement = stored.json()["clusters"]["disagreement"]
    assert any(
        item["finding_kind"] == "unsupported_citation"
        for item in disagreement
    )


@pytest.mark.asyncio
async def test_aggregator_handling_options_skip_minor_and_other(
    client: AsyncClient,
) -> None:
    await _auth_client(client)
    evidence = await _prepare_evidence_judge(
        client, claim_statement=UNSUPPORTED_CLAIM
    )
    events = await _generate_evidence_judge(
        client, evidence["id"], evidence["version"]
    )
    session = await _session(client, evidence["id"])
    session = await _prepare(
        client, evidence["id"], "independent_judges", session["version"]
    )
    _bind_experiment_judge_llm(
        {
            "issues": [
                {
                    "finding_kind": "claim_broader_than_experiment",
                    "severity": "MAJOR",
                    "reason": "The claim outruns the experiment plan.",
                    "suggestion": "Narrow the claim.",
                }
            ]
        }
    )
    await _generate_experiment_judge(
        client, session["id"], session["version"]
    )
    session = await _session(client, session["id"])
    session = await _prepare(
        client, session["id"], "independent_judges", session["version"]
    )
    draft = await _advance_to_aggregator(client, session)
    _bind_aggregator_llm(
        {
            "options": [
                {
                    "finding_kind": "unsupported_citation",
                    "source_node": "evidence_judge",
                    "label": "Revise the claim",
                    "target_node": "claims",
                    "prose": "Cite a passage that entails the claim.",
                },
                {
                    "finding_kind": "claim_broader_than_experiment",
                    "source_node": "experiment_judge",
                    "label": "Narrow the experiment",
                    "target_node": "experiment_plan",
                    "prose": "Match the experiment to the claim.",
                },
                {
                    "finding_kind": "unsupported_citation",
                    "source_node": "evidence_judge",
                    "label": "Other",
                    "target_node": "claims",
                    "prose": "Account-invented Other must be dropped.",
                },
                {
                    "finding_kind": "unsupported_citation",
                    "source_node": "evidence_judge",
                    "label": "Write a note",
                    "target_node": "other",
                    "prose": "LLM must not invent Other.",
                },
            ]
        }
    )
    events = await _generate_aggregator(client, draft["id"], draft["version"])
    patch = next(event for event in events if event["type"] == "draft_patch")
    labels = {item["label"] for item in patch["handling_options"]}
    targets = {item["target_node"] for item in patch["handling_options"]}
    assert labels == {"Revise the claim", "Narrow the experiment"}
    assert "Other" not in labels
    assert "other" not in targets
    stored = await client.get(
        f"/api/judgement/sessions/{draft['id']}/nodes/aggregator"
    )
    assert {item["label"] for item in stored.json()["handling_options"]} == labels
    assert all(
        option["finding_kind"] in {item["finding_kind"] for item in stored.json()["issues"] if item["severity"] in {"CRITICAL", "MAJOR"}}
        for option in stored.json()["handling_options"]
    )


@pytest.mark.asyncio
async def test_confirm_aggregator_with_critical_keeps_spec_version(
    client: AsyncClient,
) -> None:
    await _auth_client(client)
    evidence = await _prepare_evidence_judge(
        client, claim_statement=UNSUPPORTED_CLAIM
    )
    await _generate_evidence_judge(
        client, evidence["id"], evidence["version"]
    )
    session = await _session(client, evidence["id"])
    session = await _prepare(
        client, evidence["id"], "independent_judges", session["version"]
    )
    draft = await _advance_to_aggregator(client, session)
    produced_id = draft["produced_spec_version"]["id"]
    valid_id = draft["valid_spec_version_id"]
    _bind_aggregator_llm({"options": []})
    generated = await _generate_aggregator(client, draft["id"], draft["version"])
    confirmed = await _confirm(
        client, draft["id"], "aggregator", generated[-1]["version"]
    )
    assert _head(confirmed, "aggregator")["status"] == "current"
    assert confirmed["valid_spec_version_id"] == valid_id
    assert confirmed["produced_spec_version"]["id"] == produced_id
    revision_id = _head(confirmed, "aggregator")["stage_revision_id"]
    frozen = await client.get(
        f"/api/judgement/sessions/{draft['id']}/nodes/aggregator",
        params={"stage_revision_id": revision_id},
    )
    assert frozen.status_code == 200, frozen.text
    assert any(
        item["finding_kind"] == "unsupported_citation"
        and item["severity"] == "CRITICAL"
        for item in frozen.json()["issues"]
    )
    assert frozen.json()["scores"] == CONFERENCE_SCORES
    assert confirmed["readiness"]["state"] == "blocked"


@pytest.mark.asyncio
async def test_readiness_states_and_export_gate(client: AsyncClient) -> None:
    await _auth_client(client)
    minted = await _mint_valid_spec(client)
    readiness = await client.get(
        f"/api/judgement/sessions/{minted['id']}/readiness"
    )
    assert readiness.status_code == 200, readiness.text
    assert readiness.json()["state"] == "not_evaluated"
    assert "not conference acceptance" in readiness.json()["notice"].lower()
    session = await client.get(f"/api/loop/sessions/{minted['id']}")
    assert session.json()["readiness"]["state"] == "not_evaluated"
    export = await client.post(
        f"/api/loop/sessions/{minted['id']}/spec-artifact"
    )
    assert export.status_code == 409
    assert export.json()["code"] == "readiness_not_evaluated"

    draft = await _prepare_gap_judge(client)
    session = await _advance_to_aggregator(client, draft)
    _bind_aggregator_llm({"options": []})
    generated = await _generate_aggregator(
        client, session["id"], session["version"]
    )
    confirmed = await _confirm(
        client, session["id"], "aggregator", generated[-1]["version"]
    )
    assert confirmed["readiness"]["state"] == "ready"
    ready = await client.get(
        f"/api/judgement/sessions/{session['id']}/readiness"
    )
    assert ready.json()["state"] == "ready"
    assert ready.json()["scores"] == CONFERENCE_SCORES
    allowed = await client.post(
        f"/api/loop/sessions/{session['id']}/spec-artifact"
    )
    assert allowed.status_code == 200, allowed.text
    assert allowed.json()["spec_version_id"] == confirmed["valid_spec_version_id"]

    evidence = await _prepare_evidence_judge(
        client, claim_statement=UNSUPPORTED_CLAIM
    )
    await _generate_evidence_judge(
        client, evidence["id"], evidence["version"]
    )
    session = await _session(client, evidence["id"])
    session = await _prepare(
        client, evidence["id"], "independent_judges", session["version"]
    )
    blocked_draft = await _advance_to_aggregator(client, session)
    _bind_aggregator_llm({"options": []})
    generated = await _generate_aggregator(
        client, blocked_draft["id"], blocked_draft["version"]
    )
    blocked = await _confirm(
        client, blocked_draft["id"], "aggregator", generated[-1]["version"]
    )
    assert blocked["readiness"]["state"] == "blocked"
    blocked_readiness = await client.get(
        f"/api/judgement/sessions/{blocked_draft['id']}/readiness"
    )
    assert blocked_readiness.json()["state"] == "blocked"
    denied = await client.post(
        f"/api/loop/sessions/{blocked_draft['id']}/spec-artifact"
    )
    assert denied.status_code == 409
    assert denied.json()["code"] == "critical_issues_block_export"


def _bind_pending_judge_llms() -> dict[str, FakeLlm]:
    ports = {node.value: get_llm_port(node.value) for node in WORKFLOW_NODES}
    fakes: dict[str, FakeLlm] = {}
    for node in FIVE_JUDGE_NODES:
        payload: dict
        if node is WorkflowNode.CONFERENCE_JUDGE:
            payload = {"scores": CONFERENCE_SCORES}
        else:
            payload = {"issues": []}
        fake = FakeLlm(response=json.dumps(payload))
        ports[node.value] = fake
        fakes[node.value] = fake
    bind_llm_ports(ports)
    return fakes


def _done_nodes(events: list[dict]) -> set[str]:
    return {event["node"] for event in events if event.get("type") == "done"}


async def _run_pending(
    client: AsyncClient, session_id: str, expected_version: int, **extra: object
) -> tuple[object, list[dict]]:
    body: dict = {"expected_version": expected_version, **extra}
    response = await client.post(
        f"/api/judgement/sessions/{session_id}/generate-pending",
        json=body,
    )
    return response, _events(response.text) if response.status_code == 200 else []


async def _stale_experiment_and_conference(
    client: AsyncClient,
) -> dict:
    draft = await _prepare_gap_judge(client)
    session = await _advance_to_aggregator(client, draft)
    _bind_aggregator_llm({"options": []})
    generated = await _generate_aggregator(
        client, session["id"], session["version"]
    )
    session = await _confirm(
        client, session["id"], "aggregator", generated[-1]["version"]
    )
    reopened = await _patch_working_draft(
        client,
        session["id"],
        expected_version=session["version"],
        node="feasibility",
        narrative={"text": "Changed feasibility for a new Spec Version."},
    )
    assert reopened.status_code == 200, reopened.text
    changed = await _confirm(
        client, session["id"], "feasibility", reopened.json()["version"]
    )
    fetched = await client.get(f"/api/loop/sessions/{changed['id']}")
    payload = fetched.json()
    assert payload["valid_spec_version_id"] == payload["produced_spec_version"]["id"]
    assert _head(payload, "gap_judge")["status"] == "current"
    assert _head(payload, "experiment_judge")["status"] == "stale"
    assert _head(payload, "conference_judge")["status"] == "stale"
    assert _head(payload, "aggregator")["status"] == "stale"
    return await _prepare(
        client, payload["id"], "independent_judges", payload["version"]
    )


@pytest.mark.asyncio
async def test_run_pending_judges_skips_current_heads_and_does_not_start_aggregator(
    client: AsyncClient,
) -> None:
    await _auth_client(client)
    draft = await _prepare_gap_judge(client)
    await _generate_gap_judge(client, draft["id"], draft["version"])
    confirmed = await _session(client, draft["id"])
    prepared = await _prepare(
        client, draft["id"], "independent_judges", confirmed["version"]
    )
    assert prepared["working_draft_node"] == "aggregator"
    _bind_pending_judge_llms()
    response, pending_events = await _run_pending(
        client, draft["id"], prepared["version"]
    )
    assert response.status_code == 200, response.text
    done = _done_nodes(pending_events)
    assert "gap_judge" not in done
    assert "aggregator" not in done
    assert done == {
        "contribution_judge",
        "evidence_judge",
        "experiment_judge",
        "conference_judge",
    }
    assert all(event.get("node") != "aggregator" for event in pending_events)
    assert any(
        event.get("type") == "progress" and event.get("node") == "contribution_judge"
        for event in pending_events
    )


@pytest.mark.asyncio
async def test_run_pending_judges_allowed_when_working_draft_is_sibling_judge(
    client: AsyncClient,
) -> None:
    await _auth_client(client)
    draft = await _prepare_gap_judge(client)
    assert draft["working_draft_node"] == "aggregator"
    _bind_pending_judge_llms()
    response, pending_events = await _run_pending(
        client, draft["id"], draft["version"]
    )
    assert response.status_code == 200, response.text
    assert _done_nodes(pending_events) == {
        "gap_judge",
        "contribution_judge",
        "evidence_judge",
        "experiment_judge",
        "conference_judge",
    }
    assert all(event.get("node") != "aggregator" for event in pending_events)
    fetched = await client.get(f"/api/loop/sessions/{draft['id']}")
    assert fetched.json()["working_draft_node"] == "aggregator"


def _judge_confirm_nodes(rows: list[dict]) -> set[str]:
    return {
        row["node"]
        for row in rows
        if row["kind"] == "confirm"
        and row["node"] in {node.value for node in FIVE_JUDGE_NODES}
    }


async def _working_aggregator(client: AsyncClient, session_id: str) -> tuple[int, dict]:
    response = await client.get(
        f"/api/judgement/sessions/{session_id}/nodes/aggregator"
    )
    return response.status_code, response.json() if response.status_code == 200 else {}


@pytest.mark.asyncio
async def test_run_pending_five_empty_confirms_judges_without_composing_aggregator(
    client: AsyncClient,
) -> None:
    await _auth_client(client)
    draft = await _prepare_gap_judge(client)
    assert draft["working_draft_node"] == "aggregator"
    _bind_pending_judge_llms()
    response, pending_events = await _run_pending(
        client, draft["id"], draft["version"]
    )
    assert response.status_code == 200, response.text
    assert _done_nodes(pending_events) == {
        "gap_judge",
        "contribution_judge",
        "evidence_judge",
        "experiment_judge",
        "conference_judge",
    }
    assert all(event.get("node") != "aggregator" for event in pending_events)
    assert not any(
        event.get("type") in {"starting", "progress", "done"}
        and event.get("node") == "aggregator"
        for event in pending_events
    )
    session = await _session(client, draft["id"])
    assert session["working_draft_node"] == "aggregator"
    for node in FIVE_JUDGE_NODES:
        assert _head(session, node.value)["status"] == "current"
    assert _head(session, "aggregator")["status"] != "current"
    confirms = _judge_confirm_nodes(await _decisions(client, draft["id"]))
    assert confirms == {node.value for node in FIVE_JUDGE_NODES}
    status, working = await _working_aggregator(client, draft["id"])
    assert status in {200, 409}
    if status == 200:
        assert working.get("issues") in (None, [])
        assert working.get("handling_options") in (None, [])
        assert working.get("scores") is None
    readiness = await client.get(
        f"/api/judgement/sessions/{draft['id']}/readiness"
    )
    assert readiness.status_code == 200, readiness.text
    assert readiness.json()["state"] == "not_evaluated"


@pytest.mark.asyncio
async def test_run_pending_partial_fail_does_not_confirm_failed_judge_or_start_aggregator(
    client: AsyncClient,
) -> None:
    await _auth_client(client)
    draft = await _prepare_gap_judge(client)
    fakes = _bind_pending_judge_llms()
    ports = {node.value: get_llm_port(node.value) for node in WORKFLOW_NODES}
    for node in FIVE_JUDGE_NODES:
        ports[node.value] = fakes[node.value]
    ports[WorkflowNode.EVIDENCE_JUDGE.value] = FakeLlm(response="not-json")
    bind_llm_ports(ports)
    response, pending_events = await _run_pending(
        client, draft["id"], draft["version"]
    )
    assert response.status_code == 200, response.text
    done = _done_nodes(pending_events)
    assert "evidence_judge" not in done
    assert "aggregator" not in done
    assert all(event.get("node") != "aggregator" for event in pending_events)
    assert any(
        event.get("type") == "error" and event.get("node") == "evidence_judge"
        for event in pending_events
    )
    session = await _session(client, draft["id"])
    assert session["working_draft_node"] == "aggregator"
    assert _head(session, "evidence_judge")["status"] != "current"
    for node in (
        "gap_judge",
        "contribution_judge",
        "experiment_judge",
        "conference_judge",
    ):
        assert _head(session, node)["status"] == "current"
    confirms = _judge_confirm_nodes(await _decisions(client, draft["id"]))
    assert "evidence_judge" not in confirms
    assert confirms == {
        "gap_judge",
        "contribution_judge",
        "experiment_judge",
        "conference_judge",
    }
    assert _head(session, "aggregator")["status"] != "current"
    status, working = await _working_aggregator(client, draft["id"])
    assert status in {200, 409}
    if status == 200:
        assert working.get("handling_options") in (None, [])
        assert working.get("scores") is None


@pytest.mark.asyncio
async def test_two_of_five_current_judges_does_not_compose_aggregator(
    client: AsyncClient,
) -> None:
    await _auth_client(client)
    draft = await _prepare_gap_judge(client)
    _bind_gap_judge_llm({"issues": []})
    await _generate_gap_judge(client, draft["id"], draft["version"])
    session = await _session(client, draft["id"])
    _bind_contribution_judge_llm({"issues": []})
    await _generate_contribution_judge(client, session["id"], session["version"])
    session = await _session(client, draft["id"])
    assert _head(session, "gap_judge")["status"] == "current"
    assert _head(session, "contribution_judge")["status"] == "current"
    assert _head(session, "evidence_judge")["status"] != "current"
    denied = await client.post(
        f"/api/judgement/sessions/{draft['id']}/nodes/aggregator/generate",
        json={"expected_version": session["version"]},
    )
    assert denied.status_code == 409
    assert denied.json()["code"] == "judge_heads_not_current"
    session = await _session(client, draft["id"])
    assert session["working_draft_node"] == "aggregator"
    assert _head(session, "aggregator")["status"] != "current"
    status, working = await _working_aggregator(client, draft["id"])
    assert status in {200, 409}
    if status == 200:
        assert working.get("issues") in (None, [])
        assert working.get("handling_options") in (None, [])
        assert working.get("scores") is None


@pytest.mark.asyncio
async def test_run_pending_judges_requires_valid_spec_version(
    client: AsyncClient,
) -> None:
    await _auth_client(client)
    created = await _create_session(client)
    response = await client.post(
        f"/api/judgement/sessions/{created['id']}/generate-pending",
        json={"expected_version": created["version"]},
    )
    assert response.status_code == 409
    assert response.json()["code"] == "valid_spec_version_required"


@pytest.mark.asyncio
async def test_run_pending_judges_requires_batch_stale_reaccept(
    client: AsyncClient,
) -> None:
    await _auth_client(client)
    prepared = await _stale_experiment_and_conference(client)
    denied, _ = await _run_pending(client, prepared["id"], prepared["version"])
    assert denied.status_code == 409
    assert denied.json()["code"] == "stale_reaccept_required"

    _bind_pending_judge_llms()
    accepted, pending_events = await _run_pending(
        client,
        prepared["id"],
        prepared["version"],
        stale_reaccept=True,
    )
    assert accepted.status_code == 200, accepted.text
    done = _done_nodes(pending_events)
    assert done == {"experiment_judge", "conference_judge"}
    assert "aggregator" not in done
    assert "gap_judge" not in done


@pytest.mark.asyncio
async def test_run_pending_batch_ack_does_not_authorize_aggregator_or_confirm(
    client: AsyncClient,
) -> None:
    await _auth_client(client)
    prepared = await _stale_experiment_and_conference(client)
    _bind_pending_judge_llms()
    accepted, pending_events = await _run_pending(
        client,
        prepared["id"],
        prepared["version"],
        stale_reaccept=True,
    )
    assert accepted.status_code == 200, accepted.text
    version = pending_events[-1]["version"]

    aggregator = await client.post(
        f"/api/judgement/sessions/{prepared['id']}/nodes/aggregator/generate",
        json={"expected_version": version},
    )
    assert aggregator.status_code == 409
    assert aggregator.json()["code"] in {
        "stale_reaccept_required",
        "judge_heads_not_current",
    }
    assert all(event.get("node") != "aggregator" for event in pending_events)

    session = await _session(client, prepared["id"])
    session = await _prepare(
        client, prepared["id"], "independent_judges", session["version"]
    )
    assert session["working_draft_node"] == "aggregator"
    denied_generate = await client.post(
        f"/api/judgement/sessions/{prepared['id']}/nodes/aggregator/generate",
        json={"expected_version": session["version"]},
    )
    assert denied_generate.status_code == 409
    assert denied_generate.json()["code"] == "stale_reaccept_required"

    denied_confirm = await client.post(
        f"/api/loop/sessions/{prepared['id']}/confirm",
        json={
            "node": "aggregator",
            "expected_version": session["version"],
        },
    )
    assert denied_confirm.status_code == 409
    assert denied_confirm.json()["code"] == "stale_reaccept_required"


@pytest.mark.asyncio
async def test_single_judge_generate_still_requires_own_stale_reaccept(
    client: AsyncClient,
) -> None:
    await _auth_client(client)
    prepared = await _stale_experiment_and_conference(client)
    _bind_conference_judge_llm({"scores": CONFERENCE_SCORES})
    denied = await client.post(
        f"/api/judgement/sessions/{prepared['id']}/nodes/conference_judge/generate",
        json={"expected_version": prepared["version"]},
    )
    assert denied.status_code == 409
    assert denied.json()["code"] == "stale_reaccept_required"
    accepted = await client.post(
        f"/api/judgement/sessions/{prepared['id']}/nodes/conference_judge/generate",
        json={
            "expected_version": prepared["version"],
            "stale_reaccept": True,
        },
    )
    assert accepted.status_code == 200, accepted.text
    events = _events(accepted.text)
    assert events[-1]["type"] == "done"
    assert events[-1]["node"] == "conference_judge"
    session = await _session(client, prepared["id"])
    assert session["working_draft_node"] == "aggregator"
    assert _head(session, "conference_judge")["status"] == "current"
    confirms = [
        row
        for row in await _decisions(client, prepared["id"])
        if row["kind"] == "confirm" and row["node"] == "conference_judge"
    ]
    assert len(confirms) == 1
    still_denied = await client.post(
        f"/api/judgement/sessions/{prepared['id']}/nodes/experiment_judge/generate",
        json={"expected_version": events[-1]["version"]},
    )
    assert still_denied.status_code == 409
    assert still_denied.json()["code"] == "stale_reaccept_required"


