"""Prompt View: prompt-ready slices of a Context Projection (ADR 0035)."""

from __future__ import annotations

from typing import Any

from app.modules.loop.catalog import CardKind, WorkflowNode

_SPEC_NODES = frozenset(
    {
        WorkflowNode.CONTRIBUTION,
        WorkflowNode.CLAIMS,
        WorkflowNode.EXPERIMENT_PLAN,
        WorkflowNode.FEASIBILITY,
    }
)

# Upstream Workflow Nodes whose card_snapshot may contribute Card texts.
_SPEC_CARD_UPSTREAM: tuple[WorkflowNode, ...] = (
    WorkflowNode.IDEA_DECOMPOSITION,
    WorkflowNode.GAP,
    WorkflowNode.CONTRIBUTION,
    WorkflowNode.CLAIMS,
    WorkflowNode.EVIDENCE,
)

_SPEC_CARD_KINDS: frozenset[str] = frozenset(kind.value for kind in CardKind)


def prompt_view(node: WorkflowNode, projection: dict[str, Any]) -> dict[str, Any]:
    """Pure transform: Context Projection → Prompt View for ``node``."""
    if node not in _SPEC_NODES:
        raise ValueError(f"Prompt View is not defined for {node.value} yet")

    cards = _spec_cards(projection)
    view: dict[str, Any] = {
        "node": node.value,
        "cards": cards,
        "gap_statement": _gap_statement(projection, cards),
        "working_draft": _slim_working_draft(projection.get("working_draft")),
    }
    if node is WorkflowNode.FEASIBILITY:
        plan = _experiment_plan(projection)
        if plan:
            view["experiment_plan"] = plan
    return view


def _spec_cards(projection: dict[str, Any]) -> list[dict[str, Any]]:
    upstream = projection.get("upstream")
    if not isinstance(upstream, dict):
        return []
    collected: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for source in _SPEC_CARD_UPSTREAM:
        block = upstream.get(source.value)
        if not isinstance(block, dict):
            continue
        snapshot = block.get("card_snapshot")
        if not isinstance(snapshot, list):
            continue
        for item in snapshot:
            slim = _slim_card(item)
            if slim is None:
                continue
            key = (slim["kind"], slim.get("text") or slim.get("statement") or "")
            if key in seen:
                continue
            seen.add(key)
            collected.append(slim)
    return collected


def _slim_card(item: Any) -> dict[str, Any] | None:
    if not isinstance(item, dict):
        return None
    kind = item.get("kind")
    if not isinstance(kind, str) or kind not in _SPEC_CARD_KINDS:
        return None
    body = item.get("body")
    if not isinstance(body, dict):
        body = {}
    slim_body = _slim_body(body)
    if not slim_body:
        return None
    return {"kind": kind, **slim_body}


def _slim_body(body: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in body.items():
        if isinstance(value, str):
            text = value.strip()
            if text:
                out[key] = text
        elif isinstance(value, (bool, int, float)):
            out[key] = value
        elif isinstance(value, list) and value and all(isinstance(i, str) for i in value):
            out[key] = [item.strip() for item in value if item.strip()]
    return out


def _gap_statement(projection: dict[str, Any], cards: list[dict[str, Any]]) -> str:
    for card in cards:
        if card.get("kind") != CardKind.GAP.value:
            continue
        statement = card.get("statement") or card.get("text")
        if isinstance(statement, str) and statement.strip():
            return statement.strip()
    upstream = projection.get("upstream")
    if not isinstance(upstream, dict):
        return ""
    gap = upstream.get(WorkflowNode.GAP.value)
    if not isinstance(gap, dict):
        return ""
    narrative = gap.get("narrative")
    if not isinstance(narrative, dict):
        return ""
    for key in ("candidate", "selected", "gap"):
        block = narrative.get(key)
        if isinstance(block, dict):
            statement = block.get("statement") or block.get("text")
            if isinstance(statement, str) and statement.strip():
                return statement.strip()
    statement = narrative.get("statement")
    if isinstance(statement, str) and statement.strip():
        return statement.strip()
    return ""


def _slim_working_draft(working: Any) -> dict[str, Any]:
    if not isinstance(working, dict):
        return {"narrative": {}, "cards": []}
    narrative = working.get("narrative")
    if not isinstance(narrative, dict):
        narrative = {}
    cards_raw = working.get("card_snapshot")
    if not isinstance(cards_raw, list):
        cards_raw = []
    cards = [slim for item in cards_raw if (slim := _slim_card(item)) is not None]
    return {"narrative": narrative, "cards": cards}


def _experiment_plan(projection: dict[str, Any]) -> dict[str, Any] | None:
    working = projection.get("working_draft")
    if isinstance(working, dict):
        narrative = working.get("narrative")
        if isinstance(narrative, dict):
            plan = narrative.get("plan")
            if isinstance(plan, dict) and plan:
                return plan
    upstream = projection.get("upstream")
    if not isinstance(upstream, dict):
        return None
    block = upstream.get(WorkflowNode.EXPERIMENT_PLAN.value)
    if not isinstance(block, dict):
        return None
    narrative = block.get("narrative")
    if not isinstance(narrative, dict):
        return None
    plan = narrative.get("plan")
    if isinstance(plan, dict) and plan:
        return plan
    return None
