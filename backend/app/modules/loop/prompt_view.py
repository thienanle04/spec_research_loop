"""Prompt View: prompt-ready slices of a Context Projection (ADR 0035)."""

from __future__ import annotations

from typing import Any

from app.modules.loop.catalog import FIVE_JUDGE_NODES, CardKind, WorkflowNode

_SPEC_NODES = frozenset(
    {
        WorkflowNode.CONTRIBUTION,
        WorkflowNode.CLAIMS,
        WorkflowNode.EXPERIMENT_PLAN,
        WorkflowNode.FEASIBILITY,
    }
)

_JUDGE_NODES = frozenset({*FIVE_JUDGE_NODES, WorkflowNode.AGGREGATOR})

# Upstream Workflow Nodes whose card_snapshot may contribute Card texts.
_SPEC_CARD_UPSTREAM: tuple[WorkflowNode, ...] = (
    WorkflowNode.IDEA_DECOMPOSITION,
    WorkflowNode.GAP,
    WorkflowNode.CONTRIBUTION,
    WorkflowNode.CLAIMS,
)

_SPEC_CARD_KINDS: frozenset[str] = frozenset(kind.value for kind in CardKind)
_CONTRIBUTION_RELATED_WORK_LIMIT = 8
_CONTRIBUTION_TEXT_LIMIT = 1_200
_GAP_JUDGE_OMIT_CARD_KINDS: frozenset[str] = frozenset(
    {CardKind.CLAIM.value, CardKind.EVIDENCE.value}
)
_CONTRIBUTION_JUDGE_OMIT_CARD_KINDS: frozenset[str] = frozenset(
    {CardKind.CLAIM.value, CardKind.EVIDENCE.value}
)
_JUDGE_EXPERIMENT_PLAN_NODES: frozenset[WorkflowNode] = frozenset(
    {WorkflowNode.EXPERIMENT_JUDGE, WorkflowNode.CONFERENCE_JUDGE}
)
_GAP_JUDGE_OMIT_SPEC_NODES: frozenset[WorkflowNode] = frozenset(
    {WorkflowNode.CLAIMS, WorkflowNode.EVIDENCE}
)
_CONTRIBUTION_JUDGE_OMIT_SPEC_NODES: frozenset[WorkflowNode] = frozenset(
    {WorkflowNode.CLAIMS, WorkflowNode.EVIDENCE}
)


def prompt_view(node: WorkflowNode, projection: dict[str, Any]) -> dict[str, Any]:
    """Pure transform: Context Projection → Prompt View for ``node``."""
    if node is WorkflowNode.AGGREGATOR:
        return _aggregator_prompt_view(projection)
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
    if node is WorkflowNode.CONTRIBUTION:
        view["related_work"] = _compact_related_work(projection)
    if node is WorkflowNode.CLAIMS:
        view["related_work"] = _related_work_passages(projection)
    return view


def _aggregator_prompt_view(projection: dict[str, Any]) -> dict[str, Any]:
    upstream = projection.get("upstream")
    if not isinstance(upstream, dict):
        upstream = {}
    runs: list[dict[str, Any]] = []
    for source in FIVE_JUDGE_NODES:
        block = upstream.get(source.value)
        projected: dict[str, Any] = {}
        if isinstance(block, dict):
            raw = block.get("projected")
            if isinstance(raw, dict):
                projected = raw
        issues = projected.get("issues")
        scores = projected.get("scores")
        runs.append(
            {
                "node": source.value,
                "issues": issues if isinstance(issues, list) else [],
                "scores": scores if isinstance(scores, dict) else None,
            }
        )
    return {"node": WorkflowNode.AGGREGATOR.value, "judge_runs": runs}


def _judge_omit_card_kinds(node: WorkflowNode) -> frozenset[str]:
    if node is WorkflowNode.GAP_JUDGE:
        return _GAP_JUDGE_OMIT_CARD_KINDS
    if node is WorkflowNode.CONTRIBUTION_JUDGE:
        return _CONTRIBUTION_JUDGE_OMIT_CARD_KINDS
    return frozenset()


def _judge_omit_spec_nodes(node: WorkflowNode) -> frozenset[WorkflowNode]:
    if node is WorkflowNode.GAP_JUDGE:
        return _GAP_JUDGE_OMIT_SPEC_NODES
    if node is WorkflowNode.CONTRIBUTION_JUDGE:
        return _CONTRIBUTION_JUDGE_OMIT_SPEC_NODES
    return frozenset()


def _filter_cards(
    cards: list[dict[str, Any]], omit_kinds: frozenset[str]
) -> list[dict[str, Any]]:
    if not omit_kinds:
        return cards
    return [card for card in cards if card.get("kind") not in omit_kinds]


