"""Parse a visible-prose + ---json--- trailer completion (ADR 0023)."""

from __future__ import annotations

import json
import re
from typing import Any

from app.modules.loop.catalog import CardKind
from app.modules.loop.interpretation_turns import TurnListError, parse_frame, parse_questions

DELIMITER = "---json---"
# Own-line marker only. Mid-prose "---json---" is Account/model text, not the trailer.
_DELIMITER_LINE = re.compile(
    r"^[ \t]*---[ \t]*json(?:[ \t]*---)?[ \t]*(?:\r?\n|$)",
    re.IGNORECASE | re.MULTILINE,
)
_DELIMITER_PREFIX_CHARS = re.compile(r"^[ \t\-jsoneJSON]*$")

_ALLOWED_KINDS = {
    CardKind.PROBLEM,
    CardKind.RESEARCH_QUESTION,
    CardKind.CONSTRAINT,
    CardKind.OPEN_QUESTION,
}
_SINGULAR = {CardKind.PROBLEM, CardKind.RESEARCH_QUESTION}


def _could_become_delimiter_line(line: str) -> bool:
    if not line or not _DELIMITER_PREFIX_CHARS.fullmatch(line):
        return False
    compact = re.sub(r"\s+", "", line).casefold()
    return "---json---".startswith(compact) or compact == "---json"


def _safe_emit_end(buf: str) -> int:
    last_nl = buf.rfind("\n")
    line = buf[last_nl + 1 :]
    if _could_become_delimiter_line(line):
        return last_nl + 1
    return len(buf)


class TrailerParseError(Exception):
    """The completion had no usable JSON trailer."""


class TrailerSplitter:
    def __init__(self) -> None:
        self._buf = ""
        self._emitted = 0
        self._found = False

    def feed(self, chunk: str) -> str:
        self._buf += chunk
        if self._found:
            return ""
        match = _DELIMITER_LINE.search(self._buf)
        if match is None:
            safe_end = _safe_emit_end(self._buf)
            if safe_end > self._emitted:
                out = self._buf[self._emitted : safe_end]
                self._emitted = safe_end
                return out
            return ""
        self._found = True
        prose_out = self._buf[self._emitted : match.start()]
        self._emitted = match.start()
        return prose_out

    def finish(self, *, interpretation: bool = False) -> tuple[str, dict[str, Any]]:
        return _split_completion(self._buf, interpretation=interpretation)


def _split_completion(buf: str, *, interpretation: bool) -> tuple[str, dict[str, Any]]:
    last_error: TrailerParseError | None = None
    for match in reversed(list(_DELIMITER_LINE.finditer(buf))):
        prose = buf[: match.start()].rstrip()
        raw = buf[match.end() :]
        try:
            return prose, parse_trailer_payload(raw, interpretation=interpretation)
        except TrailerParseError as exc:
            last_error = exc
    try:
        parsed = parse_trailer_payload(buf, interpretation=interpretation)
    except TrailerParseError as exc:
        if "{" not in buf:
            raise TrailerParseError("missing json trailer") from (last_error or exc)
        raise
    return _prose_before_object(buf), parsed


def _prose_before_object(buf: str) -> str:
    start = buf.find("{")
    if start < 0:
        return buf.rstrip()
    prefix = buf[:start]
    prefix = _DELIMITER_LINE.sub("", prefix).rstrip()
    lowered = prefix.lower()
    for marker in ("```json", "```"):
        if lowered.endswith(marker):
            prefix = prefix[: -len(marker)].rstrip()
            break
    return prefix


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


def _looks_like_trailer(payload: dict[str, Any]) -> bool:
    return any(key in payload for key in ("exhausted", "questions", "cards", "frame"))


def _brace_starts(text: str) -> list[int]:
    starts: list[int] = []
    in_string = False
    escape = False
    for index, char in enumerate(text):
        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            starts.append(index)
    return starts


def _decode_trailer_dict(snippet: str) -> tuple[dict[str, Any] | None, json.JSONDecodeError | None]:
    decoder = json.JSONDecoder()
    last_error: json.JSONDecodeError | None = None
    candidates = [
        snippet,
        _fix_questions_wrapper(snippet),
        _strip_trailing_commas(snippet),
        _escape_interior_quotes(snippet),
        _strip_trailing_commas(_escape_interior_quotes(snippet)),
        _fix_questions_wrapper(_escape_interior_quotes(snippet)),
    ]
    for candidate in candidates:
        try:
            payload, _consumed = decoder.raw_decode(candidate)
        except json.JSONDecodeError as exc:
            last_error = exc
            continue
        if isinstance(payload, dict) and _looks_like_trailer(payload):
            return payload, last_error
    return None, last_error


def _iter_trailer_dicts(raw: str, *, interpretation: bool) -> list[dict[str, Any]]:
    text = _unwrap_fences(raw).replace("\u201c", '"').replace("\u201d", '"')
    found: list[dict[str, Any]] = []
    seen: set[int] = set()
    last_error: json.JSONDecodeError | None = None
    for start in reversed(_brace_starts(text)):
        payload, decode_error = _decode_trailer_dict(text[start:])
        if decode_error is not None:
            last_error = decode_error
        if payload is None:
            continue
        marker = id(payload)
        if marker in seen:
            continue
        seen.add(marker)
        found.append(payload)
    if interpretation:
        salvaged = _salvage_object(text[text.find("{") :]) if "{" in text else None
        if salvaged is not None and (salvaged["questions"] or salvaged["exhausted"]):
            found.append(salvaged)
    if not found and last_error is not None:
        raise TrailerParseError(f"invalid json trailer: {last_error.msg}")
    if not found:
        raise TrailerParseError("invalid json trailer")
    return found


def parse_trailer_payload(raw: str, *, interpretation: bool = False) -> dict[str, Any]:
    last_error: TrailerParseError | None = None
    for payload in _iter_trailer_dicts(raw, interpretation=interpretation):
        try:
            return _validated_payload(payload, interpretation=interpretation)
        except TrailerParseError as exc:
            last_error = exc
    raise last_error or TrailerParseError("invalid json trailer")


def _validated_payload(payload: dict[str, Any], *, interpretation: bool) -> dict[str, Any]:
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
