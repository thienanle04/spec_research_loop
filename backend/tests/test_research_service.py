"""Fast unit tests for research provider seams and normalization."""

import asyncio
import json
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

from app.adapters.storage import MemoryObjectStorage
from app.core.config import get_settings
from app.modules.research.adapters.fake_llm import FakeLlmPort
from app.modules.research.adapters.fake_source import FakeScholarlySourcePort
from app.modules.research.normalization import normalize_doi, normalize_url
from app.modules.research.ports import (
    DocumentText,
    ScholarlyProviderError,
    ScholarlyRecord,
    SourcePreferences,
    VerificationResult,
)
from app.modules.research.schemas import (
    CounterEvidenceContentBasis,
    CounterEvidenceOutcome,
    CounterEvidenceRelevance,
    CounterEvidenceResult,
    CounterEvidenceSupport,
    GapCardBody,
    GapClaimAssessment,
    GapClaimEvidence,
    GapClaimKind,
    GapEvidenceCheck,
    GapSearchAudit,
    GapStatus,
    GroundingStatus,
    ResearchGenerateRequest,
    ResearchInputs,
    VerificationStatus,
)
from app.modules.research.service import (
    ResearchGenerationError,
    ResearchService,
    _citation_method_queries,
    _compose_search_queries,
    _CounterEvidenceSearch,
    _diversify_records_by_research_work,
    _facet_balanced_records,
    _fallback_gap_claims,
    _fallback_search_plan,
    _gap_claims_from_answers,
    _gap_evidence_check,
    _GapClaim,
    _GapQuestionAnswers,
    _json_value,
    _missing_search_facets,
    _normalized_study_name,
    _portfolio_order_records,
    _rank_relevant_records,
    _search_plan_from_payload,
    _tag_search_facets,
    _tool_name_appears,
    _validated_counter_evidence_assessment,
    _validated_counter_support_response,
)
from app.ports.llm import LlmProviderError


def test_normalize_doi_and_url() -> None:
    assert normalize_doi(" HTTPS://DOI.ORG/10.1000/ABC ") == "10.1000/abc"
    assert (
        normalize_url("Example.COM/work/?utm_source=test&view=full#section")
        == "https://example.com/work?view=full"
    )


def test_related_work_keeps_only_one_article_per_research_work() -> None:
    records = [
        ScholarlyRecord(
            title="DSPy: Compiling Declarative Language Model Calls",
            metadata={"implementation_tool_mentions": ["DSPy"]},
        ),
        ScholarlyRecord(
            title="Benchmarking DSPy for Clinical NER",
            metadata={"implementation_tool_mentions": ["DSPy"]},
        ),
        ScholarlyRecord(
            title="TextGrad: Automatic Differentiation via Text",
            metadata={"implementation_tool_mentions": ["TextGrad"]},
        ),
    ]

    diversified = _diversify_records_by_research_work(records)

    assert [record.title for record in diversified] == [
        "DSPy: Compiling Declarative Language Model Calls",
        "TextGrad: Automatic Differentiation via Text",
    ]
    assert diversified[0].metadata["research_work_name"] == "DSPy"
    assert diversified[1].metadata["research_work_name"] == "TextGrad"
    assert records[1].metadata["work_selection"] == "same_work_excluded"


def test_related_work_reserves_best_distinct_article_for_each_discovered_tool() -> None:
    records = [
        ScholarlyRecord(
            title="Broad LLM evaluation survey",
            metadata={
                "implementation_tool_mentions": ["LLM-as-a-Judge"],
                "reranker_rank": 1,
            },
        ),
        ScholarlyRecord(
            title="DSPy benchmark",
            metadata={
                "implementation_tool_mentions": ["DSPy"],
                "reranker_rank": 3,
            },
        ),
        ScholarlyRecord(
            title="A second judge study",
            metadata={
                "implementation_tool_mentions": ["LLM-as-a-Judge"],
                "reranker_rank": 2,
            },
        ),
        ScholarlyRecord(
            title="TextGrad optimization",
            metadata={
                "implementation_tool_mentions": ["TextGrad"],
                "reranker_rank": 4,
            },
        ),
    ]

    diversified = _diversify_records_by_research_work(
        records,
        tool_names=["DSPy", "TextGrad", "LLM-as-a-Judge"],
    )

    assert [record.title for record in diversified] == [
        "DSPy benchmark",
        "TextGrad optimization",
        "Broad LLM evaluation survey",
    ]
    assert diversified[0].metadata["tool_quota_name"] == "DSPy"
    assert diversified[1].metadata["tool_quota_name"] == "TextGrad"
    assert diversified[2].metadata["tool_quota_name"] == "LLM-as-a-Judge"
    assert records[2].metadata["work_selection"] == "same_work_excluded"


def test_tool_generation_keywords_choose_the_relevant_article_within_one_tool() -> None:
    broad = ScholarlyRecord(
        title="DSPy: Declarative Language Model Programming",
        abstract="Introduces a general framework for composing language model programs.",
        metadata={
            "implementation_tool_mentions": ["DSPy"],
            "reranker_rank": 1,
        },
    )
    relevant = ScholarlyRecord(
        title="Iterative Prompt Optimization with DSPy",
        abstract="Evaluates iterative prompt optimization using local feedback.",
        metadata={
            "implementation_tool_mentions": ["DSPy"],
            "reranker_rank": 2,
        },
    )

    diversified = _diversify_records_by_research_work(
        [broad, relevant],
        tool_names=["DSPy"],
        tool_relevance_keywords=["iterative prompt optimization"],
    )

    assert diversified == [relevant]
    assert broad.metadata["tool_relevance_keyword_match_count"] == 0
    assert relevant.metadata["tool_relevance_keyword_match_count"] == 1
    assert relevant.metadata["selected_tool_name"] == "DSPy"


def test_tool_detection_accepts_hyphenated_title_suffixes() -> None:
    assert _tool_name_appears(
        "DSPy",
        "Optimizing prompts with DSPy-Based Declarative Learning",
    )


def test_study_name_prefers_tool_and_rejects_full_article_title() -> None:
    dspy = ScholarlyRecord(
        title="Manual Prompt Engineering with DSPy for Vulnerability Detection",
        metadata={"implementation_tool_mentions": ["DSPy"]},
    )
    sapo = ScholarlyRecord(
        title="From Monolithic to Modular: Segment-level Prompt Optimization",
        abstract="We introduce SAPO for segment-level automatic prompt optimization.",
    )

    assert _normalized_study_name(dspy.title, dspy) == "DSPy"
    assert _normalized_study_name(sapo.title, sapo) == "SAPO"


def test_grounded_abstract_citation_can_support_gap_candidate() -> None:
    check = _gap_evidence_check(
        [
            {
                "id": "citation-1",
                "citation_key": "dspy-2024",
                "verification_status": "verified",
                "text_source_kind": "abstract",
            }
        ],
        [
            {
                "citation_key": "dspy-2024",
                "grounding_status": "grounded",
                "limitation": "Only one benchmark was evaluated.",
                "evidence": {
                    "limitation": {
                        "passage": "Only one benchmark was evaluated.",
                        "location": "Abstract",
                    }
                },
            }
        ],
    )

    assert check.ready is True
    assert check.eligible_citation_keys == ["dspy-2024"]


@pytest.mark.parametrize(
    "raw",
    [
        '<think>Need four queries.</think>\n{"queries":["claim evidence"]}',
        'Here is the JSON:\n```json\n{"queries":["claim evidence"]}\n```',
        'Reasoning before the answer. {"queries":["claim evidence"]} Done.',
    ],
)
def test_json_value_extracts_structured_output_from_model_wrappers(raw: str) -> None:
    assert _json_value(raw, dict) == {"queries": ["claim evidence"]}


def test_json_value_still_rejects_unstructured_model_output() -> None:
    with pytest.raises(json.JSONDecodeError):
        _json_value("I could not produce the requested queries.", dict)


@pytest.mark.asyncio
async def test_coalesced_provider_failure_is_reported_once() -> None:
    class FailingMultiQuerySource:
        async def search_many(
            self,
            *,
            queries: list[str],
            preferences: SourcePreferences | None = None,
            limit: int = 10,
        ) -> list[ScholarlyRecord]:
            del queries, preferences, limit
            raise ScholarlyProviderError(
                "Semantic Scholar request failed (HTTP 500).",
                status_code=500,
            )

        async def search(
            self,
            *,
            query: str,
            preferences: SourcePreferences | None = None,
            limit: int = 10,
        ) -> list[ScholarlyRecord]:
            del query, preferences, limit
            return []

        async def get_source(self, *, identifier: str) -> ScholarlyRecord | None:
            del identifier
            return None

    service = ResearchService(
        _UnusedDb(),  # type: ignore[arg-type]
        source=FailingMultiQuerySource(),
        verifier=_UnusedVerifier(),  # type: ignore[arg-type]
        llm=FakeLlmPort(),
    )

    records, failures = await service._search_provider_queries(
        queries=["first counter query", "second counter query"],
        preferences=SourcePreferences(),
        limit=5,
    )

    assert records == []
    assert failures == ["Semantic Scholar request failed (HTTP 500)."]


def _ready_gap_candidate() -> GapCardBody:
    statement = "A source-grounded atomic Gap remains unresolved."
    return GapCardBody(
        statement=statement,
        supporting_citation_keys=["smith-2025"],
        status=GapStatus.CANDIDATE,
        search_audit=GapSearchAudit(
            assessed_statement=statement,
            related_work_queries=["source grounded gap"],
            counter_evidence_queries=["source grounded gap competing method"],
            providers=["fixture"],
            related_work_candidate_count=1,
            related_work_analyzed_count=1,
            counter_evidence_candidate_count=1,
            counter_evidence_analyzed_count=1,
            complete=True,
            completed_at="2026-08-26T00:00:00Z",
            counter_evidence_outcome=(
                CounterEvidenceOutcome.NO_DIRECT_COUNTER_EVIDENCE
            ),
            counter_evidence_results=[
                CounterEvidenceResult(
                    result_key="counter-1",
                    title="Counter source",
                    verification_status=VerificationStatus.VERIFIED,
                    content_basis=CounterEvidenceContentBasis.ABSTRACT,
                    evidence_passage="The study evaluates a different mechanism.",
                    evidence_location="Abstract",
                    grounding_status=GroundingStatus.GROUNDED,
                    relevance_status=CounterEvidenceRelevance.RELEVANT,
                    support_status=CounterEvidenceSupport.SUPPORTED,
                    impact=CounterEvidenceOutcome.NO_DIRECT_COUNTER_EVIDENCE,
                )
            ],
            claim_assessments=[
                GapClaimAssessment(
                    claim_id="c1",
                    kind=GapClaimKind.UNRESOLVED_LIMITATION,
                    statement=statement,
                    supporting_citation_keys=["smith-2025"],
                    supporting_evidence=[
                        GapClaimEvidence(
                            citation_key="smith-2025",
                            passage="The source reports an unresolved atomic limitation.",
                            location="Abstract",
                        )
                    ],
                    counter_evidence_result_keys=["counter-1"],
                    outcome=CounterEvidenceOutcome.NO_DIRECT_COUNTER_EVIDENCE,
                )
            ],
        ),
        evidence_check=GapEvidenceCheck(
            eligible_citation_keys=["smith-2025"],
            ready=True,
        ),
    )


def test_gap_readiness_becomes_stale_when_statement_changes() -> None:
    candidate = _ready_gap_candidate()

    assert candidate.is_evidence_ready()
    candidate.statement = "A materially different Gap statement."
    assert not candidate.is_evidence_ready()
    reparsed = GapCardBody.model_validate(candidate.model_dump(mode="json"))
    assert reparsed.status is GapStatus.INSUFFICIENT_EVIDENCE


@pytest.mark.parametrize(
    ("case", "expected_message"),
    [
        ("identity", "source identity"),
        ("grounding", "grounded in source content"),
        ("relevance", "directly relevant"),
        ("claim_counter_mapping", "every selected counter-evidence source"),
        ("claim_support_mapping", "mapped exactly"),
        ("portfolio_coverage", "selected source portfolio"),
        ("aggregate_outcome", "inconsistent with the atomic claims"),
    ],
)
def test_gap_readiness_rejects_incomplete_evidence_contract(
    case: str,
    expected_message: str,
) -> None:
    candidate = _ready_gap_candidate()
    if case == "identity":
        candidate.search_audit.counter_evidence_results[
            0
        ].verification_status = VerificationStatus.WARNING
    elif case == "grounding":
        candidate.search_audit.counter_evidence_results[
            0
        ].grounding_status = GroundingStatus.WARNING
    elif case == "relevance":
        candidate.search_audit.counter_evidence_results[
            0
        ].relevance_status = CounterEvidenceRelevance.IRRELEVANT
    elif case == "claim_counter_mapping":
        candidate.search_audit.claim_assessments[0].counter_evidence_result_keys = []
    elif case == "claim_support_mapping":
        candidate.search_audit.claim_assessments[0].supporting_citation_keys = [
            "lee-2024"
        ]
        candidate.evidence_check.eligible_citation_keys.append("lee-2024")
    elif case == "portfolio_coverage":
        candidate.search_audit.counter_evidence_analyzed_count = 2
    elif case == "aggregate_outcome":
        candidate.search_audit.counter_evidence_outcome = (
            CounterEvidenceOutcome.GAP_NARROWED
        )
    else:  # pragma: no cover - parametrization is exhaustive
        raise AssertionError(f"Unknown readiness case: {case}")

    messages = candidate.evidence_readiness_messages()
    assert any(expected_message in message.casefold() for message in messages)
    assert not candidate.is_evidence_ready()
    reparsed = GapCardBody.model_validate(candidate.model_dump(mode="json"))
    assert reparsed.status is GapStatus.INSUFFICIENT_EVIDENCE


def test_gap_readiness_allows_a_smaller_relevant_counter_portfolio() -> None:
    candidate = _ready_gap_candidate()
    candidate.search_audit.counter_evidence_candidate_count = 5

    assert candidate.evidence_readiness_messages() == []
    assert candidate.is_evidence_ready() is True


def test_gap_claims_reject_model_invented_details_outside_grounded_candidates() -> None:
    source_claim = _GapClaim(
        claim_id="c1",
        kind=GapClaimKind.UNRESOLVED_LIMITATION,
        statement="The study evaluates only one dataset.",
        supporting_citation_keys=["smith-2025"],
        supporting_evidence=[
            GapClaimEvidence(
                citation_key="smith-2025",
                passage="The evaluation uses a single dataset.",
                location="Abstract",
            )
        ],
    )
    answers = _GapQuestionAnswers(
        prior_work="The study evaluates a verification method.",
        limitation="The evaluation uses one dataset.",
        importance="Generalization matters.",
        testability="Evaluate on held-out datasets.",
        covered_citation_keys=["smith-2025"],
        claims=[
            _GapClaim(
                claim_id="c1",
                kind=GapClaimKind.UNRESOLVED_LIMITATION,
                statement=(
                    "MAX_RETRY = 3 fails because the classifier was trained only "
                    "on Indonesian data."
                ),
                supporting_citation_keys=["smith-2025"],
            )
        ],
    )

    with pytest.raises(ValueError, match="grounded claim candidates"):
        _gap_claims_from_answers(answers, [source_claim])


@pytest.mark.asyncio
async def test_gap_claim_support_rejects_a_semantically_unrelated_passage() -> None:
    candidate = _GapClaim(
        claim_id="c1",
        kind=GapClaimKind.UNRESOLVED_LIMITATION,
        statement="The classifier was trained only on Indonesian data.",
        supporting_citation_keys=["smith-2025"],
        supporting_evidence=[
            GapClaimEvidence(
                citation_key="smith-2025",
                passage="The model exhibits safety vulnerabilities during evaluation.",
                location="Abstract",
            )
        ],
    )
    service = ResearchService(
        _UnusedDb(),  # type: ignore[arg-type]
        source=FakeScholarlySourcePort(),
        verifier=_UnusedVerifier(),  # type: ignore[arg-type]
        llm=FakeLlmPort(
            responses={
                "research-gap-claim-support-check": json.dumps(
                    {
                        "assessments": [
                            {
                                "claim_id": "c1",
                                "support_status": "unsupported",
                            }
                        ]
                    }
                )
            }
        ),
    )

    supported, warnings = await service._validate_gap_claim_support(
        idea={},
        claim_candidates=[candidate],
    )

    assert supported == []
    assert any("Excluded 1 atomic Gap claim" in warning for warning in warnings)


