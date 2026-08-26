"""Parse a visible-prose + ---json--- trailer completion (ADR 0023)."""

from __future__ import annotations

import json
from typing import Any

from app.modules.loop.catalog import CardKind
from app.modules.loop.interpretation_turns import TurnListError, parse_frame, parse_questions

DELIMITER = "---json---"

_ALLOWED_KINDS = {
    CardKind.PROBLEM,
    CardKind.RESEARCH_QUESTION,
    CardKind.CONSTRAINT,
    CardKind.OPEN_QUESTION,
}
_SINGULAR = {CardKind.PROBLEM, CardKind.RESEARCH_QUESTION}


def _safe_emit_end(buf: str) -> int:
    max_hold = len(DELIMITER) - 1
    hold = 0
    for size in range(min(max_hold, len(buf)), 0, -1):
        if DELIMITER.startswith(buf[-size:]):
            hold = size
            break
    return len(buf) - hold


class TrailerParseError(Exception):
    """The completion had no usable JSON trailer."""


class TrailerSplitter:
    def __init__(self) -> None:
        self._buf = ""
        self._emitted = 0
        self._found = False
        self._json_parts: list[str] = []

    def feed(self, chunk: str) -> str:
        if self._found:
            self._json_parts.append(chunk)
            return ""
        self._buf += chunk
        idx = self._buf.find(DELIMITER)
        if idx == -1:
            safe_end = _safe_emit_end(self._buf)
            if safe_end > self._emitted:
                out = self._buf[self._emitted : safe_end]
                self._emitted = safe_end
                return out
            return ""
        self._found = True
        prose_out = self._buf[self._emitted : idx]
        self._json_parts.append(self._buf[idx + len(DELIMITER) :])
        return prose_out

    def finish(self, *, interpretation: bool = False) -> tuple[str, dict[str, Any]]:
        if not self._found:
            raise TrailerParseError("missing json trailer")
        idx = self._buf.find(DELIMITER)
        prose = self._buf[:idx].rstrip()
        raw = "".join(self._json_parts).strip()
        return prose, parse_trailer_payload(raw, interpretation=interpretation)


def _unwrap_fences(text: str) -> str:
    stripped = text.strip()
    if not stripped.startswith("```"):
        return stripped
    rest = stripped[3:]
    if rest.startswith("json"):
        rest = rest[4:]
    rest = rest.lstrip("\n").strip()
    if rest.endswith("```"):
        rest = rest[: -3].rstrip()
    return rest


def _strip_trailing_commas(text: str) -> str:
    out: list[str] = []
    in_string = False
    escape = False
    index = 0
    while index < len(text):
        char = text[index]
        if in_string:
            out.append(char)
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            index += 1
            continue
        if char == '"':
            in_string = True
            out.append(char)
            index += 1
            continue
        if char == ",":
            cursor = index + 1
            while cursor < len(text) and text[cursor].isspace():
                cursor += 1
            if cursor < len(text) and text[cursor] in "}]":
                index += 1
                continue
        out.append(char)
        index += 1
    return "".join(out)


def _next_significant(text: str, index: int) -> str:
    while index < len(text) and text[index].isspace():
        index += 1
    return text[index] if index < len(text) else ""


def _escape_interior_quotes(text: str) -> str:
    """Treat a " inside a JSON string as literal unless it closes the string."""
    out: list[str] = []
    in_string = False
    escape = False
    index = 0
    while index < len(text):
        char = text[index]
        if not in_string:
            out.append(char)
            if char == '"':
                in_string = True
            index += 1
            continue
        if escape:
            out.append(char)
            escape = False
            index += 1
            continue
        if char == "\\":
            out.append(char)
            escape = True
            index += 1
            continue
        if char == '"':
            nxt = _next_significant(text, index + 1)
            if nxt in ",}]:":
                out.append('"')
                in_string = False
            else:
                out.append('\\"')
            index += 1
            continue
        out.append(char)
        index += 1
    return "".join(out)


def _fix_questions_wrapper(snippet: str) -> str:
    """Rewrite a common Qwen close: ]}}] instead of ]}]."""
    stripped = snippet.rstrip()
    if stripped.endswith("]}}]"):
        return stripped[:-4] + "]}]"
    return snippet


def _object_span(text: str, start: int) -> int:
    """Length of the JSON object at start, tracking strings so inner braces do not count."""
    if start >= len(text) or text[start] != "{":
        return 0
    depth = 0
    in_string = False
    escape = False
    index = start
    while index < len(text):
        char = text[index]
        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            index += 1
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return index + 1 - start
        index += 1
    return 0


