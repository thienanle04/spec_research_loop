"""Interpretation Working Draft turn list (ADR 0025, 0027, 0029)."""

from __future__ import annotations

from typing import Any

from fastapi import status

from app.core.errors import OperationalErrorException

_MIN_OPTIONS = 2
_ACCOUNT_KINDS = {"idea", "answers", "note"}


class TurnListError(ValueError):
    """The Working Draft turn list is not a valid interpretation transcript."""


def turns_of(narrative: dict[str, Any]) -> list[dict[str, Any]]:
    raw = narrative.get("turns")
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise TurnListError("turns must be a list")
    return [dict(item) for item in raw if isinstance(item, dict)]


def empty_frame() -> dict[str, str]:
    return {"intent": "", "problem": "", "research_question": ""}


def parse_frame(raw: Any) -> dict[str, str]:
    if raw is None:
        return empty_frame()
    if not isinstance(raw, dict):
        raise TurnListError("Idea Frame must be an object")
    intent = raw.get("intent", "")
    problem = raw.get("problem", "")
    research_question = raw.get("research_question", "")
    if (
        not isinstance(intent, str)
        or not isinstance(problem, str)
        or not isinstance(research_question, str)
    ):
        raise TurnListError("Idea Frame fields must be strings")
    return {
        "intent": intent.strip(),
        "problem": problem.strip(),
        "research_question": research_question.strip(),
    }


def frame_complete(frame: Any) -> bool:
    try:
        parsed = parse_frame(frame)
    except TurnListError:
        return False
    return bool(parsed["intent"]) and bool(parsed["problem"]) and bool(parsed["research_question"])


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
    pending = False
    for item in turns:
        if item.get("role") == "model":
            questions = item.get("questions")
            has_questions = isinstance(questions, list) and bool(questions)
            if has_questions and pending:
                return False
            if has_questions:
                pending = True
        elif item.get("role") == "account" and item.get("kind") in {"answers", "note"}:
            pending = False
    return not pending


def interpretation_confirmable(narrative: dict[str, Any]) -> bool:
    return frame_complete(narrative.get("frame"))


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


def _with_frame(
    turns: list[dict[str, Any]],
    *,
    exhausted: bool,
    frame: dict[str, str],
) -> dict[str, Any]:
    return {"turns": turns, "exhausted": exhausted, "frame": frame}


def append_idea_cluster(
    narrative: dict[str, Any],
    *,
    idea: str,
    preamble: str,
    questions: list[dict[str, Any]],
    exhausted: bool,
    frame: dict[str, str],
) -> dict[str, Any]:
    turns = turns_of(narrative)
    turns.append({"role": "account", "kind": "idea", "text": idea.strip()})
    turns.append({"role": "model", "preamble": preamble, "questions": questions})
    return _with_frame(turns, exhausted=exhausted, frame=frame)


def append_answers_cluster(
    narrative: dict[str, Any],
    *,
    answers: list[dict[str, str]],
    preamble: str,
    questions: list[dict[str, Any]],
    exhausted: bool,
    frame: dict[str, str],
    note: str | None = None,
) -> dict[str, Any]:
    turns = turns_of(narrative)
    turns.append({"role": "account", "kind": "answers", "answers": answers})
    if note:
        turns.append({"role": "account", "kind": "note", "text": note})
    turns.append({"role": "model", "preamble": preamble, "questions": questions})
    return _with_frame(turns, exhausted=exhausted, frame=frame)


def append_note_cluster(
    narrative: dict[str, Any],
    *,
    note: str,
    preamble: str,
    questions: list[dict[str, Any]],
    exhausted: bool,
    frame: dict[str, str],
) -> dict[str, Any]:
    turns = turns_of(narrative)
    turns.append({"role": "account", "kind": "note", "text": note})
    turns.append({"role": "model", "preamble": preamble, "questions": questions})
    return _with_frame(turns, exhausted=exhausted, frame=frame)


def append_cluster_only(
    narrative: dict[str, Any],
    *,
    preamble: str,
    questions: list[dict[str, Any]],
    exhausted: bool,
    frame: dict[str, str],
) -> dict[str, Any]:
    turns = turns_of(narrative)
    turns.append({"role": "model", "preamble": preamble, "questions": questions})
    return _with_frame(turns, exhausted=exhausted, frame=frame)


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
    if left.get("kind") in {"idea", "note"}:
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
    if "frame" in incoming:
        try:
            incoming_frame = parse_frame(incoming.get("frame"))
            current_frame = parse_frame(current.get("frame"))
        except TurnListError as exc:
            raise OperationalErrorException(
                status_code=status.HTTP_409_CONFLICT,
                code="invalid_working_draft_narrative",
                detail=str(exc),
            ) from exc
        if incoming_frame != current_frame:
            raise OperationalErrorException(
                status_code=status.HTTP_409_CONFLICT,
                code="invalid_working_draft_narrative",
                detail="The Idea Frame cannot be edited",
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
        if existing.get("kind") not in _ACCOUNT_KINDS:
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
    try:
        frame = parse_frame(current.get("frame"))
    except TurnListError:
        frame = empty_frame()
    return _with_frame(result, exhausted=exhausted, frame=frame)


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
