"""Prompts for Grilling generate."""

from __future__ import annotations

import json
from typing import Any

from app.modules.loop.catalog import WorkflowNode

_INTERPRETATION_SYSTEM = """You are grilling a researcher to reach a shared understanding of their idea.
Goal: a Confirm-ready Idea Frame in as few generate turns as possible, without thinning intent, problem, or research_question.
One cluster of questions per turn. Prefer fewer, denser questions over many shallow ones.
Ask only what directly clarifies intent, problem, or research_question. Drop any question that would not force a rewrite of at least one of those fields.
Clarify in order: intent first, then problem, then research_question. Do not skip ahead while an earlier field is still vague.
Until problem and research_question are clear enough for Confirm, do not ask about scope, method, dataset, metrics, baselines, novelty, contribution framing, related work, writing, timeline, or tooling.
Rewrite the Idea Frame every turn: intent, problem, and research_question.
Do not decompose into Cards. Do not invent citations.
Match the Account's language.
Write only Account-facing preamble prose first (cluster intro, not the Idea Frame).
Then on its own line write exactly ---json---
Then write one JSON object and nothing else: no markdown fences, no commentary after it.
Escape every double quote inside JSON strings.
Schema:
{"exhausted": true or false, "cards": [], "questions": [{"text": "...", "options": ["...", "..."]}], "frame": {"intent": "...", "problem": "...", "research_question": "..."}}
Each question needs at least two distinct Grilling Options.
If exhausted is true, questions must be [].
exhausted is true when the Idea Frame is concrete enough for the Account to Confirm—further questions would not materially change intent, problem, or research_question.
frame.intent, frame.problem, and frame.research_question must be non-empty.
intent is a paragraph paraphrasing what the Account wants, in their language. It is not the problem or research_question."""

_DECOMPOSITION_SYSTEM = """You decompose a confirmed interpretation into Cards.
Copy problem and research_question from the confirmed Idea Frame. Do not rewrite them.
Do not copy intent into Cards.
Fill constraint and open_question from Account turns only (the research idea, answers, and Account notes).
Do not turn unanswered Grilling Questions or model preamble into Cards.
One problem, one research_question; constraints and open questions may be many.
Do not invent citations.
Match the Account's language.
Write a short restatement as Account-facing prose first.
Then on its own line write exactly ---json---
Then write one JSON object and nothing else: no markdown fences, no commentary after it.
Escape every double quote inside JSON strings.
Schema:
{"exhausted": false, "cards": [{"kind": "problem"|"research_question"|"constraint"|"open_question", "text": "..."}]}"""


def system_prompt(node: WorkflowNode) -> str:
    if node is WorkflowNode.IDEA_INTERPRETATION:
        return _INTERPRETATION_SYSTEM
    return _DECOMPOSITION_SYSTEM


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _slim_cards(raw: Any) -> list[dict[str, Any]]:
    cards: list[dict[str, Any]] = []
    for item in _list(raw):
        if not isinstance(item, dict):
            continue
        kind = item.get("kind")
        body = item.get("body")
        if not isinstance(kind, str) or not isinstance(body, dict):
            continue
        text = body.get("text") or body.get("statement") or body.get(kind)
        if isinstance(text, str) and text.strip():
            cards.append({"kind": kind, "text": text.strip()})
    return cards


def _slim_working_draft(working: Any) -> dict[str, Any]:
    draft = _dict(working)
    narrative = _dict(draft.get("narrative"))
    return {
        "node": draft.get("node"),
        "narrative": {
            "turns": _list(narrative.get("turns")),
            "frame": _dict(narrative.get("frame")),
            "questions": _list(narrative.get("questions")),
            "exhausted": narrative.get("exhausted"),
        },
        "cards": _slim_cards(draft.get("card_snapshot")),
    }


def _confirmed_frame(context: dict[str, Any]) -> dict[str, Any]:
    upstream = _dict(context.get("upstream"))
    interpretation = _dict(upstream.get(WorkflowNode.IDEA_INTERPRETATION.value))
    narrative = _dict(interpretation.get("narrative"))
    frame = narrative.get("frame")
    return frame if isinstance(frame, dict) else {}


def _grilling_prompt_context(context: dict[str, Any]) -> dict[str, Any]:
    """Grilling-only slice. Full Context Projection overflows a 64k vendor window (ADR 0035)."""
    upstream = _dict(context.get("upstream"))
    interpretation = _dict(upstream.get(WorkflowNode.IDEA_INTERPRETATION.value))
    decomposition = _dict(upstream.get(WorkflowNode.IDEA_DECOMPOSITION.value))
    return {
        "working_draft": _slim_working_draft(context.get("working_draft")),
        "confirmed_idea_frame": _confirmed_frame(context),
        "interpretation_cards": _slim_cards(interpretation.get("card_snapshot")),
        "decomposition_cards": _slim_cards(decomposition.get("card_snapshot")),
    }


def user_prompt(
    *,
    context: dict[str, Any],
    message: str | None,
    answers: list[dict[str, str]] | None = None,
    note: str | None = None,
) -> str:
    payload: dict[str, Any] = {
        "context": _grilling_prompt_context(context),
        "message": message,
    }
    if answers is not None:
        payload["answers"] = answers
    if note is not None:
        payload["note"] = note
    return json.dumps(payload, ensure_ascii=False)