@pytest.mark.asyncio
async def test_gap_claim_support_narrows_an_overbroad_related_work_limitation() -> None:
    passage = (
        "Additionally, the reliance on binary YES/NO questions, while simplifying "
        "evaluation, may oversimplify very open-ended tasks requiring more nuanced "
        "judgements."
    )
    candidate = _GapClaim(
        claim_id="c1",
        kind=GapClaimKind.UNRESOLVED_LIMITATION,
        statement=(
            "Checklist quality depends on the base LLM, and binary questions may "
            "oversimplify open-ended tasks."
        ),
        supporting_citation_keys=["check-your-work-2026"],
        supporting_evidence=[
            GapClaimEvidence(
                citation_key="check-your-work-2026",
                passage=passage,
                location="Limitations",
            )
        ],
    )
    narrowed_statement = (
        "Binary YES/NO questions may oversimplify open-ended tasks that require "
        "more nuanced judgements."
    )
    llm = FakeLlmPort(
        responses={
            "research-gap-claim-support-check": json.dumps(
                {
                    "assessments": [
                        {"claim_id": "c1", "support_status": "uncertain"}
                    ]
                }
            ),
            "research-gap-claim-narrowing": json.dumps(
                {
                    "claim_id": "c1",
                    "can_narrow": True,
                    "statement": narrowed_statement,
                    "evidence_span": passage,
                }
            ),
            "research-gap-claim-support-confirmation": json.dumps(
                {
                    "assessments": [
                        {
                            "claim_id": "c1",
                            "support_status": "supported",
                            "atomicity_status": "atomic",
                            "evidence_span": passage,
                            "unsupported_fragments": [],
                        }
                    ]
                }
            ),
        }
    )
    service = ResearchService(
        _UnusedDb(),  # type: ignore[arg-type]
        source=FakeScholarlySourcePort(),
        verifier=_UnusedVerifier(),  # type: ignore[arg-type]
        llm=llm,
    )

    supported, warnings = await service._validate_gap_claim_support(
        idea={"problems": ["Unsupported LLM outputs"]},
        claim_candidates=[candidate],
    )

    assert [claim.statement for claim in supported] == [narrowed_statement]
    assert any("Narrowed 1 Related Work limitation" in item for item in warnings)
    assert not any("Excluded 1 atomic Gap claim" in item for item in warnings)
    assert len(llm.calls) == 3


@pytest.mark.asyncio
async def test_gap_claim_support_normalizes_wrapped_alias_fields() -> None:
    candidate = _GapClaim(
        claim_id="c1",
        kind=GapClaimKind.UNRESOLVED_LIMITATION,
        statement="The evaluation uses one dataset.",
        supporting_citation_keys=["smith-2025"],
        supporting_evidence=[
            GapClaimEvidence(
                citation_key="smith-2025",
                passage="The evaluation uses a single dataset.",
                location="Abstract",
            )
        ],
    )
    llm = FakeLlmPort(
        responses={
            "research-gap-claim-support-check": json.dumps(
                {"data": {"results": [{"id": "c1", "status": "yes"}]}}
            )
        }
    )
    service = ResearchService(
        _UnusedDb(),  # type: ignore[arg-type]
        source=FakeScholarlySourcePort(),
        verifier=_UnusedVerifier(),  # type: ignore[arg-type]
        llm=llm,
    )

    supported, warnings = await service._validate_gap_claim_support(
        idea={},
        claim_candidates=[candidate],
    )

    assert supported == [candidate]
    assert warnings == []
    assert len(llm.calls) == 2


@pytest.mark.asyncio
async def test_gap_claim_support_repairs_an_incomplete_bulk_response() -> None:
    candidate = _GapClaim(
        claim_id="c1",
        kind=GapClaimKind.UNRESOLVED_LIMITATION,
        statement="The evaluation uses one dataset.",
        supporting_citation_keys=["smith-2025"],
        supporting_evidence=[
            GapClaimEvidence(
                citation_key="smith-2025",
                passage="The evaluation uses a single dataset.",
                location="Abstract",
            )
        ],
    )
    llm = FakeLlmPort(
        responses={"research-gap-claim-support-check": "{}"}
    )
    service = ResearchService(
        _UnusedDb(),  # type: ignore[arg-type]
        source=FakeScholarlySourcePort(),
        verifier=_UnusedVerifier(),  # type: ignore[arg-type]
        llm=llm,
    )

    supported, warnings = await service._validate_gap_claim_support(
        idea={},
        claim_candidates=[candidate],
    )

    assert supported == [candidate]
    assert any("structured-output recovery" in warning for warning in warnings)
    assert any("schema validation failed" in warning for warning in warnings)
    assert len(llm.calls) == 3


@pytest.mark.asyncio
async def test_gap_claim_support_recovers_independently_per_claim() -> None:
    candidate = _GapClaim(
        claim_id="c1",
        kind=GapClaimKind.UNRESOLVED_LIMITATION,
        statement="The evaluation uses one dataset.",
        supporting_citation_keys=["smith-2025"],
        supporting_evidence=[
            GapClaimEvidence(
                citation_key="smith-2025",
                passage="The evaluation uses a single dataset.",
                location="Abstract",
            )
        ],
    )
    llm = FakeLlmPort(
        responses={
            "research-gap-claim-support-check": "{}",
            "research-gap-claim-support-repair": "{}",
            "research-gap-claim-support-item-check": '{"supported":true}',
        }
    )
    service = ResearchService(
        _UnusedDb(),  # type: ignore[arg-type]
        source=FakeScholarlySourcePort(),
        verifier=_UnusedVerifier(),  # type: ignore[arg-type]
        llm=llm,
    )

    supported, warnings = await service._validate_gap_claim_support(
        idea={},
        claim_candidates=[candidate],
    )

    assert supported == [candidate]
    assert any("per-claim recovery left 0/1" in warning for warning in warnings)
    assert len(llm.calls) == 4


def test_gap_claim_preparation_splits_composites_and_flags_nonmention() -> None:
    related_work = [
        {
            "citation_key": "multi-kb-2026",
            "limitation": (
                "Cơ chế hiện tại tập trung vào nguồn văn bản và chưa được mở rộng "
                "sang xác thực đa phương tiện; khuôn khổ hiện chỉ được tối ưu hóa "
                "cho một cơ sở dữ liệu kiến thức duy nhất."
            ),
            "evidence": {
                "limitation": {
                    "passage": (
                        "The framework is currently optimized only for a single "
                        "knowledge base and does not explore coordination across "
                        "multiple heterogeneous knowledge bases."
                    ),
                    "location": "Limitations",
                }
            },
        },
        {
            "citation_key": "dynamic-kg-2026",
            "limitation": (
                "Hệ thống dùng Dynamic KG nhưng không đề cập đến việc tự động "
                "khởi động lại suy luận hoặc sử dụng External Critic."
            ),
            "evidence": {
                "limitation": {
                    "passage": (
                        "Dynamic KG injection substantially reduces factual errors."
                    ),
                    "location": "Abstract",
                }
            },
        },
    ]

    claims, warnings = _fallback_gap_claims(
        related_work,
        ["multi-kb-2026", "dynamic-kg-2026"],
    )

    assert [claim.statement for claim in claims] == [
        "Cơ chế hiện tại tập trung vào nguồn văn bản và chưa được mở rộng sang xác thực đa phương tiện",
        "Khuôn khổ hiện chỉ được tối ưu hóa cho một cơ sở dữ liệu kiến thức duy nhất.",
        (
            "Hệ thống dùng Dynamic KG nhưng không đề cập đến việc tự động khởi động "
            "lại suy luận hoặc sử dụng External Critic."
        ),
    ]
    assert any("Split 1 composite" in warning for warning in warnings)
    assert any("source non-mention" in warning for warning in warnings)


def test_gap_claim_preparation_removes_unanchored_clinical_scope() -> None:
    claims, warnings = _fallback_gap_claims(
        [
            {
                "citation_key": "ultrasound-2026",
                "limitation": (
                    "Nghiên cứu dựa trên đầu vào văn bản có cấu trúc thay vì ảnh "
                    "siêu âm thô, nên kết quả có thể không chuyển trực tiếp sang "
                    "ứng dụng đa phương thức trong thực tế lâm sàng."
                ),
                "evidence": {
                    "limitation": {
                        "passage": (
                            "The study relied on structured text inputs rather than raw "
                            "ultrasound images; therefore, the findings may not directly "
                            "translate to multimodal image-based applications."
                        ),
                        "location": "Page 10",
                    }
                },
            }
        ],
        ["ultrasound-2026"],
    )

    assert claims[0].statement.endswith("ứng dụng đa phương thức.")
    assert "lâm sàng" not in claims[0].statement
    assert any("removing clinical scope" in warning for warning in warnings)


@pytest.mark.asyncio
async def test_gap_claim_confirmation_rejects_an_unsupported_fragment() -> None:
    candidate = _GapClaim(
        claim_id="c1",
        kind=GapClaimKind.UNRESOLVED_LIMITATION,
        statement=(
            "Cơ chế hiện tại chưa được mở rộng sang xác thực cộng tác của thông tin "
            "đa phương tiện."
        ),
        supporting_citation_keys=["multi-kb-2026"],
        supporting_evidence=[
            GapClaimEvidence(
                citation_key="multi-kb-2026",
                passage=(
                    "The framework is currently optimized only for a single knowledge "
                    "base and does not explore coordination across heterogeneous "
                    "knowledge bases."
                ),
                location="Limitations",
            )
        ],
    )
    llm = FakeLlmPort(
        responses={
            "research-gap-claim-support-confirmation": json.dumps(
                {
                    "assessments": [
                        {
                            "claim_id": "c1",
                            "support_status": "supported",
                            "atomicity_status": "atomic",
                            "evidence_span": (
                                "The framework is currently optimized only for a single "
                                "knowledge base"
                            ),
                            "unsupported_fragments": [
                                "xác thực cộng tác của thông tin đa phương tiện"
                            ],
                        }
                    ]
                }
            )
        }
    )
    service = ResearchService(
        _UnusedDb(),  # type: ignore[arg-type]
        source=FakeScholarlySourcePort(),
        verifier=_UnusedVerifier(),  # type: ignore[arg-type]
        llm=llm,
    )

    supported, warnings = await service._validate_gap_claim_support(
        idea={},
        claim_candidates=[candidate],
    )

    assert supported == []
    assert any("Excluded 1 atomic Gap claim" in warning for warning in warnings)


@pytest.mark.asyncio
async def test_gap_claim_support_accepts_the_grounded_ultrasound_limitation() -> None:
    candidate = _GapClaim(
        claim_id="c1",
        kind=GapClaimKind.UNRESOLVED_LIMITATION,
        statement=(
            "Nghiên cứu dựa trên đầu vào văn bản có cấu trúc thay vì hình ảnh siêu "
            "âm thô, nên kết quả có thể không chuyển trực tiếp sang ứng dụng đa phương thức."
        ),
        supporting_citation_keys=["ultrasound-2026"],
        supporting_evidence=[
            GapClaimEvidence(
                citation_key="ultrasound-2026",
                passage=(
                    "The study relied on structured text inputs rather than raw "
                    "ultrasound images; therefore, the findings may not directly "
                    "translate to multimodal image-based applications."
                ),
                location="Page 10",
            )
        ],
    )
    llm = FakeLlmPort()
    service = ResearchService(
        _UnusedDb(),  # type: ignore[arg-type]
        source=FakeScholarlySourcePort(),
        verifier=_UnusedVerifier(),  # type: ignore[arg-type]
        llm=llm,
    )

    supported, warnings = await service._validate_gap_claim_support(
        idea={},
        claim_candidates=[candidate],
    )

    assert supported == [candidate]
    assert warnings == []
    assert len(llm.calls) == 2


@pytest.mark.asyncio
async def test_gap_claim_support_rejects_nonmention_when_narrowing_fails() -> None:
    candidate = _GapClaim(
        claim_id="c1",
        kind=GapClaimKind.UNRESOLVED_LIMITATION,
        statement=(
            "Dynamic KG giảm lỗi nhưng không đề cập đến restart hoặc External Critic."
        ),
        supporting_citation_keys=["dynamic-kg-2026"],
        supporting_evidence=[
            GapClaimEvidence(
                citation_key="dynamic-kg-2026",
                passage="Dynamic KG injection substantially reduces factual errors.",
                location="Abstract",
            )
        ],
    )
    llm = FakeLlmPort()
    service = ResearchService(
        _UnusedDb(),  # type: ignore[arg-type]
        source=FakeScholarlySourcePort(),
        verifier=_UnusedVerifier(),  # type: ignore[arg-type]
        llm=llm,
    )

    supported, warnings = await service._validate_gap_claim_support(
        idea={},
        claim_candidates=[candidate],
    )

    assert supported == []
    assert any("Excluded 1 atomic Gap claim" in warning for warning in warnings)
    assert len(llm.calls) == 2
    assert "research-gap-claim-narrowing" in llm.calls[1]["system"]


def test_counter_support_normalizes_wrapped_alias_fields() -> None:
    response = _validated_counter_support_response(
        '{"output":[{"key":"result-1","verdict":"entailed"}]}',
        ["result-1"],
    )

    assert response.assessments[0].result_key == "result-1"
    assert (
        response.assessments[0].support_status
        is CounterEvidenceSupport.SUPPORTED
    )


