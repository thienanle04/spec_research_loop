"""Judge Issue verifiers read Prompt View only."""

from uuid import UUID

from app.modules.judgement.verifiers import (
    gap_unsupported_by_sources,
    unsupported_citation,
)

UNSUPPORTED_CLAIM = (
    "The literature has not measured whether brass instruments improve "
    "soil nitrogen fixation in alpine peat bogs."
)
FIXTURE_PASSAGE = (
    "An optimizer model proposes prompts and receives task scores as "
    "feedback over multiple optimization rounds."
)
CLAIM_ID = UUID("11111111-1111-1111-1111-111111111111")


def test_unsupported_citation_emits_critical_when_passage_does_not_entail_claim() -> None:
    issues = unsupported_citation(
        {
            "claim_citation_passages": [
                {
                    "claim_id": str(CLAIM_ID),
                    "claim": UNSUPPORTED_CLAIM,
                    "citation_key": "large-language-models-as-optimizers-2023",
                    "passage": FIXTURE_PASSAGE,
                }
            ]
        }
    )
    assert len(issues) == 1
    issue = issues[0]
    assert issue.finding_kind == "unsupported_citation"
    assert issue.severity == "CRITICAL"
    assert issue.target_card_id == CLAIM_ID


def test_unsupported_citation_reads_triples_not_other_view_keys() -> None:
    issues = unsupported_citation(
        {
            "cards": [
                {
                    "id": str(CLAIM_ID),
                    "kind": "claim",
                    "text": "An optimizer model proposes prompts",
                    "supporting_citation_keys": [
                        "large-language-models-as-optimizers-2023"
                    ],
                }
            ],
            "related_work": [
                {
                    "citation_key": "large-language-models-as-optimizers-2023",
                    "supporting_passage": FIXTURE_PASSAGE,
                }
            ],
            "claim_citation_passages": [
                {
                    "claim_id": str(CLAIM_ID),
                    "claim": UNSUPPORTED_CLAIM,
                    "citation_key": "large-language-models-as-optimizers-2023",
                    "passage": FIXTURE_PASSAGE,
                }
            ],
        }
    )
    assert len(issues) == 1
    assert issues[0].finding_kind == "unsupported_citation"
    assert issues[0].severity == "CRITICAL"


def test_unsupported_citation_silent_when_passage_entails_claim() -> None:
    issues = unsupported_citation(
        {
            "claim_citation_passages": [
                {
                    "claim_id": str(CLAIM_ID),
                    "claim": "An optimizer model proposes prompts",
                    "citation_key": "large-language-models-as-optimizers-2023",
                    "passage": FIXTURE_PASSAGE,
                }
            ]
        }
    )
    assert issues == []


def test_gap_unsupported_by_sources_reads_passages_from_related_work_dict() -> None:
    gap_id = UUID("22222222-2222-2222-2222-222222222222")
    silent = gap_unsupported_by_sources(
        {
            "gap_statement": "No cited method does X.",
            "cards": [
                {
                    "id": str(gap_id),
                    "kind": "gap",
                    "statement": "No cited method does X.",
                    "supporting_citation_keys": ["paper-2024"],
                }
            ],
            "related_work": {
                "studies": [{"limitation": "Does not do X."}],
                "passages": [
                    {
                        "citation_key": "paper-2024",
                        "supporting_passage": "The method never does X.",
                    }
                ],
            },
        }
    )
    assert silent == []
    issues = gap_unsupported_by_sources(
        {
            "gap_statement": "No cited method does X.",
            "cards": [
                {
                    "id": str(gap_id),
                    "kind": "gap",
                    "statement": "No cited method does X.",
                    "supporting_citation_keys": ["paper-2024"],
                }
            ],
            "related_work": {
                "studies": [{"limitation": "Does not do X."}],
                "passages": [],
            },
        }
    )
    assert len(issues) == 1
    assert issues[0].finding_kind == "gap_unsupported_by_sources"
