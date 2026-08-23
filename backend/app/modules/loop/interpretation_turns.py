"""Interpretation Working Draft turn list (ADR 0025)."""

from __future__ import annotations

from typing import Any

from fastapi import status

from app.core.errors import OperationalErrorException

_MIN_OPTIONS = 2


class TurnListError(ValueError):
    """The Working Draft turn list is not a valid interpretation transcript."""


def turns_of(narrative: dict[str, Any]) -> list[dict[str, Any]]:
    raw = narrative.get("turns")
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise TurnListError("turns must be a list")
    return [dict(item) for item in raw if isinstance(item, dict)]


def unanswered_cluster(turns: list[dict[str, Any]]) -> list[dict[str, Any]] | None:
    if not turns:
        return None
    last = turns[-1]
    if last.get("role") != "model":
        return None
    questions = last.get("questions")
    if not isinstance(questions, list) or not questions:
        return None
    return questions


def has_idea(turns: list[dict[str, Any]]) -> bool:
    return any(item.get("role") == "account" and item.get("kind") == "idea" for item in turns)


def last_is_account(turns: list[dict[str, Any]]) -> bool:
    return bool(turns) and turns[-1].get("role") == "account"


def clusters_answered(turns: list[dict[str, Any]]) -> bool:
    if not has_idea(turns):
        return False
    pending: list[dict[str, Any]] | None = None
    for item in turns:
        if item.get("role") == "model":
            questions = item.get("questions")
            pending = questions if isinstance(questions, list) and questions else None
        elif item.get("role") == "account" and item.get("kind") == "answers":
            pending = None
    return pending is None


def _question_options(question: dict[str, Any]) -> list[str]:
    options = question.get("options")
    if not isinstance(options, list):
        return []
    return [item for item in options if isinstance(item, str)]


def normalize_answers(
    questions: list[dict[str, Any]],
    answers: list[dict[str, Any]],
) -> list[dict[str, str]]:
    if len(answers) != len(questions):
        raise OperationalErrorException(
            status_code=status.HTTP_409_CONFLICT,
            code="invalid_generate_answers",
            detail="answers must match the unanswered Grilling Question cluster",
        )
    normalized: list[dict[str, str]] = []
    for question, answer in zip(questions, answers, strict=True):
        option = answer.get("option")
        other = answer.get("other")
        option_text = option.strip() if isinstance(option, str) else ""
        other_text = other.strip() if isinstance(other, str) else ""
        if bool(option_text) == bool(other_text):
            raise OperationalErrorException(
                status_code=status.HTTP_409_CONFLICT,
                code="invalid_generate_answers",
                detail="Each answer must be a Grilling Option or Other text",
            )
        if option_text:
            if option_text not in _question_options(question):
                raise OperationalErrorException(
                    status_code=status.HTTP_409_CONFLICT,
                    code="invalid_generate_answers",
                    detail="Grilling Option is not one of the proposed replies",
                )
            normalized.append({"option": option_text})
        else:
            normalized.append({"other": other_text})
    return normalized


def append_idea_cluster(
    narrative: dict[str, Any],
    *,
    idea: str,
    preamble: str,
    questions: list[dict[str, Any]],
    exhausted: bool,
) -> dict[str, Any]:
    turns = turns_of(narrative)
    turns.append({"role": "account", "kind": "idea", "text": idea.strip()})
    turns.append({"role": "model", "preamble": preamble, "questions": questions})
    return {"turns": turns, "exhausted": exhausted}


def append_answers_cluster(
    narrative: dict[str, Any],
    *,
    answers: list[dict[str, str]],
    preamble: str,
    questions: list[dict[str, Any]],
    exhausted: bool,
) -> dict[str, Any]:
    turns = turns_of(narrative)
    turns.append({"role": "account", "kind": "answers", "answers": answers})
    turns.append({"role": "model", "preamble": preamble, "questions": questions})
    return {"turns": turns, "exhausted": exhausted}


def append_cluster_only(
    narrative: dict[str, Any],
    *,
    preamble: str,
    questions: list[dict[str, Any]],
    exhausted: bool,
) -> dict[str, Any]:
    turns = turns_of(narrative)
    turns.append({"role": "model", "preamble": preamble, "questions": questions})
    return {"turns": turns, "exhausted": exhausted}


