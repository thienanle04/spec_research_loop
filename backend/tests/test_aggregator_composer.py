from types import SimpleNamespace

from app.modules.judgement.composer import (
    apply_handling_option_phrasing,
    compose_from_view,
    filter_handling_options,
    needs_handling_option_phrasing,
    plant_handling_options,
)

CONFERENCE_SCORES = {
    "originality": 7,
    "significance": 8,
    "soundness": 6,
    "clarity": 7,
    "reproducibility": 5,
}


def _run(node: str, issues: list, scores: dict | None = None) -> dict:
    return {"node": node, "issues": issues, "scores": scores}


def test_composer_copies_critical_and_does_not_majority_vote() -> None:
    report = compose_from_view(
        {
            "judge_runs": [
                _run("gap_judge", []),
                _run("contribution_judge", []),
                _run(
                    "evidence_judge",
                    [
                        {
                            "finding_kind": "unsupported_citation",
                            "severity": "CRITICAL",
                            "reason": "The cited passage does not entail the claim.",
                            "suggestion": "Cite a passage that entails the claim.",
                            "grounds": {
                                "subject": "Brass instruments improve soil nitrogen.",
                                "excerpts": [
                                    {
                                        "citation_key": "large-language-models-as-optimizers-2023",
                                        "passage": "An optimizer model proposes prompts.",
                                    }
                                ],
                            },
                        }
                    ],
                ),
                _run("experiment_judge", []),
                _run("conference_judge", [], CONFERENCE_SCORES),
            ]
        }
    )
    assert report.readiness == "blocked"
    assert report.scores == CONFERENCE_SCORES
    assert [item.severity for item in report.issues] == ["CRITICAL"]
    assert report.issues[0].cluster == "disagreement"
    assert report.issues[0].source_node == "evidence_judge"
    assert report.issues[0].grounds["subject"] == (
        "Brass instruments improve soil nitrogen."
    )


def test_composer_lists_minor_without_handling_options() -> None:
    report = compose_from_view(
        {
            "judge_runs": [
                _run(
                    "gap_judge",
                    [
                        {
                            "finding_kind": "gap_untestable",
                            "severity": "MINOR",
                            "reason": "The gap is hard to test as stated.",
                            "suggestion": "Tighten the gap.",
                        }
                    ],
                ),
                _run("contribution_judge", []),
                _run("evidence_judge", []),
                _run("experiment_judge", []),
                _run("conference_judge", [], CONFERENCE_SCORES),
            ]
        }
    )
    assert report.readiness == "ready"
    assert report.issues[0].severity == "MINOR"
    drafts = [
        SimpleNamespace(
            finding_kind="gap_untestable",
            source_node="gap_judge",
            label="Tighten the gap",
            target_node="gap",
            prose="Make the gap testable.",
        ),
        SimpleNamespace(
            finding_kind="gap_untestable",
            source_node="gap_judge",
            label="Other",
            target_node="gap",
            prose="LLM must not invent Other.",
        ),
    ]
    assert filter_handling_options(drafts, report.issues) == []
    assert plant_handling_options(report.issues) == []
    assert needs_handling_option_phrasing(report.issues) is False


def test_plant_handling_options_covers_each_critical_issue_target() -> None:
    report = compose_from_view(
        {
            "judge_runs": [
                _run("gap_judge", []),
                _run("contribution_judge", []),
                _run(
                    "evidence_judge",
                    [
                        {
                            "finding_kind": "unsupported_citation",
                            "severity": "CRITICAL",
                            "reason": "No entailment.",
                            "suggestion": "Cite a passage.",
                        }
                    ],
                ),
                _run(
                    "experiment_judge",
                    [
                        {
                            "finding_kind": "claim_broader_than_experiment",
                            "severity": "MAJOR",
                            "reason": "Too broad.",
                            "suggestion": "Narrow the claim.",
                        }
                    ],
                ),
                _run("conference_judge", [], CONFERENCE_SCORES),
            ]
        }
    )
    planted = plant_handling_options(report.issues)
    assert [(item["finding_kind"], item["target_node"]) for item in planted] == [
        ("unsupported_citation", "claims"),
        ("claim_broader_than_experiment", "claims"),
        ("claim_broader_than_experiment", "experiment_plan"),
    ]
    assert all(item["label"] != "Other" for item in planted)
    assert "idea_decomposition" not in {item["target_node"] for item in planted}
    assert needs_handling_option_phrasing(report.issues) is True
    drafts = [
        SimpleNamespace(
            finding_kind="unsupported_citation",
            source_node="evidence_judge",
            label="Revise the claim",
            target_node="claims",
            prose="Cite a passage that entails the claim.",
        ),
        SimpleNamespace(
            finding_kind="unsupported_citation",
            source_node="evidence_judge",
            label="Other",
            target_node="claims",
            prose="Dropped.",
        ),
        SimpleNamespace(
            finding_kind="claim_broader_than_experiment",
            source_node="experiment_judge",
            label="Go grill",
            target_node="idea_decomposition",
            prose="Dropped.",
        ),
    ]
    phrased = apply_handling_option_phrasing(planted, drafts, report.issues)
    assert [item["label"] for item in phrased] == [
        "Revise the claim",
        "Revise claims and evidence",
        "Revise the experiment plan",
    ]
    assert phrased[0]["prose"] == "Cite a passage that entails the claim."


def test_plant_handling_options_overclaimed_targets_contribution_only() -> None:
    report = compose_from_view(
        {
            "judge_runs": [
                _run("gap_judge", []),
                _run(
                    "contribution_judge",
                    [
                        {
                            "finding_kind": "contribution_overclaimed",
                            "severity": "MAJOR",
                            "reason": "Contribution is broader than the gap.",
                            "suggestion": "Narrow the contribution.",
                        }
                    ],
                ),
                _run("evidence_judge", []),
                _run("experiment_judge", []),
                _run("conference_judge", [], CONFERENCE_SCORES),
            ]
        }
    )
    planted = plant_handling_options(report.issues)
    assert [(item["finding_kind"], item["target_node"]) for item in planted] == [
        ("contribution_overclaimed", "contribution"),
    ]


def test_filter_handling_options_drops_other_and_keeps_critical() -> None:
    report = compose_from_view(
        {
            "judge_runs": [
                _run("gap_judge", []),
                _run("contribution_judge", []),
                _run(
                    "evidence_judge",
                    [
                        {
                            "finding_kind": "unsupported_citation",
                            "severity": "CRITICAL",
                            "reason": "No entailment.",
                            "suggestion": "Cite a passage.",
                        }
                    ],
                ),
                _run("experiment_judge", []),
                _run("conference_judge", [], CONFERENCE_SCORES),
            ]
        }
    )
    drafts = [
        SimpleNamespace(
            finding_kind="unsupported_citation",
            source_node="evidence_judge",
            label="Revise the claim",
            target_node="claims",
            prose="Cite a passage that entails the claim.",
        ),
        SimpleNamespace(
            finding_kind="unsupported_citation",
            source_node="evidence_judge",
            label="Other",
            target_node="claims",
            prose="Dropped.",
        ),
        SimpleNamespace(
            finding_kind="unsupported_citation",
            source_node="evidence_judge",
            label="Write a note",
            target_node="other",
            prose="Dropped.",
        ),
    ]
    kept = filter_handling_options(drafts, report.issues)
    assert [item["label"] for item in kept] == ["Revise the claim"]
    assert [item["target_node"] for item in kept] == ["claims"]
