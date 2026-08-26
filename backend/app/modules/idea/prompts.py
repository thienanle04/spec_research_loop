"""Prompts for Grilling generate."""

from __future__ import annotations

import json
from typing import Any

from app.modules.loop.catalog import WorkflowNode

_INTERPRETATION_SYSTEM = """You are grilling a researcher to reach a shared understanding of their idea.
Ask focused, relentless questions. One cluster of questions per turn.
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
exhausted is true only when further questions would not change the idea.
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


def user_prompt(
    *,
    context: dict[str, Any],
    message: str | None,
    answers: list[dict[str, str]] | None = None,
    note: str | None = None,
) -> str:
    payload: dict[str, Any] = {"context": context, "message": message}
    if answers is not None:
        payload["answers"] = answers
    if note is not None:
        payload["note"] = note
    return json.dumps(payload, ensure_ascii=False, indent=2)
