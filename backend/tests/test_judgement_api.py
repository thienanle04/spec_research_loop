"""Judgement HTTP seam: Gap Judge generate, floors, Confirm, ownership."""

import json

import pytest
from httpx import AsyncClient

from app.adapters.llm import FakeLlm, bind_llm_ports, get_llm_port
from app.modules.loop.catalog import WORKFLOW_NODES, WorkflowNode
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


async def _prepare_evidence_judge(
    client: AsyncClient, *, claim_statement: str | None = UNSUPPORTED_CLAIM
) -> dict:
    draft = await _prepare_gap_judge(client, claim_statement=claim_statement)
    session = await _confirm(client, draft["id"], "gap_judge", draft["version"])
    session = await _prepare(
        client, draft["id"], "independent_judges", session["version"]
    )
    session = await _confirm(
        client, draft["id"], session["working_draft_node"], session["version"]
    )
    session = await _prepare(
        client, draft["id"], "independent_judges", session["version"]
    )
    assert session["working_draft_node"] == "evidence_judge"
    return session


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


@pytest.mark.asyncio
async def test_confirm_gap_judge_with_critical_keeps_spec_version(
    client: AsyncClient,
) -> None:
    await _auth_client(client)
    draft = await _prepare_gap_judge(client, gap_statement=UNSUPPORTED_GAP)
    events = await _generate_gap_judge(client, draft["id"], draft["version"])
    confirmed = await _confirm(
        client, draft["id"], "gap_judge", events[-1]["version"]
    )
    assert _head(confirmed, "gap_judge")["status"] == "current"
    assert confirmed["valid_spec_version_id"] == confirmed["produced_spec_version"]["id"]
    revision_id = _head(confirmed, "gap_judge")["stage_revision_id"]
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


@pytest.mark.asyncio
async def test_prepare_independent_judges_does_not_wipe_current_gap_judge(
    client: AsyncClient,
) -> None:
    await _auth_client(client)
    draft = await _prepare_gap_judge(client, gap_statement=UNSUPPORTED_GAP)
    events = await _generate_gap_judge(client, draft["id"], draft["version"])
    confirmed = await _confirm(
        client, draft["id"], "gap_judge", events[-1]["version"]
    )
    revision_id = _head(confirmed, "gap_judge")["stage_revision_id"]
    prepared = await _prepare(
        client, draft["id"], "independent_judges", confirmed["version"]
    )
    assert prepared["working_draft_node"] == "contribution_judge"
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
async def test_gap_judge_generate_allowed_when_working_draft_is_sibling_judge(
    client: AsyncClient,
) -> None:
    await _auth_client(client)
    draft = await _prepare_gap_judge(client, gap_statement=UNSUPPORTED_GAP)
    events = await _generate_gap_judge(client, draft["id"], draft["version"])
    confirmed = await _confirm(
        client, draft["id"], "gap_judge", events[-1]["version"]
    )
    prepared = await _prepare(
        client, draft["id"], "independent_judges", confirmed["version"]
    )
    assert prepared["working_draft_node"] == "contribution_judge"
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
    events = await _generate_gap_judge(client, draft["id"], draft["version"])
    session = await _confirm(client, draft["id"], "gap_judge", events[-1]["version"])
    for _ in range(5):
        session = await _prepare(
            client, draft["id"], "independent_judges", session["version"]
        )
        session = await _confirm(
            client, draft["id"], session["working_draft_node"], session["version"]
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
    regenerated = await _generate_gap_judge(
        client, draft["id"], reopened.json()["version"]
    )
    changed = await _confirm(
        client, draft["id"], "gap_judge", regenerated[-1]["version"]
    )
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
    events = await _generate_evidence_judge(client, draft["id"], draft["version"])
    confirmed = await _confirm(
        client, draft["id"], "evidence_judge", events[-1]["version"]
    )
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
    events = await _generate_gap_judge(client, draft["id"], draft["version"])
    confirmed = await _confirm(
        client, draft["id"], "gap_judge", events[-1]["version"]
    )
    prepared = await _prepare(
        client, draft["id"], "independent_judges", confirmed["version"]
    )
    assert prepared["working_draft_node"] == "contribution_judge"
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
    events = await _generate_evidence_judge(client, draft["id"], draft["version"])
    session = await _confirm(
        client, draft["id"], "evidence_judge", events[-1]["version"]
    )
    for _ in range(3):
        session = await _prepare(
            client, draft["id"], "independent_judges", session["version"]
        )
        session = await _confirm(
            client, draft["id"], session["working_draft_node"], session["version"]
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
    regenerated = await _generate_evidence_judge(
        client, draft["id"], reopened.json()["version"]
    )
    changed = await _confirm(
        client, draft["id"], "evidence_judge", regenerated[-1]["version"]
    )
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
    session = await _confirm(client, draft["id"], "gap_judge", draft["version"])
    session = await _prepare(
        client, draft["id"], "independent_judges", session["version"]
    )
    assert session["working_draft_node"] == "contribution_judge"
    return session


async def _prepare_experiment_judge(client: AsyncClient) -> dict:
    draft = await _prepare_evidence_judge(client)
    session = await _confirm(
        client, draft["id"], "evidence_judge", draft["version"]
    )
    session = await _prepare(
        client, draft["id"], "independent_judges", session["version"]
    )
    assert session["working_draft_node"] == "experiment_judge"
    return session


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
    events = await _generate_contribution_judge(
        client, draft["id"], draft["version"]
    )
    confirmed = await _confirm(
        client, draft["id"], "contribution_judge", events[-1]["version"]
    )
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
    events = await _generate_experiment_judge(client, draft["id"], draft["version"])
    confirmed = await _confirm(
        client, draft["id"], "experiment_judge", events[-1]["version"]
    )
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
    events = await _generate_gap_judge(client, draft["id"], draft["version"])
    confirmed = await _confirm(
        client, draft["id"], "gap_judge", events[-1]["version"]
    )
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


async def _prepare_conference_judge(client: AsyncClient) -> dict:
    draft = await _prepare_experiment_judge(client)
    session = await _confirm(
        client, draft["id"], "experiment_judge", draft["version"]
    )
    session = await _prepare(
        client, draft["id"], "independent_judges", session["version"]
    )
    assert session["working_draft_node"] == "conference_judge"
    return session


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
    events = await _generate_gap_judge(client, draft["id"], draft["version"])
    confirmed = await _confirm(
        client, draft["id"], "gap_judge", events[-1]["version"]
    )
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
    events = await _generate_conference_judge(
        client, draft["id"], draft["version"]
    )
    confirmed = await _confirm(
        client, draft["id"], "conference_judge", events[-1]["version"]
    )
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