def _salvage_object(snippet: str) -> dict[str, Any] | None:
    """Collect question objects when the wrapper braces are wrong (e.g. ]}}] not ]}])."""
    marker = snippet.find('"questions"')
    if marker < 0:
        return None
    bracket = snippet.find("[", marker)
    if bracket < 0:
        return None
    decoder = json.JSONDecoder()
    questions: list[dict[str, Any]] = []
    index = bracket + 1
    while index < len(snippet):
        while index < len(snippet) and snippet[index] in " \n\r\t,]}":
            index += 1
        if index >= len(snippet):
            break
        if snippet[index] != "{":
            index += 1
            continue
        parsed: dict[str, Any] | None = None
        for candidate in (
            snippet[index:],
            _escape_interior_quotes(snippet[index:]),
            _strip_trailing_commas(_escape_interior_quotes(snippet[index:])),
        ):
            try:
                obj, _ = decoder.raw_decode(candidate)
            except json.JSONDecodeError:
                continue
            if isinstance(obj, dict):
                parsed = obj
                break
        span = _object_span(snippet, index)
        if parsed is None or span == 0:
            index += 1
            continue
        if isinstance(parsed.get("text"), str) and isinstance(parsed.get("options"), list):
            questions.append(parsed)
        index += span
    compact = "".join(snippet.split())
    return {
        "exhausted": '"exhausted":true' in compact,
        "cards": [],
        "questions": questions,
    }


def _load_json_object(raw: str, *, interpretation: bool = False) -> dict[str, Any]:
    text = _unwrap_fences(raw).replace("\u201c", '"').replace("\u201d", '"')
    start = text.find("{")
    if start < 0:
        raise TrailerParseError("invalid json trailer")
    snippet = text[start:]
    decoder = json.JSONDecoder()
    candidates = [
        snippet,
        _fix_questions_wrapper(snippet),
        _strip_trailing_commas(snippet),
        _escape_interior_quotes(snippet),
        _strip_trailing_commas(_escape_interior_quotes(snippet)),
        _fix_questions_wrapper(_escape_interior_quotes(snippet)),
    ]
    last_error: json.JSONDecodeError | None = None
    for candidate in candidates:
        try:
            payload, consumed = decoder.raw_decode(candidate)
        except json.JSONDecodeError as exc:
            last_error = exc
            continue
        if not isinstance(payload, dict):
            raise TrailerParseError("trailer must be a JSON object")
        rest = candidate[consumed:].lstrip()
        if interpretation and rest.startswith((",", "{")):
            continue
        return payload
    if interpretation:
        salvaged = _salvage_object(snippet)
        if salvaged is not None and (salvaged["questions"] or salvaged["exhausted"]):
            return salvaged
    detail = last_error.msg if last_error is not None else "invalid json trailer"
    raise TrailerParseError(f"invalid json trailer: {detail}")


def parse_trailer_payload(raw: str, *, interpretation: bool = False) -> dict[str, Any]:
    payload = _load_json_object(raw, interpretation=interpretation)

    exhausted = payload.get("exhausted", False)
    if not isinstance(exhausted, bool):
        raise TrailerParseError("exhausted must be a boolean")

    cards_raw = payload.get("cards", [])
    if cards_raw is None:
        cards_raw = []
    if not isinstance(cards_raw, list):
        raise TrailerParseError("cards must be a list")

    cards: list[tuple[CardKind, str]] = []
    counts: dict[CardKind, int] = {kind: 0 for kind in _SINGULAR}
    for item in cards_raw:
        if not isinstance(item, dict):
            raise TrailerParseError("each card must be an object")
        kind_value = item.get("kind")
        text = item.get("text")
        if not isinstance(kind_value, str) or not isinstance(text, str):
            raise TrailerParseError("card kind and text must be strings")
        try:
            kind = CardKind(kind_value)
        except ValueError as exc:
            raise TrailerParseError("unknown card kind") from exc
        if kind not in _ALLOWED_KINDS:
            raise TrailerParseError("unknown card kind")
        if not text.strip():
            raise TrailerParseError("card text must be non-empty")
        if kind in _SINGULAR:
            counts[kind] += 1
            if counts[kind] > 1:
                raise TrailerParseError(f"duplicate {kind.value} card")
        cards.append((kind, text.strip()))

    preamble = payload.get("preamble")
    if preamble is not None and not isinstance(preamble, str):
        raise TrailerParseError("preamble must be a string")

    questions: list[dict[str, Any]] = []
    frame = parse_frame(None)
    if interpretation:
        if cards:
            raise TrailerParseError("interpretation trailer cards must be empty")
        try:
            questions = parse_questions(payload.get("questions"), exhausted=exhausted)
            frame = parse_frame(payload.get("frame"))
        except TurnListError as exc:
            raise TrailerParseError(str(exc)) from exc

    return {
        "exhausted": exhausted,
        "cards": cards,
        "questions": questions,
        "preamble": preamble.strip() if isinstance(preamble, str) else None,
        "frame": frame,
    }
