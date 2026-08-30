"""HTTP seam: Handling Option PICK is a loop Decision (ticket 06)."""

from uuid import uuid4

import pytest
from httpx import AsyncClient

from tests.test_judgement_api import (
    UNSUPPORTED_CLAIM,
    _advance_to_aggregator,
    _bind_aggregator_llm,
    _generate_aggregator,
    _generate_evidence_judge,
    _prepare_evidence_judge,
    _prepare_gap_judge,
)
from tests.test_loop_api import (
    _auth_client,
    _confirm,
    _create_session,
    _head,
    _patch_working_draft,
    _prepare,
    _register,
)

CLAIM_OPTION = {
    "finding_kind": "unsupported_citation",
    "source_node": "evidence_judge",
    "label": "Revise the claim",
    "target_node": "claims",
    "prose": "Cite a passage that entails the claim.",
}
EVIDENCE_OPTION = {
    "finding_kind": "unsupported_citation",
    "source_node": "evidence_judge",
    "label": "Replace the citation",
    "target_node": "evidence",
    "prose": "Attach a passage that supports the claim.",
}


async def _confirmed_aggregator_with_options(
    client: AsyncClient,
    options: list[dict],
    *,
    claim_statement: str | None = UNSUPPORTED_CLAIM,
) -> tuple[dict, list[dict], list[dict]]:
    evidence = await _prepare_evidence_judge(
        client, claim_statement=claim_statement
    )
    events = await _generate_evidence_judge(
        client, evidence["id"], evidence["version"]
    )
    session = await _confirm(
        client, evidence["id"], "evidence_judge", events[-1]["version"]
    )
    session = await _prepare(
        client, evidence["id"], "independent_judges", session["version"]
    )
    draft = await _advance_to_aggregator(client, session)
    _bind_aggregator_llm({"options": options})
    generated = await _generate_aggregator(client, draft["id"], draft["version"])
    confirmed = await _confirm(
        client, draft["id"], "aggregator", generated[-1]["version"]
    )
    stored = await client.get(
        f"/api/judgement/sessions/{draft['id']}/nodes/aggregator"
    )
    assert stored.status_code == 200, stored.text
    return confirmed, stored.json()["handling_options"], stored.json()["issues"]


@pytest.mark.asyncio
async def test_pick_is_loop_decision_and_requires_working_draft_aggregator(
    client: AsyncClient,
) -> None:
    await _auth_client(client)
    created = await _create_session(client)
    response = await client.post(
        f"/api/loop/sessions/{created['id']}/pick",
        json={
            "expected_version": created["version"],
            "handling_option_id": str(uuid4()),
        },
    )
    assert response.status_code == 409
    assert response.json()["code"] == "invalid_working_draft_target"
    decisions = await client.get(f"/api/loop/sessions/{created['id']}/decisions")
    assert decisions.json() == []


@pytest.mark.asyncio
async def test_pick_foreign_session_is_not_found(client: AsyncClient) -> None:
    await _auth_client(client)
    created = await _create_session(client)
    other_token = await _register(client)
    client.headers["Authorization"] = f"Bearer {other_token}"
    response = await client.post(
        f"/api/loop/sessions/{created['id']}/pick",
        json={
            "expected_version": created["version"],
            "handling_option_id": str(uuid4()),
        },
    )
    assert response.status_code == 404
    missing = await client.post(
        f"/api/loop/sessions/{uuid4()}/pick",
        json={"expected_version": 1, "handling_option_id": str(uuid4())},
    )
    assert missing.status_code == 404


@pytest.mark.asyncio
async def test_pick_version_conflict_on_working_draft_aggregator(
    client: AsyncClient,
) -> None:
    await _auth_client(client)
    confirmed, options, _issues = await _confirmed_aggregator_with_options(
        client, [CLAIM_OPTION]
    )
    assert confirmed["working_draft_node"] == "aggregator"
    response = await client.post(
        f"/api/loop/sessions/{confirmed['id']}/pick",
        json={
            "expected_version": confirmed["version"] - 1,
            "handling_option_id": options[0]["id"],
        },
    )
    assert response.status_code == 409
    assert response.json()["code"] == "version_conflict"
    fetched = await client.get(f"/api/loop/sessions/{confirmed['id']}")
    assert fetched.json()["working_draft_node"] == "aggregator"
    assert fetched.json()["version"] == confirmed["version"]