def _model_fingerprint(turn: dict[str, Any]) -> tuple[str, tuple[tuple[str, tuple[str, ...]], ...]]:
    questions = turn.get("questions")
    if not isinstance(questions, list):
        questions = []
    q_fp = []
    for item in questions:
        if not isinstance(item, dict):
            continue
        text = item.get("text") if isinstance(item.get("text"), str) else ""
        options = tuple(_question_options(item))
        q_fp.append((text, options))
    preamble = turn.get("preamble") if isinstance(turn.get("preamble"), str) else ""
    return preamble, tuple(q_fp)


def _account_equal(left: dict[str, Any], right: dict[str, Any]) -> bool:
    if left.get("kind") != right.get("kind"):
        return False
    if left.get("kind") == "idea":
        return (left.get("text") or "") == (right.get("text") or "")
    return left.get("answers") == right.get("answers")


def apply_account_reply_patch(
    current: dict[str, Any],
    incoming: dict[str, Any],
) -> dict[str, Any]:
    current_turns = turns_of(current)
    incoming_turns = turns_of(incoming)
    if not incoming_turns:
        raise OperationalErrorException(
            status_code=status.HTTP_409_CONFLICT,
            code="invalid_working_draft_narrative",
            detail="Interpretation PATCH must keep the structured turn list",
        )
    if len(incoming_turns) > len(current_turns):
        raise OperationalErrorException(
            status_code=status.HTTP_409_CONFLICT,
            code="invalid_working_draft_narrative",
            detail="Interpretation PATCH cannot append generate turns",
        )
    result: list[dict[str, Any]] = []
    truncated = False
    for index, turn in enumerate(incoming_turns):
        existing = current_turns[index]
        if turn.get("role") != existing.get("role"):
            raise OperationalErrorException(
                status_code=status.HTTP_409_CONFLICT,
                code="invalid_working_draft_narrative",
                detail="Interpretation PATCH cannot change turn roles",
            )
        if turn.get("role") == "model":
            if _model_fingerprint(turn) != _model_fingerprint(existing):
                raise OperationalErrorException(
                    status_code=status.HTTP_409_CONFLICT,
                    code="invalid_working_draft_narrative",
                    detail="Grilling Questions cannot be edited",
                )
            result.append(existing)
            continue
        if existing.get("kind") != turn.get("kind"):
            raise OperationalErrorException(
                status_code=status.HTTP_409_CONFLICT,
                code="invalid_working_draft_narrative",
                detail="Interpretation PATCH cannot change Account turn kinds",
            )
        changed = not _account_equal(existing, turn)
        result.append(dict(turn))
        if changed and index < len(current_turns) - 1:
            truncated = True
            break
    if not truncated and len(incoming_turns) < len(current_turns):
        truncated = True
        result = incoming_turns
    exhausted = False if truncated else bool(current.get("exhausted"))
    if not truncated and len(incoming_turns) == len(current_turns):
        exhausted = bool(incoming.get("exhausted", current.get("exhausted")))
    return {"turns": result, "exhausted": exhausted}


def parse_questions(raw: Any, *, exhausted: bool) -> list[dict[str, Any]]:
    if raw is None:
        questions: list[Any] = []
    elif isinstance(raw, list):
        questions = raw
    else:
        raise TurnListError("questions must be a list")
    if exhausted and questions:
        raise TurnListError("exhausted questions must be empty")
    parsed: list[dict[str, Any]] = []
    for item in questions:
        if not isinstance(item, dict):
            raise TurnListError("each question must be an object")
        text = item.get("text")
        options = item.get("options")
        if not isinstance(text, str) or not text.strip():
            raise TurnListError("question text must be a non-empty string")
        if not isinstance(options, list):
            raise TurnListError("question options must be a list")
        cleaned: list[str] = []
        for option in options:
            if not isinstance(option, str) or not option.strip():
                raise TurnListError("each Grilling Option must be a non-empty string")
            value = option.strip()
            if value in cleaned:
                raise TurnListError("Grilling Options must be unique")
            cleaned.append(value)
        if len(cleaned) < _MIN_OPTIONS:
            raise TurnListError("each Grilling Question needs at least two Grilling Options")
        parsed.append({"text": text.strip(), "options": cleaned})
    return parsed
