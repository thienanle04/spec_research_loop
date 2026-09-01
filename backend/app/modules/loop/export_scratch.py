"""Deterministic paper projection from a Spec Version document (no LLM)."""

from __future__ import annotations

from typing import Any

PAPER_SECTION_IDS: tuple[str, ...] = (
    "problem_statement",
    "research_question",
    "related_work",
    "research_gap",
    "contribution",
    "claims",
    "evidence",
    "experiment_plan",
    "constraints",
    "required_resources",
    "potential_bottlenecks",
    "mitigation_strategies",
    "open_issues",
)

PAPER_SECTIONS: tuple[tuple[str, str], ...] = (
    ("problem_statement", "Problem Statement"),
    ("research_question", "Research Question"),
    ("related_work", "Related Work"),
    ("research_gap", "Research Gap"),
    ("contribution", "Proposed Approach & Contribution"),
    ("claims", "Claims"),
    ("evidence", "Evidence"),
    ("experiment_plan", "Experiment Plan"),
    ("constraints", "Constraints"),
    ("required_resources", "Required Resources"),
    ("potential_bottlenecks", "Potential Bottlenecks"),
    ("mitigation_strategies", "Mitigation Strategies"),
    ("open_issues", "Open Issues"),
)


def clarification_review_from_spec(spec_document: dict[str, Any] | None) -> dict[str, Any]:
    nodes = _dict(spec_document).get("nodes")
    nodes = nodes if isinstance(nodes, dict) else {}
    cards = _all_cards(nodes)
    original_idea = ""
    turns = _list(_dict(_dict(nodes.get("idea_interpretation")).get("narrative")).get("turns"))
    for turn in turns:
        if not isinstance(turn, dict):
            continue
        if turn.get("role") == "account" and turn.get("kind") == "idea":
            text = turn.get("text")
            if isinstance(text, str):
                original_idea = text
            break
    return {
        "original_idea": original_idea,
        "gap": _card_texts(cards, "gap"),
        "contribution": _card_texts(cards, "contribution"),
        "claims": _card_text_list(cards, "claim"),
    }


def project_paper_document(spec_document: dict[str, Any] | None) -> dict[str, Any]:
    nodes = _dict(spec_document).get("nodes")
    nodes = nodes if isinstance(nodes, dict) else {}
    cards = _all_cards(nodes)
    bodies = {
        "problem_statement": _card_texts(cards, "problem"),
        "research_question": _card_texts(cards, "research_question"),
        "related_work": _related_work_body(nodes),
        "research_gap": _card_texts(cards, "gap"),
        "contribution": _card_texts(cards, "contribution"),
        "claims": _card_texts(cards, "claim"),
        "evidence": _card_texts(cards, "evidence"),
        "experiment_plan": _experiment_plan_body(nodes),
        "constraints": _card_texts(cards, "constraint"),
        "required_resources": _feasibility_list(nodes, "required_resources"),
        "potential_bottlenecks": _feasibility_list(nodes, "potential_bottlenecks"),
        "mitigation_strategies": _feasibility_list(nodes, "mitigation_strategies"),
        "open_issues": _card_texts(cards, "open_question"),
    }
    return {
        "sections": [
            {"id": section_id, "title": title, "body": bodies[section_id]}
            for section_id, title in PAPER_SECTIONS
        ]
    }


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _all_cards(nodes: dict[str, Any]) -> list[dict[str, Any]]:
    cards: list[dict[str, Any]] = []
    for block in nodes.values():
        if not isinstance(block, dict):
            continue
        for item in _list(block.get("card_snapshot")):
            if isinstance(item, dict):
                cards.append(item)
    return cards


def _card_text(item: dict[str, Any]) -> str:
    body = _dict(item.get("body"))
    for key in ("text", "statement"):
        value = body.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _card_text_list(cards: list[dict[str, Any]], kind: str) -> list[str]:
    seen: set[str] = set()
    texts: list[str] = []
    for item in cards:
        if item.get("kind") != kind:
            continue
        text = _card_text(item)
        if not text or text in seen:
            continue
        seen.add(text)
        texts.append(text)
    return texts


def _card_texts(cards: list[dict[str, Any]], kind: str) -> str:
    return "\n\n".join(_card_text_list(cards, kind))


def _related_work_body(nodes: dict[str, Any]) -> str:
    block = _dict(nodes.get("related_work"))
    projection = _dict(block.get("projection"))
    findings = _list(projection.get("related_work"))
    parts: list[str] = []
    for finding in findings:
        if not isinstance(finding, dict):
            continue
        what = finding.get("what_was_done")
        if isinstance(what, str) and what.strip():
            parts.append(what.strip())
            continue
        evidence = _dict(finding.get("evidence"))
        nested = _dict(evidence.get("what_was_done")).get("passage")
        if isinstance(nested, str) and nested.strip():
            parts.append(nested.strip())
    if parts:
        return "\n\n".join(parts)
    titles: list[str] = []
    for citation in _list(projection.get("citations")):
        if not isinstance(citation, dict):
            continue
        title = citation.get("title")
        if isinstance(title, str) and title.strip():
            titles.append(title.strip())
    return "\n\n".join(titles)


def _experiment_plan_body(nodes: dict[str, Any]) -> str:
    narrative = _dict(_dict(nodes.get("experiment_plan")).get("narrative"))
    plan = _dict(narrative.get("plan"))
    experiments = _list(plan.get("experiments"))
    blocks: list[str] = []
    for item in experiments:
        if not isinstance(item, dict):
            continue
        lines = [
            str(item[key]).strip()
            for key in ("claim", "action", "objective", "significance")
            if isinstance(item.get(key), str) and str(item[key]).strip()
        ]
        if lines:
            blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def _feasibility_list(nodes: dict[str, Any], field: str) -> str:
    narrative = _dict(_dict(nodes.get("feasibility")).get("narrative"))
    report = _dict(narrative.get("feasibility_report"))
    items = [
        item.strip()
        for item in _list(report.get(field))
        if isinstance(item, str) and item.strip()
    ]
    return "\n".join(items)