@pytest.mark.asyncio
async def test_pick_reopens_current_target_without_stale_or_card_patch(
    client: AsyncClient,
) -> None:
    await _auth_client(client)
    confirmed, options, issues = await _confirmed_aggregator_with_options(
        client, [CLAIM_OPTION]
    )
    option = next(item for item in options if item["target_node"] == "claims")
    cards_before = await client.get(f"/api/loop/sessions/{confirmed['id']}/cards")
    assert cards_before.status_code == 200
    claim_ids = [
        item["id"] for item in cards_before.json() if item["kind"] == "claim"
    ]
    issue_card_ids = [
        item["target_card_id"]
        for item in issues
        if item["finding_kind"] == "unsupported_citation" and item["target_card_id"]
    ]
    assert _head(confirmed, "claims")["status"] == "current"
    aggregator_revision = _head(confirmed, "aggregator")["stage_revision_id"]

    picked = await client.post(
        f"/api/loop/sessions/{confirmed['id']}/pick",
        json={
            "expected_version": confirmed["version"],
            "handling_option_id": option["id"],
        },
    )
    assert picked.status_code == 200, picked.text
    payload = picked.json()
    assert payload["working_draft_node"] == "claims"
    assert _head(payload, "claims")["status"] == "current"
    assert _head(payload, "aggregator")["status"] == "current"
    assert _head(payload, "aggregator")["stage_revision_id"] == aggregator_revision
    assert payload["valid_spec_version_id"] == confirmed["valid_spec_version_id"]
    narrative = payload["working_draft_narrative"]
    assert narrative["suggested_patch"] == CLAIM_OPTION["prose"]
    assert narrative["target_card_ids"] == issue_card_ids
    cards_after = await client.get(f"/api/loop/sessions/{confirmed['id']}/cards")
    assert cards_after.json() == cards_before.json()
    assert claim_ids
    decisions = await client.get(f"/api/loop/sessions/{confirmed['id']}/decisions")
    kinds = [item["kind"] for item in decisions.json()]
    assert kinds[-1] == "pick"
    assert decisions.json()[-1]["node"] == "claims"
    listed = await client.get(
        f"/api/judgement/sessions/{confirmed['id']}/nodes/aggregator"
    )
    assert listed.json()["handling_options"] == options
    assert any(
        item["finding_kind"] == "unsupported_citation"
        and item["severity"] == "CRITICAL"
        for item in listed.json()["issues"]
    )


@pytest.mark.asyncio
async def test_pick_shared_issue_targets_chosen_node(client: AsyncClient) -> None:
    await _auth_client(client)
    confirmed, options, _issues = await _confirmed_aggregator_with_options(
        client, [CLAIM_OPTION, EVIDENCE_OPTION]
    )
    kinds = {(item["finding_kind"], item["source_node"]) for item in options}
    assert kinds == {("unsupported_citation", "evidence_judge")}
    by_target = {item["target_node"]: item for item in options}
    assert set(by_target) == {"claims", "evidence"}
    picked = await client.post(
        f"/api/loop/sessions/{confirmed['id']}/pick",
        json={
            "expected_version": confirmed["version"],
            "handling_option_id": by_target["evidence"]["id"],
        },
    )
    assert picked.status_code == 200, picked.text
    assert picked.json()["working_draft_node"] == "evidence"
    assert (
        picked.json()["working_draft_narrative"]["suggested_patch"]
        == EVIDENCE_OPTION["prose"]
    )
    restored = await _patch_working_draft(
        client,
        confirmed["id"],
        expected_version=picked.json()["version"],
        node="aggregator",
    )
    second = await client.post(
        f"/api/loop/sessions/{confirmed['id']}/pick",
        json={
            "expected_version": restored.json()["version"],
            "handling_option_id": by_target["claims"]["id"],
        },
    )
    assert second.status_code == 200, second.text
    assert second.json()["working_draft_node"] == "claims"
    assert _head(second.json(), "evidence")["status"] == "current"


@pytest.mark.asyncio
async def test_pick_other_uses_account_prose_and_target(client: AsyncClient) -> None:
    await _auth_client(client)
    confirmed, _options, _issues = await _confirmed_aggregator_with_options(
        client, [CLAIM_OPTION]
    )
    denied = await client.post(
        f"/api/loop/sessions/{confirmed['id']}/pick",
        json={
            "expected_version": confirmed["version"],
            "prose": "Rewrite interpretation.",
            "target_node": "idea_interpretation",
        },
    )
    assert denied.status_code == 409
    assert denied.json()["code"] == "invalid_working_draft_target"

    picked = await client.post(
        f"/api/loop/sessions/{confirmed['id']}/pick",
        json={
            "expected_version": confirmed["version"],
            "prose": "Narrow the decomposition into testable Cards.",
            "target_node": "idea_decomposition",
        },
    )
    assert picked.status_code == 200, picked.text
    payload = picked.json()
    assert payload["working_draft_node"] == "idea_decomposition"
    assert payload["working_draft_narrative"]["suggested_patch"] == (
        "Narrow the decomposition into testable Cards."
    )
    assert payload["working_draft_narrative"]["target_card_ids"] == []
    assert _head(payload, "idea_decomposition")["status"] == "current"
    decisions = await client.get(f"/api/loop/sessions/{confirmed['id']}/decisions")
    assert decisions.json()[-1]["kind"] == "pick"
    assert decisions.json()[-1]["node"] == "idea_decomposition"


