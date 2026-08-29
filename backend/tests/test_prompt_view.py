"""Prompt View slices of Context Projection (ADR 0035)."""

import pytest

from app.modules.loop.catalog import WorkflowNode
from app.modules.loop.prompt_view import prompt_view


def _fat_projection(*, with_plan: bool = False) -> dict:
    projection = {
        "node": WorkflowNode.CLAIMS.value,
        "projected": {},
        "upstream": {
            WorkflowNode.IDEA_INTERPRETATION.value: {
                "card_snapshot": [],
                "narrative": {
                    "turns": [
                        {
                            "role": "account",
                            "text": "long grilling transcript that must not appear",
                        }
                    ],
                    "frame": {
                        "intent": "i",
                        "problem": "p",
                        "research_question": "rq",
                    },
                    "questions": [{"text": "q?", "options": ["a", "b"]}],
                },
                "projected": {},
            },
            WorkflowNode.IDEA_DECOMPOSITION.value: {
                "card_snapshot": [
                    {
                        "id": "card-1",
                        "kind": "problem",
                        "body": {"text": "Problem text"},
                    },
                    {
                        "id": "card-2",
                        "kind": "research_question",
                        "body": {"text": "RQ text"},
                    },
                    {
                        "id": "card-3",
                        "kind": "constraint",
                        "body": {"text": "Constraint text"},
                    },
                ],
                "narrative": {"restatement": "ignored for Spec Prompt View cards"},
                "projected": {},
            },
            WorkflowNode.RELATED_WORK.value: {
                "card_snapshot": [],
                "narrative": {"matrix": "noise"},
                "projected": {
                    "citations": [
                        {
                            "id": "cite-1",
                            "title": "Paper",
                            "abstract": "Very long abstract " * 40,
                            "metadata": {"provider_ids": {"x": "y"}},
                            "text_object_key": "s3://blob",
                            "text_checksum": "abc",
                        }
                    ],
                    "related_work": [
                        {
                            "what_was_done": "x",
                            "supporting_passage": "y",
                        }
                    ],
                },
            },
            WorkflowNode.GAP.value: {
                "card_snapshot": [
                    {
                        "id": "gap-1",
                        "kind": "gap",
                        "body": {"statement": "Confirmed gap statement"},
                    }
                ],
                "narrative": {"candidate": {"statement": "Confirmed gap statement"}},
                "projected": {},
            },
            WorkflowNode.CONTRIBUTION.value: {
                "card_snapshot": [
                    {
                        "id": "contrib-1",
                        "kind": "contribution",
                        "body": {"text": "Primary contribution"},
                    }
                ],
                "narrative": {"directions": []},
                "projected": {},
            },
        },
        "working_draft": {
            "node": WorkflowNode.CLAIMS.value,
            "narrative": {"cards": []},
            "card_snapshot": [],
        },
    }
    if with_plan:
        projection["upstream"][WorkflowNode.EXPERIMENT_PLAN.value] = {
            "card_snapshot": [],
            "narrative": {
                "plan": {
                    "experiments": [
                        {"claim": "c", "action": "a", "objective": "o", "significance": "s"}
                    ]
                }
            },
            "projected": {},
        }
    return projection


def test_prompt_view_keeps_cards_and_gap_drops_grilling_and_citations() -> None:
    view = prompt_view(WorkflowNode.CLAIMS, _fat_projection())
    assert view["node"] == "claims"
    assert view["gap_statement"] == "Confirmed gap statement"
    kinds = {card["kind"] for card in view["cards"]}
    assert kinds == {"problem", "research_question", "constraint", "gap", "contribution"}
    assert all("id" not in card for card in view["cards"])
    blob = str(view)
    assert "long grilling transcript" not in blob
    assert "Very long abstract" not in blob
    assert "text_object_key" not in blob
    assert "idea_interpretation" not in blob
    assert "related_work" not in blob


def test_feasibility_prompt_view_adds_experiment_plan() -> None:
    view = prompt_view(
        WorkflowNode.FEASIBILITY, _fat_projection(with_plan=True)
    )
    assert view["experiment_plan"]["experiments"][0]["claim"] == "c"


def test_prompt_view_rejects_undefined_nodes() -> None:
    with pytest.raises(ValueError, match="not defined"):
        prompt_view(WorkflowNode.GAP, _fat_projection())
