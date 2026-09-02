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
                            "citation_id": "cite-1",
                            "what_was_done": "x",
                            "limitation": "Does not localize unsupported claims.",
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


def test_contribution_prompt_view_adds_compact_related_work_studies() -> None:
    view = prompt_view(WorkflowNode.CONTRIBUTION, _fat_projection())
    studies = view["related_work"]["studies"]
    assert studies[0]["source"]["title"] == "Paper"
    assert studies[0]["limitation"] == "Does not localize unsupported claims."
    blob = str(view)
    assert "Very long abstract" not in blob
    assert "text_object_key" not in blob
    assert "long grilling transcript" not in blob


def test_feasibility_prompt_view_adds_experiment_plan() -> None:
    view = prompt_view(
        WorkflowNode.FEASIBILITY, _fat_projection(with_plan=True)
    )
    assert view["experiment_plan"]["experiments"][0]["claim"] == "c"


def test_gap_judge_prompt_view_includes_spec_slices_and_drops_peer_judge_runs() -> None:
    projection = _fat_projection(with_plan=True)
    projection["valid_spec_version"] = {
        "id": "spec-1",
        "document": {
            "nodes": {
                WorkflowNode.GAP.value: {
                    "card_snapshot": [
                        {
                            "id": "gap-1",
                            "kind": "gap",
                            "body": {"statement": "Confirmed gap statement"},
                        }
                    ],
                    "narrative": {},
                }
            }
        },
    }
    projection["upstream"][WorkflowNode.CONTRIBUTION_JUDGE.value] = {
        "card_snapshot": [],
        "narrative": {"issues": [{"finding_kind": "contribution_not_novel"}]},
        "projected": {
            "issues": [
                {
                    "finding_kind": "contribution_not_novel",
                    "severity": "MAJOR",
                    "reason": "peer judge must not appear",
                }
            ]
        },
    }
    view = prompt_view(WorkflowNode.GAP_JUDGE, projection)
    assert view["node"] == "gap_judge"
    assert view["valid_spec_version"]["id"] == "spec-1"
    assert view["gap_statement"] == "Confirmed gap statement"
    assert view["related_work"][0]["supporting_passage"] == "y"
    assert view["experiment_plan"]["experiments"][0]["claim"] == "c"
    kinds = {card["kind"] for card in view["cards"]}
    assert "gap" in kinds
    assert any(card.get("id") == "gap-1" for card in view["cards"])
    blob = str(view)
    assert "peer judge must not appear" not in blob
    assert "contribution_not_novel" not in blob
    assert "contribution_judge" not in blob
    assert "long grilling transcript" not in blob


def test_gap_judge_prompt_view_omits_sibling_judge_working_draft() -> None:
    projection = _fat_projection(with_plan=True)
    projection["working_draft"] = {
        "node": WorkflowNode.CONTRIBUTION_JUDGE.value,
        "narrative": {
            "issues": [
                {
                    "finding_kind": "contribution_not_novel",
                    "reason": "sibling working draft must not leak",
                }
            ]
        },
        "card_snapshot": [],
    }
    view = prompt_view(WorkflowNode.GAP_JUDGE, projection)
    blob = str(view)
    assert "sibling working draft must not leak" not in blob
    assert "contribution_not_novel" not in blob
    assert view["working_draft"] == {"narrative": {}, "cards": []}


def test_contribution_and_experiment_judge_prompt_views_drop_peer_judge_runs() -> None:
    projection = _fat_projection(with_plan=True)
    projection["valid_spec_version"] = {
        "id": "spec-1",
        "document": {"nodes": {}},
    }
    projection["upstream"][WorkflowNode.GAP_JUDGE.value] = {
        "card_snapshot": [],
        "narrative": {},
        "projected": {
            "issues": [
                {
                    "finding_kind": "gap_unsupported_by_sources",
                    "severity": "CRITICAL",
                    "reason": "peer judge must not appear",
                }
            ]
        },
    }
    projection["upstream"][WorkflowNode.EVIDENCE_JUDGE.value] = {
        "card_snapshot": [],
        "narrative": {},
        "projected": {
            "issues": [
                {
                    "finding_kind": "unsupported_citation",
                    "severity": "CRITICAL",
                    "reason": "evidence peer must not appear",
                }
            ]
        },
    }
    for node in (WorkflowNode.CONTRIBUTION_JUDGE, WorkflowNode.EXPERIMENT_JUDGE):
        view = prompt_view(node, projection)
        assert view["node"] == node.value
        assert view["valid_spec_version"]["id"] == "spec-1"
        blob = str(view)
        assert "peer judge must not appear" not in blob
        assert "evidence peer must not appear" not in blob
        assert "gap_unsupported_by_sources" not in blob
        assert "unsupported_citation" not in blob
        assert "gap_judge" not in blob
        assert "evidence_judge" not in blob


