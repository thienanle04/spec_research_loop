"""Export Scratch projection: Confirm Aggregator seed (Loop Session HTTP seam)."""

import hashlib
import json
import re

import pytest
from httpx import AsyncClient

from tests.test_judgement_api import (
    UNSUPPORTED_CLAIM,
    _advance_to_aggregator,
    _auth_client,
    _bind_aggregator_llm,
    _confirm,
    _create_session,
    _events,
    _generate_aggregator,
    _generate_evidence_judge,
    _interpret,
    _prepare,
    _prepare_aggregator,
    _prepare_evidence_judge,
    _session,
)
from tests.test_loop_api import IDEA_FRAME, _head, _patch_working_draft

PAPER_TITLES = (
    "Problem Statement",
    "Research Question",
    "Related Work",
    "Research Gap",
    "Proposed Approach & Contribution",
    "Claims and Evidence",
    "Experiment Plan",
    "Constraints",
    "Required Resources",
    "Potential Bottlenecks",
    "Mitigation Strategies",
    "Open Issues",
)

ATX_HEADINGS = tuple(
    f"## {index}. {title}" for index, title in enumerate(PAPER_TITLES, start=1)
)

PROBLEM_TEXT = IDEA_FRAME["problem"]
RQ_TEXT = IDEA_FRAME["research_question"]
CONSTRAINT_TEXT = "Single-accelerator GPU kernel latency budget"
OPEN_Q_TEXT = "How does tiling change GPU kernel DRAM traffic?"
CONTRIBUTION_TEXT = "A tiling schedule that cuts DRAM traffic"
CLAIM_TEXT = "Tiling cuts DRAM traffic by at least 20%"
EVIDENCE_TEXT = "Held-out kernel traces show traffic reduction"
GAP_TEXT = (
    "The literature has not measured whether brass instruments improve "
    "soil nitrogen fixation in alpine peat bogs."
)
RESOURCE_TEXT = "Held-out scholarly sources"
BOTTLENECK_TEXT = "Evidence annotation time"
MITIGATION_TEXT = "Start with a smaller evaluation set"
EXPERIMENT_ACTION = (
    "Compare claim-level and aggregate verification on held-out sources."
)


def _markdown(payload: dict) -> str:
    return payload["export_scratch"]["document"]["markdown"]


async def _confirm_aggregator(client: AsyncClient, session: dict) -> dict:
    if (
        session["working_draft_node"] != "aggregator"
        and _head(session, "aggregator")["status"] == "empty"
    ):
        session = await _prepare(
            client, session["id"], "independent_judges", session["version"]
        )
    session = await _advance_to_aggregator(client, session)
    _bind_aggregator_llm({"options": []})
    generated = await _generate_aggregator(
        client, session["id"], session["version"]
    )
    return await _confirm(
        client, session["id"], "aggregator", generated[-1]["version"]
    )


