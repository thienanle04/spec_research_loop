"""Interpretation turn list helpers (ADR 0025)."""

import pytest

from app.core.errors import OperationalErrorException
from app.modules.loop.interpretation_turns import (
    apply_account_reply_patch,
    append_idea_cluster,
    clusters_answered,
    normalize_answers,
    unanswered_cluster,
)


def test_unanswered_cluster_is_the_latest_model_questions() -> None:
    narrative = append_idea_cluster(
        {},
        idea="GPU kernel latency",
        preamble="Need the budget.",
        questions=[{"text": "Training or inference?", "options": ["Training", "Inference"]}],
        exhausted=False,
    )
    assert unanswered_cluster(narrative["turns"]) == [
        {"text": "Training or inference?", "options": ["Training", "Inference"]}
    ]
    assert clusters_answered(narrative["turns"]) is False


def test_normalize_answers_accepts_option_xor_other() -> None:
    questions = [
        {"text": "Q1", "options": ["A", "B"]},
        {"text": "Q2", "options": ["C", "D"]},
    ]
    assert normalize_answers(questions, [{"option": "A"}, {"other": "  8GB  "}]) == [
        {"option": "A"},
        {"other": "8GB"},
    ]


def test_normalize_answers_rejects_unknown_option() -> None:
    with pytest.raises(OperationalErrorException) as exc:
        normalize_answers(
            [{"text": "Q1", "options": ["A", "B"]}],
            [{"option": "Nope"}],
        )
    assert exc.value.error.code == "invalid_generate_answers"


def test_patch_earlier_reply_truncates_later_turns() -> None:
    current = {
        "exhausted": True,
        "turns": [
            {"role": "account", "kind": "idea", "text": "old idea"},
            {
                "role": "model",
                "preamble": "p1",
                "questions": [{"text": "Q1", "options": ["A", "B"]}],
            },
            {"role": "account", "kind": "answers", "answers": [{"option": "A"}]},
            {"role": "model", "preamble": "p2", "questions": []},
        ],
    }
    incoming = {
        "turns": [
            {"role": "account", "kind": "idea", "text": "new idea"},
            {
                "role": "model",
                "preamble": "p1",
                "questions": [{"text": "Q1", "options": ["A", "B"]}],
            },
            {"role": "account", "kind": "answers", "answers": [{"option": "A"}]},
            {"role": "model", "preamble": "p2", "questions": []},
        ]
    }
    patched = apply_account_reply_patch(current, incoming)
    assert patched["exhausted"] is False
    assert patched["turns"] == [{"role": "account", "kind": "idea", "text": "new idea"}]


def test_patch_rejects_question_edits() -> None:
    current = {
        "turns": [
            {"role": "account", "kind": "idea", "text": "idea"},
            {
                "role": "model",
                "preamble": "p",
                "questions": [{"text": "Q1", "options": ["A", "B"]}],
            },
        ]
    }
    incoming = {
        "turns": [
            {"role": "account", "kind": "idea", "text": "idea"},
            {
                "role": "model",
                "preamble": "p",
                "questions": [{"text": "changed", "options": ["A", "B"]}],
            },
        ]
    }
    with pytest.raises(OperationalErrorException) as exc:
        apply_account_reply_patch(current, incoming)
    assert exc.value.error.code == "invalid_working_draft_narrative"