def _judge_prompt_view(node: WorkflowNode, projection: dict[str, Any]) -> dict[str, Any]:
    omit_kinds = _judge_omit_card_kinds(node)
    cards = _filter_cards(
        _spec_cards(projection, keep_ids=True, include_spec_version=True),
        omit_kinds,
    )
    passages = _related_work_passages(projection)
    view: dict[str, Any] = {
        "node": node.value,
        "cards": cards,
        "gap_statement": _gap_statement(projection, cards),
        "working_draft": _judge_working_draft(node, projection.get("working_draft")),
        "valid_spec_version": _slim_valid_spec_version(
            projection.get("valid_spec_version"),
            omit_card_kinds=omit_kinds,
            omit_nodes=_judge_omit_spec_nodes(node),
        ),
    }
    if node in (WorkflowNode.GAP_JUDGE, WorkflowNode.CONTRIBUTION_JUDGE):
        compact = _compact_related_work(projection)
        view["related_work"] = {**compact, "passages": passages}
    else:
        view["related_work"] = passages
    if node in _JUDGE_EXPERIMENT_PLAN_NODES:
        plan = _experiment_plan(projection)
        if plan:
            view["experiment_plan"] = plan
    if node is WorkflowNode.CONFERENCE_JUDGE:
        feasibility = _feasibility_report(projection)
        if feasibility:
            view["feasibility"] = feasibility
    if node is WorkflowNode.EVIDENCE_JUDGE:
        view["claim_citation_passages"] = _claim_citation_passages(cards, passages)
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


def _feasibility_report(projection: dict[str, Any]) -> dict[str, Any] | None:
    working = projection.get("working_draft")
    if isinstance(working, dict):
        narrative = working.get("narrative")
        if isinstance(narrative, dict):
            report = _slim_feasibility_report(narrative.get("feasibility_report"))
            if report:
                return report
    upstream = projection.get("upstream")
    if isinstance(upstream, dict):
        block = upstream.get(WorkflowNode.FEASIBILITY.value)
        if isinstance(block, dict):
            narrative = block.get("narrative")
            if isinstance(narrative, dict):
                report = _slim_feasibility_report(narrative.get("feasibility_report"))
                if report:
                    return report
    spec = projection.get("valid_spec_version")
    if isinstance(spec, dict):
        document = spec.get("document")
        if isinstance(document, dict):
            nodes = document.get("nodes")
            if isinstance(nodes, dict):
                block = nodes.get(WorkflowNode.FEASIBILITY.value)
                if isinstance(block, dict):
                    narrative = block.get("narrative")
                    if isinstance(narrative, dict):
                        return _slim_feasibility_report(
                            narrative.get("feasibility_report")
                        )
    return None


def _slim_feasibility_report(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict) or not raw:
        return None
    report: dict[str, Any] = {}
    for key in (
        "is_feasible",
        "conclusion",
        "required_resources",
        "potential_bottlenecks",
        "mitigation_strategies",
    ):
        value = raw.get(key)
        if isinstance(value, str):
            text = value.strip()
            if text:
                report[key] = text
        elif isinstance(value, bool):
            report[key] = value
        elif isinstance(value, list):
            items = [
                item.strip()
                for item in value
                if isinstance(item, str) and item.strip()
            ]
            if items:
                report[key] = items
    return report or None


def _compact_text(value: Any, *, limit: int = _CONTRIBUTION_TEXT_LIMIT) -> str:
    if not isinstance(value, str):
        return ""
    compact = " ".join(value.split())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 1].rstrip() + "…"


def _citation_source(raw: dict[str, Any]) -> dict[str, Any]:
    source = {
        "citation_key": _compact_text(raw.get("citation_key"), limit=200),
        "title": _compact_text(raw.get("title"), limit=500),
        "year": raw.get("year"),
        "venue": _compact_text(raw.get("venue"), limit=300),
        "verification_status": raw.get("verification_status"),
    }
    return {key: value for key, value in source.items() if value not in ("", None)}