def test_conference_judge_prompt_view_includes_spec_slices_and_drops_peer_judge_runs() -> None:
    projection = _fat_projection(with_plan=True)
    projection["valid_spec_version"] = {
        "id": "spec-1",
        "document": {
            "nodes": {
                WorkflowNode.GAP.value: {
                    "card_snapshot": [
                        {
                            "id": "gap-1",
                            "kind": "gap",
                            "body": {"statement": "Confirmed gap statement"},
                        }
                    ],
                    "narrative": {},
                },
                WorkflowNode.CONTRIBUTION.value: {
                    "card_snapshot": [
                        {
                            "id": "contrib-1",
                            "kind": "contribution",
                            "body": {"text": "Primary contribution"},
                        }
                    ],
                    "narrative": {},
                },
                WorkflowNode.CLAIMS.value: {
                    "card_snapshot": [
                        {
                            "id": "claim-1",
                            "kind": "claim",
                            "body": {"statement": "The method improves nitrogen fixation."},
                        }
                    ],
                    "narrative": {},
                },
                WorkflowNode.EVIDENCE.value: {
                    "card_snapshot": [
                        {
                            "id": "ev-1",
                            "kind": "evidence",
                            "body": {"text": "Cited passage supports the claim."},
                        }
                    ],
                    "narrative": {},
                },
                WorkflowNode.EXPERIMENT_PLAN.value: {
                    "card_snapshot": [],
                    "narrative": {
                        "plan": {
                            "experiments": [
                                {
                                    "claim": "c",
                                    "action": "a",
                                    "objective": "o",
                                    "significance": "s",
                                }
                            ]
                        }
                    },
                },
            }
        },
    }
    projection["upstream"][WorkflowNode.CLAIMS.value] = {
        "card_snapshot": [
            {
                "id": "claim-1",
                "kind": "claim",
                "body": {"statement": "The method improves nitrogen fixation."},
            }
        ],
        "narrative": {},
        "projected": {},
    }
    projection["upstream"][WorkflowNode.EVIDENCE.value] = {
        "card_snapshot": [
            {
                "id": "ev-1",
                "kind": "evidence",
                "body": {"text": "Cited passage supports the claim."},
            }
        ],
        "narrative": {},
        "projected": {},
    }
    projection["upstream"][WorkflowNode.GAP_JUDGE.value] = {
        "card_snapshot": [],
        "narrative": {},
        "projected": {
            "issues": [
                {
                    "finding_kind": "gap_unsupported_by_sources",
                    "severity": "CRITICAL",
                    "reason": "peer judge must not appear",
                }
            ]
        },
    }
    projection["upstream"][WorkflowNode.CONTRIBUTION_JUDGE.value] = {
        "card_snapshot": [],
        "narrative": {},
        "projected": {
            "issues": [
                {
                    "finding_kind": "contribution_not_novel",
                    "severity": "MAJOR",
                    "reason": "contribution peer must not appear",
                }
            ]
        },
    }
    view = prompt_view(WorkflowNode.CONFERENCE_JUDGE, projection)
    assert view["node"] == "conference_judge"
    assert view["valid_spec_version"]["id"] == "spec-1"
    assert view["gap_statement"] == "Confirmed gap statement"
    assert view["experiment_plan"]["experiments"][0]["claim"] == "c"
    kinds = {card["kind"] for card in view["cards"]}
    assert kinds >= {"gap", "contribution", "claim", "evidence"}
    blob = str(view)
    assert "peer judge must not appear" not in blob
    assert "contribution peer must not appear" not in blob
    assert "gap_unsupported_by_sources" not in blob
    assert "contribution_not_novel" not in blob
    assert "gap_judge" not in blob
    assert "contribution_judge" not in blob
    assert "evidence_judge" not in blob
    assert "experiment_judge" not in blob