@pytest.mark.asyncio
async def test_gap_generation_skips_counter_search_without_supported_claims(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    llm = FakeLlmPort(
        responses={
            "research-gap-claim-support-check": json.dumps(
                {
                    "assessments": [
                        {"claim_id": "c1", "support_status": "unsupported"}
                    ]
                }
            )
        }
    )
    service = ResearchService(
        _UnusedDb(),  # type: ignore[arg-type]
        source=FakeScholarlySourcePort(_relevant_counter_records(5)),
        verifier=_RecordingVerifier(),
        llm=llm,
    )

    async def unexpected_counter_search(**_kwargs: Any) -> None:
        raise AssertionError("Counter search must be skipped without supported claims")

    monkeypatch.setattr(service, "_search_counter_evidence", unexpected_counter_search)
    context = {
        "upstream": {
            "idea_decomposition": {
                "card_snapshot": [
                    {"kind": "problem", "body": {"text": "Unsupported claims"}}
                ]
            },
            "research_inputs": {"narrative": {"keywords": ["claim verification"]}},
            "related_work": {
                "narrative": {
                    "search_queries": ["claim verification"],
                    "candidate_count": 1,
                },
                "projected": {
                    "citations": [
                        {
                            "id": "citation-1",
                            "citation_key": "smith-2025",
                            "title": "Claim verification",
                            "provider": "fixture",
                            "verification_status": "verified",
                        }
                    ],
                    "related_work": [
                        {
                            "citation_id": "citation-1",
                            "what_was_done": "Evaluates aggregate feedback",
                            "limitation": "Does not isolate claim-level errors",
                            "source_location": "Abstract",
                            "evidence": {
                                "limitation": {
                                    "passage": "Does not isolate claim-level errors",
                                    "location": "Abstract",
                                }
                            },
                            "grounding_status": "grounded",
                        }
                    ],
                },
            },
        },
        "working_draft": {"narrative": {}},
    }

    narrative, warnings = await service._generate_gaps(context)

    audit = narrative["candidate"]["search_audit"]
    assert audit["counter_evidence_queries"] == []
    assert audit["counter_evidence_candidate_count"] == 0
    assert "search was skipped" in audit["counter_evidence_assessment"]
    assert any("Skipped counter-evidence search" in warning for warning in warnings)
    assert not any("research-counter-query" in call["system"] for call in llm.calls)


def test_counter_assessment_requires_a_complete_claim_source_matrix() -> None:
    payload = {
        "outcome": "no_direct_counter_evidence",
        "statement": "The limitation remains testable.",
        "assessment": "Neither source resolves either claim.",
        "covered_result_keys": ["r1", "r2"],
        "findings": [
            {
                "result_key": key,
                "claim_ids": ["c1"],
                "impact": "no_direct_counter_evidence",
                "relevance_status": "relevant",
                "rationale": "The source does not resolve the claims.",
                "supporting_passage": "A directly relevant source passage.",
                "source_location": "Abstract",
            }
            for key in ("r1", "r2")
        ],
        "claim_assessments": [
            {
                "claim_id": claim_id,
                "outcome": "no_direct_counter_evidence",
                "assessment": "The sources do not resolve this claim.",
                "counter_evidence_result_keys": ["r1", "r2"],
            }
            for claim_id in ("c1", "c2")
        ],
    }

    with pytest.raises(ValueError, match="every Gap claim"):
        _validated_counter_evidence_assessment(
            json.dumps(payload),
            ["r1", "r2"],
            ["c1", "c2"],
        )

    for finding in payload["findings"]:
        finding["claim_ids"] = ["c1", "c2"]
    payload["claim_assessments"][0]["counter_evidence_result_keys"] = ["r1"]
    with pytest.raises(ValueError, match="every counter-evidence result"):
        _validated_counter_evidence_assessment(
            json.dumps(payload),
            ["r1", "r2"],
            ["c1", "c2"],
        )


@pytest.mark.asyncio
async def test_fake_source_loads_fixed_fixture_without_network() -> None:
    fixture = Path(__file__).parent / "fixtures" / "research" / "scholarly_records.json"
    source = FakeScholarlySourcePort.from_json(fixture)
    records = await source.search(query="prompt optimization", limit=2)
    assert len(records) == 2
    assert records[0].retrieved_at is not None
    resolved = await source.get_source(identifier="doi:10.48550/ARXIV.2309.03409")
    assert resolved is not None
    assert resolved.provider_source_id == "opro-2023"


@pytest.mark.asyncio
async def test_source_preferences_are_applied_by_provider_port() -> None:
    fixture = Path(__file__).parent / "fixtures" / "research" / "scholarly_records.json"
    source = FakeScholarlySourcePort.from_json(fixture)

    records = await source.search(
        query="optimization",
        preferences=SourcePreferences(
            peer_reviewed_papers=True,
            official_proceedings=False,
            author_materials=False,
            sourced_surveys=False,
        ),
        limit=10,
    )

    assert len(records) == 2
    assert records[0].metadata["is_peer_reviewed"] is True
    assert source.search_calls[0][1] is not None


@pytest.mark.asyncio
async def test_search_queries_use_english_while_outputs_follow_idea_language() -> None:
    llm = FakeLlmPort(
        responses={
            "research-inputs": '{"keywords":["scientific claim verification"]}',
            "research-query": '{"queries":["scientific claim verification"]}',
            "research-analysis": (
                '{"what_was_done":"Kiểm tra từng tuyên bố",'
                '"method_or_feedback":"Đối chiếu bằng chứng",'
                '"limitation":"Chỉ đánh giá một tập dữ liệu",'
                '"relevance":"Liên quan trực tiếp đến ý tưởng",'
                '"supporting_passage":"Kiểm tra từng tuyên bố.",'
                '"confidence":0.8}'
            ),
            "research-gap-analysis": (
                '{"prior_work":"Các nghiên cứu đã kiểm tra từng tuyên bố",'
                '"limitation":"Chưa đánh giá trên nhiều lĩnh vực",'
                '"importance":"Kết quả cần có khả năng khái quát",'
                '"testability":"So sánh trên nhiều bộ dữ liệu",'
                '"covered_citation_keys":["nguyen-2026"]}'
            ),
            "research-gap-synthesis": (
                '{"statement":"Các nghiên cứu đã kiểm tra từng tuyên bố. Chưa rõ '
                'phương pháp có khái quát sang nhiều lĩnh vực hay không."}'
            ),
        }
    )
    service = ResearchService(
        _UnusedDb(),  # type: ignore[arg-type]
        source=FakeScholarlySourcePort(_relevant_counter_records()),
        verifier=_RecordingVerifier(),
        llm=llm,
    )
    idea = {
        "problems": ["Các bản tóm tắt có tuyên bố không được nguồn hỗ trợ"],
        "research_questions": ["Kiểm chứng từng tuyên bố có giảm lỗi không?"],
    }
    context = {
        "upstream": {
            "idea_decomposition": {
                "card_snapshot": [
                    {"kind": "problem", "body": {"text": idea["problems"][0]}},
                    {
                        "kind": "research_question",
                        "body": {"text": idea["research_questions"][0]},
                    },
                ]
            },
            "related_work": {
                "narrative": {
                    "search_queries": ["scientific claim verification"],
                    "candidate_count": 1,
                },
                "projected": {
                    "citations": [
                        {
                            "id": "citation-1",
                            "citation_key": "nguyen-2026",
                            "title": "Kiểm chứng tuyên bố",
                            "abstract": "Kiểm tra từng tuyên bố.",
                            "provider": "fixture",
                            "verification_status": "verified",
                        }
                    ],
                    "related_work": [
                        {
                            "citation_id": "citation-1",
                            "what_was_done": "Kiểm tra từng tuyên bố",
                            "limitation": "Chỉ đánh giá một tập dữ liệu",
                            "evidence": {
                                "limitation": {
                                    "passage": "Chỉ đánh giá một tập dữ liệu",
                                    "location": "Abstract",
                                }
                            },
                            "grounding_status": "grounded",
                        }
                    ],
                },
            },
        },
        "working_draft": {"narrative": {}},
    }

    inputs, _ = await service._generate_research_inputs(context)
    queries, _ = await service._generate_queries(
        ResearchInputs(keywords=["kiểm chứng tuyên bố"]), idea
    )
    finding, _ = await service._analyze(
        ScholarlyRecord(
            title="Kiểm chứng tuyên bố",
            abstract="Kiểm tra từng tuyên bố.",
        ),
        uuid4(),
        research_context={"idea": idea, "research_inputs": inputs},
    )
    gap, _ = await service._generate_gaps(context)

    assert "scientific claim verification" in inputs["keywords"]
    assert queries[0].strip('"') == "scientific claim verification"
    assert len(queries) >= 2
    assert finding.what_was_done == "Kiểm tra từng tuyên bố"
    assert gap["candidate"]["statement"].startswith("Các nghiên cứu")
    assert len(llm.calls) == 12
    discovery_call = next(
        call for call in llm.calls if "research-discovery" in call["system"]
    )
    assert "candidate_work_titles" in discovery_call["system"]
    assert any("research-rerank" in call["system"] for call in llm.calls)
    query_call = next(call for call in llm.calls if "research-query" in call["system"])
    assert "English regardless of the input language" in query_call["system"]
    research_inputs_call = next(
        call for call in llm.calls if "research-inputs" in call["system"]
    )
    assert "Write every keyword in English" in research_inputs_call["system"]
    assert "idea's language" in research_inputs_call["system"]
    user_facing_calls = [
        call
        for call in llm.calls
        if "research-query" not in call["system"]
        and "research-discovery" not in call["system"]
        and "research-inputs" not in call["system"]
        and "research-counter-query" not in call["system"]
        and "research-rerank" not in call["system"]
    ]
    assert all(
        "write every generated user-facing value in that same language"
        in call["system"]
        for call in user_facing_calls
    )


@pytest.mark.asyncio
async def test_related_work_repairs_prose_that_does_not_match_idea_language() -> None:
    source_passage = (
        "The study compares prompt engineering, retrieval-augmented generation, "
        "and self-consistency decoding on 7B-scale models."
    )
    llm = FakeLlmPort(
        responses={
            "research-analysis-language-repair": json.dumps(
                {
                    "what_was_done": (
                        "Nghiên cứu thực hiện đánh giá so sánh các kỹ thuật giảm ảo giác."
                    ),
                    "method_or_feedback": (
                        "Sử dụng một giao thức đánh giá thống nhất trên nhiều tiêu chí."
                    ),
                    "limitation": "Đánh giá chỉ giới hạn ở các mô hình quy mô 7B.",
                    "relevance": "Có liên quan trực tiếp đến câu hỏi nghiên cứu.",
                    "supporting_passage": source_passage,
                    "evidence": {
                        field: {"passage": source_passage, "location": "Abstract"}
                        for field in (
                            "what_was_done",
                            "method_or_feedback",
                            "limitation",
                        )
                    },
                    "confidence": 0.8,
                },
                ensure_ascii=False,
            ),
            "research-analysis": json.dumps(
                {
                    "what_was_done": (
                        "The paper conducted a comparative evaluation of hallucination "
                        "mitigation strategies."
                    ),
                    "method_or_feedback": (
                        "Uses a unified multi-dimensional evaluation protocol."
                    ),
                    "limitation": "The evaluation is limited to 7B-scale models.",
                    "relevance": "The study is directly relevant to the research idea.",
                    "supporting_passage": source_passage,
                    "evidence": {
                        field: {"passage": source_passage, "location": "Abstract"}
                        for field in (
                            "what_was_done",
                            "method_or_feedback",
                            "limitation",
                        )
                    },
                    "confidence": 0.8,
                }
            ),
        }
    )
    service = ResearchService(
        _UnusedDb(),  # type: ignore[arg-type]
        source=FakeScholarlySourcePort(),
        verifier=_UnusedVerifier(),  # type: ignore[arg-type]
        llm=llm,
    )

    finding, warnings = await service._analyze(
        ScholarlyRecord(
            title="Benchmarking Hallucination Mitigation Techniques",
            abstract=source_passage,
        ),
        uuid4(),
        research_context={
            "idea": {
                "problems": ["Mô hình ngôn ngữ tạo ra thông tin không có căn cứ."],
                "research_questions": [
                    "Kỹ thuật nào giúp giảm lỗi bịa đặt trong trích xuất dữ liệu?"
                ],
            },
            "research_inputs": {"keywords": ["hallucination mitigation"]},
        },
    )

    assert finding.what_was_done.startswith("Nghiên cứu thực hiện")
    assert finding.method_or_feedback.startswith("Sử dụng một giao thức")
    assert finding.limitation.startswith("Đánh giá chỉ giới hạn")
    assert finding.evidence["what_was_done"].passage == source_passage
    assert warnings == []
    assert len(llm.calls) == 2
    assert "Required output language: Vietnamese (vi)" in llm.calls[0]["system"]
    assert "research-analysis-language-repair" in llm.calls[1]["system"]


@pytest.mark.asyncio
async def test_related_work_fallback_uses_vietnamese_for_a_vietnamese_idea() -> None:
    llm = FakeLlmPort(responses={"research-analysis": "not-json"})
    service = ResearchService(
        _UnusedDb(),  # type: ignore[arg-type]
        source=FakeScholarlySourcePort(),
        verifier=_UnusedVerifier(),  # type: ignore[arg-type]
        llm=llm,
    )

    finding, warnings = await service._analyze(
        ScholarlyRecord(
            title="An English Paper Title",
            abstract="The source reports one bounded evaluation.",
        ),
        uuid4(),
        research_context={
            "idea": {
                "problems": ["Kết quả trích xuất có thể chứa thông tin bịa đặt."],
                "research_questions": ["Làm thế nào để giảm lỗi này?"],
            }
        },
    )

    assert finding.what_was_done == "Trình bày nghiên cứu An English Paper Title."
    assert finding.method_or_feedback == (
        "Nguồn không nêu rõ phương pháp hoặc hình thức phản hồi."
    )
    assert finding.limitation.startswith("Metadata nguồn chưa đủ")
    assert warnings


@pytest.mark.asyncio
async def test_analysis_uses_research_context_and_separate_grounding_status() -> None:
    passage = "A verifier checks evidence for each claim."
    llm = FakeLlmPort(
        responses={
            "research-analysis": (
                '{"what_was_done":"Checks claims",'
                '"limitation":"One dataset",'
                f'"supporting_passage":"{passage}",'
                '"confidence":0.9}'
            )
        }
    )
    service = ResearchService(
        _UnusedDb(),  # type: ignore[arg-type]
        source=FakeScholarlySourcePort(),
        verifier=_UnusedVerifier(),  # type: ignore[arg-type]
        llm=llm,
    )

    finding, warnings = await service._analyze(
        ScholarlyRecord(title="Verifier", abstract=passage),
        uuid4(),
        research_context={
            "idea": {
                "cards": [{"kind": "problem", "body": {"text": "Unsupported claims"}}]
            },
            "research_inputs": {
                "keywords": ["claim verification"],
            },
        },
    )
    prompt = llm.calls[0]["prompt"]

    assert "Unsupported claims" in prompt
    assert "claim verification" in prompt
    assert "what_was_done" in llm.calls[0]["system"]
    assert "method_or_feedback" in llm.calls[0]["system"]
    assert finding.method_or_feedback == "Not stated in the source metadata."
    assert finding.grounding_status is GroundingStatus.GROUNDED
    assert warnings == []


@pytest.mark.asyncio
async def test_strict_mode_marks_abstract_only_analysis_as_warning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    passage = "A verifier checks evidence for each generated claim."
    llm = FakeLlmPort(
        responses={
            "research-analysis": json.dumps(
                {
                    "what_was_done": "Checks evidence for generated claims",
                    "method_or_feedback": "Claim-level evidence verification",
                    "limitation": "The evaluation covers one benchmark",
                    "relevance": "Directly evaluates the confirmed problem",
                    "supporting_passage": passage,
                    "evidence": {
                        field: {"passage": passage, "location": "Abstract"}
                        for field in (
                            "what_was_done",
                            "method_or_feedback",
                            "limitation",
                        )
                    },
                    "confidence": 0.8,
                }
            )
        }
    )
    service = ResearchService(
        _UnusedDb(),  # type: ignore[arg-type]
        source=FakeScholarlySourcePort(),
        verifier=_UnusedVerifier(),  # type: ignore[arg-type]
        llm=llm,
    )

    monkeypatch.setenv("RESEARCH_REQUIRE_DOWNLOADABLE_FULL_TEXT", "true")
    get_settings.cache_clear()
    try:
        finding, warnings = await service._analyze(
            ScholarlyRecord(title="Verifier", abstract=passage),
            uuid4(),
            research_context={
                "idea": {"problems": ["Unsupported generated claims"]},
                "research_inputs": {"keywords": ["claim verification"]},
            },
            document=DocumentText(text=passage, source_kind="abstract"),
        )
    finally:
        get_settings.cache_clear()

    assert finding.grounding_status is GroundingStatus.WARNING
    assert any("provider abstract" in warning for warning in warnings)


@pytest.mark.asyncio
async def test_permissive_mode_accepts_grounded_abstract_analysis(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    passage = "A verifier checks evidence for each generated claim."
    llm = FakeLlmPort(
        responses={
            "research-analysis": json.dumps(
                {
                    "what_was_done": "Checks evidence for generated claims",
                    "method_or_feedback": "Claim-level evidence verification",
                    "limitation": "The evaluation covers one benchmark",
                    "relevance": "Directly evaluates the confirmed problem",
                    "supporting_passage": passage,
                    "evidence": {
                        field: {"passage": passage, "location": "Abstract"}
                        for field in (
                            "what_was_done",
                            "method_or_feedback",
                            "limitation",
                        )
                    },
                    "confidence": 0.8,
                }
            )
        }
    )
    service = ResearchService(
        _UnusedDb(),  # type: ignore[arg-type]
        source=FakeScholarlySourcePort(),
        verifier=_UnusedVerifier(),  # type: ignore[arg-type]
        llm=llm,
    )
    monkeypatch.setenv("RESEARCH_REQUIRE_DOWNLOADABLE_FULL_TEXT", "false")
    get_settings.cache_clear()
    try:
        finding, warnings = await service._analyze(
            ScholarlyRecord(title="Verifier", abstract=passage),
            uuid4(),
            research_context={
                "idea": {"problems": ["Unsupported generated claims"]},
                "research_inputs": {"keywords": ["claim verification"]},
            },
            document=DocumentText(text=passage, source_kind="abstract"),
        )
    finally:
        get_settings.cache_clear()

    assert finding.grounding_status is GroundingStatus.GROUNDED
    assert warnings == []


@pytest.mark.asyncio
async def test_analysis_normalizes_fit_webui_field_aliases() -> None:
    source_passage = "The method uses an aggregate task score to optimize prompts."
    proposed_passage = "The method uses an aggregate score to optimize prompts."
    llm = FakeLlmPort(
        responses={
            "research-analysis": (
                '{"finding":"Optimizes prompts with an aggregate score",'
                '"feedback":"Aggregate score",'
                '"limitation":"Does not localize errors",'
                f'"supporting_passage":"{proposed_passage}",'
                '"confidence":0.8}'
            )
        }
    )
    service = ResearchService(
        _UnusedDb(),  # type: ignore[arg-type]
        source=FakeScholarlySourcePort(),
        verifier=_UnusedVerifier(),  # type: ignore[arg-type]
        llm=llm,
    )

    finding, warnings = await service._analyze(
        ScholarlyRecord(title="Prompt optimizer", abstract=source_passage),
        uuid4(),
        research_context={"idea": {}, "research_inputs": {}},
    )

    assert finding.what_was_done == "Optimizes prompts with an aggregate score"
    assert finding.method_or_feedback == "Aggregate score"
    assert finding.limitation == "Does not localize errors"
    assert finding.supporting_passage == source_passage
    assert finding.grounding_status is GroundingStatus.GROUNDED
    assert warnings == []


@pytest.mark.asyncio
async def test_analysis_uses_distinct_content_passages_instead_of_html_or_pdf_dump() -> (
    None
):
    source_text = (
        "Username Password Remember me Journal Content Search Scope Browse By Title\n"
        "Abstract\n"
        "This study evaluates reverse logistics service quality for online shoppers.\n"
        "Research Methodology\n"
        "Data were collected from 300 participants using a structured questionnaire.\n"
        "Limitations\n"
        "The convenience sample was limited to young adults in Bangalore."
    )
    llm = FakeLlmPort(
        responses={
            "research-analysis": json.dumps(
                {
                    "what_was_done": "Evaluates reverse logistics service quality.",
                    "method_or_feedback": "Uses a questionnaire with 300 participants.",
                    "limitation": "Uses a local convenience sample.",
                    "relevance": "Directly relevant.",
                    "supporting_passage": "Full text (HTML)",
                    "evidence": {
                        "what_was_done": {
                            "passage": "Full text (HTML)",
                            "location": "HTML",
                        },
                        "method_or_feedback": {
                            "passage": "Full text (PDF)",
                            "location": "PDF",
                        },
                        "limitation": {
                            "passage": "VI. RESEARCH METHODOLOGY",
                            "location": "PDF",
                        },
                    },
                    "confidence": 0.8,
                }
            )
        }
    )
    service = ResearchService(
        _UnusedDb(),  # type: ignore[arg-type]
        source=FakeScholarlySourcePort(),
        verifier=_UnusedVerifier(),  # type: ignore[arg-type]
        llm=llm,
    )

    finding, warnings = await service._analyze(
        ScholarlyRecord(title="Reverse logistics", abstract=None),
        uuid4(),
        research_context={"idea": {}, "research_inputs": {}},
        document=DocumentText(text=source_text, source_kind="full_text_html"),
    )

    evidence = finding.evidence
    assert evidence["what_was_done"].passage.startswith("This study evaluates")
    assert evidence["method_or_feedback"].passage.startswith("Data were collected")
    assert evidence["limitation"].passage.startswith("The convenience sample")
    assert evidence["what_was_done"].location == "Abstract"
    assert evidence["method_or_feedback"].location == "Research Methodology"
    assert evidence["limitation"].location == "Limitations"
    assert len({item.passage for item in evidence.values()}) == 3
    assert not any("Username Password" in item.passage for item in evidence.values())
    assert finding.grounding_status is GroundingStatus.GROUNDED
    assert warnings == []


@pytest.mark.asyncio
async def test_analysis_expands_pdf_line_fragments_to_complete_source_sentences() -> None:
    source_text = (
        "Abstract\n"
        "Dependencies between tokens (e.g., bank must be prop-\n"
        "erly contextualized) remain difficult for large language models.\n"
        "Method\n"
        "We provide correlational and causal evidence in\n"
        "controlled experiments across three model families.\n"
        "Limitations\n"
        "Errors due to missing factual knowledge (Haset et al.,\n"
        "2024) are outside the scope of this analysis."
    )
    llm = FakeLlmPort(
        responses={
            "research-analysis": json.dumps(
                {
                    "what_was_done": "Studies contextualization errors.",
                    "method_or_feedback": "Uses correlational and causal evidence.",
                    "limitation": "Does not cover missing factual knowledge.",
                    "relevance": "Directly relevant.",
                    "supporting_passage": "cies between tokens (e.g., bank must be prop-",
                    "evidence": {
                        "what_was_done": {
                            "passage": "cies between tokens (e.g., bank must be prop-",
                            "location": "Page 1",
                        },
                        "method_or_feedback": {
                            "passage": "we provide correlational and causal evidence in",
                            "location": "Page 1",
                        },
                        "limitation": {
                            "passage": "rors due to missing factual knowledge (Haset et al.,",
                            "location": "Page 1",
                        },
                    },
                    "confidence": 0.9,
                }
            )
        }
    )
    service = ResearchService(
        _UnusedDb(),  # type: ignore[arg-type]
        source=FakeScholarlySourcePort(),
        verifier=_UnusedVerifier(),  # type: ignore[arg-type]
        llm=llm,
    )

    finding, warnings = await service._analyze(
        ScholarlyRecord(title="Contextualization errors", abstract=None),
        uuid4(),
        research_context={"idea": {}, "research_inputs": {}},
        document=DocumentText(text=source_text, source_kind="full_text_pdf"),
    )

    assert finding.evidence["what_was_done"].passage == (
        "Dependencies between tokens (e.g., bank must be prop-\n"
        "erly contextualized) remain difficult for large language models."
    )
    assert finding.evidence["method_or_feedback"].passage == (
        "We provide correlational and causal evidence in\n"
        "controlled experiments across three model families."
    )
    assert finding.evidence["limitation"].passage == (
        "Errors due to missing factual knowledge (Haset et al.,\n"
        "2024) are outside the scope of this analysis."
    )
    assert finding.source_location == "Abstract"
    assert finding.evidence["method_or_feedback"].location == "Method"
    assert finding.evidence["limitation"].location == "Limitations"
    assert finding.grounding_status is GroundingStatus.GROUNDED
    assert warnings == []


@pytest.mark.asyncio
async def test_analysis_fallback_hides_validation_implementation_details() -> None:
    llm = FakeLlmPort(responses={"research-analysis": "not-json"})
    service = ResearchService(
        _UnusedDb(),  # type: ignore[arg-type]
        source=FakeScholarlySourcePort(),
        verifier=_UnusedVerifier(),  # type: ignore[arg-type]
        llm=llm,
    )

    finding, warnings = await service._analyze(
        ScholarlyRecord(title="Metadata-only source", abstract=None),
        uuid4(),
        research_context={"idea": {}, "research_inputs": {}},
    )

    assert finding.method_or_feedback == "Not stated in the source metadata."
    assert finding.limitation
    assert "not valid structured JSON" in warnings[0]
    assert "JSONDecodeError" not in warnings[0]
    assert "ValidationError" not in warnings[0]


@pytest.mark.asyncio
async def test_gap_generation_privately_analyzes_and_synthesizes_all_related_work() -> (
    None
):
    llm = FakeLlmPort()
    service = ResearchService(
        _UnusedDb(),  # type: ignore[arg-type]
        source=FakeScholarlySourcePort(_relevant_counter_records()),
        verifier=_RecordingVerifier(),
        llm=llm,
    )
    context = {
        "upstream": {
            "idea_decomposition": {
                "card_snapshot": [
                    {"kind": "problem", "body": {"text": "Unsupported claims"}}
                ]
            },
            "research_inputs": {
                "narrative": {
                    "keywords": ["claim verification"],
                    "preferred_sources": {
                        "peer_reviewed_papers": True,
                        "official_proceedings": True,
                        "author_materials": False,
                        "sourced_surveys": True,
                    },
                }
            },
            "related_work": {
                "narrative": {
                    "search_queries": ["claim verification"],
                    "candidate_count": 2,
                },
                "projected": {
                    "citations": [
                        {
                            "id": "citation-1",
                            "citation_key": "smith-2025",
                            "title": "Claim verification",
                            "abstract": "Evaluates aggregate feedback.",
                            "provider": "fixture",
                            "verification_status": "verified",
                            "metadata": {"large-provider-payload": "must-not-be-sent"},
                        },
                        {
                            "id": "citation-2",
                            "citation_key": "lee-2024",
                            "title": "Evidence feedback",
                            "abstract": "Evaluates textual feedback.",
                            "provider": "fixture",
                            "verification_status": "verified",
                        },
                    ],
                    "related_work": [
                        {
                            "citation_id": "citation-1",
                            "what_was_done": "Optimizes prompts with aggregate scores",
                            "limitation": "Uses aggregate feedback",
                            "evidence": {
                                "limitation": {
                                    "passage": "Uses aggregate feedback",
                                    "location": "Abstract",
                                }
                            },
                            "grounding_status": "grounded",
                        },
                        {
                            "citation_id": "citation-2",
                            "what_was_done": "Refines outputs with textual feedback",
                            "limitation": "Does not verify evidence per claim",
                            "evidence": {
                                "limitation": {
                                    "passage": "Does not verify evidence per claim",
                                    "location": "Abstract",
                                }
                            },
                            "grounding_status": "grounded",
                        },
                    ],
                },
            },
        },
        "working_draft": {"narrative": {}},
    }

    narrative, warnings = await service._generate_gaps(context)
    analysis_prompt = next(
        call["prompt"]
        for call in llm.calls
        if "research-gap-analysis" in call["system"]
    )
    synthesis_prompt = next(
        call["prompt"]
        for call in llm.calls
        if "research-gap-synthesis" in call["system"]
    )

    assert "Unsupported claims" in analysis_prompt
    assert "claim verification" in analysis_prompt
    assert "Uses aggregate feedback" in analysis_prompt
    assert "Does not verify evidence per claim" in analysis_prompt
    assert "large-provider-payload" not in analysis_prompt
    assert '"citation_key": "smith-2025"' in analysis_prompt
    assert '"citation_key": "lee-2024"' in analysis_prompt
    assert "Uses aggregate feedback" in synthesis_prompt
    assert "Does not verify evidence per claim" in synthesis_prompt
    assert narrative["candidate"]["supporting_citation_keys"] == [
        "smith-2025",
        "lee-2024",
    ]
    assert set(narrative["candidate"]) == {
        "statement",
        "supporting_citation_keys",
        "status",
        "search_audit",
        "evidence_check",
    }
    assert narrative["candidate"]["status"] == "candidate"
    assert narrative["candidate"]["search_audit"]["complete"] is True
    assert (
        narrative["candidate"]["search_audit"]["counter_evidence_analyzed_count"] == 2
    )
    counter_results = narrative["candidate"]["search_audit"]["counter_evidence_results"]
    assert len(counter_results) == 2
    assert all(result["title"] for result in counter_results)
    assert all(result["rationale"] for result in counter_results)
    assert narrative["candidate"]["search_audit"]["counter_evidence_assessment"]
    claim_assessments = narrative["candidate"]["search_audit"]["claim_assessments"]
    assert {item["claim_id"] for item in claim_assessments} == {"c1", "c2"}
    assert all(item["supporting_citation_keys"] for item in claim_assessments)
    assert all(item["supporting_evidence"] for item in claim_assessments)
    assert all(result["grounding_status"] == "grounded" for result in counter_results)
    assert all(result["support_status"] == "supported" for result in counter_results)
    assert '"claim_assessments"' in synthesis_prompt
    assert narrative["candidate"]["evidence_check"]["ready"] is True
    assert warnings == []


@pytest.mark.asyncio
async def test_gap_regeneration_ignores_prior_gap_and_counter_evidence() -> None:
    llm = FakeLlmPort()
    service = ResearchService(
        _UnusedDb(),  # type: ignore[arg-type]
        source=FakeScholarlySourcePort(_relevant_counter_records()),
        verifier=_RecordingVerifier(),
        llm=llm,
    )
    prior_result = {
        "result_key": "prior-counter-1",
        "title": "Existing claim-level verifier",
        "authors": ["Lee"],
        "year": 2025,
        "provider": "fixture",
        "provider_source_id": "prior-counter-1",
        "abstract": "Already verifies evidence for every generated claim.",
        "verification_status": "verified",
        "impact": "gap_not_supported",
        "rationale": "This method already addresses the proposed limitation.",
    }
    context = {
        "upstream": {
            "idea_decomposition": {
                "card_snapshot": [
                    {"kind": "problem", "body": {"text": "Unsupported claims"}}
                ]
            },
            "research_inputs": {"narrative": {"keywords": ["claim verification"]}},
            "related_work": {
                "narrative": {
                    "search_queries": ["claim verification"],
                    "candidate_count": 1,
                },
                "projected": {
                    "citations": [
                        {
                            "id": "citation-1",
                            "citation_key": "smith-2025",
                            "title": "Claim verification",
                            "abstract": "Evaluates aggregate feedback.",
                            "provider": "fixture",
                            "verification_status": "verified",
                        }
                    ],
                    "related_work": [
                        {
                            "citation_id": "citation-1",
                            "what_was_done": "Optimizes prompts with aggregate scores",
                            "limitation": "Uses aggregate feedback",
                            "evidence": {
                                "limitation": {
                                    "passage": "Uses aggregate feedback",
                                    "location": "Abstract",
                                }
                            },
                            "grounding_status": "grounded",
                        }
                    ],
                },
            },
        },
        "working_draft": {
            "card_snapshot": [
                {
                    "kind": "gap",
                    "body": {
                        "statement": "Edited saved Gap takes precedence.",
                        "search_audit": {
                            "counter_evidence_outcome": "gap_not_supported",
                            "counter_evidence_assessment": (
                                "Existing work already performs claim-level verification."
                            ),
                            "counter_evidence_results": [prior_result],
                        },
                    },
                }
            ],
            "narrative": {
                "candidate": {
                    "statement": "No system verifies evidence for every claim.",
                    "search_audit": {
                        "counter_evidence_outcome": "gap_not_supported",
                        "counter_evidence_assessment": (
                            "Existing work already performs claim-level verification."
                        ),
                        "counter_evidence_results": [prior_result],
                    },
                }
            },
        },
    }

    _, warnings = await service._generate_gaps(context)
    analysis_prompt = next(
        call["prompt"]
        for call in llm.calls
        if "research-gap-analysis" in call["system"]
    )
    synthesis_prompt = next(
        call["prompt"]
        for call in llm.calls
        if "research-gap-synthesis" in call["system"]
    )
    counter_query_prompt = next(
        call["prompt"]
        for call in llm.calls
        if "research-counter-query" in call["system"]
    )
    counter_query_system = next(
        call["system"]
        for call in llm.calls
        if "research-counter-query" in call["system"]
    )

    for prompt in (analysis_prompt, synthesis_prompt, counter_query_prompt):
        assert "gap_not_supported" not in prompt
        assert "Edited saved Gap takes precedence." not in prompt
        assert "No system verifies evidence for every claim." not in prompt
        assert "Existing claim-level verifier" not in prompt
        assert "already addresses the proposed limitation" not in prompt
        assert "previous_counter_feedback" not in prompt
    assert "required_counter_evidence_keys" not in analysis_prompt
    assert "claim-specific query" in counter_query_system
    assert warnings == []


@pytest.mark.asyncio
async def test_counter_evidence_analysis_repairs_missing_required_fields() -> None:
    records = [
        ScholarlyRecord(
            title=f"Counter evidence {identifier}",
            abstract="Evaluates an existing claim verification method.",
            provider="fixture",
            provider_source_id=identifier,
        )
        for identifier in ("first", "second")
    ]
    llm = FakeLlmPort(
        responses={
            "research-counter-analysis-repair": json.dumps(
                {
                    "outcome": "no_direct_counter_evidence",
                    "statement": "The limitation remains testable.",
                    "assessment": "Neither result directly resolves the limitation.",
                    "covered_result_keys": ["first", "second"],
                    "findings": [
                        {
                            "result_key": identifier,
                            "claim_ids": [],
                                "impact": "no_direct_counter_evidence",
                                "relevance_status": "relevant",
                                "rationale": "The abstract does not report the proposed check.",
                            "supporting_passage": (
                                "Evaluates an existing claim verification method."
                            ),
                            "source_location": "Abstract",
                        }
                        for identifier in ("first", "second")
                    ],
                }
            ),
            "research-counter-analysis": json.dumps(
                {
                    "outcome": "inconclusive",
                    "statement": "The limitation remains testable.",
                }
            ),
        }
    )
    service = ResearchService(
        _UnusedDb(),  # type: ignore[arg-type]
        source=FakeScholarlySourcePort(),
        verifier=_UnusedVerifier(),  # type: ignore[arg-type]
        llm=llm,
    )

    materials, material_warnings = await service._counter_evidence_materials(records)
    assessment, warnings = await service._assess_counter_evidence(
        idea={},
        provisional_statement="The limitation remains testable.",
        records=records,
        materials=materials,
    )

    assert assessment.outcome.value == "no_direct_counter_evidence"
    assert {item.result_key for item in assessment.findings} == {"first", "second"}
    assert material_warnings == []
    assert warnings == []
    assert len(llm.calls) == 3
    assert "research-counter-analysis-repair" in llm.calls[1]["system"]


@pytest.mark.asyncio
async def test_counter_evidence_downgrades_semantically_unsupported_rationale() -> None:
    record = ScholarlyRecord(
        title="Reasoning safety analysis",
        abstract="The study reports safety vulnerabilities in a reasoning model.",
        provider="fixture",
        provider_source_id="reasoning-safety",
    )
    llm = FakeLlmPort(
        responses={
            "research-counter-support-check": json.dumps(
                {
                    "assessments": [
                        {
                            "result_key": "reasoning-safety",
                            "support_status": "unsupported",
                        }
                    ]
                }
            )
        }
    )
    service = ResearchService(
        _UnusedDb(),  # type: ignore[arg-type]
        source=FakeScholarlySourcePort(),
        verifier=_UnusedVerifier(),  # type: ignore[arg-type]
        llm=llm,
    )

    materials, _ = await service._counter_evidence_materials([record])
    assessment, warnings = await service._assess_counter_evidence(
        idea={},
        provisional_statement="An external critic restarts reasoning at the error point.",
        records=[record],
        materials=materials,
    )

    assert assessment.outcome is CounterEvidenceOutcome.INCONCLUSIVE
    assert assessment.findings[0].support_status is CounterEvidenceSupport.UNSUPPORTED
    assert any("semantically supported" in warning for warning in warnings)


@pytest.mark.asyncio
async def test_counter_support_repairs_an_incomplete_bulk_response() -> None:
    record = ScholarlyRecord(
        title="Claim verification method",
        abstract="The study evaluates claim verification with evidence feedback.",
        provider="fixture",
        provider_source_id="claim-verification",
    )
    llm = FakeLlmPort(responses={"research-counter-support-check": "{}"})
    service = ResearchService(
        _UnusedDb(),  # type: ignore[arg-type]
        source=FakeScholarlySourcePort(),
        verifier=_UnusedVerifier(),  # type: ignore[arg-type]
        llm=llm,
    )

    materials, _ = await service._counter_evidence_materials([record])
    assessment, warnings = await service._assess_counter_evidence(
        idea={},
        provisional_statement="Claim-level verification remains limited.",
        records=[record],
        materials=materials,
    )

    assert assessment.outcome is CounterEvidenceOutcome.NO_DIRECT_COUNTER_EVIDENCE
    assert assessment.findings[0].support_status is CounterEvidenceSupport.SUPPORTED
    assert any("structured-output recovery" in warning for warning in warnings)
    assert any("schema validation failed" in warning for warning in warnings)
    assert len(llm.calls) == 3


@pytest.mark.asyncio
async def test_counter_evidence_analysis_recovers_a_second_incomplete_response() -> (
    None
):
    records = [
        ScholarlyRecord(
            title=f"Counter evidence {identifier}",
            abstract="Evaluates an existing uncertainty method.",
            provider="fixture",
            provider_source_id=identifier,
        )
        for identifier in ("first", "second")
    ]
    incomplete = json.dumps(
        {
            "outcome": "inconclusive",
            "statement": "The limitation remains provisional.",
            "assessment": "The response omitted required per-claim fields.",
            "findings": [
                {
                    "result_key": "first",
                    "rationale": "The source evaluates uncertainty.",
                    "supporting_passage": (
                        "Evaluates an existing uncertainty method."
                    ),
                    "source_location": "Abstract",
                }
            ],
        }
    )
    llm = FakeLlmPort(
        responses={
            "research-counter-analysis-repair": incomplete,
            "research-counter-analysis": incomplete,
        }
    )
    service = ResearchService(
        _UnusedDb(),  # type: ignore[arg-type]
        source=FakeScholarlySourcePort(),
        verifier=_UnusedVerifier(),  # type: ignore[arg-type]
        llm=llm,
    )
    claims = [
        _GapClaim(
            claim_id="c1",
            kind=GapClaimKind.UNRESOLVED_LIMITATION,
            statement="The limitation remains unresolved.",
            supporting_citation_keys=["source-1"],
        )
    ]

    materials, _ = await service._counter_evidence_materials(records)
    assessment, warnings = await service._assess_counter_evidence(
        idea={},
        provisional_statement="The limitation remains provisional.",
        records=records,
        materials=materials,
        gap_claims=claims,
    )

    assert assessment.outcome is CounterEvidenceOutcome.NO_DIRECT_COUNTER_EVIDENCE
    assert assessment.covered_result_keys == ["first", "second"]
    assert [item.result_key for item in assessment.findings] == ["first", "second"]
    assert all(
        item.impact is CounterEvidenceOutcome.NO_DIRECT_COUNTER_EVIDENCE
        for item in assessment.findings
    )
    assert all(
        item.grounding_status is GroundingStatus.GROUNDED
        for item in assessment.findings
    )
    assert len(assessment.claim_assessments) == 1
    assert assessment.claim_assessments[0].claim_id == "c1"
    assert assessment.claim_assessments[0].counter_evidence_result_keys == [
        "first",
        "second",
    ]
    assert warnings == []
    assert len(llm.calls) == 5


@pytest.mark.asyncio
async def test_inconclusive_counter_audit_uses_a_conservative_provisional_gap() -> None:
    incomplete = json.dumps(
        {
            "outcome": "inconclusive",
            "statement": "Raw private analysis should not be displayed.",
        }
    )
    llm = FakeLlmPort(
        responses={
            "research-counter-analysis-repair": incomplete,
            "research-counter-analysis": incomplete,
            "research-counter-source-analysis": "{}",
            "research-gap-synthesis": (
                '{"statement":"Các phương pháp tối ưu prompt hiện tại có thể sử dụng '
                'điểm tổng hoặc textual feedback. Chưa rõ việc tách output thành từng '
                'claim, kiểm tra evidence độc lập và dùng lỗi claim-level làm feedback '
                'có giúp giảm unsupported claims trong cùng ngân sách inference hay không."}'
            ),
        }
    )
    service = ResearchService(
        _UnusedDb(),  # type: ignore[arg-type]
        source=FakeScholarlySourcePort(_relevant_counter_records()),
        verifier=_RecordingVerifier(),
        llm=llm,
    )
    context = {
        "upstream": {
            "idea_decomposition": {
                "card_snapshot": [
                    {
                        "kind": "problem",
                        "body": {"text": "Tuyên bố không được hỗ trợ"},
                    }
                ]
            },
            "research_inputs": {
                "narrative": {"keywords": ["claim verification"]}
            },
            "related_work": {
                "narrative": {
                    "search_queries": ["claim verification"],
                    "candidate_count": 1,
                },
                "projected": {
                    "citations": [
                        {
                            "id": "citation-1",
                            "citation_key": "smith-2025",
                            "title": "Claim verification",
                            "abstract": "Evaluates aggregate feedback.",
                            "provider": "fixture",
                            "verification_status": "verified",
                        }
                    ],
                    "related_work": [
                        {
                            "citation_id": "citation-1",
                            "what_was_done": "Evaluates aggregate feedback",
                            "limitation": "Does not isolate claim-level errors",
                            "evidence": {
                                "limitation": {
                                    "passage": "Does not isolate claim-level errors",
                                    "location": "Abstract",
                                }
                            },
                            "grounding_status": "grounded",
                        }
                    ],
                },
            },
        },
        "working_draft": {"narrative": {}},
    }

    narrative, warnings = await service._generate_gaps(context)

    assert narrative["candidate"]["statement"] == (
        "Các phương pháp tối ưu prompt hiện tại có thể sử dụng điểm tổng hoặc textual "
        "feedback. Chưa rõ việc tách output thành từng claim, kiểm tra evidence độc lập "
        "và dùng lỗi claim-level làm feedback có giúp giảm unsupported claims trong cùng "
        "ngân sách inference hay không."
    )
    assert narrative["candidate"]["status"] == "insufficient_evidence"
    audit = narrative["candidate"]["search_audit"]
    assert audit["counter_evidence_outcome"] == "inconclusive"
    assert audit["claim_assessments"]
    assert any(
        "research-gap-synthesis" in call["system"] for call in llm.calls
    )
    assert any("Excluded" in warning for warning in warnings)


@pytest.mark.asyncio
async def test_counter_evidence_without_source_content_remains_inconclusive() -> None:
    record = ScholarlyRecord(
        title="Metadata-only counter source",
        provider="fixture",
        provider_source_id="metadata-only",
    )
    llm = FakeLlmPort(
        responses={
            "research-counter-analysis": json.dumps(
                {
                    "outcome": "inconclusive",
                    "statement": "The limitation remains testable.",
                    "assessment": "No source content was available.",
                    "covered_result_keys": ["metadata-only"],
                    "findings": [
                        {
                            "result_key": "metadata-only",
                            "claim_ids": [],
                            "impact": "inconclusive",
                            "rationale": "Metadata cannot establish content coverage.",
                            "supporting_passage": "",
                            "source_location": "Metadata only",
                        }
                    ],
                    "claim_assessments": [],
                }
            )
        }
    )
    service = ResearchService(
        _UnusedDb(),  # type: ignore[arg-type]
        source=FakeScholarlySourcePort(),
        verifier=_UnusedVerifier(),  # type: ignore[arg-type]
        llm=llm,
    )

    materials, material_warnings = await service._counter_evidence_materials([record])
    assessment, warnings = await service._assess_counter_evidence(
        idea={},
        provisional_statement="The limitation remains testable.",
        records=[record],
        materials=materials,
    )

    assert assessment.outcome is CounterEvidenceOutcome.INCONCLUSIVE
    assert assessment.findings[0].grounding_status is GroundingStatus.REJECTED
    assert any("content was unavailable" in item for item in material_warnings)
    assert any("downgraded to inconclusive" in item for item in warnings)


@pytest.mark.asyncio
async def test_gap_generation_preserves_valid_analysis_when_synthesis_times_out() -> (
    None
):
    service = ResearchService(
        _UnusedDb(),  # type: ignore[arg-type]
        source=FakeScholarlySourcePort(_relevant_counter_records()),
        verifier=_RecordingVerifier(),
        llm=_GapSynthesisTimeoutLlm(),
    )
    context = {
        "upstream": {
            "idea_decomposition": {
                "card_snapshot": [
                    {"kind": "problem", "body": {"text": "Unsupported claims"}}
                ]
            },
            "related_work": {
                "narrative": {
                    "search_queries": ["claim verification"],
                    "candidate_count": 1,
                },
                "projected": {
                    "citations": [
                        {
                            "id": "citation-1",
                            "citation_key": "smith-2025",
                            "title": "Claim verification",
                            "abstract": "Evaluates aggregate feedback.",
                            "provider": "fixture",
                            "verification_status": "verified",
                        }
                    ],
                    "related_work": [
                        {
                            "citation_id": "citation-1",
                            "what_was_done": "Optimizes prompts with aggregate scores",
                            "limitation": "Does not verify evidence per claim",
                            "evidence": {
                                "limitation": {
                                    "passage": "Does not verify evidence per claim",
                                    "location": "Abstract",
                                }
                            },
                            "grounding_status": "grounded",
                        }
                    ],
                },
            },
        },
        "working_draft": {"narrative": {}},
    }

    narrative, warnings = await service._generate_gaps(context)

    statement = narrative["candidate"]["statement"]
    assert "Prior systems optimize outputs or prompts" in statement
    assert "It remains unclear whether" in statement
    assert narrative["candidate"]["supporting_citation_keys"] == ["smith-2025"]
    assert "validated source-grounded analysis" in warnings[0]
    assert "timed out" in warnings[0]


@pytest.mark.asyncio
async def test_research_input_generation_falls_back_to_idea_keywords_on_quota_error() -> (
    None
):
    service = ResearchService(
        _UnusedDb(),  # type: ignore[arg-type]
        source=FakeScholarlySourcePort(),
        verifier=_UnusedVerifier(),  # type: ignore[arg-type]
        llm=_QuotaLlm(),
    )
    context = {
        "upstream": {
            "idea_decomposition": {
                "card_snapshot": [
                    {
                        "kind": "problem",
                        "body": {
                            "text": "Unsupported research claims reduce verification reliability."
                        },
                    }
                ]
            }
        },
        "working_draft": {"narrative": {}},
    }

    narrative, warnings = await service._generate_research_inputs(context)

    assert "unsupported claim detection" in narrative["keywords"]
    assert "claim verification" in narrative["keywords"]
    assert set(narrative) == {"keywords", "preferred_sources"}
    assert "insufficient_quota" in warnings[0]
    assert "HTTPStatusError" not in warnings[0]


@pytest.mark.asyncio
async def test_research_input_generation_normalizes_wrappers_and_filters_noise() -> (
    None
):
    llm = FakeLlmPort(
        responses={
            "research-inputs": (
                '{"result":{"suggestions":['
                '{"term":"paper"},'
                '{"term":"claim-evidence verification"},'
                '{"keyword":"e85393f1-11bb-43f0-a8f1-81018daaa6ea"},'
                '{"phrase":"unsupported claim detection"}'
                "]}}"
            )
        }
    )
    service = ResearchService(
        _UnusedDb(),  # type: ignore[arg-type]
        source=FakeScholarlySourcePort(),
        verifier=_UnusedVerifier(),  # type: ignore[arg-type]
        llm=llm,
    )
    context = {
        "upstream": {
            "idea_decomposition": {
                "card_snapshot": [
                    {
                        "id": "e85393f1-11bb-43f0-a8f1-81018daaa6ea",
                        "kind": "problem",
                        "body": {
                            "text": "LLM paper summaries contain unsupported claims."
                        },
                    },
                    {
                        "id": "question-id",
                        "kind": "research_question",
                        "body": {
                            "text": "Does claim evidence checking reduce unsupported claims under the same inference budget?"
                        },
                    },
                ]
            }
        },
        "working_draft": {"narrative": {}},
    }

    narrative, warnings = await service._generate_research_inputs(context)
    prompt = llm.calls[0]["prompt"]
    keywords = narrative["keywords"]

    assert warnings == []
    assert "claim-evidence verification" in keywords
    assert "unsupported claim detection" in keywords
    assert "paper" not in keywords
    assert not any("e85393f1" in item for item in keywords)
    assert "e85393f1" not in prompt
    assert "unsupported claims" in prompt


@pytest.mark.asyncio
async def test_research_input_schema_mismatch_uses_clean_idea_phrases_without_warning() -> (
    None
):
    llm = FakeLlmPort(responses={"research-inputs": '{"unexpected":"shape"}'})
    service = ResearchService(
        _UnusedDb(),  # type: ignore[arg-type]
        source=FakeScholarlySourcePort(),
        verifier=_UnusedVerifier(),  # type: ignore[arg-type]
        llm=llm,
    )
    context = {
        "upstream": {
            "idea_decomposition": {
                "card_snapshot": [
                    {
                        "kind": "problem",
                        "body": {
                            "text": "LLM-generated paper summaries can contain plausible statements unsupported by source evidence."
                        },
                    },
                    {
                        "kind": "research_question",
                        "body": {
                            "text": "Can claim evidence verification reduce unsupported claims within the same inference budget?"
                        },
                    },
                ]
            }
        },
        "working_draft": {"narrative": {}},
    }

    narrative, warnings = await service._generate_research_inputs(context)

    assert warnings == []
    assert "LLM paper summarization" in narrative["keywords"]
    assert "claim-evidence verification" in narrative["keywords"]
    assert "unsupported claim detection" in narrative["keywords"]
    assert "inference budget" in narrative["keywords"]
    assert not set(narrative["keywords"]) & {
        "paper",
        "source",
        "llm-generated",
        "summaries",
        "contain",
        "plausible",
        "statements",
    }


@pytest.mark.asyncio
async def test_research_inputs_do_not_pad_a_complete_model_keyword_set() -> None:
    llm = FakeLlmPort(
        responses={
            "research-inputs": (
                '{"keywords":["claim verification","factual consistency",'
                '"source attribution","summary evaluation","language model outputs"],'
                '"preferred_sources":{"peer_reviewed_papers":true,'
                '"official_proceedings":true,"author_materials":true,'
                '"sourced_surveys":true}}'
            )
        }
    )
    service = ResearchService(
        _UnusedDb(),  # type: ignore[arg-type]
        source=FakeScholarlySourcePort(),
        verifier=_UnusedVerifier(),  # type: ignore[arg-type]
        llm=llm,
    )
    context = {
        "upstream": {
            "idea_decomposition": {
                "card_snapshot": [
                    {
                        "kind": "problem",
                        "body": {"text": "Claim checklist for paper summaries"},
                    }
                ]
            }
        },
        "working_draft": {"narrative": {}},
    }

    narrative, warnings = await service._generate_research_inputs(context)

    assert warnings == []
    assert narrative["keywords"] == [
        "claim verification",
        "factual consistency",
        "source attribution",
        "summary evaluation",
        "language model outputs",
    ]


@pytest.mark.asyncio
async def test_research_inputs_reject_narrative_fragments_as_search_keywords() -> None:
    llm = FakeLlmPort(
        responses={
            "research-inputs": (
                '{"keywords":["measure","analyze phone usage","moment","user gets",'
                '"bed until sleep","sleep onset categorized",'
                '"emotional arousal stressful","stressful vs calming"]}'
            )
        }
    )
    service = ResearchService(
        _UnusedDb(),  # type: ignore[arg-type]
        source=FakeScholarlySourcePort(),
        verifier=_UnusedVerifier(),  # type: ignore[arg-type]
        llm=llm,
    )
    context = {
        "upstream": {
            "idea_decomposition": {
                "card_snapshot": [
                    {
                        "kind": "problem",
                        "body": {
                            "text": (
                                "Measure and analyze phone usage from the moment a user "
                                "gets in bed until sleep onset."
                            )
                        },
                    },
                    {
                        "kind": "research_question",
                        "body": {
                            "text": "Categorize emotional arousal as stressful vs calming."
                        },
                    },
                ]
            }
        },
        "working_draft": {"narrative": {}},
    }

    narrative, warnings = await service._generate_research_inputs(context)

    assert warnings == []
    assert narrative["keywords"] == [
        "phone usage",
        "sleep onset",
        "emotional arousal",
    ]


@pytest.mark.asyncio
async def test_research_inputs_flatten_only_core_role_aware_concepts() -> None:
    llm = FakeLlmPort(
        responses={
            "research-inputs": (
                '{"problem_concepts":['
                '{"term":"teacher administrative workload",'
                '"synonyms":["administrative burden"]},'
                '{"term":"instructional time","synonyms":[]}],'
                '"research_question_concepts":['
                '{"term":"automated grading","synonyms":["automated assessment"]}],'
                '"constraint_filters":['
                '{"term":"two-week team deadline","searchable":false},'
                '{"term":"low-resource schools","searchable":true}],'
                '"open_question_concepts":['
                '{"term":"verification workload","synonyms":[]}]} '
            )
        }
    )
    service = ResearchService(
        _UnusedDb(),  # type: ignore[arg-type]
        source=FakeScholarlySourcePort(),
        verifier=_UnusedVerifier(),  # type: ignore[arg-type]
        llm=llm,
    )
    context = {
        "upstream": {
            "idea_decomposition": {
                "card_snapshot": [
                    {
                        "kind": "problem",
                        "body": {
                            "text": "Teacher administrative workload reduces instructional time."
                        },
                    },
                    {
                        "kind": "research_question",
                        "body": {
                            "text": "Does automated grading reduce teacher workload?"
                        },
                    },
                    {
                        "kind": "constraint",
                        "body": {
                            "text": "Two-week team deadline in low-resource schools."
                        },
                    },
                    {
                        "kind": "open_question",
                        "body": {"text": "Verification workload after automation."},
                    },
                ]
            }
        },
        "working_draft": {"narrative": {}},
    }

    narrative, warnings = await service._generate_research_inputs(context)

    assert warnings == []
    assert "teacher administrative workload" in narrative["keywords"]
    assert "automated grading" in narrative["keywords"]
    assert "administrative burden" in narrative["keywords"]
    assert "two-week team deadline" not in narrative["keywords"]
    assert "low-resource schools" not in narrative["keywords"]
    assert "verification workload" not in narrative["keywords"]
    assert set(narrative) == {"keywords", "preferred_sources"}


@pytest.mark.asyncio
async def test_research_inputs_generate_english_keywords_for_a_vietnamese_idea() -> (
    None
):
    llm = FakeLlmPort(
        responses={
            "research-inputs": (
                '{"keywords":["teacher administrative workload",'
                '"teacher workload","automated grading",'
                '"automated attendance","teacher-student interaction",'
                '"instructional time"]}'
            )
        }
    )
    service = ResearchService(
        _UnusedDb(),  # type: ignore[arg-type]
        source=FakeScholarlySourcePort(),
        verifier=_UnusedVerifier(),  # type: ignore[arg-type]
        llm=llm,
    )
    context = {
        "upstream": {
            "idea_decomposition": {
                "card_snapshot": [
                    {
                        "kind": "problem",
                        "body": {
                            "text": (
                                "Giáo viên mất quá nhiều thời gian cho nhiệm vụ hành "
                                "chính, điểm danh và chấm bài khiến họ thiếu thời gian "
                                "tương tác với học sinh."
                            )
                        },
                    },
                    {
                        "kind": "research_question",
                        "body": {
                            "text": (
                                "Tự động hóa chấm điểm và điểm danh có làm tăng thời "
                                "gian giảng dạy hay không?"
                            )
                        },
                    },
                ]
            }
        },
        "working_draft": {"narrative": {}},
    }

    narrative, warnings = await service._generate_research_inputs(context)

    assert warnings == []
    assert narrative["keywords"] == [
        "teacher administrative workload",
        "teacher workload",
        "automated grading",
        "automated attendance",
        "teacher-student interaction",
        "instructional time",
    ]
    assert "Write every keyword in English" in llm.calls[0]["system"]
    assert "regardless of the input idea's language" in llm.calls[0]["system"]
    assert (
        "write every generated user-facing value in that same language"
        not in (llm.calls[0]["system"])
    )


@pytest.mark.asyncio
async def test_query_generation_does_not_invent_tools_from_context_only_keywords() -> None:
    llm = FakeLlmPort(
        responses={"research-query": '{"queries":["language model evaluation"]}'}
    )
    service = ResearchService(
        _UnusedDb(),  # type: ignore[arg-type]
        source=FakeScholarlySourcePort(),
        verifier=_UnusedVerifier(),  # type: ignore[arg-type]
        llm=llm,
    )
    idea = {"problems": ["Danh sách kiểm tra tuyên bố cho bản tóm tắt bài báo"]}

    queries, warnings = await service._generate_queries(
        ResearchInputs(
            keywords=["kiểm chứng tuyên bố", "tính nhất quán thực tế"],
        ),
        idea,
    )

    assert warnings == []
    assert all("kiểm" not in query and "tuyên" not in query for query in queries)
    assert any("language model evaluation" in query for query in queries)
    assert all('"G-Eval"' not in query for query in queries)
    assert all('"Prometheus"' not in query for query in queries)
    assert len(queries) >= 2
    assert "research-discovery" in llm.calls[0]["system"]
    assert "English regardless of the input language" in llm.calls[1]["system"]


@pytest.mark.asyncio
async def test_search_plan_repairs_invalid_json_before_using_fallback() -> None:
    class RepairingQueryLlm:
        def __init__(self) -> None:
            self.calls: list[dict[str, str]] = []

        async def complete(
            self,
            *,
            system: str,
            prompt: str,
            model: str | None = None,
        ) -> str:
            del model
            self.calls.append({"system": system, "prompt": prompt})
            if "research-query-repair" in system:
                return '{"queries":["scientific claim verification"]}'
            return "I will provide a plan, but this is not JSON."

    llm = RepairingQueryLlm()
    service = ResearchService(
        _UnusedDb(),  # type: ignore[arg-type]
        source=FakeScholarlySourcePort(),
        verifier=_UnusedVerifier(),  # type: ignore[arg-type]
        llm=llm,  # type: ignore[arg-type]
    )

    plan, warnings = await service._generate_search_plan(
        ResearchInputs(keywords=["scientific claim verification"]),
        {"problems": ["Unsupported claims in scientific summaries"]},
    )

    assert warnings == []
    assert any("scientific claim verification" in query for query in plan.queries)
    assert len(llm.calls) == 2
    assert "research-query-repair" in llm.calls[1]["system"]
    repair_payload = json.loads(llm.calls[1]["prompt"])
    assert repair_payload["previous_response"].startswith("I will provide")
    assert repair_payload["confirmed_keywords"] == [
        "scientific claim verification"
    ]


def test_search_plan_keyword_coverage_accepts_terms_in_queries() -> None:
    plan = _search_plan_from_payload(
        {
            "facets": [
                {
                    "id": "failure_mitigation",
                    "objective": "Reduce model errors",
                    "anchors": ["local prompt refinement"],
                    "queries": [
                        "structured information extraction hallucination mitigation"
                    ],
                    "min_results": 2,
                }
            ]
        },
        inputs=ResearchInputs(keywords=["hallucination mitigation"]),
        idea={},
        limit=12,
    )

    assert plan.facets[0].id == "failure_mitigation"
    assert any(
        "hallucination mitigation" in query for query in plan.facets[0].queries
    )


def test_search_plan_coverage_error_names_uncovered_keywords() -> None:
    with pytest.raises(ValueError, match="hallucination mitigation"):
        _search_plan_from_payload(
            {
                "facets": [
                    {
                        "id": "optimization_method",
                        "objective": "Optimize prompts",
                        "anchors": ["prompt optimization"],
                        "queries": ["automatic prompt optimization benchmark"],
                        "min_results": 2,
                    }
                ]
            },
            inputs=ResearchInputs(keywords=["hallucination mitigation"]),
            idea={},
            limit=12,
        )


@pytest.mark.asyncio
async def test_only_discovered_tools_become_exact_search_queries() -> None:
    candidate_title = "DSPy: Compiling Declarative Language Model Calls"
    llm = FakeLlmPort(
        responses={
            "research-discovery": json.dumps(
                {
                    "tools_and_frameworks": ["DSPy", "TextGrad"],
                    "techniques": ["automatic prompt optimization"],
                    "candidate_work_titles": [candidate_title],
                    "aliases": ["textual gradient optimization"],
                }
            ),
            "research-query": '{"queries":["automatic prompt optimization"]}',
        }
    )
    service = ResearchService(
        _UnusedDb(),  # type: ignore[arg-type]
        source=FakeScholarlySourcePort(),
        verifier=_UnusedVerifier(),  # type: ignore[arg-type]
        llm=llm,
    )

    queries, warnings = await service._generate_queries(
        ResearchInputs(keywords=["iterative prompt optimization"]),
        {"problems": ["Prompt refinement from local error feedback"]},
    )

    assert warnings == []
    assert queries == [
        '"DSPy"',
        '"TextGrad"',
        '"OPRO"',
        '"ProTeGi"',
    ]
    assert f'"{candidate_title}"' not in queries
    assert all(" AND " not in query for query in queries)
    query_call = next(call for call in llm.calls if "research-query" in call["system"])
    assert candidate_title in query_call["prompt"]
    assert "evaluation context" in query_call["system"]


@pytest.mark.asyncio
async def test_query_count_equals_discovered_tool_count_without_fixed_cap() -> None:
    tools = [
        "OpenAI Evaluator",
        "Ragas",
        "DeepEval",
        "LLM-as-a-Judge",
        "LangChain",
        "DSPy",
        "TextGrad",
        "OPRO",
        "ProTeGi",
        "Guidance",
    ]
    candidate_title = "Judging LLM-as-a-Judge with MT-Bench and Chatbot Arena"
    llm = FakeLlmPort(
        responses={
            "research-discovery": json.dumps(
                {
                    "tools_and_frameworks": tools,
                    "techniques": ["automatic prompt optimization"],
                    "candidate_work_titles": [candidate_title],
                    "aliases": [],
                }
            ),
            "research-query": '{"queries":["automatic prompt optimization"]}',
        }
    )
    service = ResearchService(
        _UnusedDb(),  # type: ignore[arg-type]
        source=FakeScholarlySourcePort(),
        verifier=_UnusedVerifier(),  # type: ignore[arg-type]
        llm=llm,
    )
    queries, warnings = await service._generate_queries(
        ResearchInputs(keywords=["iterative prompt optimization"]),
        {"problems": ["Prompt refinement from local error feedback"]},
    )

    assert warnings == []
    assert queries == [f'"{tool}"' for tool in tools]
    assert len(queries) == len(tools)
    assert f'"{candidate_title}"' not in queries


@pytest.mark.asyncio
async def test_supporting_keywords_rank_papers_but_do_not_generate_tools() -> None:
    llm = FakeLlmPort(
        responses={
            "research-discovery": json.dumps(
                {
                    "tool_discovery_keywords": ["iterative prompt optimization"],
                    "supporting_context_keywords": [
                        "LLM-as-a-Judge evaluation",
                        "scientific information extraction",
                    ],
                    "tools_and_frameworks": ["DSPy", "G-Eval", "Prometheus"],
                    "techniques": ["automatic prompt optimization"],
                    "candidate_work_titles": [],
                    "aliases": [],
                }
            ),
            "research-query": '{"queries":["automatic prompt optimization"]}',
        }
    )
    service = ResearchService(
        _UnusedDb(),  # type: ignore[arg-type]
        source=FakeScholarlySourcePort(),
        verifier=_UnusedVerifier(),  # type: ignore[arg-type]
        llm=llm,
    )
    inputs = ResearchInputs(
        keywords=[
            "iterative prompt optimization",
            "LLM-as-a-Judge evaluation",
            "scientific information extraction",
        ]
    )

    discovery, warnings = await service._generate_discovery_expansion(inputs, {})
    queries, query_warnings = await service._generate_search_plan(
        inputs,
        {},
        discovery=discovery,
    )

    assert warnings == []
    assert query_warnings == []
    assert discovery.tool_discovery_keywords == ["iterative prompt optimization"]
    assert discovery.supporting_context_keywords == [
        "LLM-as-a-Judge evaluation",
        "scientific information extraction",
    ]
    assert "G-Eval" not in discovery.tools_and_frameworks
    assert "Prometheus" not in discovery.tools_and_frameworks
    assert queries.queries == ['"DSPy"', '"TextGrad"', '"OPRO"', '"ProTeGi"']


@pytest.mark.asyncio
async def test_provider_query_plan_uses_one_multi_query_call_when_available() -> None:
    class MultiQuerySource:
        def __init__(self) -> None:
            self.queries: list[str] = []

        async def search_many(
            self,
            *,
            queries: list[str],
            preferences: SourcePreferences | None = None,
            limit: int = 10,
        ) -> list[ScholarlyRecord]:
            del preferences, limit
            self.queries = queries
            return [ScholarlyRecord(title="Batched result")]

        async def search(self, **_kwargs: object) -> list[ScholarlyRecord]:
            raise AssertionError("Individual query search should not be used")

        async def get_source(self, *, identifier: str) -> ScholarlyRecord | None:
            del identifier
            return None

    source = MultiQuerySource()
    service = ResearchService(
        _UnusedDb(),  # type: ignore[arg-type]
        source=source,
        verifier=_UnusedVerifier(),  # type: ignore[arg-type]
        llm=FakeLlmPort(),
    )

    records, failures = await service._search_provider_queries(
        queries=["claim verification", "fact checking"],
        preferences=SourcePreferences(),
        limit=20,
    )

    assert source.queries == ["claim verification", "fact checking"]
    assert failures == []
    assert records[0].metadata["discovery_queries"] == []


@pytest.mark.asyncio
async def test_query_generation_preserves_multiple_model_queries_and_expands_them() -> (
    None
):
    model_queries = [
        "claim evidence verification",
        "unsupported claim detection",
        "claim verification benchmark",
    ]
    llm = FakeLlmPort(
        responses={"research-query": json.dumps({"queries": model_queries})}
    )
    service = ResearchService(
        _UnusedDb(),  # type: ignore[arg-type]
        source=FakeScholarlySourcePort(),
        verifier=_UnusedVerifier(),  # type: ignore[arg-type]
        llm=llm,
    )

    queries, warnings = await service._generate_queries(
        ResearchInputs(
            keywords=["claim evidence verification", "unsupported claim detection"]
        ),
        {"problems": ["Unsupported claims in scholarly summaries"]},
    )

    assert warnings == []
    assert len(set(model_queries) & set(queries)) >= 2
    assert len(queries) >= 4


@pytest.mark.asyncio
async def test_listwise_reranker_reorders_candidates_and_preserves_heuristic_metadata() -> (
    None
):
    first = ScholarlyRecord(
        title="Broad language model evaluation",
        abstract="A general evaluation survey.",
        provider="fixture",
        provider_source_id="broad",
        metadata={"retrieval_score": 0.8},
    )
    second = ScholarlyRecord(
        title="Claim evidence verification for paper summaries",
        abstract="Evaluates claim-level evidence checks for scholarly summaries.",
        provider="fixture",
        provider_source_id="direct",
        metadata={"retrieval_score": 0.7},
    )
    llm = FakeLlmPort(
        responses={
            "research-rerank": json.dumps(
                {
                    "rankings": [
                        {"result_key": "direct", "relevance_score": 0.95},
                        {"result_key": "broad", "relevance_score": 0.25},
                    ]
                }
            )
        }
    )
    service = ResearchService(
        _UnusedDb(),  # type: ignore[arg-type]
        source=FakeScholarlySourcePort(),
        verifier=_UnusedVerifier(),  # type: ignore[arg-type]
        llm=llm,
    )

    outcome = await service._rerank_records(
        [first, second],
        idea={"problems": ["Unsupported claims in paper summaries"]},
        inputs=ResearchInputs(keywords=["claim evidence verification"]),
        queries=["claim evidence verification paper summaries"],
        objective="Build a directly relevant Related Work comparison.",
    )

    assert outcome.applied is True
    assert [record.provider_source_id for record in outcome.records] == [
        "direct",
        "broad",
    ]
    assert second.metadata["heuristic_rank"] == 2
    assert second.metadata["heuristic_retrieval_score"] == 0.7
    assert second.metadata["reranker_rank"] == 1
    assert second.metadata["reranker_score"] == 0.95
    assert second.metadata["portfolio_rank"] == 1
    assert second.metadata["selection_rule"] == "quality_diversity_portfolio"


def test_portfolio_order_prefers_new_coverage_over_a_near_duplicate() -> None:
    relationship_query = "claim evidence verification"
    calibration_query = "confidence calibration benchmark"
    primary = ScholarlyRecord(
        title="Claim evidence verification for scholarly summaries",
        abstract=(
            "Evaluates claim evidence verification for scholarly summaries with "
            "claim-level factuality outcomes."
        ),
        provider="fixture",
        provider_source_id="primary",
        metadata={
            "reranker_score": 0.95,
            "discovery_queries": [relationship_query],
            "publicationTypes": ["JournalArticle"],
        },
    )
    duplicate = ScholarlyRecord(
        title="Claim evidence verification for scholarly summaries extended",
        abstract=(
            "Evaluates claim evidence verification for scholarly summaries with "
            "claim-level factuality outcomes."
        ),
        provider="fixture",
        provider_source_id="duplicate",
        metadata={
            "reranker_score": 0.92,
            "discovery_queries": [relationship_query],
            "publicationTypes": ["JournalArticle"],
        },
    )
    benchmark = ScholarlyRecord(
        title="Confidence calibration benchmark for retrieval systems",
        abstract=(
            "Benchmarks confidence calibration and user decisions under conflicting "
            "retrieved evidence."
        ),
        provider="fixture",
        provider_source_id="benchmark",
        metadata={
            "reranker_score": 0.82,
            "discovery_queries": [calibration_query],
            "publicationTypes": ["Conference"],
        },
    )

    ordered = _portfolio_order_records(
        [primary, duplicate, benchmark],
        queries=[relationship_query, calibration_query],
    )

    assert [record.provider_source_id for record in ordered] == [
        "primary",
        "benchmark",
        "duplicate",
    ]
    assert benchmark.metadata["portfolio_query_indexes"] == [1]
    assert duplicate.metadata["portfolio_redundancy"] > 0.8


@pytest.mark.asyncio
async def test_listwise_reranker_repairs_invalid_model_json() -> None:
    records = [
        ScholarlyRecord(
            title=f"Candidate {identifier}",
            provider="fixture",
            provider_source_id=identifier,
            metadata={"retrieval_score": score},
        )
        for identifier, score in (("first", 0.8), ("second", 0.7))
    ]
    llm = FakeLlmPort(
        responses={
            "research-rerank-repair": json.dumps(
                {
                    "rankings": [
                        {"result_key": "second", "relevance_score": 0.9},
                        {"result_key": "first", "relevance_score": 0.4},
                    ]
                }
            ),
            "research-rerank": "The ranking is: second, then first.",
        }
    )
    service = ResearchService(
        _UnusedDb(),  # type: ignore[arg-type]
        source=FakeScholarlySourcePort(),
        verifier=_UnusedVerifier(),  # type: ignore[arg-type]
        llm=llm,
    )

    outcome = await service._rerank_records(
        records,
        idea={},
        inputs=ResearchInputs(),
        queries=["evidence review"],
        objective="Build Related Work.",
    )

    assert outcome.applied is True
    assert not outcome.warnings
    assert [record.provider_source_id for record in outcome.records] == [
        "second",
        "first",
    ]
    assert len(llm.calls) == 2
    assert "research-rerank-repair" in llm.calls[1]["system"]


@pytest.mark.asyncio
async def test_listwise_reranker_falls_back_when_candidate_coverage_is_incomplete() -> (
    None
):
    records = [
        ScholarlyRecord(
            title=f"Candidate {identifier}",
            provider="fixture",
            provider_source_id=identifier,
            metadata={"retrieval_score": score},
        )
        for identifier, score in (("first", 0.8), ("second", 0.7))
    ]
    service = ResearchService(
        _UnusedDb(),  # type: ignore[arg-type]
        source=FakeScholarlySourcePort(),
        verifier=_UnusedVerifier(),  # type: ignore[arg-type]
        llm=FakeLlmPort(
            responses={
                "research-rerank": (
                    '{"rankings":[{"result_key":"second","relevance_score":0.9}]}'
                )
            }
        ),
    )

    outcome = await service._rerank_records(
        records,
        idea={},
        inputs=ResearchInputs(),
        queries=["evidence review"],
        objective="Build Related Work.",
    )

    assert outcome.applied is False
    assert outcome.records == records
    assert outcome.warnings and "heuristic order" in outcome.warnings[0]


@pytest.mark.asyncio
async def test_counter_query_generation_accepts_json_after_reasoning_wrapper() -> None:
    llm = FakeLlmPort(
        responses={
            "research-counter-query": (
                "<think>Generate falsification branches.</think>\n"
                '```json\n{"queries":["claim verification competing methods",'
                '"claim verification equivalent approach",'
                '"claim verification replication benchmark",'
                '"claim verification conflicting findings"]}\n```'
            )
        }
    )
    service = ResearchService(
        _UnusedDb(),  # type: ignore[arg-type]
        source=FakeScholarlySourcePort([]),
        verifier=_UnusedVerifier(),  # type: ignore[arg-type]
        llm=llm,
    )

    result = await service._search_counter_evidence(
        idea={"problems": ["Unsupported claims"]},
        inputs=ResearchInputs(keywords=["claim verification"]),
        provisional_statement="It remains unclear whether verification reduces errors.",
        related_work_queries=["claim verification"],
        preferences=SourcePreferences(),
    )

    assert result.queries[0] == "claim verification competing methods"
    assert not any("deterministic English queries" in item for item in result.warnings)


@pytest.mark.asyncio
async def test_counter_evidence_search_selects_five_portfolio_results() -> None:
    records = [
        ScholarlyRecord(
            title=f"Claim evidence verification benchmark {index}",
            abstract=(
                "Evaluates claim evidence verification and unsupported claim detection "
                f"with comparison protocol {index}."
            ),
            provider="fixture",
            provider_source_id=f"relevant-{index}",
        )
        for index in range(7)
    ] + [
        ScholarlyRecord(
            title="Unrelated image segmentation",
            abstract="Segments medical images.",
            provider="fixture",
            provider_source_id="irrelevant",
        )
    ]
    verifier = _RecordingVerifier()
    service = ResearchService(
        _UnusedDb(),  # type: ignore[arg-type]
        source=FakeScholarlySourcePort(records),
        verifier=verifier,  # type: ignore[arg-type]
        llm=FakeLlmPort(),
    )

    result = await service._search_counter_evidence(
        idea={"problems": ["Unsupported claims in scholarly summaries"]},
        inputs=ResearchInputs(
            keywords=["claim evidence verification", "unsupported claim detection"]
        ),
        provisional_statement=(
            "It remains unclear whether claim-level evidence feedback reduces "
            "unsupported claims."
        ),
        related_work_queries=["claim evidence verification"],
        preferences=SourcePreferences(),
    )

    assert result.complete is True
    assert len(result.queries) >= 3
    assert result.candidate_count == 7
    assert len(result.records) == 5
    assert len(result.selected_records) == 5
    assert len(verifier.records) == 5
    assert all(
        record.metadata["counter_verification_status"] == "verified"
        for record in result.records
    )
    assert all(
        "Claim evidence verification" in record.title for record in result.records
    )
    assert [record.metadata["portfolio_rank"] for record in result.records] == [
        1,
        2,
        3,
        4,
        5,
    ]


@pytest.mark.asyncio
async def test_counter_evidence_verification_backfills_a_rejected_top_source() -> None:
    records = [
        ScholarlyRecord(
            title=f"Claim evidence verification approach {index}",
            abstract=(
                "Evaluates claim evidence verification and unsupported claim detection "
                f"with distinct protocol {index}."
            ),
            provider="fixture",
            provider_source_id=f"candidate-{index}",
        )
        for index in range(6)
    ]

    class RejectFirstVerifier:
        def __init__(self) -> None:
            self.records: list[ScholarlyRecord] = []

        async def verify(self, *, citation: ScholarlyRecord) -> VerificationResult:
            self.records.append(citation)
            if citation.provider_source_id == "candidate-0":
                return VerificationResult(status=VerificationStatus.REJECTED)
            return VerificationResult(
                status=VerificationStatus.VERIFIED,
                record=citation,
            )

    verifier = RejectFirstVerifier()
    service = ResearchService(
        _UnusedDb(),  # type: ignore[arg-type]
        source=FakeScholarlySourcePort(records),
        verifier=verifier,  # type: ignore[arg-type]
        llm=FakeLlmPort(),
    )

    result = await service._search_counter_evidence(
        idea={"problems": ["Unsupported claims in scholarly summaries"]},
        inputs=ResearchInputs(keywords=["claim evidence verification"]),
        provisional_statement=(
            "It remains unclear whether claim evidence verification reduces errors."
        ),
        related_work_queries=["claim evidence verification"],
        preferences=SourcePreferences(),
    )

    assert len(result.records) == 5
    assert "candidate-0" not in {record.provider_source_id for record in result.records}
    assert len(verifier.records) == 6
    assert any("Rejected and backfilled 1" in warning for warning in result.warnings)


@pytest.mark.asyncio
async def test_query_generation_failure_never_sends_vietnamese_to_provider() -> None:
    service = ResearchService(
        _UnusedDb(),  # type: ignore[arg-type]
        source=FakeScholarlySourcePort(),
        verifier=_UnusedVerifier(),  # type: ignore[arg-type]
        llm=_QuotaLlm(),
    )

    queries, warnings = await service._generate_queries(
        ResearchInputs(keywords=["kiểm chứng tuyên bố"]),
        {"problems": ["Tóm tắt bài báo có tuyên bố không được hỗ trợ"]},
    )

    assert all("kiểm" not in query and "tuyên" not in query for query in queries)
    assert len(queries) >= 2
    assert warnings and "conservative fallback" in warnings[0]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "model_query",
    ["kiểm chứng tuyên bố", "kiem chung tuyen bo"],
)
async def test_query_generation_rejects_vietnamese_model_output(
    model_query: str,
) -> None:
    service = ResearchService(
        _UnusedDb(),  # type: ignore[arg-type]
        source=FakeScholarlySourcePort(),
        verifier=_UnusedVerifier(),  # type: ignore[arg-type]
        llm=FakeLlmPort(
            responses={"research-query": f'{{"queries":["{model_query}"]}}'}
        ),
    )

    queries, warnings = await service._generate_queries(
        ResearchInputs(keywords=["kiểm chứng tuyên bố"]),
        {"problems": ["Tóm tắt có tuyên bố không được hỗ trợ"]},
    )

    assert all("kiểm" not in query and "tuyên" not in query for query in queries)
    assert all("kiem" not in query and "tuyen" not in query for query in queries)
    assert len(queries) >= 2
    assert warnings and "conservative fallback" in warnings[0]


def test_query_composition_covers_all_keywords_without_a_five_query_cap() -> None:
    keywords = [
        "paper summarization",
        "claim decomposition",
        "evidence verification",
        "unsupported claims",
        "iterative prompt optimization",
        "equal inference budget",
    ]

    queries = _compose_search_queries(
        ["language model evaluation"],
        ResearchInputs(keywords=keywords),
        {},
    )

    assert queries[0] == "language model evaluation"
    assert all(any(keyword in query for query in queries) for keyword in keywords)
    assert not any(query in keywords for query in queries)


def test_query_composition_separates_open_questions_and_ignores_constraints() -> None:
    queries = _compose_search_queries(
        [],
        ResearchInputs(keywords=["automated grading", "teacher workload"]),
        {
            "problems": ["Teacher workload from automated grading"],
            "constraints": ["Two-week team deadline", "Low-resource schools"],
            "open_questions": ["verification workload"],
        },
    )

    assert any("verification workload" in query for query in queries)
    assert all("two-week team deadline" not in query.casefold() for query in queries)
    assert all("low-resource schools" not in query.casefold() for query in queries)


def test_search_plan_groups_confirmed_keywords_into_distinct_facets() -> None:
    plan = _fallback_search_plan(
        ResearchInputs(
            keywords=[
                "LLM fabrication",
                "LLM-as-a-Judge evaluation",
                "iterative prompt optimization",
                "scientific information extraction",
                "hallucination mitigation",
                "ground truth verification",
            ]
        ),
        {},
        limit=12,
    )

    assert [facet.id for facet in plan.facets] == [
        "implementation_tools",
        "evaluation_verification",
        "task_domain",
        "failure_mitigation",
    ]
    assert all(facet.min_results == 2 for facet in plan.facets)
    assert all(len(facet.queries) == 2 for facet in plan.facets)
    assert len(plan.queries) == 8
    tool_queries = plan.facets[0].queries
    assert tool_queries == ['"DSPy"', '"TextGrad"']


def test_facet_balancing_prioritizes_coverage_before_global_tail() -> None:
    plan = _fallback_search_plan(
        ResearchInputs(
            keywords=["iterative prompt optimization", "scientific information extraction"]
        ),
        {},
        limit=8,
    )
    records = [
        ScholarlyRecord(
            title="DSPy optimization framework",
            metadata={
                "search_facets": ["implementation_tools"],
                "implementation_tool_mentions": ["DSPy"],
            },
        ),
        ScholarlyRecord(
            title="TextGrad optimization framework",
            metadata={
                "search_facets": ["implementation_tools"],
                "implementation_tool_mentions": ["TextGrad"],
            },
        ),
        ScholarlyRecord(
            title="Extraction benchmark",
            metadata={"search_facets": ["task_domain"]},
        ),
        ScholarlyRecord(
            title="Extraction system",
            metadata={"search_facets": ["task_domain"]},
        ),
    ]

    ordered = _facet_balanced_records(records, plan)

    assert [record.title for record in ordered[:4]] == [
        "DSPy optimization framework",
        "Extraction benchmark",
        "TextGrad optimization framework",
        "Extraction system",
    ]


def test_search_facet_coverage_detects_only_missing_facets() -> None:
    plan = _fallback_search_plan(
        ResearchInputs(
            keywords=["iterative prompt optimization", "scientific information extraction"]
        ),
        {},
        limit=8,
    )
    records = [
        ScholarlyRecord(
            title="DSPy prompt optimization with textual feedback",
            abstract="An iterative prompt optimization method.",
        ),
        ScholarlyRecord(
            title="TextGrad automatic prompt refinement",
            abstract="An iterative prompt optimization system using feedback.",
        ),
    ]
    _tag_search_facets(records, plan)

    missing = _missing_search_facets(records, plan)

    assert [facet.id for facet in missing] == ["task_domain"]


def test_tool_specific_papers_rank_above_concept_only_matches() -> None:
    inputs = ResearchInputs(keywords=["iterative prompt optimization"])
    plan = _fallback_search_plan(inputs, {}, limit=4)
    tool_query = plan.facets[0].queries[1]
    conceptual = ScholarlyRecord(
        title="A survey of iterative prompt optimization",
        abstract="Reviews iterative prompt optimization concepts and terminology.",
    )
    tool_specific = ScholarlyRecord(
        title="TextGrad: Automatic Differentiation via Text",
        abstract="TextGrad is an optimization framework using textual feedback.",
        metadata={"discovery_queries": [tool_query]},
    )
    records = [conceptual, tool_specific]
    _tag_search_facets(records, plan)

    ranked, discarded = _rank_relevant_records(
        records,
        inputs=inputs,
        idea={},
        queries=plan.queries,
    )

    assert discarded == 0
    assert ranked[0].title.startswith("TextGrad")
    assert ranked[0].metadata["implementation_tool_mentions"] == ["TextGrad"]
    assert ranked[0].metadata["tool_specific_relevance"] is True


def test_related_work_ranking_filters_generic_results_and_covers_idea_concepts() -> (
    None
):
    generic = ScholarlyRecord(
        title="Claim verification for language models",
        abstract="Verifies factual claims in generated text.",
    )
    checklist = ScholarlyRecord(
        title="A claim checklist for scientific writing",
        abstract="Evaluates a structured checklist for individual claims.",
    )
    summaries = ScholarlyRecord(
        title="Evaluating paper summaries",
        abstract="Measures factual quality in summaries of scholarly papers.",
    )

    ranked, discarded = _rank_relevant_records(
        [generic, summaries, checklist],
        inputs=ResearchInputs(
            keywords=["claim checklist", "paper summaries", "claim verification"],
        ),
        idea={"problems": ["Claim checklist for paper summaries"]},
        queries=["claim verification language models"],
    )

    assert discarded == 0
    assert {record.title for record in ranked[:2]} == {
        checklist.title,
        summaries.title,
    }


def test_related_work_ranking_does_not_filter_without_confirmed_anchors() -> None:
    records = [
        ScholarlyRecord(title="Iterative refinement with feedback"),
        ScholarlyRecord(title="Prompt optimization benchmark"),
    ]

    ranked, discarded = _rank_relevant_records(
        records,
        inputs=ResearchInputs(),
        idea={},
        queries=["related work survey"],
    )

    assert ranked == records
    assert discarded == 0


def test_related_work_ranking_uses_english_queries_for_vietnamese_idea() -> None:
    strong = ScholarlyRecord(
        title="Evidence verification for scientific paper summaries",
        abstract="A claim-level checklist detects unsupported statements.",
    )
    weak = ScholarlyRecord(
        title="General language model evaluation",
        abstract="A broad benchmark of generated text.",
    )

    ranked, discarded = _rank_relevant_records(
        [weak, strong],
        inputs=ResearchInputs(keywords=["kiểm chứng tuyên bố"]),
        idea={"problems": ["Tuyên bố không được hỗ trợ trong tóm tắt bài báo"]},
        queries=[
            '"evidence verification" AND "scientific paper summaries"',
            '"unsupported statements" AND "claim-level checklist"',
        ],
        require_domain_match=True,
    )

    assert [record.title for record in ranked] == [strong.title]
    assert discarded == 1


def test_counter_queries_use_confirmed_citation_method_identifiers() -> None:
    citations = [
        {"title": "Cog-CoT: A Cognitive Chain-of-Thought Framework"},
        {"title": "VisPath: Visual Reasoning with Verified Paths"},
    ]

    assert _citation_method_queries(citations) == ['"Cog-CoT"', '"VisPath"']


def test_counter_queries_ignore_ambiguous_or_implementation_identifiers() -> None:
    citations = [{"title": "CoT evaluation with MAX_RETRY in LLM pipelines"}]

    assert _citation_method_queries(citations) == []


def test_counter_ranking_rejects_ambiguous_cot_and_retry_domain_matches() -> None:
    relevant = ScholarlyRecord(
        title="External critics for chain-of-thought reasoning in language models",
        abstract="Evaluates feedback that verifies intermediate LLM reasoning steps.",
    )
    cost_of_travelling = ScholarlyRecord(
        title="Cost of Travelling and pavement maintenance",
        abstract="Models road costs with retries in a transport simulation.",
    )
    cot_preh = ScholarlyRecord(
        title="Cot preh utilization in agricultural soils",
        abstract="Studies crop yield and irrigation treatments.",
    )

    ranked, discarded = _rank_relevant_records(
        [cost_of_travelling, cot_preh, relevant],
        inputs=ResearchInputs(keywords=["LLM reasoning verification"]),
        idea={"problems": ["Unsupported chain-of-thought reasoning in LLMs"]},
        queries=[
            '"chain of thought" external critic language model',
            'retry verification for LLM reasoning',
        ],
        require_domain_match=True,
    )

    assert [record.title for record in ranked] == [relevant.title]
    assert discarded == 2


@pytest.mark.asyncio
async def test_counter_audit_backfills_a_source_without_grounded_content() -> None:
    class RecordingDocumentTextSource:
        def __init__(self) -> None:
            self.calls: list[str] = []

        async def fetch_text(
            self,
            *,
            record: ScholarlyRecord,
        ) -> DocumentText | None:
            result_key = str(record.provider_source_id)
            self.calls.append(result_key)
            await asyncio.sleep(0)
            if result_key == "candidate-0":
                return None
            return DocumentText(
                text=str(record.abstract or ""),
                source_kind="full_text_html",
            )

    records = [
        ScholarlyRecord(
            title=f"Claim verification method {index}",
            abstract=(
                None
                if index == 0
                else f"Method {index} evaluates claim verification at each reasoning step."
            ),
            provider="fixture",
            provider_source_id=f"candidate-{index}",
        )
        for index in range(6)
    ]
    verifier = _RecordingVerifier()
    document_text_source = RecordingDocumentTextSource()
    service = ResearchService(
        _UnusedDb(),  # type: ignore[arg-type]
        source=FakeScholarlySourcePort(records),
        verifier=verifier,  # type: ignore[arg-type]
        llm=FakeLlmPort(),
        document_text_source=document_text_source,
    )
    search = _CounterEvidenceSearch(
        queries=["claim verification reasoning step"],
        records=records[:5],
        selected_records=records[:5],
        candidate_records=records,
        candidate_count=6,
        complete=True,
        warnings=[],
    )
    claims = [
        _GapClaim(
            claim_id="c1",
            kind=GapClaimKind.UNRESOLVED_LIMITATION,
            statement="The step-level limitation remains unresolved.",
            supporting_citation_keys=["source-1"],
        )
    ]

    selected, materials, assessment, warnings = (
        await service._audit_counter_evidence_with_backfill(
            idea={},
            provisional_statement="The limitation remains unresolved.",
            gap_claims=claims,
            counter_search=search,
            session_id=None,
        )
    )

    selected_ids = {record.provider_source_id for record in selected}
    assert "candidate-0" not in selected_ids
    assert "candidate-5" in selected_ids
    assert len(materials) == 5
    assert assessment.outcome is CounterEvidenceOutcome.NO_DIRECT_COUNTER_EVIDENCE
    assert any("Backfilled 1" in warning for warning in warnings)
    assert set(document_text_source.calls) == {
        f"candidate-{index}" for index in range(6)
    }
    assert all(
        document_text_source.calls.count(f"candidate-{index}") == 1
        for index in range(6)
    )


@pytest.mark.asyncio
async def test_counter_audit_stops_after_one_backfill_round() -> None:
    records = [
        ScholarlyRecord(
            title=f"Claim verification method {index}",
            abstract=(
                None
                if index in {0, 5}
                else f"Method {index} evaluates claim verification evidence."
            ),
            provider="fixture",
            provider_source_id=f"candidate-{index}",
        )
        for index in range(7)
    ]
    verifier = _RecordingVerifier()
    service = ResearchService(
        _UnusedDb(),  # type: ignore[arg-type]
        source=FakeScholarlySourcePort(records),
        verifier=verifier,  # type: ignore[arg-type]
        llm=FakeLlmPort(),
    )
    search = _CounterEvidenceSearch(
        queries=["claim verification evidence"],
        records=records[:5],
        selected_records=records[:5],
        candidate_records=records,
        candidate_count=len(records),
        complete=True,
        warnings=[],
    )
    claims = [
        _GapClaim(
            claim_id="c1",
            kind=GapClaimKind.UNRESOLVED_LIMITATION,
            statement="The claim-verification limitation remains unresolved.",
            supporting_citation_keys=["source-1"],
        )
    ]

    selected, _materials, _assessment, warnings = (
        await service._audit_counter_evidence_with_backfill(
            idea={},
            provisional_statement=claims[0].statement,
            gap_claims=claims,
            counter_search=search,
            session_id=None,
        )
    )

    assert [record.provider_source_id for record in verifier.records] == [
        "candidate-5"
    ]
    assert {record.provider_source_id for record in selected} == {
        f"candidate-{index}" for index in range(1, 5)
    }
    assert any("Backfilled 1" in warning for warning in warnings)
    assert any("Excluded 1" in warning for warning in warnings)


@pytest.mark.asyncio
async def test_counter_audit_excludes_grounded_but_irrelevant_sources() -> None:
    irrelevant = ScholarlyRecord(
        title="Cost of Travelling with pavement retries",
        abstract="This transport study estimates road costs and pavement maintenance.",
        provider="fixture",
        provider_source_id="transport",
    )
    relevant = ScholarlyRecord(
        title="External critics for language-model reasoning",
        abstract="This study verifies intermediate LLM reasoning with external feedback.",
        provider="fixture",
        provider_source_id="llm-reasoning",
    )
    service = ResearchService(
        _UnusedDb(),  # type: ignore[arg-type]
        source=FakeScholarlySourcePort([irrelevant, relevant]),
        verifier=_RecordingVerifier(),
        llm=_DomainAwareCounterLlm(),
    )
    search = _CounterEvidenceSearch(
        queries=['"chain of thought" external critic language model'],
        records=[irrelevant, relevant],
        selected_records=[irrelevant, relevant],
        candidate_records=[irrelevant, relevant],
        candidate_count=2,
        complete=True,
        warnings=[],
    )
    claims = [
        _GapClaim(
            claim_id="c1",
            kind=GapClaimKind.UNRESOLVED_LIMITATION,
            statement="External verification of intermediate LLM reasoning is unresolved.",
            supporting_citation_keys=["source-1"],
        )
    ]

    selected, _materials, assessment, warnings = (
        await service._audit_counter_evidence_with_backfill(
            idea={"problems": ["Unsupported LLM reasoning"]},
            provisional_statement=claims[0].statement,
            gap_claims=claims,
            counter_search=search,
            session_id=None,
        )
    )

    assert [record.provider_source_id for record in selected] == ["llm-reasoning"]
    assert all(
        finding.relevance_status is CounterEvidenceRelevance.RELEVANT
        for finding in assessment.findings
    )
    assert any("Excluded 1" in warning for warning in warnings)


def test_related_work_generation_has_no_fixed_citation_cap() -> None:
    assert ResearchGenerateRequest(expected_version=1).max_results is None
    assert ResearchGenerateRequest(expected_version=1, max_results=12).max_results == 12


@pytest.mark.asyncio
async def test_counter_evidence_source_text_is_persisted_to_object_storage() -> None:
    storage = MemoryObjectStorage()
    service = ResearchService(
        _UnusedDb(),  # type: ignore[arg-type]
        source=FakeScholarlySourcePort(),
        verifier=_UnusedVerifier(),  # type: ignore[arg-type]
        llm=FakeLlmPort(),
        object_storage=storage,
    )
    session_id = uuid4()
    record = ScholarlyRecord(
        title="Counter source",
        abstract="This source evaluates an existing competing method.",
        provider="fixture",
        provider_source_id="counter-1",
    )

    materials, warnings = await service._counter_evidence_materials(
        [record],
        session_id=session_id,
    )

    assert warnings == []
    assert len(materials) == 1
    object_key = materials[0].source_object_key
    assert object_key is not None
    assert object_key.startswith(f"research/{session_id}/gap/counter-evidence/")
    assert (await storage.get_bytes(key=object_key)).decode() == record.abstract


@pytest.mark.asyncio
async def test_counter_evidence_full_text_is_loaded_concurrently() -> None:
    class ConcurrentDocumentTextSource:
        def __init__(self) -> None:
            self.active = 0
            self.max_active = 0

        async def fetch_text(self, *, record: ScholarlyRecord) -> DocumentText:
            self.active += 1
            self.max_active = max(self.max_active, self.active)
            await asyncio.sleep(0)
            self.active -= 1
            return DocumentText(
                text=f"Full text for {record.provider_source_id}",
                source_kind="full_text_html",
            )

    document_text_source = ConcurrentDocumentTextSource()
    service = ResearchService(
        _UnusedDb(),  # type: ignore[arg-type]
        source=FakeScholarlySourcePort(),
        verifier=_UnusedVerifier(),  # type: ignore[arg-type]
        llm=FakeLlmPort(),
        document_text_source=document_text_source,
    )
    records = [
        ScholarlyRecord(
            title=f"Counter source {index}",
            provider="fixture",
            provider_source_id=f"counter-{index}",
        )
        for index in range(3)
    ]

    materials, warnings = await service._counter_evidence_materials(records)

    assert warnings == []
    assert document_text_source.max_active == len(records)
    assert [material.record for material in materials] == records
    assert [material.source_text for material in materials] == [
        f"Full text for counter-{index}" for index in range(3)
    ]


@pytest.mark.asyncio
async def test_counter_evidence_does_not_continue_with_ram_only_text() -> None:
    class FailingStorage(MemoryObjectStorage):
        async def put_bytes(
            self,
            *,
            key: str,
            data: bytes,
            content_type: str,
        ) -> str:
            raise OSError("storage unavailable")

    service = ResearchService(
        _UnusedDb(),  # type: ignore[arg-type]
        source=FakeScholarlySourcePort(),
        verifier=_UnusedVerifier(),  # type: ignore[arg-type]
        llm=FakeLlmPort(),
        object_storage=FailingStorage(),
    )
    record = ScholarlyRecord(
        title="Counter source",
        abstract="This source evaluates an existing competing method.",
        provider="fixture",
        provider_source_id="counter-1",
    )

    with pytest.raises(ResearchGenerationError, match="could not be persisted"):
        await service._counter_evidence_materials(
            [record],
            session_id=uuid4(),
        )


@pytest.mark.asyncio
async def test_deleting_related_work_removes_only_unreferenced_source_text() -> None:
    storage = MemoryObjectStorage()
    orphaned_key = "research/session/citations/orphaned.txt"
    revision_key = "research/session/citations/revision.txt"
    for key in (orphaned_key, revision_key):
        await storage.put_bytes(key=key, data=b"passage", content_type="text/plain")
    db = _CleanupDb(
        scalar_results=[
            [orphaned_key, revision_key],
            [revision_key],
        ]
    )
    service = ResearchService(
        db,  # type: ignore[arg-type]
        source=FakeScholarlySourcePort(),
        verifier=_UnusedVerifier(),  # type: ignore[arg-type]
        llm=FakeLlmPort(),
        object_storage=storage,
    )

    await service._delete_working_related_work(uuid4())

    assert orphaned_key not in storage.objects
    assert revision_key in storage.objects
    assert len(db.executed) == 2


@pytest.mark.asyncio
async def test_deleting_gap_removes_only_unreferenced_counter_evidence_text() -> None:
    storage = MemoryObjectStorage()
    orphaned_key = "research/session/gap/counter-evidence/orphaned.txt"
    revision_key = "research/session/gap/counter-evidence/revision.txt"
    for key in (orphaned_key, revision_key):
        await storage.put_bytes(key=key, data=b"passage", content_type="text/plain")
    working_gap = _gap_narrative_with_object_keys(orphaned_key, revision_key)
    revision_gap = _gap_narrative_with_object_keys(revision_key)
    db = _CleanupDb(
        scalar_value={"gap": working_gap},
        scalar_results=[[revision_gap]],
    )
    service = ResearchService(
        db,  # type: ignore[arg-type]
        source=FakeScholarlySourcePort(),
        verifier=_UnusedVerifier(),  # type: ignore[arg-type]
        llm=FakeLlmPort(),
        object_storage=storage,
    )

    await service._delete_working_gap(uuid4())

    assert orphaned_key not in storage.objects
    assert revision_key in storage.objects
    assert len(db.executed) == 1


def _gap_narrative_with_object_keys(*keys: str) -> dict[str, Any]:
    return {
        "candidate": {
            "search_audit": {
                "counter_evidence_results": [
                    {"source_object_key": key} for key in keys
                ]
            }
        }
    }


class _ScalarResults:
    def __init__(self, values: list[Any]) -> None:
        self._values = values

    def all(self) -> list[Any]:
        return self._values


class _CleanupDb:
    def __init__(
        self,
        *,
        scalar_value: Any = None,
        scalar_results: list[list[Any]] | None = None,
    ) -> None:
        self.scalar_value = scalar_value
        self.scalar_results = list(scalar_results or [])
        self.executed: list[Any] = []

    async def scalar(self, _statement: Any) -> Any:
        return self.scalar_value

    async def scalars(self, _statement: Any) -> _ScalarResults:
        return _ScalarResults(self.scalar_results.pop(0))

    async def execute(self, statement: Any) -> None:
        self.executed.append(statement)


class _UnusedDb:
    pass


def _relevant_counter_records(count: int = 2) -> list[ScholarlyRecord]:
    return [
        ScholarlyRecord(
            title=f"Claim verification at each reasoning step {index}",
            abstract=(
                "Evaluates claim verification and evidence feedback for each "
                f"reasoning step under protocol {index}."
            ),
            provider="fixture",
            provider_source_id=f"counter-{index}",
        )
        for index in range(count)
    ]


class _UnusedVerifier:
    async def verify(self, **_kwargs: Any) -> Any:
        raise AssertionError("Verifier should not be called")


class _RecordingVerifier:
    def __init__(self) -> None:
        self.records: list[ScholarlyRecord] = []

    async def verify(self, *, citation: ScholarlyRecord) -> VerificationResult:
        self.records.append(citation)
        return VerificationResult(
            status=VerificationStatus.VERIFIED,
            messages=["Identifier and title match the scholarly provider"],
            record=citation,
        )


class _QuotaLlm:
    async def complete(self, **_kwargs: Any) -> str:
        raise LlmProviderError(
            "LLM rate limit or quota was reached; retry later",
            provider="langchain",
            status_code=429,
            code="insufficient_quota",
        )


class _GapSynthesisTimeoutLlm(FakeLlmPort):
    async def complete(
        self,
        *,
        system: str,
        prompt: str,
        model: str | None = None,
    ) -> str:
        if "research-gap-synthesis" in system:
            raise LlmProviderError(
                "LLM request timed out; retry later",
                provider="langchain",
                code="timeout",
            )
        return await super().complete(system=system, prompt=prompt, model=model)


class _DomainAwareCounterLlm(FakeLlmPort):
    async def complete(
        self,
        *,
        system: str,
        prompt: str,
        model: str | None = None,
    ) -> str:
        response = await super().complete(system=system, prompt=prompt, model=model)
        if "research-counter-analysis" not in system:
            return response
        payload = json.loads(prompt)
        irrelevant_keys = {
            item["result_key"]
            for item in payload.get("counter_evidence_results", [])
            if "transport" in str(item.get("source_text") or "").casefold()
        }
        parsed = json.loads(response)
        for finding in parsed.get("findings", []):
            if finding.get("result_key") in irrelevant_keys:
                finding["relevance_status"] = "irrelevant"
        return json.dumps(parsed)