@pytest.mark.asyncio
async def test_pick_does_not_clear_critical_export_gate(client: AsyncClient) -> None:
    await _auth_client(client)
    blocked, options, _issues = await _confirmed_aggregator_with_options(
        client, [CLAIM_OPTION]
    )
    assert blocked["readiness"]["state"] == "blocked"
    picked = await client.post(
        f"/api/loop/sessions/{blocked['id']}/pick",
        json={
            "expected_version": blocked["version"],
            "handling_option_id": options[0]["id"],
        },
    )
    assert picked.status_code == 200, picked.text
    assert picked.json()["readiness"]["state"] == "blocked"
    denied = await client.post(f"/api/loop/sessions/{blocked['id']}/spec-artifact")
    assert denied.status_code == 409
    assert denied.json()["code"] == "critical_issues_block_export"

    draft = await _prepare_gap_judge(client)
    session = await _advance_to_aggregator(client, draft)
    _bind_aggregator_llm({"options": []})
    generated = await _generate_aggregator(
        client, session["id"], session["version"]
    )
    ready = await _confirm(
        client, session["id"], "aggregator", generated[-1]["version"]
    )
    assert ready["readiness"]["state"] == "ready"
    picked_major = await client.post(
        f"/api/loop/sessions/{ready['id']}/pick",
        json={
            "expected_version": ready["version"],
            "prose": "Tighten the experiment plan.",
            "target_node": "experiment_plan",
        },
    )
    assert picked_major.status_code == 200, picked_major.text
    assert picked_major.json()["readiness"]["state"] == "ready"
    allowed = await client.post(f"/api/loop/sessions/{ready['id']}/spec-artifact")
    assert allowed.status_code == 200, allowed.text
    assert allowed.json()["spec_version_id"] == ready["valid_spec_version_id"]


@pytest.mark.asyncio
async def test_confirm_after_pick_stales_related_judges_without_autorun(
    client: AsyncClient,
) -> None:
    await _auth_client(client)
    confirmed, options, _issues = await _confirmed_aggregator_with_options(
        client, [CLAIM_OPTION]
    )
    option = next(item for item in options if item["target_node"] == "claims")
    picked = await client.post(
        f"/api/loop/sessions/{confirmed['id']}/pick",
        json={
            "expected_version": confirmed["version"],
            "handling_option_id": option["id"],
        },
    )
    assert picked.status_code == 200, picked.text
    assert _head(picked.json(), "evidence_judge")["status"] == "current"
    assert _head(picked.json(), "aggregator")["status"] == "current"
    assert _head(picked.json(), "evidence_judge")["generated_since_prepare"] is False

    claim = next(
        card for card in picked.json()["cards"] if card["kind"] == "claim"
    )
    patched = await client.patch(
        f"/api/loop/sessions/{confirmed['id']}/cards/{claim['id']}",
        json={
            "body": {**claim["body"], "statement": "A narrower claim after PICK."},
            "expected_version": picked.json()["version"],
        },
    )
    assert patched.status_code == 200, patched.text
    changed = await _confirm(
        client, confirmed["id"], "claims", patched.json()["version"]
    )
    assert _head(changed, "evidence_judge")["status"] == "stale"
    assert _head(changed, "experiment_judge")["status"] == "stale"
    assert _head(changed, "aggregator")["status"] == "stale"
    assert _head(changed, "evidence_judge")["generated_since_prepare"] is False
    assert _head(changed, "aggregator")["generated_since_prepare"] is False
    frozen = await client.get(
        f"/api/judgement/sessions/{confirmed['id']}/nodes/aggregator",
        params={
            "stage_revision_id": _head(confirmed, "aggregator")["stage_revision_id"]
        },
    )
    assert frozen.status_code == 200, frozen.text
    assert any(
        item["finding_kind"] == "unsupported_citation"
        and item["severity"] == "CRITICAL"
        for item in frozen.json()["issues"]
    )
