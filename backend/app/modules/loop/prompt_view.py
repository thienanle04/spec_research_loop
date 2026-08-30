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

_JUDGE_NODES = frozenset(
    {
        WorkflowNode.GAP_JUDGE,
        WorkflowNode.CONTRIBUTION_JUDGE,
        WorkflowNode.EVIDENCE_JUDGE,
        WorkflowNode.EXPERIMENT_JUDGE,
        WorkflowNode.CONFERENCE_JUDGE,
        WorkflowNode.AGGREGATOR,
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
    if node in _JUDGE_NODES:
        return _judge_prompt_view(node, projection)
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


def _judge_prompt_view(node: WorkflowNode, projection: dict[str, Any]) -> dict[str, Any]:
    cards = _spec_cards(projection, keep_ids=True, include_spec_version=True)
    view: dict[str, Any] = {
        "node": node.value,
        "cards": cards,
        "gap_statement": _gap_statement(projection, cards),
        "related_work": _related_work_passages(projection),
        "working_draft": _judge_working_draft(node, projection.get("working_draft")),
        "valid_spec_version": _slim_valid_spec_version(projection.get("valid_spec_version")),
    }
    plan = _experiment_plan(projection)
    if plan:
        view["experiment_plan"] = plan
    if node is WorkflowNode.EVIDENCE_JUDGE:
        view["claim_citation_passages"] = _claim_citation_passages(
            cards, view["related_work"]
        )
    return view


def _spec_cards(
    projection: dict[str, Any],
    *,
    keep_ids: bool = False,
    include_spec_version: bool = False,
) -> list[dict[str, Any]]:
    collected: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for snapshot in _card_snapshots(
        projection, include_spec_version=include_spec_version
    ):
        for item in snapshot:
            slim = _slim_card(item, keep_id=keep_ids)
            if slim is None:
                continue
            key = (slim["kind"], slim.get("text") or slim.get("statement") or "")
            if key in seen:
                continue
            seen.add(key)
            collected.append(slim)
    return collected


def _card_snapshots(
    projection: dict[str, Any], *, include_spec_version: bool = False
) -> list[list[Any]]:
    snapshots: list[list[Any]] = []
    if include_spec_version:
        spec = projection.get("valid_spec_version")
        if isinstance(spec, dict):
            document = spec.get("document")
            if isinstance(document, dict):
                nodes = document.get("nodes")
                if isinstance(nodes, dict):
                    for source in _SPEC_CARD_UPSTREAM:
                        block = nodes.get(source.value)
                        if isinstance(block, dict):
                            snapshot = block.get("card_snapshot")
                            if isinstance(snapshot, list):
                                snapshots.append(snapshot)
    upstream = projection.get("upstream")
    if isinstance(upstream, dict):
        for source in _SPEC_CARD_UPSTREAM:
            block = upstream.get(source.value)
            if not isinstance(block, dict):
                continue
            snapshot = block.get("card_snapshot")
            if isinstance(snapshot, list):
                snapshots.append(snapshot)
    return snapshots


def _slim_card(item: Any, *, keep_id: bool = False) -> dict[str, Any] | None:
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
    slim = {"kind": kind, **slim_body}
    if keep_id:
        card_id = item.get("id")
        if isinstance(card_id, str) and card_id:
            slim["id"] = card_id
    return slim


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


def _judge_working_draft(node: WorkflowNode, working: Any) -> dict[str, Any]:
    if not isinstance(working, dict):
        return {"narrative": {}, "cards": []}
    if working.get("node") != node.value:
        return {"narrative": {}, "cards": []}
    return _slim_working_draft(working)


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


def _related_work_passages(projection: dict[str, Any]) -> list[dict[str, Any]]:
    upstream = projection.get("upstream")
    if not isinstance(upstream, dict):
        return []
    block = upstream.get(WorkflowNode.RELATED_WORK.value)
    if not isinstance(block, dict):
        return []
    projected = block.get("projected")
    if not isinstance(projected, dict):
        return []
    id_to_key: dict[str, str] = {}
    citations = projected.get("citations")
    if isinstance(citations, list):
        for cite in citations:
            if not isinstance(cite, dict):
                continue
            cite_id = cite.get("id")
            key = cite.get("citation_key")
            if isinstance(cite_id, str) and isinstance(key, str) and key.strip():
                id_to_key[cite_id] = key.strip()
    findings = projected.get("related_work")
    if not isinstance(findings, list):
        return []
    passages: list[dict[str, Any]] = []
    for item in findings:
        if not isinstance(item, dict):
            continue
        passage = item.get("supporting_passage")
        if not isinstance(passage, str) or not passage.strip():
            continue
        slim: dict[str, Any] = {"supporting_passage": passage.strip()}
        citation_key = item.get("citation_key")
        citation_id = item.get("citation_id")
        if isinstance(citation_id, str) and citation_id.strip():
            slim["citation_id"] = citation_id.strip()
            if citation_id in id_to_key:
                slim["citation_key"] = id_to_key[citation_id]
        if isinstance(citation_key, str) and citation_key.strip():
            slim["citation_key"] = citation_key.strip()
        passages.append(slim)
    return passages


def _claim_text(card: dict[str, Any]) -> str:
    for key in ("statement", "text", "claim"):
        value = card.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _claim_citation_passages(
    cards: list[dict[str, Any]], related_work: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    passages_by_key: dict[str, str] = {}
    for item in related_work:
        if not isinstance(item, dict):
            continue
        key = item.get("citation_key")
        passage = item.get("supporting_passage")
        if isinstance(key, str) and key.strip() and isinstance(passage, str) and passage.strip():
            passages_by_key[key.strip()] = passage.strip()
    triples: list[dict[str, Any]] = []
    for card in cards:
        if not isinstance(card, dict) or card.get("kind") != CardKind.CLAIM.value:
            continue
        claim = _claim_text(card)
        if not claim:
            continue
        card_id = card.get("id")
        keys = card.get("supporting_citation_keys")
        cited = [
            key.strip()
            for key in keys
            if isinstance(key, str) and key.strip()
        ] if isinstance(keys, list) else []
        if not cited:
            triple: dict[str, Any] = {
                "claim": claim,
                "citation_key": "",
                "passage": "",
            }
            if isinstance(card_id, str) and card_id:
                triple["claim_id"] = card_id
            triples.append(triple)
            continue
        for key in cited:
            triple = {
                "claim": claim,
                "citation_key": key,
                "passage": passages_by_key.get(key, ""),
            }
            if isinstance(card_id, str) and card_id:
                triple["claim_id"] = card_id
            triples.append(triple)
    return triples


def _slim_valid_spec_version(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    spec_id = raw.get("id")
    if not isinstance(spec_id, str) or not spec_id:
        return None
    document = raw.get("document")
    nodes: dict[str, Any] = {}
    if isinstance(document, dict):
        raw_nodes = document.get("nodes")
        if isinstance(raw_nodes, dict):
            for source in (
                *_SPEC_CARD_UPSTREAM,
                WorkflowNode.EXPERIMENT_PLAN,
                WorkflowNode.FEASIBILITY,
            ):
                block = raw_nodes.get(source.value)
                if not isinstance(block, dict):
                    continue
                snapshot = block.get("card_snapshot")
                cards = []
                if isinstance(snapshot, list):
                    cards = [
                        slim
                        for item in snapshot
                        if (slim := _slim_card(item, keep_id=True)) is not None
                    ]
                narrative = block.get("narrative")
                slim_narrative: dict[str, Any] = {}
                if isinstance(narrative, dict):
                    plan = narrative.get("plan")
                    if isinstance(plan, dict) and plan:
                        slim_narrative["plan"] = plan
                nodes[source.value] = {
                    "card_snapshot": cards,
                    "narrative": slim_narrative,
                }
    return {"id": spec_id, "document": {"nodes": nodes}}
