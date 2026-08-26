"""Interpretation turn list helpers (ADR 0025)."""

import pytest

from app.core.errors import OperationalErrorException
from app.modules.loop.interpretation_turns import (
    apply_account_reply_patch,
    append_idea_cluster,
    clusters_answered,
    interpretation_confirmable,
    normalize_answers,
    unanswered_cluster,
)

FRAME = {
    "intent": "You want to cut GPU kernel DRAM traffic by tiling.",
    "problem": "GPU kernel latency is memory bound",
    "research_question": "Can tiling cut DRAM traffic?",
}


def test_unanswered_cluster_is_the_latest_model_questions() -> None:
    narrative = append_idea_cluster(
        {},
        idea="GPU kernel latency",
        preamble="Need the budget.",
        questions=[{"text": "Training or inference?", "options": ["Training", "Inference"]}],
        exhausted=False,
        frame=FRAME,
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
    assert patched["frame"] == {
        "intent": "",
        "problem": "",
        "research_question": "",
    }


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


def test_note_closes_a_cluster_for_confirm() -> None:
    turns = [
        {"role": "account", "kind": "idea", "text": "idea"},
        {
            "role": "model",
            "preamble": "p1",
            "questions": [{"text": "Q1", "options": ["A", "B"]}],
        },
        {"role": "account", "kind": "note", "text": "Skip this. Focus on inference."},
        {"role": "model", "preamble": "p2", "questions": []},
    ]
    assert clusters_answered(turns) is True
    assert (
        interpretation_confirmable({"turns": turns, "frame": FRAME}) is True
    )


def test_confirmable_requires_nonblank_frame() -> None:
    turns = [
        {"role": "account", "kind": "idea", "text": "idea"},
        {"role": "model", "preamble": "p", "questions": []},
    ]
    assert clusters_answered(turns) is True
    assert interpretation_confirmable({"turns": turns, "frame": FRAME}) is True
    assert interpretation_confirmable({"turns": turns}) is False
    assert interpretation_confirmable({"turns": turns, "frame": {**FRAME, "intent": ""}}) is False


def test_confirmable_when_frame_complete_even_with_open_cluster() -> None:
    turns = [
        {"role": "account", "kind": "idea", "text": "idea"},
        {
            "role": "model",
            "preamble": "p1",
            "questions": [{"text": "Q1", "options": ["A", "B"]}],
        },
    ]
    assert clusters_answered(turns) is False
    assert interpretation_confirmable({"turns": turns, "frame": FRAME}) is True


def test_two_open_clusters_without_note_are_not_answered() -> None:
    turns = [
        {"role": "account", "kind": "idea", "text": "idea"},
        {
            "role": "model",
            "preamble": "p1",
            "questions": [{"text": "Q1", "options": ["A", "B"]}],
        },
        {
            "role": "model",
            "preamble": "p2",
            "questions": [{"text": "Q2", "options": ["C", "D"]}],
        },
    ]
    assert clusters_answered(turns) is False
