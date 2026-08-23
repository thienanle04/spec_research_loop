"""Trailer splitter and payload parse."""

import pytest

from app.modules.idea.trailer import TrailerParseError, TrailerSplitter, parse_trailer_payload
from app.modules.loop.catalog import CardKind


def test_splitter_holds_back_trailer_and_split_delimiter() -> None:
    splitter = TrailerSplitter()
    visible = splitter.feed("What is X?\n--")
    assert visible == "What is X?\n"
    assert splitter.feed("-json") == ""
    assert splitter.feed("---\n{\"exhausted\": true, \"cards\": []}") == ""
    prose, payload = splitter.finish()
    assert prose == "What is X?"
    assert payload["exhausted"] is True
    assert payload["cards"] == []


def test_parse_rejects_duplicate_problem() -> None:
    raw = """
    {"exhausted": false, "cards": [
      {"kind": "problem", "text": "A"},
      {"kind": "problem", "text": "B"}
    ]}
    """
    with pytest.raises(TrailerParseError, match="duplicate"):
        parse_trailer_payload(raw)


def test_parse_rejects_unknown_kind() -> None:
    with pytest.raises(TrailerParseError, match="unknown card kind"):
        parse_trailer_payload('{"exhausted": false, "cards": [{"kind": "gap", "text": "no"}]}')


def test_parse_accepts_constraints() -> None:
    payload = parse_trailer_payload(
        '{"exhausted": false, "cards": ['
        '{"kind": "problem", "text": "P"},'
        '{"kind": "constraint", "text": "C1"},'
        '{"kind": "constraint", "text": "C2"}'
        "]}"
    )
    assert [kind for kind, _ in payload["cards"]] == [
        CardKind.PROBLEM,
        CardKind.CONSTRAINT,
        CardKind.CONSTRAINT,
    ]


def test_parse_interpretation_rejects_single_option() -> None:
    with pytest.raises(TrailerParseError, match="at least two"):
        parse_trailer_payload(
            '{"exhausted": false, "cards": [], "questions": [{"text": "Q", "options": ["A"]}]}',
            interpretation=True,
        )


def test_parse_interpretation_rejects_questions_when_exhausted() -> None:
    with pytest.raises(TrailerParseError, match="exhausted"):
        parse_trailer_payload(
            '{"exhausted": true, "cards": [], "questions": ['
            '{"text": "Q", "options": ["A", "B"]}]}',
            interpretation=True,
        )


def test_parse_accepts_fence_trailing_prose_and_trailing_comma() -> None:
    raw = """
    ```json
    {"exhausted": false, "cards": [], "questions": [
      {"text": "Clock-in sớm hay muộn?", "options": ["Sớm", "Muộn",]}
    ]}
    ```
    Extra model commentary after the object.
    """
    payload = parse_trailer_payload(raw, interpretation=True)
    assert payload["exhausted"] is False
    assert payload["questions"] == [
        {"text": "Clock-in sớm hay muộn?", "options": ["Sớm", "Muộn"]}
    ]


def test_parse_accepts_object_with_leading_junk() -> None:
    payload = parse_trailer_payload(
        'Here you go:\n{"exhausted": true, "cards": [], "questions": []}\n',
        interpretation=True,
    )
    assert payload["exhausted"] is True
    assert payload["questions"] == []


def test_parse_escapes_quotes_inside_question_text() -> None:
    payload = parse_trailer_payload(
        '{"exhausted": false, "cards": [], "questions": ['
        '{"text": "Cho phép "ghi đè" thủ công?", "options": ["Trust but Verify", "Không"]}'
        "]}",
        interpretation=True,
    )
    assert payload["questions"][0]["text"] == 'Cho phép "ghi đè" thủ công?'
    assert payload["questions"][0]["options"] == ["Trust but Verify", "Không"]


def test_parse_salvages_extra_brace_before_questions_close() -> None:
    raw = (
        '{"exhausted": false, "cards": [], "questions": ['
        '{"text": "Q1", "options": ["A", "B"]},'
        '{"text": "Q2", "options": ["C", "D"]}}]'
    )
    payload = parse_trailer_payload(raw, interpretation=True)
    assert payload["exhausted"] is False
    assert [item["text"] for item in payload["questions"]] == ["Q1", "Q2"]


def test_parse_salvages_premature_questions_array_close() -> None:
    raw = (
        '{"exhausted": false, "cards": [], "questions": ['
        '{"text": "Q1", "options": ["A", "B"]}], '
        '{"text": "Q2", "options": ["C", "D"]}, '
        '{"text": "Q3", "options": ["E", "F"]}}'
    )
    payload = parse_trailer_payload(raw, interpretation=True)
    assert [item["text"] for item in payload["questions"]] == ["Q1", "Q2", "Q3"]


def test_parse_salvages_logged_qwen_wrapper() -> None:
    raw = (
        '{"exhausted": false, "cards": [], "questions": ['
        '{"text": "Override?", "options": ["A", "B"]},'
        '{"text": "Store?", "options": ["C", "D"]},'
        '{"text": "KPI?", "options": ["E", "F"]},'
        '{"text": "Cadence?", "options": ["Hàng ngày", "Hàng tuần", "Hàng tháng: rủi ro cao."]}}]'
    )
    payload = parse_trailer_payload(raw, interpretation=True)
    assert [item["text"] for item in payload["questions"]] == [
        "Override?",
        "Store?",
        "KPI?",
        "Cadence?",
    ]


def test_invalid_json_includes_decode_hint() -> None:
    with pytest.raises(TrailerParseError, match="invalid json trailer"):
        parse_trailer_payload("{not json", interpretation=True)


def test_finish_without_delimiter_fails() -> None:
    splitter = TrailerSplitter()
    splitter.feed("only prose")
    with pytest.raises(TrailerParseError, match="missing"):
        splitter.finish()