async def _post_card(
    client: AsyncClient,
    session_id: str,
    *,
    kind: str,
    text: str,
    expected_version: int,
) -> int:
    response = await client.post(
        f"/api/loop/sessions/{session_id}/cards",
        json={
            "kind": kind,
            "body": {"text": text} if kind != "claim" else {"statement": text},
            "expected_version": expected_version,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["version"]


async def _mint_spec_with_paper_sources(client: AsyncClient) -> dict:
    created = await _create_session(client)
    session_id = created["id"]
    interpreted = await _interpret(client, session_id, created["version"])
    decomposed = await _confirm(
        client, session_id, "idea_decomposition", interpreted["version"]
    )
    return await _mint_valid_spec_from_decomposition(
        client, decomposed, claim_text=CLAIM_TEXT
    )


async def _mint_valid_spec_from_decomposition(
    client: AsyncClient, decomposed: dict, *, claim_text: str
) -> dict:
    """Continue the mint path after Confirm of idea_decomposition."""
    session_id = decomposed["id"]
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
    assert related_generation.status_code == 200, related_generation.text
    related_events = _events(related_generation.text)
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
    candidate = {
        **candidate,
        "statement": GAP_TEXT,
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
    gap_confirmed = await _confirm(client, session_id, "gap", card.json()["version"])
    expected_version = gap_confirmed["version"]

    contribution_prepared = await _prepare(
        client, session_id, "contribution", expected_version
    )
    expected_version = await _post_card(
        client,
        session_id,
        kind="contribution",
        text=CONTRIBUTION_TEXT,
        expected_version=contribution_prepared["version"],
    )
    expected_version = (
        await _confirm(client, session_id, "contribution", expected_version)
    )["version"]

    claims_prepared = await _prepare(
        client, session_id, "claims_evidence", expected_version
    )
    expected_version = await _post_card(
        client,
        session_id,
        kind="claim",
        text=claim_text,
        expected_version=claims_prepared["version"],
    )
    expected_version = await _post_card(
        client,
        session_id,
        kind="evidence",
        text=EVIDENCE_TEXT,
        expected_version=expected_version,
    )
    expected_version = (
        await _confirm(client, session_id, "claims", expected_version)
    )["version"]

    experiment_prepared = await _prepare(
        client, session_id, "experiment_planning", expected_version
    )
    plan_patch = await _patch_working_draft(
        client,
        session_id,
        expected_version=experiment_prepared["version"],
        narrative={
            "plan": {
                "experiments": [
                    {
                        "claim": CLAIM_TEXT,
                        "action": EXPERIMENT_ACTION,
                        "objective": "Measure DRAM traffic.",
                        "significance": "Tests whether tiling helps.",
                    }
                ]
            }
        },
    )
    assert plan_patch.status_code == 200, plan_patch.text
    expected_version = (
        await _confirm(
            client, session_id, "experiment_plan", plan_patch.json()["version"]
        )
    )["version"]

    feasibility_prepared = await _prepare(
        client, session_id, "experiment_planning", expected_version
    )
    checked = await client.post(
        f"/api/spec/sessions/{session_id}/feasibility/check",
        json={"expected_version": feasibility_prepared["version"]},
    )
    assert checked.status_code == 200, checked.text
    expected_version = checked.json()["version"]
    await _confirm(client, session_id, "feasibility", expected_version)
    fetched = await client.get(f"/api/loop/sessions/{session_id}")
    payload = fetched.json()
    assert payload["valid_spec_version_id"] == payload["produced_spec_version"]["id"]
    return payload


@pytest.mark.asyncio
async def test_confirm_aggregator_seeds_twelve_section_export_scratch(
    client: AsyncClient,
) -> None:
    await _auth_client(client)
    draft = await _prepare_aggregator(client)
    assert draft.get("export_scratch_snapshots", []) == []

    confirmed = await _confirm_aggregator(client, draft)
    assert confirmed["valid_spec_version_id"] == draft["valid_spec_version_id"]
    scratch = confirmed["export_scratch"]
    assert scratch["spec_version_id"] == confirmed["valid_spec_version_id"]
    body = scratch["document"]["markdown"]
    _assert_twelve_atx_headings(body)
    assert str(confirmed["valid_spec_version_id"]) in body
    snapshots = confirmed["export_scratch_snapshots"]
    assert len(snapshots) == 1
    assert snapshots[0]["snapshot_n"] == 1
    assert snapshots[0]["spec_version_id"] == confirmed["valid_spec_version_id"]
    _assert_twelve_atx_headings(snapshots[0]["document"]["markdown"])


@pytest.mark.asyncio
async def test_export_scratch_projection_maps_spec_version_sources(
    client: AsyncClient,
) -> None:
    await _auth_client(client)
    minted = await _mint_spec_with_paper_sources(client)
    confirmed = await _confirm_aggregator(client, minted)
    body = _markdown(confirmed)
    assert GAP_TEXT in body
    assert CONTRIBUTION_TEXT in body
    assert f"### **{CLAIM_TEXT}**" in body
    assert "### **Unpaired evidence**" in body
    assert EVIDENCE_TEXT in body
    assert "**Action:**" in body
    assert EXPERIMENT_ACTION in body
    assert "## 6. Claims and Evidence" in body
    assert "## 7. Experiment Plan" in body
    assert "## 7. Evidence" not in body
    assert RESOURCE_TEXT in body
    assert BOTTLENECK_TEXT in body
    assert MITIGATION_TEXT in body
    assert "Analyzes" in body


@pytest.mark.asyncio
async def test_export_scratch_projects_constraint_and_open_question_cards(
    client: AsyncClient,
) -> None:
    await _auth_client(client)
    created = await _create_session(client)
    session_id = created["id"]
    interpreted = await _interpret(client, session_id, created["version"])
    version = await _post_card(
        client,
        session_id,
        kind="problem",
        text=PROBLEM_TEXT,
        expected_version=interpreted["version"],
    )
    version = await _post_card(
        client,
        session_id,
        kind="research_question",
        text=RQ_TEXT,
        expected_version=version,
    )
    version = await _post_card(
        client,
        session_id,
        kind="constraint",
        text=CONSTRAINT_TEXT,
        expected_version=version,
    )
    version = await _post_card(
        client,
        session_id,
        kind="open_question",
        text=OPEN_Q_TEXT,
        expected_version=version,
    )
    decomposed = await _confirm(client, session_id, "idea_decomposition", version)
    minted = await _mint_valid_spec_from_decomposition(
        client, decomposed, claim_text=CLAIM_TEXT
    )
    confirmed = await _confirm_aggregator(client, minted)
    body = _markdown(confirmed)
    assert PROBLEM_TEXT in body
    assert RQ_TEXT in body
    assert IDEA_FRAME["intent"] not in body
    assert CONSTRAINT_TEXT in body
    assert OPEN_Q_TEXT in body
    _assert_twelve_atx_headings(body)


@pytest.mark.asyncio
async def test_second_confirm_aggregator_does_not_clone_snapshot_or_reset_buffer(
    client: AsyncClient,
) -> None:
    await _auth_client(client)
    draft = await _prepare_aggregator(client)
    first = await _confirm_aggregator(client, draft)
    first_snapshot_id = first["export_scratch_snapshots"][0]["id"]
    first_buffer = first["export_scratch"]["document"]
    second = await _confirm(
        client, first["id"], "aggregator", first["version"]
    )
    assert _head(second, "aggregator")["status"] == "current"
    assert second["valid_spec_version_id"] == first["valid_spec_version_id"]
    assert len(second["export_scratch_snapshots"]) == 1
    assert second["export_scratch_snapshots"][0]["id"] == first_snapshot_id
    assert second["export_scratch_snapshots"][0]["snapshot_n"] == 1
    assert second["export_scratch"]["document"] == first_buffer


@pytest.mark.asyncio
async def test_confirm_aggregator_snapshot_one_is_filter_not_preconfirm_overlay(
    client: AsyncClient,
) -> None:
    await _auth_client(client)
    minted = await _mint_spec_with_paper_sources(client)
    assert minted["export_scratch_snapshots"] == []
    projected = minted["export_scratch"]["document"]
    overlay = "Overlay written before Confirm Aggregator"
    patched = await _patch_export_scratch(
        client,
        minted,
        _edited_document(projected, problem_body=overlay),
    )
    confirmed = await _confirm_aggregator(client, patched)
    snapshot_one = confirmed["export_scratch_snapshots"][0]["document"]
    assert snapshot_one == projected
    assert overlay not in snapshot_one["markdown"]
    assert overlay not in json.dumps(snapshot_one)


@pytest.mark.asyncio
async def test_get_session_returns_export_scratch_for_valid_spec_version(
    client: AsyncClient,
) -> None:
    await _auth_client(client)
    draft = await _prepare_aggregator(client)
    confirmed = await _confirm_aggregator(client, draft)
    fetched = await client.get(f"/api/loop/sessions/{confirmed['id']}")
    assert fetched.status_code == 200, fetched.text
    payload = fetched.json()
    assert payload["export_scratch"]["id"] == confirmed["export_scratch"]["id"]
    assert payload["export_scratch"]["document"] == confirmed["export_scratch"]["document"]
    assert len(payload["export_scratch_snapshots"]) == 1
    scoped = await client.get(
        f"/api/loop/sessions/{confirmed['id']}",
        params={"spec_version_id": confirmed["valid_spec_version_id"]},
    )
    assert scoped.status_code == 200, scoped.text
    assert scoped.json()["export_scratch"]["spec_version_id"] == confirmed[
        "valid_spec_version_id"
    ]


def _first_idea_text(session: dict) -> str:
    revisions = [
        row
        for row in session["stage_revisions"]
        if row["node"] == "idea_interpretation"
    ]
    revisions.sort(key=lambda row: row["revision_n"])
    for turn in revisions[0]["narrative"]["turns"]:
        if turn.get("role") == "account" and turn.get("kind") == "idea":
            return turn["text"]
    raise AssertionError("no interpretation idea turn")


async def _remint_second_spec(client: AsyncClient, session: dict) -> dict:
    """Change contribution and remint a second Spec Version without Confirm Aggregator."""
    session_id = session["id"]
    contribution = next(
        card for card in session["cards"] if card["kind"] == "contribution"
    )
    reopened = await _patch_working_draft(
        client,
        session_id,
        expected_version=session["version"],
        node="contribution",
    )
    assert reopened.status_code == 200, reopened.text
    patched = await client.patch(
        f"/api/loop/sessions/{session_id}/cards/{contribution['id']}",
        json={
            "body": {"text": "A second contribution for a later Spec Version"},
            "expected_version": reopened.json()["version"],
        },
    )
    assert patched.status_code == 200, patched.text
    changed = await _confirm(
        client, session_id, "contribution", patched.json()["version"]
    )
    claims_prepared = await _prepare(
        client, session_id, "claims_evidence", changed["version"]
    )
    claims_confirmed = await _confirm(
        client,
        session_id,
        "claims",
        claims_prepared["version"],
        stale_reaccept=True,
    )
    experiment_prepared = await _prepare(
        client, session_id, "experiment_planning", claims_confirmed["version"]
    )
    experiment_confirmed = await _confirm(
        client,
        session_id,
        "experiment_plan",
        experiment_prepared["version"],
        stale_reaccept=True,
    )
    feasibility_prepared = await _prepare(
        client, session_id, "experiment_planning", experiment_confirmed["version"]
    )
    checked = await client.post(
        f"/api/spec/sessions/{session_id}/feasibility/check",
        json={"expected_version": feasibility_prepared["version"]},
    )
    assert checked.status_code == 200, checked.text
    reminted = await _confirm(
        client,
        session_id,
        "feasibility",
        checked.json()["version"],
        stale_reaccept=True,
    )
    assert reminted["valid_spec_version_id"] == reminted["produced_spec_version"]["id"]
    assert reminted["valid_spec_version_id"] != session["valid_spec_version_id"]
    return reminted


@pytest.mark.asyncio
async def test_get_session_lists_spec_versions_with_valid_flag(
    client: AsyncClient,
) -> None:
    await _auth_client(client)
    confirmed = await _confirm_aggregator(client, await _prepare_aggregator(client))
    fetched = await client.get(f"/api/loop/sessions/{confirmed['id']}")
    assert fetched.status_code == 200, fetched.text
    payload = fetched.json()
    versions = payload["spec_versions"]
    assert len(versions) == 1
    assert versions[0]["id"] == confirmed["valid_spec_version_id"]
    assert versions[0]["valid"] is True
    assert versions[0]["created_at"]


@pytest.mark.asyncio
async def test_get_selected_non_valid_spec_version_keeps_readiness_criteria(
    client: AsyncClient,
) -> None:
    await _auth_client(client)
    minted = await _mint_spec_with_paper_sources(client)
    first = await _confirm_aggregator(client, minted)
    first_id = first["valid_spec_version_id"]
    reminted = await _remint_second_spec(client, first)
    second_id = reminted["valid_spec_version_id"]
    current = await client.get(f"/api/loop/sessions/{first['id']}")
    assert current.status_code == 200, current.text
    current_payload = current.json()
    selected = await client.get(
        f"/api/loop/sessions/{first['id']}",
        params={"spec_version_id": first_id},
    )
    assert selected.status_code == 200, selected.text
    older = selected.json()
    assert older["export_scratch"]["spec_version_id"] == first_id
    assert older["valid_spec_version_id"] == second_id
    assert older["readiness"] == current_payload["readiness"]
    listed = {row["id"]: row["valid"] for row in older["spec_versions"]}
    assert listed[first_id] is False
    assert listed[second_id] is True


@pytest.mark.asyncio
async def test_clarification_review_matches_stage_revisions_of_selected_spec(
    client: AsyncClient,
) -> None:
    await _auth_client(client)
    minted = await _mint_spec_with_paper_sources(client)
    confirmed = await _confirm_aggregator(client, minted)
    fetched = await client.get(f"/api/loop/sessions/{confirmed['id']}")
    payload = fetched.json()
    review = payload["clarification_review"]
    assert review["original_idea"] == _first_idea_text(payload)
    assert review["gap"] == GAP_TEXT
    assert review["contribution"] == CONTRIBUTION_TEXT
    claims_revs = [
        row for row in payload["stage_revisions"] if row["node"] == "claims"
    ]
    claims_revs.sort(key=lambda row: row["revision_n"])
    expected_claims = []
    for card in claims_revs[-1]["card_snapshot"]:
        if card.get("kind") != "claim":
            continue
        body = card.get("body") or {}
        text = body.get("statement") or body.get("text")
        if isinstance(text, str) and text.strip():
            expected_claims.append(text.strip())
    assert review["claims"] == expected_claims
    assert review["claims"] == [CLAIM_TEXT]


@pytest.mark.asyncio
async def test_get_spec_version_without_snapshot_projects_buffer_only(
    client: AsyncClient,
) -> None:
    await _auth_client(client)
    minted = await _mint_spec_with_paper_sources(client)
    assert minted["export_scratch"]["spec_version_id"] == minted["valid_spec_version_id"]
    _assert_twelve_atx_headings(_markdown(minted))
    assert minted["export_scratch_snapshots"] == []
    again = await client.get(f"/api/loop/sessions/{minted['id']}")
    assert again.status_code == 200, again.text
    payload = again.json()
    assert payload["export_scratch_snapshots"] == []
    assert payload["export_scratch"]["id"] == minted["export_scratch"]["id"]


def _document_hash(document: dict) -> str:
    payload = json.dumps(document, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()


def _edited_document(source: dict, *, problem_body: str) -> dict:
    updated = re.sub(
        r"(## 1\. Problem Statement\n)(.*?)(?=\n## 2\. |\Z)",
        lambda _match: f"## 1. Problem Statement\n{problem_body}\n",
        source["markdown"],
        count=1,
        flags=re.DOTALL,
    )
    return {"markdown": updated}


async def _patch_export_scratch(
    client: AsyncClient,
    session: dict,
    document: dict,
    *,
    spec_version_id: str | None = None,
) -> dict:
    body: dict = {
        "expected_version": session["version"],
        "document": document,
    }
    if spec_version_id is not None:
        body["spec_version_id"] = spec_version_id
    response = await client.patch(
        f"/api/loop/sessions/{session['id']}/export-scratch",
        json=body,
    )
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.asyncio
async def test_patch_export_scratch_updates_buffer_and_get_returns_it(
    client: AsyncClient,
) -> None:
    await _auth_client(client)
    confirmed = await _confirm_aggregator(client, await _prepare_aggregator(client))
    edited = _edited_document(
        confirmed["export_scratch"]["document"],
        problem_body="Overlay problem statement for export only",
    )
    patched = await _patch_export_scratch(client, confirmed, edited)
    assert "Overlay problem statement for export only" in _markdown(patched)
    fetched = await client.get(f"/api/loop/sessions/{confirmed['id']}")
    assert fetched.status_code == 200, fetched.text
    payload = fetched.json()
    assert "Overlay problem statement for export only" in _markdown(payload)
    _assert_twelve_atx_headings(_markdown(payload))


@pytest.mark.asyncio
async def test_patch_export_scratch_does_not_change_cards_or_spec_version(
    client: AsyncClient,
) -> None:
    await _auth_client(client)
    confirmed = await _confirm_aggregator(client, await _prepare_aggregator(client))
    cards_before = await client.get(f"/api/loop/sessions/{confirmed['id']}/cards")
    assert cards_before.status_code == 200, cards_before.text
    card_bodies = {row["id"]: row["body"] for row in cards_before.json()}
    produced_id = confirmed["produced_spec_version"]["id"]
    valid_id = confirmed["valid_spec_version_id"]
    spec_hash = _document_hash(confirmed["produced_spec_version"]["document"])
    snapshot_id = confirmed["export_scratch_snapshots"][0]["id"]
    snapshot_doc = confirmed["export_scratch_snapshots"][0]["document"]
    edited = _edited_document(
        confirmed["export_scratch"]["document"],
        problem_body="Buffer-only rewrite",
    )
    await _patch_export_scratch(client, confirmed, edited)
    fetched = await client.get(f"/api/loop/sessions/{confirmed['id']}")
    payload = fetched.json()
    cards_after = await client.get(f"/api/loop/sessions/{confirmed['id']}/cards")
    assert {row["id"]: row["body"] for row in cards_after.json()} == card_bodies
    assert payload["produced_spec_version"]["id"] == produced_id
    assert payload["valid_spec_version_id"] == valid_id
    assert _document_hash(payload["produced_spec_version"]["document"]) == spec_hash
    assert payload["export_scratch_snapshots"][0]["id"] == snapshot_id
    assert payload["export_scratch_snapshots"][0]["document"] == snapshot_doc


@pytest.mark.asyncio
async def test_patch_export_scratch_writes_no_decision(
    client: AsyncClient,
) -> None:
    await _auth_client(client)
    confirmed = await _confirm_aggregator(client, await _prepare_aggregator(client))
    before = await client.get(f"/api/loop/sessions/{confirmed['id']}/decisions")
    assert before.status_code == 200, before.text
    decision_ids = [row["id"] for row in before.json()]
    edited = _edited_document(
        confirmed["export_scratch"]["document"],
        problem_body="Still not a Decision",
    )
    await _patch_export_scratch(client, confirmed, edited)
    after = await client.get(f"/api/loop/sessions/{confirmed['id']}/decisions")
    assert [row["id"] for row in after.json()] == decision_ids


EDITED_PROBLEM = "Snapshot-saved problem statement rewrite"


async def _save_export_scratch_snapshot(
    client: AsyncClient,
    session: dict,
    *,
    spec_version_id: str | None = None,
) -> dict:
    body: dict = {"expected_version": session["version"]}
    if spec_version_id is not None:
        body["spec_version_id"] = spec_version_id
    response = await client.post(
        f"/api/loop/sessions/{session['id']}/export-scratch/snapshots",
        json=body,
    )
    assert response.status_code == 200, response.text
    return response.json()


async def _restore_export_scratch_snapshot(
    client: AsyncClient,
    session: dict,
    snapshot_id: str,
) -> dict:
    response = await client.post(
        f"/api/loop/sessions/{session['id']}/export-scratch/snapshots/{snapshot_id}/restore",
        json={"expected_version": session["version"]},
    )
    assert response.status_code == 200, response.text
    return response.json()


async def _get_export_scratch_diff(
    client: AsyncClient,
    session_id: str,
    *,
    against: str,
    spec_version_id: str | None = None,
) -> dict:
    params: dict[str, str] = {"against": against}
    if spec_version_id is not None:
        params["spec_version_id"] = spec_version_id
    response = await client.get(
        f"/api/loop/sessions/{session_id}/export-scratch/diff",
        params=params,
    )
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.asyncio
async def test_save_export_scratch_appends_snapshot_from_buffer(
    client: AsyncClient,
) -> None:
    await _auth_client(client)
    confirmed = await _confirm_aggregator(client, await _prepare_aggregator(client))
    assert [row["snapshot_n"] for row in confirmed["export_scratch_snapshots"]] == [1]
    cards_before = await client.get(f"/api/loop/sessions/{confirmed['id']}/cards")
    card_bodies = {row["id"]: row["body"] for row in cards_before.json()}
    produced_id = confirmed["produced_spec_version"]["id"]
    valid_id = confirmed["valid_spec_version_id"]
    snapshot_one = confirmed["export_scratch_snapshots"][0]
    edited = _edited_document(
        confirmed["export_scratch"]["document"],
        problem_body=EDITED_PROBLEM,
    )
    patched = await _patch_export_scratch(client, confirmed, edited)
    saved = await _save_export_scratch_snapshot(client, patched)
    snapshots = saved["export_scratch_snapshots"]
    assert [row["snapshot_n"] for row in snapshots] == [1, 2]
    assert snapshots[0]["id"] == snapshot_one["id"]
    assert snapshots[0]["document"] == snapshot_one["document"]
    assert snapshots[1]["snapshot_n"] == 2
    assert snapshots[1]["spec_version_id"] == valid_id
    assert EDITED_PROBLEM in snapshots[1]["document"]["markdown"]
    assert EDITED_PROBLEM in _markdown(saved)
    cards_after = await client.get(f"/api/loop/sessions/{confirmed['id']}/cards")
    assert {row["id"]: row["body"] for row in cards_after.json()} == card_bodies
    assert saved["produced_spec_version"]["id"] == produced_id
    assert saved["valid_spec_version_id"] == valid_id


@pytest.mark.asyncio
async def test_save_export_scratch_creates_snapshot_one_when_none(
    client: AsyncClient,
) -> None:
    await _auth_client(client)
    minted = await _mint_spec_with_paper_sources(client)
    assert minted["export_scratch_snapshots"] == []
    edited = _edited_document(
        minted["export_scratch"]["document"],
        problem_body=EDITED_PROBLEM,
    )
    patched = await _patch_export_scratch(client, minted, edited)
    saved = await _save_export_scratch_snapshot(client, patched)
    snapshots = saved["export_scratch_snapshots"]
    assert [row["snapshot_n"] for row in snapshots] == [1]
    assert EDITED_PROBLEM in snapshots[0]["document"]["markdown"]


@pytest.mark.asyncio
async def test_get_lists_export_scratch_snapshots_in_order(
    client: AsyncClient,
) -> None:
    await _auth_client(client)
    confirmed = await _confirm_aggregator(client, await _prepare_aggregator(client))
    patched = await _patch_export_scratch(
        client,
        confirmed,
        _edited_document(
            confirmed["export_scratch"]["document"],
            problem_body=EDITED_PROBLEM,
        ),
    )
    saved = await _save_export_scratch_snapshot(client, patched)
    fetched = await client.get(f"/api/loop/sessions/{confirmed['id']}")
    assert fetched.status_code == 200, fetched.text
    listed = fetched.json()["export_scratch_snapshots"]
    assert [row["snapshot_n"] for row in listed] == [1, 2]
    assert listed[1]["id"] == saved["export_scratch_snapshots"][1]["id"]


@pytest.mark.asyncio
async def test_restore_export_scratch_snapshot_replaces_buffer(
    client: AsyncClient,
) -> None:
    await _auth_client(client)
    confirmed = await _confirm_aggregator(client, await _prepare_aggregator(client))
    original_markdown = _markdown(confirmed)
    patched = await _patch_export_scratch(
        client,
        confirmed,
        _edited_document(
            confirmed["export_scratch"]["document"],
            problem_body=EDITED_PROBLEM,
        ),
    )
    saved = await _save_export_scratch_snapshot(client, patched)
    snapshot_one_id = saved["export_scratch_snapshots"][0]["id"]
    restored = await _restore_export_scratch_snapshot(
        client, saved, snapshot_one_id
    )
    assert _markdown(restored) == original_markdown
    fetched = await client.get(f"/api/loop/sessions/{confirmed['id']}")
    assert _markdown(fetched.json()) == original_markdown


@pytest.mark.asyncio
async def test_diff_vs_previous_snapshot_after_edit_and_save(
    client: AsyncClient,
) -> None:
    await _auth_client(client)
    confirmed = await _confirm_aggregator(client, await _prepare_aggregator(client))
    original_markdown = _markdown(confirmed)
    patched = await _patch_export_scratch(
        client,
        confirmed,
        _edited_document(
            confirmed["export_scratch"]["document"],
            problem_body=EDITED_PROBLEM,
        ),
    )
    saved = await _save_export_scratch_snapshot(client, patched)
    payload = await _get_export_scratch_diff(
        client, confirmed["id"], against="previous"
    )
    bodies = f"{payload['before']} {payload['after']}"
    assert EDITED_PROBLEM in bodies
    assert original_markdown in bodies or "## 1. Problem Statement" in payload["before"]
    assert payload["spec_version_id"] == saved["valid_spec_version_id"]


@pytest.mark.asyncio
async def test_diff_vs_snapshot_one_after_edit(
    client: AsyncClient,
) -> None:
    await _auth_client(client)
    confirmed = await _confirm_aggregator(client, await _prepare_aggregator(client))
    original_markdown = _markdown(confirmed)
    await _patch_export_scratch(
        client,
        confirmed,
        _edited_document(
            confirmed["export_scratch"]["document"],
            problem_body=EDITED_PROBLEM,
        ),
    )
    payload = await _get_export_scratch_diff(
        client, confirmed["id"], against="original"
    )
    bodies = f"{payload['before']} {payload['after']}"
    assert EDITED_PROBLEM in bodies
    assert original_markdown in bodies


@pytest.mark.asyncio
async def test_export_scratch_diffs_do_not_compare_across_spec_versions(
    client: AsyncClient,
) -> None:
    await _auth_client(client)
    minted = await _mint_spec_with_paper_sources(client)
    first = await _confirm_aggregator(client, minted)
    first_id = first["valid_spec_version_id"]
    patched = await _patch_export_scratch(
        client,
        first,
        _edited_document(
            first["export_scratch"]["document"],
            problem_body=EDITED_PROBLEM,
        ),
        spec_version_id=first_id,
    )
    saved = await _save_export_scratch_snapshot(
        client, patched, spec_version_id=first_id
    )
    reminted = await _remint_second_spec(client, saved)
    second_id = reminted["valid_spec_version_id"]
    second_diff = await _get_export_scratch_diff(
        client, first["id"], against="original", spec_version_id=second_id
    )
    second_bodies = f"{second_diff['before']} {second_diff['after']}"
    assert EDITED_PROBLEM not in second_bodies
    assert second_diff["spec_version_id"] == second_id
    first_diff = await _get_export_scratch_diff(
        client, first["id"], against="previous", spec_version_id=first_id
    )
    first_bodies = f"{first_diff['before']} {first_diff['after']}"
    assert EDITED_PROBLEM in first_bodies
    assert first_diff["spec_version_id"] == first_id


@pytest.mark.asyncio
async def test_save_export_scratch_writes_no_decision_and_does_not_mint(
    client: AsyncClient,
) -> None:
    await _auth_client(client)
    confirmed = await _confirm_aggregator(client, await _prepare_aggregator(client))
    before = await client.get(f"/api/loop/sessions/{confirmed['id']}/decisions")
    decision_ids = [row["id"] for row in before.json()]
    kinds = [row["kind"] for row in before.json()]
    produced_id = confirmed["produced_spec_version"]["id"]
    valid_id = confirmed["valid_spec_version_id"]
    patched = await _patch_export_scratch(
        client,
        confirmed,
        _edited_document(
            confirmed["export_scratch"]["document"],
            problem_body=EDITED_PROBLEM,
        ),
    )
    saved = await _save_export_scratch_snapshot(client, patched)
    after = await client.get(f"/api/loop/sessions/{confirmed['id']}/decisions")
    assert [row["id"] for row in after.json()] == decision_ids
    assert "export_ack" not in [row["kind"] for row in after.json()]
    assert kinds == [row["kind"] for row in after.json()]
    assert saved["produced_spec_version"]["id"] == produced_id
    assert saved["valid_spec_version_id"] == valid_id
    assert saved["produced_spec_version"]["id"] == confirmed["produced_spec_version"]["id"]


MARKDOWN_PATH = "/api/loop/sessions/{session_id}/export-scratch/markdown"
PDF_PATH = "/api/loop/sessions/{session_id}/export-scratch/pdf"
OVERLAY_PROBLEM = "Unsaved overlay problem statement for markdown download"
OVERLAY_PROBLEM_PDF = "Unsaved overlay problem statement for pdf download"


def _pdf_payload_text(payload: bytes) -> str:
    from io import BytesIO

    from pypdf import PdfReader

    return "\n".join(page.extract_text() or "" for page in PdfReader(BytesIO(payload)).pages)


def _assert_twelve_atx_headings(body: str) -> None:
    for heading in ATX_HEADINGS:
        assert heading in body
    positions = [body.index(heading) for heading in ATX_HEADINGS]
    assert positions == sorted(positions)


@pytest.mark.asyncio
async def test_ready_markdown_download_has_twelve_headings_and_writes_no_decision(
    client: AsyncClient,
) -> None:
    await _auth_client(client)
    confirmed = await _confirm_aggregator(client, await _prepare_aggregator(client))
    assert confirmed["readiness"]["state"] == "ready"
    spec_id = confirmed["valid_spec_version_id"]
    before = await client.get(f"/api/loop/sessions/{confirmed['id']}/decisions")
    download = await client.post(MARKDOWN_PATH.format(session_id=confirmed["id"]))
    assert download.status_code == 200, download.text
    assert "text/markdown" in download.headers["content-type"]
    assert spec_id in download.headers.get("content-disposition", "")
    body = download.text
    assert spec_id in body
    _assert_twelve_atx_headings(body)
    after = await client.get(f"/api/loop/sessions/{confirmed['id']}/decisions")
    assert after.json() == before.json()
    assert all(row["kind"] != "export_ack" for row in after.json())


@pytest.mark.asyncio
async def test_markdown_download_uses_patched_buffer_not_snapshot(
    client: AsyncClient,
) -> None:
    await _auth_client(client)
    confirmed = await _confirm_aggregator(client, await _mint_spec_with_paper_sources(client))
    snapshot_one = confirmed["export_scratch_snapshots"][0]["document"]
    snapshot_problem = snapshot_one["markdown"]
    patched = await _patch_export_scratch(
        client,
        confirmed,
        _edited_document(
            confirmed["export_scratch"]["document"],
            problem_body=OVERLAY_PROBLEM,
        ),
    )
    download = await client.post(MARKDOWN_PATH.format(session_id=patched["id"]))
    assert download.status_code == 200, download.text
    body = download.text
    assert OVERLAY_PROBLEM in body
    if snapshot_problem and OVERLAY_PROBLEM not in snapshot_problem:
        assert body != snapshot_problem


@pytest.mark.asyncio
async def test_markdown_preamble_names_spec_version_and_disclaims_when_blocked(
    client: AsyncClient,
) -> None:
    await _auth_client(client)
    confirmed = await _confirm_aggregator(client, await _prepare_aggregator(client))
    spec_id = confirmed["valid_spec_version_id"]
    ready = await client.post(MARKDOWN_PATH.format(session_id=confirmed["id"]))
    assert ready.status_code == 200, ready.text
    assert f"Source Spec Version: {spec_id}" in ready.text
    assert "not the Valid Spec Version" not in ready.text
    assert "Readiness did not pass" not in ready.text

    evidence = await _prepare_evidence_judge(
        client, claim_statement=UNSUPPORTED_CLAIM
    )
    await _generate_evidence_judge(client, evidence["id"], evidence["version"])
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
    blocked_id = blocked["valid_spec_version_id"]
    download = await client.post(
        MARKDOWN_PATH.format(session_id=blocked["id"]),
        json={"critical_export_ack": True},
    )
    assert download.status_code == 200, download.text
    assert f"Source Spec Version: {blocked_id}" in download.text
    assert download.text == _markdown(blocked)
    assert "This file is not the Valid Spec Version. Readiness did not pass." in (
        blocked["export_scratch_snapshots"][0]["document"]["markdown"]
    )


@pytest.mark.asyncio
async def test_blocked_markdown_download_requires_ack_and_records_export_ack(
    client: AsyncClient,
) -> None:
    await _auth_client(client)
    evidence = await _prepare_evidence_judge(
        client, claim_statement=UNSUPPORTED_CLAIM
    )
    await _generate_evidence_judge(client, evidence["id"], evidence["version"])
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
    denied = await client.post(MARKDOWN_PATH.format(session_id=blocked["id"]))
    assert denied.status_code == 409
    assert denied.json()["code"] == "critical_export_confirmation_required"

    before = await client.get(f"/api/loop/sessions/{blocked['id']}/decisions")
    allowed = await client.post(
        MARKDOWN_PATH.format(session_id=blocked["id"]),
        json={"critical_export_ack": True},
    )
    assert allowed.status_code == 200, allowed.text
    after = await client.get(f"/api/loop/sessions/{blocked['id']}/decisions")
    acks = [row for row in after.json() if row["kind"] == "export_ack"]
    assert len(acks) == 1
    assert acks[0]["detail"] == {
        "target": "export_scratch",
        "format": "markdown",
        "spec_version_id": blocked["valid_spec_version_id"],
    }
    assert len(after.json()) == len(before.json()) + 1

    again = await client.post(MARKDOWN_PATH.format(session_id=blocked["id"]))
    assert again.status_code == 409
    assert again.json()["code"] == "critical_export_confirmation_required"


@pytest.mark.asyncio
async def test_spec_artifact_export_stays_unedited_valid_json_after_scratch_patch(
    client: AsyncClient,
) -> None:
    await _auth_client(client)
    confirmed = await _confirm_aggregator(client, await _prepare_aggregator(client))
    valid_id = confirmed["valid_spec_version_id"]
    valid_document = confirmed["produced_spec_version"]["document"]
    await _patch_export_scratch(
        client,
        confirmed,
        _edited_document(
            confirmed["export_scratch"]["document"],
            problem_body=OVERLAY_PROBLEM,
        ),
    )
    artifact = await client.post(
        f"/api/loop/sessions/{confirmed['id']}/spec-artifact"
    )
    assert artifact.status_code == 200, artifact.text
    assert artifact.json()["spec_version_id"] == valid_id
    assert artifact.json()["document"] == valid_document
    assert OVERLAY_PROBLEM not in json.dumps(artifact.json()["document"])


@pytest.mark.asyncio
async def test_ready_pdf_download_is_pdf_and_writes_no_decision(
    client: AsyncClient,
) -> None:
    await _auth_client(client)
    confirmed = await _confirm_aggregator(client, await _prepare_aggregator(client))
    assert confirmed["readiness"]["state"] == "ready"
    spec_id = confirmed["valid_spec_version_id"]
    before = await client.get(f"/api/loop/sessions/{confirmed['id']}/decisions")
    download = await client.post(PDF_PATH.format(session_id=confirmed["id"]))
    assert download.status_code == 200, download.text
    assert "application/pdf" in download.headers["content-type"]
    assert spec_id in download.headers.get("content-disposition", "")
    assert download.content.startswith(b"%PDF")
    after = await client.get(f"/api/loop/sessions/{confirmed['id']}/decisions")
    assert after.json() == before.json()
    assert all(row["kind"] != "export_ack" for row in after.json())


@pytest.mark.asyncio
async def test_pdf_download_uses_patched_buffer_not_snapshot(
    client: AsyncClient,
) -> None:
    await _auth_client(client)
    confirmed = await _confirm_aggregator(client, await _mint_spec_with_paper_sources(client))
    snapshot_one = confirmed["export_scratch_snapshots"][0]["document"]
    snapshot_problem = snapshot_one["markdown"]
    patched = await _patch_export_scratch(
        client,
        confirmed,
        _edited_document(
            confirmed["export_scratch"]["document"],
            problem_body=OVERLAY_PROBLEM_PDF,
        ),
    )
    download = await client.post(PDF_PATH.format(session_id=patched["id"]))
    assert download.status_code == 200, download.text
    assert download.content.startswith(b"%PDF")
    body = _pdf_payload_text(download.content)
    assert OVERLAY_PROBLEM_PDF in body
    if snapshot_problem and OVERLAY_PROBLEM_PDF not in snapshot_problem:
        # Overlay replaced the problem body; leftover projection text may remain.
        assert OVERLAY_PROBLEM_PDF in body


@pytest.mark.asyncio
async def test_pdf_download_keeps_non_latin1_characters_from_the_same_markdown(
    client: AsyncClient,
) -> None:
    await _auth_client(client)
    confirmed = await _confirm_aggregator(client, await _prepare_aggregator(client))
    unicode_body = "λ-calculus — nghiên cứu"
    patched = await _patch_export_scratch(
        client,
        confirmed,
        _edited_document(
            confirmed["export_scratch"]["document"],
            problem_body=unicode_body,
        ),
    )
    markdown = await client.post(MARKDOWN_PATH.format(session_id=patched["id"]))
    assert markdown.status_code == 200, markdown.text
    assert unicode_body in markdown.text
    download = await client.post(PDF_PATH.format(session_id=patched["id"]))
    assert download.status_code == 200, download.text
    body = _pdf_payload_text(download.content)
    assert unicode_body in body


@pytest.mark.asyncio
async def test_blocked_pdf_download_requires_ack_and_records_export_ack(
    client: AsyncClient,
) -> None:
    await _auth_client(client)
    evidence = await _prepare_evidence_judge(
        client, claim_statement=UNSUPPORTED_CLAIM
    )
    await _generate_evidence_judge(client, evidence["id"], evidence["version"])
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
    denied = await client.post(PDF_PATH.format(session_id=blocked["id"]))
    assert denied.status_code == 409
    assert denied.json()["code"] == "critical_export_confirmation_required"

    before = await client.get(f"/api/loop/sessions/{blocked['id']}/decisions")
    allowed = await client.post(
        PDF_PATH.format(session_id=blocked["id"]),
        json={"critical_export_ack": True},
    )
    assert allowed.status_code == 200, allowed.text
    assert allowed.content.startswith(b"%PDF")
    after = await client.get(f"/api/loop/sessions/{blocked['id']}/decisions")
    acks = [row for row in after.json() if row["kind"] == "export_ack"]
    assert len(acks) == 1
    assert acks[0]["detail"] == {
        "target": "export_scratch",
        "format": "pdf",
        "spec_version_id": blocked["valid_spec_version_id"],
    }
    assert len(after.json()) == len(before.json()) + 1

    again = await client.post(PDF_PATH.format(session_id=blocked["id"]))
    assert again.status_code == 409
    assert again.json()["code"] == "critical_export_confirmation_required"

