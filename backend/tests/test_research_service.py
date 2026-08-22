"""Fast unit tests for research provider seams and normalization."""

from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

from app.modules.research.adapters.fake_llm import FakeLlmPort
from app.modules.research.adapters.fake_source import FakeScholarlySourcePort
from app.modules.research.normalization import normalize_doi, normalize_url
from app.modules.research.ports import ScholarlyRecord, SourcePreferences
from app.modules.research.schemas import GroundingStatus, ResearchInputs
from app.modules.research.service import ResearchService, _rank_relevant_records
from app.ports.llm import LlmProviderError


def test_normalize_doi_and_url() -> None:
    assert normalize_doi(" HTTPS://DOI.ORG/10.1000/ABC ") == "10.1000/abc"
    assert (
        normalize_url("Example.COM/work/?utm_source=test&view=full#section")
        == "https://example.com/work?view=full"
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
                "projected": {
                    "citations": [
                        {
                            "id": "citation-1",
                            "citation_key": "smith-2025",
                            "title": "Claim verification",
                            "abstract": "Evaluates aggregate feedback.",
                            "metadata": {"large-provider-payload": "must-not-be-sent"},
                        },
                        {
                            "id": "citation-2",
                            "citation_key": "lee-2024",
                            "title": "Evidence feedback",
                            "abstract": "Evaluates textual feedback.",
                        },
                    ],
                    "related_work": [
                        {
                            "citation_id": "citation-1",
                            "what_was_done": "Optimizes prompts with aggregate scores",
                            "limitation": "Uses aggregate feedback",
                        },
                        {
                            "citation_id": "citation-2",
                            "what_was_done": "Refines outputs with textual feedback",
                            "limitation": "Does not verify evidence per claim",
                        },
                    ],
                }
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
    }
    assert warnings == []


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
async def test_research_inputs_preserve_distinctive_idea_concepts_when_model_omits_them() -> (
    None
):
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
    assert "claim checklist" in narrative["keywords"]
    assert "paper summaries" in narrative["keywords"]


@pytest.mark.asyncio
async def test_query_generation_restores_idea_anchors_omitted_by_model() -> None:
    llm = FakeLlmPort(
        responses={"research-query": '{"queries":["language model evaluation"]}'}
    )
    service = ResearchService(
        _UnusedDb(),  # type: ignore[arg-type]
        source=FakeScholarlySourcePort(),
        verifier=_UnusedVerifier(),  # type: ignore[arg-type]
        llm=llm,
    )
    idea = {"problems": ["Claim checklist for paper summaries"]}

    queries, warnings = await service._generate_queries(
        ResearchInputs(
            keywords=["claim verification", "factual consistency"],
        ),
        idea,
    )

    assert warnings == []
    assert "claim checklist" in queries
    assert "paper summaries" in queries
    assert "language model evaluation" in queries


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


class _UnusedDb:
    pass


class _UnusedVerifier:
    async def verify(self, **_kwargs: Any) -> Any:
        raise AssertionError("Verifier should not be called")


class _QuotaLlm:
    async def complete(self, **_kwargs: Any) -> str:
        raise LlmProviderError(
            "FIT WebUI quota or rate limit was reached",
            provider="fit_webui",
            status_code=429,
            code="insufficient_quota",
        )
