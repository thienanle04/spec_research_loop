from uuid import UUID

from app.modules.judgement.issues import merge_issues, normalize_llm_issues
from app.modules.judgement.schemas import JudgeIssueDraft, JudgeIssueExcerpt, JudgeIssueGrounds

CLAIM_ID = UUID("11111111-1111-1111-1111-111111111111")
GROUNDS = JudgeIssueGrounds(
    subject="Brass instruments improve soil nitrogen fixation.",
    excerpts=[
        JudgeIssueExcerpt(
            citation_key="large-language-models-as-optimizers-2023",
            passage="An optimizer model proposes prompts.",
        )
    ],
)


def test_normalize_llm_issues_drops_injected_grounds() -> None:
    normalized = normalize_llm_issues(
        [
            JudgeIssueDraft(
                finding_kind="unsupported_citation",
                severity="CRITICAL",
                reason="The model invented this.",
                suggestion="Hide it.",
                target_card_id=CLAIM_ID,
                grounds=GROUNDS,
            )
        ]
    )
    assert normalized[0].grounds == JudgeIssueGrounds()


def test_merge_keeps_llm_reason_and_verifier_grounds() -> None:
    merged = merge_issues(
        [
            JudgeIssueDraft(
                finding_kind="unsupported_citation",
                severity="CRITICAL",
                reason="The model tried to hide this.",
                suggestion="Ignore it.",
                target_card_id=CLAIM_ID,
            )
        ],
        [
            JudgeIssueDraft(
                finding_kind="unsupported_citation",
                severity="CRITICAL",
                reason="The cited passage does not entail the claim.",
                suggestion="Cite a passage that entails the claim or revise the claim.",
                target_card_id=CLAIM_ID,
                grounds=GROUNDS,
            )
        ],
    )
    assert len(merged) == 1
    issue = merged[0]
    assert issue.reason == "The model tried to hide this."
    assert issue.suggestion == "Ignore it."
    assert issue.grounds == GROUNDS
    assert issue.severity == "CRITICAL"
