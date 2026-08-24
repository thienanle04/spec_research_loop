"""Fast unit tests for research provider seams and normalization."""

import json
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

from app.modules.research.adapters.fake_llm import FakeLlmPort
from app.modules.research.adapters.fake_source import FakeScholarlySourcePort
from app.modules.research.normalization import normalize_doi, normalize_url
from app.modules.research.ports import (
    DocumentText,
    ScholarlyRecord,
    SourcePreferences,
    VerificationResult,
)
from app.modules.research.schemas import (
    GroundingStatus,
    ResearchGenerateRequest,
    ResearchInputs,
    VerificationStatus,
)
from app.modules.research.service import (
    ResearchService,
    _compose_search_queries,
    _json_value,
    _rank_relevant_records,
)
from app.ports.llm import LlmProviderError


def test_normalize_doi_and_url() -> None:
    assert normalize_doi(" HTTPS://DOI.ORG/10.1000/ABC ") == "10.1000/abc"
    assert (
        normalize_url("Example.COM/work/?utm_source=test&view=full#section")
        == "https://example.com/work?view=full"
    )


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
            "research-inputs": '{"keywords":["kiểm chứng tuyên bố"]}',
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
                '{"statement":"Các nghiên cứu đã kiểm tra từng tuyên bố, nhưng chưa '
                'rõ phương pháp có khái quát sang nhiều lĩnh vực hay không."}'
            ),
        }
    )
    service = ResearchService(
        _UnusedDb(),  # type: ignore[arg-type]
        source=FakeScholarlySourcePort(),
        verifier=_UnusedVerifier(),  # type: ignore[arg-type]
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

    assert "kiểm chứng tuyên bố" in inputs["keywords"]
    assert queries[0] == "scientific claim verification"
    assert len(queries) >= 4
    assert any("survey OR review" in query for query in queries)
    assert finding.what_was_done == "Kiểm tra từng tuyên bố"
    assert gap["candidate"]["statement"].startswith("Các nghiên cứu")
    assert len(llm.calls) == 8
    assert any("research-rerank" in call["system"] for call in llm.calls)
    query_call = next(call for call in llm.calls if "research-query" in call["system"])
    assert "English regardless of the input language" in query_call["system"]
    user_facing_calls = [
        call
        for call in llm.calls
        if "research-query" not in call["system"]
        and "research-counter-query" not in call["system"]
        and "research-rerank" not in call["system"]
    ]
    assert all(
        "write every generated user-facing value in that same language"
        in call["system"]
        for call in user_facing_calls
    )


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
async def test_analysis_uses_distinct_content_passages_instead_of_html_or_pdf_dump() -> None:
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
                        "what_was_done": {"passage": "Full text (HTML)", "location": "HTML"},
                        "method_or_feedback": {"passage": "Full text (PDF)", "location": "PDF"},
                        "limitation": {"passage": "VI. RESEARCH METHODOLOGY", "location": "PDF"},
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
        source=FakeScholarlySourcePort(),
        verifier=_UnusedVerifier(),  # type: ignore[arg-type]
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
                            "grounding_status": "grounded",
                        },
                        {
                            "citation_id": "citation-2",
                            "what_was_done": "Refines outputs with textual feedback",
                            "limitation": "Does not verify evidence per claim",
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
    counter_results = narrative["candidate"]["search_audit"][
        "counter_evidence_results"
    ]
    assert len(counter_results) == 2
    assert all(result["title"] for result in counter_results)
    assert all(result["rationale"] for result in counter_results)
    assert narrative["candidate"]["search_audit"]["counter_evidence_assessment"]
    assert narrative["candidate"]["evidence_check"]["ready"] is True
    assert warnings == []


@pytest.mark.asyncio
async def test_gap_regeneration_uses_prior_counter_evidence_feedback() -> None:
    llm = FakeLlmPort()
    service = ResearchService(
        _UnusedDb(),  # type: ignore[arg-type]
        source=FakeScholarlySourcePort(),
        verifier=_UnusedVerifier(),  # type: ignore[arg-type]
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
                            "what_was_done": "Optimizes prompts with aggregate scores",
                            "limitation": "Uses aggregate feedback",
                            "grounding_status": "grounded",
                        }
                    ],
                },
            },
        },
        "working_draft": {
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
            }
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

    for prompt in (analysis_prompt, synthesis_prompt, counter_query_prompt):
        assert "gap_not_supported" in prompt
        assert "Existing claim-level verifier" in prompt
        assert "already addresses the proposed limitation" in prompt
    assert '"required_counter_evidence_keys": ["prior-counter-1"]' in analysis_prompt
    assert warnings == []


@pytest.mark.asyncio
async def test_gap_generation_preserves_valid_analysis_when_synthesis_times_out() -> (
    None
):
    service = ResearchService(
        _UnusedDb(),  # type: ignore[arg-type]
        source=FakeScholarlySourcePort(),
        verifier=_UnusedVerifier(),  # type: ignore[arg-type]
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
    assert "Localized feedback can make optimization more reliable" in statement
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
async def test_research_inputs_prefer_normalized_model_terms_over_vietnamese_fragments() -> (
    None
):
    llm = FakeLlmPort(
        responses={
            "research-inputs": (
                '{"keywords":["khối lượng hành chính",'
                '"khối lượng công việc giáo viên","chấm điểm tự động",'
                '"điểm danh tự động","tương tác thầy trò",'
                '"thời gian giảng dạy"]}'
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
        "khối lượng hành chính",
        "khối lượng công việc giáo viên",
        "chấm điểm tự động",
        "điểm danh tự động",
        "tương tác thầy trò",
        "thời gian giảng dạy",
    ]
    assert not set(narrative["keywords"]) & {
        "giáo viên mất",
        "mất quá nhiều",
        "nhiều thời gian",
        "nhiệm vụ hành",
    }


@pytest.mark.asyncio
async def test_query_generation_uses_only_model_translated_english_queries() -> None:
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
    assert queries[0] == "language model evaluation"
    assert len(queries) >= 4
    assert "English regardless of the input language" in llm.calls[0]["system"]


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
    assert records[0].metadata["discovery_queries"] == source.queries


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
    assert queries[:3] == model_queries
    assert len(queries) == 4


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
async def test_counter_evidence_search_analyzes_only_top_five_relevant_results() -> (
    None
):
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
    assert result.candidate_count == 8
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
    scores = [float(record.metadata["retrieval_score"]) for record in result.records]
    assert scores == sorted(scores, reverse=True)


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

    assert queries[:2] == ["scholarly evidence review", "systematic literature review"]
    assert len(queries) == 4
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

    assert queries[:2] == ["scholarly evidence review", "systematic literature review"]
    assert len(queries) == 4
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
    )

    assert discarded == 1
    assert {record.title for record in ranked[:2]} == {
        checklist.title,
        summaries.title,
    }


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
    )

    assert [record.title for record in ranked] == [strong.title, weak.title]
    assert discarded == 0


def test_related_work_generation_is_capped_at_five_results() -> None:
    assert ResearchGenerateRequest(expected_version=1).max_results == 5
    with pytest.raises(ValueError):
        ResearchGenerateRequest(expected_version=1, max_results=6)


class _UnusedDb:
    pass


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
            "FIT WebUI quota or rate limit was reached",
            provider="fit_webui",
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
                "FIT WebUI request timed out; retry later",
                provider="fit_webui",
                code="timeout",
            )
        return await super().complete(system=system, prompt=prompt, model=model)