def _citation_indexes(
    projection: dict[str, Any],
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    by_id: dict[str, dict[str, Any]] = {}
    by_key: dict[str, dict[str, Any]] = {}
    upstream = projection.get("upstream")
    if not isinstance(upstream, dict):
        return by_id, by_key
    node = upstream.get(WorkflowNode.RELATED_WORK.value)
    if not isinstance(node, dict):
        return by_id, by_key
    projected = node.get("projected")
    if not isinstance(projected, dict):
        return by_id, by_key
    citations = projected.get("citations")
    if not isinstance(citations, list):
        return by_id, by_key
    for raw in citations:
        if not isinstance(raw, dict):
            continue
        source = _citation_source(raw)
        identifier = str(raw.get("id") or "")
        if identifier:
            by_id[identifier] = source
        key = source.get("citation_key")
        if isinstance(key, str) and key:
            by_key[key] = source
    return by_id, by_key


def _compact_related_work(projection: dict[str, Any]) -> dict[str, Any]:
    upstream = projection.get("upstream")
    if not isinstance(upstream, dict):
        return {"studies": [], "coverage": {}}
    node = upstream.get(WorkflowNode.RELATED_WORK.value)
    if not isinstance(node, dict):
        return {"studies": [], "coverage": {}}
    projected = node.get("projected")
    if not isinstance(projected, dict):
        projected = {}
    citations_by_id, _citations_by_key = _citation_indexes(projection)
    findings = projected.get("related_work")
    if not isinstance(findings, list):
        findings = []
    studies: list[dict[str, Any]] = []
    for raw in findings[:_CONTRIBUTION_RELATED_WORK_LIMIT]:
        if not isinstance(raw, dict):
            continue
        citation_id = str(raw.get("citation_id") or "")
        source = citations_by_id.get(citation_id, {})
        study = {
            "source": source,
            "what_was_done": _compact_text(raw.get("what_was_done")),
            "method_or_feedback": _compact_text(raw.get("method_or_feedback")),
            "limitation": _compact_text(raw.get("limitation")),
            "relevance": _compact_text(raw.get("relevance")),
            "grounding_status": raw.get("grounding_status"),
            "confidence": raw.get("confidence"),
        }
        studies.append(
            {key: value for key, value in study.items() if value not in ("", None, {})}
        )
    if not studies:
        for source in list(citations_by_id.values())[:_CONTRIBUTION_RELATED_WORK_LIMIT]:
            studies.append({"source": source})
    narrative = node.get("narrative")
    if not isinstance(narrative, dict):
        narrative = {}
    coverage = {
        key: narrative.get(key)
        for key in (
            "candidate_count",
            "ranked_candidate_count",
            "selected_count",
            "skipped_inaccessible_count",
        )
        if narrative.get(key) is not None
    }
    return {"studies": studies, "coverage": coverage}


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
    by_id, by_key = _citation_indexes(projection)
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
        source: dict[str, Any] = {}
        if isinstance(citation_id, str) and citation_id.strip():
            slim["citation_id"] = citation_id.strip()
            source = by_id.get(citation_id.strip(), {})
            key_from_id = source.get("citation_key")
            if isinstance(key_from_id, str) and key_from_id:
                slim["citation_key"] = key_from_id
        if isinstance(citation_key, str) and citation_key.strip():
            slim["citation_key"] = citation_key.strip()
            if not source:
                source = by_key.get(citation_key.strip(), {})
        if source:
            slim["source"] = source
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
    source_by_key: dict[str, dict[str, Any]] = {}
    for item in related_work:
        if not isinstance(item, dict):
            continue
        key = item.get("citation_key")
        passage = item.get("supporting_passage")
        if isinstance(key, str) and key.strip() and isinstance(passage, str) and passage.strip():
            passages_by_key[key.strip()] = passage.strip()
        source = item.get("source")
        if isinstance(key, str) and key.strip() and isinstance(source, dict) and source:
            source_by_key[key.strip()] = source
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
            source = source_by_key.get(key)
            if source:
                triple["source"] = source
            if isinstance(card_id, str) and card_id:
                triple["claim_id"] = card_id
            triples.append(triple)
    return triples


def _slim_valid_spec_version(
    raw: Any,
    *,
    omit_card_kinds: frozenset[str] = frozenset(),
    omit_nodes: frozenset[WorkflowNode] = frozenset(),
) -> dict[str, Any] | None:
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
                if source in omit_nodes:
                    continue
                block = raw_nodes.get(source.value)
                if not isinstance(block, dict):
                    continue
                snapshot = block.get("card_snapshot")
                cards = []
                if isinstance(snapshot, list):
                    cards = _filter_cards(
                        [
                            slim
                            for item in snapshot
                            if (slim := _slim_card(item, keep_id=True)) is not None
                        ],
                        omit_card_kinds,
                    )
                narrative = block.get("narrative")
                slim_narrative: dict[str, Any] = {}
                if isinstance(narrative, dict):
                    plan = narrative.get("plan")
                    if isinstance(plan, dict) and plan:
                        slim_narrative["plan"] = plan
                    report = _slim_feasibility_report(
                        narrative.get("feasibility_report")
                    )
                    if report:
                        slim_narrative["feasibility_report"] = report
                nodes[source.value] = {
                    "card_snapshot": cards,
                    "narrative": slim_narrative,
                }
    return {"id": spec_id, "document": {"nodes": nodes}}