def test_evidence_judge_prompt_view_includes_claim_citation_passage_triples() -> None:
    projection = _fat_projection()
    projection["upstream"][WorkflowNode.CLAIMS.value] = {
        "card_snapshot": [
            {
                "id": "claim-1",
                "kind": "claim",
                "body": {
                    "statement": "Brass instruments improve soil nitrogen fixation.",
                    "supporting_citation_keys": ["large-language-models-as-optimizers-2023"],
                },
            }
        ],
        "narrative": {},
        "projected": {},
    }
    projection["upstream"][WorkflowNode.RELATED_WORK.value]["projected"]["citations"] = [
        {
            "id": "cite-1",
            "citation_key": "large-language-models-as-optimizers-2023",
        }
    ]
    projection["upstream"][WorkflowNode.RELATED_WORK.value]["projected"]["related_work"] = [
        {
            "citation_id": "cite-1",
            "citation_key": "large-language-models-as-optimizers-2023",
            "supporting_passage": (
                "An optimizer model proposes prompts and receives task scores as "
                "feedback over multiple optimization rounds."
            ),
        }
    ]
    view = prompt_view(WorkflowNode.EVIDENCE_JUDGE, projection)
    assert view["node"] == "evidence_judge"
    assert view["claim_citation_passages"] == [
        {
            "claim_id": "claim-1",
            "claim": "Brass instruments improve soil nitrogen fixation.",
            "citation_key": "large-language-models-as-optimizers-2023",
            "passage": (
                "An optimizer model proposes prompts and receives task scores as "
                "feedback over multiple optimization rounds."
            ),
        }
    ]


def test_aggregator_prompt_view_is_the_five_current_judge_runs_only() -> None:
    projection = _fat_projection(with_plan=True)
    projection["valid_spec_version"] = {
        "id": "spec-1",
        "document": {"nodes": {}},
    }
    projection["upstream"][WorkflowNode.GAP_JUDGE.value] = {
        "card_snapshot": [],
        "narrative": {},
        "projected": {
            "issues": [
                {
                    "id": "gap-issue",
                    "finding_kind": "gap_unsupported_by_sources",
                    "severity": "CRITICAL",
                    "reason": "No cited passage supports the gap statement.",
                    "suggestion": "Cite a supporting passage.",
                    "target_card_id": None,
                }
            ]
        },
    }
    projection["upstream"][WorkflowNode.CONTRIBUTION_JUDGE.value] = {
        "card_snapshot": [],
        "narrative": {},
        "projected": {"issues": []},
    }
    projection["upstream"][WorkflowNode.EVIDENCE_JUDGE.value] = {
        "card_snapshot": [],
        "narrative": {},
        "projected": {
            "issues": [
                {
                    "id": "evidence-issue",
                    "finding_kind": "unsupported_citation",
                    "severity": "CRITICAL",
                    "reason": "The cited passage does not entail the claim.",
                    "suggestion": "Cite a passage that entails the claim.",
                    "target_card_id": None,
                }
            ]
        },
    }
    projection["upstream"][WorkflowNode.EXPERIMENT_JUDGE.value] = {
        "card_snapshot": [],
        "narrative": {},
        "projected": {"issues": []},
    }
    projection["upstream"][WorkflowNode.CONFERENCE_JUDGE.value] = {
        "card_snapshot": [],
        "narrative": {},
        "projected": {
            "issues": [],
            "scores": {
                "originality": 7,
                "significance": 8,
                "soundness": 6,
                "clarity": 7,
                "reproducibility": 5,
            },
        },
    }
    view = prompt_view(WorkflowNode.AGGREGATOR, projection)
    assert view == {
        "node": "aggregator",
        "judge_runs": [
            {
                "node": "gap_judge",
                "issues": projection["upstream"][WorkflowNode.GAP_JUDGE.value][
                    "projected"
                ]["issues"],
                "scores": None,
            },
            {
                "node": "contribution_judge",
                "issues": [],
                "scores": None,
            },
            {
                "node": "evidence_judge",
                "issues": projection["upstream"][WorkflowNode.EVIDENCE_JUDGE.value][
                    "projected"
                ]["issues"],
                "scores": None,
            },
            {
                "node": "experiment_judge",
                "issues": [],
                "scores": None,
            },
            {
                "node": "conference_judge",
                "issues": [],
                "scores": {
                    "originality": 7,
                    "significance": 8,
                    "soundness": 6,
                    "clarity": 7,
                    "reproducibility": 5,
                },
            },
        ],
    }
    blob = str(view)
    assert "Confirmed gap statement" not in blob
    assert "Primary contribution" not in blob
    assert "valid_spec_version" not in blob
    assert "related_work" not in blob
    assert "experiment_plan" not in blob


def test_prompt_view_rejects_undefined_nodes() -> None:
    with pytest.raises(ValueError, match="not defined"):
        prompt_view(WorkflowNode.GAP, _fat_projection())
