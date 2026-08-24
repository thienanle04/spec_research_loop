"""Research application services and in-request generation workflow."""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime
from difflib import SequenceMatcher
from typing import Any
from uuid import UUID, uuid4

from fastapi import HTTPException, status
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import OperationalErrorException
from app.modules.loop.catalog import NodeHeadStatus, WorkflowNode, ancestors
from app.modules.loop.models import LoopSession, NodeHead
from app.modules.loop.service import LoopService
from app.modules.research.models import Citation, RelatedWorkFinding
from app.modules.research.normalization import (
    citation_key,
    normalize_doi,
    normalize_url,
)
from app.modules.research.ports import (
    BatchCitationVerifier,
    CitationGraphPort,
    CitationVerifier,
    DocumentText,
    DocumentTextPort,
    MultiQueryScholarlySourcePort,
    ScholarlyProviderError,
    ScholarlyRecord,
    ScholarlySourcePort,
    SourcePreferences,
    VerificationResult,
)
from app.modules.research.schemas import (
    CitationCreate,
    CitationResponse,
    CitationUpsertEvent,
    CounterEvidenceOutcome,
    DoneEvent,
    DraftPatchEvent,
    ErrorEvent,
    GapCardBody,
    GapEvidenceCheck,
    GapSearchAudit,
    GapStatus,
    GroundingStatus,
    PreferredSources,
    ProgressEvent,
    RelatedWorkFindingCreate,
    RelatedWorkFindingResponse,
    ResearchGenerateRequest,
    ResearchInputs,
    ResearchNode,
    SourceEvidence,
    VerificationStatus,
    WarningEvent,
)
from app.ports.llm import LlmPort, LlmProviderError
from app.ports.storage import ObjectStoragePort


@dataclass(slots=True)
class GenerationRun:
    session_id: UUID
    account_id: UUID
    node: ResearchNode
    version: int
    body: ResearchGenerateRequest
    context: dict[str, Any]


class ResearchGenerationError(RuntimeError):
    """Generation failure with a message safe to return in the SSE stream."""


class _GapQuestionAnswers(BaseModel):
    """Internal analysis used to produce the single user-facing Gap statement."""

    prior_work: str = Field(min_length=1)
    limitation: str = Field(min_length=1)
    importance: str = Field(min_length=1)
    testability: str = Field(min_length=1)
    covered_citation_keys: list[str] = Field(min_length=1)


class _GapSynthesis(BaseModel):
    statement: str = Field(min_length=1)


class _CounterEvidenceAssessment(BaseModel):
    outcome: CounterEvidenceOutcome
    statement: str = Field(min_length=1)
    assessment: str = Field(min_length=1)
    covered_result_keys: list[str] = Field(default_factory=list)


class _RerankItem(BaseModel):
    result_key: str = Field(min_length=1)
    relevance_score: float = Field(ge=0, le=1)


class _RerankResponse(BaseModel):
    rankings: list[_RerankItem] = Field(min_length=1)


@dataclass(slots=True)
class _CounterEvidenceSearch:
    queries: list[str]
    records: list[ScholarlyRecord]
    candidate_count: int
    complete: bool
    warnings: list[str]


@dataclass(slots=True)
class _RerankOutcome:
    records: list[ScholarlyRecord]
    applied: bool
    candidate_count: int
    warnings: list[str]


class ResearchService:
    def __init__(
        self,
        db: AsyncSession,
        *,
        source: ScholarlySourcePort,
        verifier: CitationVerifier,
        llm: LlmPort,
        document_text_source: DocumentTextPort | None = None,
        object_storage: ObjectStoragePort | None = None,
    ) -> None:
        self._db = db
        self._source = source
        self._verifier = verifier
        self._llm = llm
        self._document_text_source = document_text_source
        self._object_storage = object_storage

    async def list_citations(
        self,
        *,
        session_id: UUID,
        account_id: UUID,
    ) -> list[CitationResponse]:
        await self._load_owned_session(session_id, account_id)
        rows = await self._working_citations(session_id)
        return [self._citation_response(row) for row in rows]

    async def list_findings(
        self,
        *,
        session_id: UUID,
        account_id: UUID,
    ) -> list[RelatedWorkFindingResponse]:
        await self._load_owned_session(session_id, account_id)
        rows = list(
            (
                await self._db.scalars(
                    select(RelatedWorkFinding)
                    .join(
                        Citation,
                        (Citation.session_id == RelatedWorkFinding.session_id)
                        & (Citation.stage_revision_id.is_(None))
                        & (Citation.id == RelatedWorkFinding.citation_id),
                    )
                    .where(
                        RelatedWorkFinding.session_id == session_id,
                        RelatedWorkFinding.stage_revision_id.is_(None),
                        Citation.is_active.is_(True),
                    )
                    .order_by(RelatedWorkFinding.created_at, RelatedWorkFinding.id)
                )
            ).all()
        )
        return [RelatedWorkFindingResponse.model_validate(row) for row in rows]

    async def set_citation_pinned(
        self,
        *,
        session_id: UUID,
        citation_id: UUID,
        account_id: UUID,
        pinned: bool,
    ) -> CitationResponse:
        await self._load_owned_session(session_id, account_id)
        row = await self._db.scalar(
            select(Citation).where(
                Citation.session_id == session_id,
                Citation.stage_revision_id.is_(None),
                Citation.is_active.is_(True),
                Citation.id == citation_id,
            )
        )
        if row is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Citation not found",
            )
        row.pinned = pinned
        if pinned:
            row.is_active = True
        await self._db.commit()
        await self._db.refresh(row)
        return self._citation_response(row)

    async def begin_generation(
        self,
        *,
        session_id: UUID,
        account_id: UUID,
        node: ResearchNode,
        body: ResearchGenerateRequest,
    ) -> GenerationRun:
        session = await self._load_owned_session(session_id, account_id)
        if session.working_draft_node != node.value:
            raise OperationalErrorException(
                status_code=status.HTTP_409_CONFLICT,
                code="invalid_working_draft_target",
                detail="generate must target the Working Draft Workflow Node",
            )
        workflow_node = WorkflowNode(node.value)
        await self._assert_upstream_current(session_id, workflow_node)
        context = await LoopService(self._db).project_context(
            session_id=session_id,
            account_id=account_id,
            node=workflow_node,
        )
        version = await self._claim_version(
            session=session,
            account_id=account_id,
            expected_version=body.expected_version,
        )
        return GenerationRun(
            session_id=session_id,
            account_id=account_id,
            node=node,
            version=version,
            body=body,
            context=context,
        )

    async def generate(self, run: GenerationRun) -> AsyncIterator[dict[str, Any]]:
        citation_count = 0
        started_message = {
            ResearchNode.RESEARCH_INPUTS: "Generating keyword suggestions",
            ResearchNode.RELATED_WORK: "Starting Related Work search and analysis",
            ResearchNode.GAP: "Generating the Gap Candidate",
        }[run.node]
        completed_message = {
            ResearchNode.RESEARCH_INPUTS: "Keyword suggestions complete",
            ResearchNode.RELATED_WORK: "Related Work search and analysis complete",
            ResearchNode.GAP: "Gap Candidate generation complete",
        }[run.node]
        try:
            yield self._event(
                ProgressEvent(
                    node=run.node,
                    message=started_message,
                    pct=0,
                )
            )
            if run.node is ResearchNode.RESEARCH_INPUTS:
                narrative, warnings = await self._generate_research_inputs(run.context)
                for warning in warnings:
                    yield self._warning(run.node, "llm_fallback", warning)
                await self._set_narrative(run.session_id, narrative)
                yield self._event(DraftPatchEvent(node=run.node, narrative=narrative))
            elif run.node is ResearchNode.RELATED_WORK:
                async for event in self._generate_related_work(run):
                    if event.get("type") == "citation_upsert":
                        citation_count += 1
                    yield event
            else:
                narrative, warnings = await self._generate_gaps(run.context)
                for warning in warnings:
                    yield self._warning(run.node, "llm_fallback", warning)
                await self._set_narrative(run.session_id, narrative)
                yield self._event(DraftPatchEvent(node=run.node, narrative=narrative))

            await self._db.commit()
            yield self._event(
                ProgressEvent(
                    node=run.node,
                    message=completed_message,
                    pct=100,
                )
            )
            yield self._event(
                DoneEvent(
                    node=run.node,
                    version=run.version,
                    citation_count=citation_count,
                )
            )
        except Exception as exc:  # noqa: BLE001 - stream converts failures to typed events
            await self._db.rollback()
            message = (
                str(exc)
                if isinstance(exc, ResearchGenerationError)
                else f"Research generation failed: {type(exc).__name__}"
            )
            yield self._event(
                ErrorEvent(
                    node=run.node,
                    code="generation_failed",
                    message=message,
                )
            )

    async def _generate_related_work(
        self,
        run: GenerationRun,
    ) -> AsyncIterator[dict[str, Any]]:
        inputs_payload = (
            run.context.get("upstream", {})
            .get(WorkflowNode.RESEARCH_INPUTS.value, {})
            .get("narrative", {})
        )
        try:
            inputs = ResearchInputs.model_validate(inputs_payload)
        except ValidationError:
            inputs = ResearchInputs()
            yield self._warning(
                run.node,
                "invalid_research_inputs",
                "Confirmed research inputs were invalid; safe defaults were used",
            )

        idea = _idea_context(run.context)
        queries, query_warnings = await self._generate_queries(inputs, idea)
        for warning in query_warnings:
            yield self._warning(run.node, "llm_fallback", warning)

        preferred = inputs.preferred_sources
        source_preferences = SourcePreferences(
            peer_reviewed_papers=preferred.peer_reviewed_papers,
            official_proceedings=preferred.official_proceedings,
            author_materials=preferred.author_materials,
            sourced_surveys=preferred.sourced_surveys,
        )
        settings = get_settings()
        candidate_limit = min(
            max(settings.research_candidate_limit, run.body.max_results * 5), 100
        )
        records, provider_failures = await self._search_provider_queries(
            queries=queries,
            preferences=source_preferences,
            limit=candidate_limit,
        )

        if queries and len(provider_failures) == len(queries):
            raise ResearchGenerationError(provider_failures[-1])
        for failure in provider_failures:
            yield self._warning(run.node, "provider_error", failure)

        unique_records = _deduplicate_records(records)
        ranked_records, discarded_count = _rank_relevant_records(
            unique_records,
            inputs=inputs,
            idea=idea,
            queries=queries,
        )
        if discarded_count:
            yield self._warning(
                run.node,
                "low_relevance_results",
                (
                    f"Discarded {discarded_count} scholarly result(s) that did not "
                    "cover a distinctive concept from the confirmed research idea."
                ),
            )
        if ranked_records and isinstance(self._source, CitationGraphPort):
            try:
                expanded = await self._source.expand_related(
                    seeds=ranked_records[: settings.research_graph_seed_count],
                    limit=candidate_limit,
                )
            except Exception as exc:  # noqa: BLE001 - graph expansion is best effort
                yield self._warning(
                    run.node,
                    "citation_graph_error",
                    f"Citation graph expansion failed: {type(exc).__name__}",
                )
            else:
                unique_records = _deduplicate_records([*unique_records, *expanded])
                ranked_records, graph_discarded = _rank_relevant_records(
                    unique_records,
                    inputs=inputs,
                    idea=idea,
                    queries=queries,
                )
                discarded_count += graph_discarded
        rerank = await self._rerank_records(
            ranked_records,
            idea=idea,
            inputs=inputs,
            queries=queries,
            objective="Find the most useful sources for a source-grounded Related Work comparison.",
        )
        for warning in rerank.warnings:
            yield self._warning(run.node, "rerank_fallback", warning)
        ranked_records = rerank.records
        ranked_candidate_count = len(ranked_records)
        unique_records = ranked_records[: run.body.max_results]
        for rank, record in enumerate(unique_records, start=1):
            record.metadata["relevance_rank"] = rank

        # Reruns preserve prior rows and S3 references. Only current results and
        # explicitly pinned Citations remain active for projection and freeze.
        await self._db.execute(
            update(Citation)
            .where(
                Citation.session_id == run.session_id,
                Citation.stage_revision_id.is_(None),
            )
            .values(is_active=Citation.pinned)
            .execution_options(synchronize_session=False)
        )
        total = max(len(unique_records), 1)
        batch_verifications = None
        if isinstance(self._verifier, BatchCitationVerifier):
            try:
                batch_verifications = await self._verifier.verify_many(
                    citations=unique_records
                )
            except Exception as exc:  # noqa: BLE001 - preserve search without a burst
                # Do not turn one failed batch request into N individual provider
                # requests. Keep the citations and mark verification as deferred.
                batch_verifications = [
                    VerificationResult(status=VerificationStatus.WARNING)
                    for _ in unique_records
                ]
                yield self._warning(
                    run.node,
                    "verification_error",
                    "Batch citation verification was deferred: "
                    + (
                        str(exc)
                        if isinstance(exc, ScholarlyProviderError)
                        else type(exc).__name__
                    ),
                )
        for index, record in enumerate(unique_records, start=1):
            data = self._record_create(record)
            citation, _ = await self._upsert_citation(
                session_id=run.session_id,
                data=data,
            )
            citation.is_active = True
            try:
                verification = (
                    batch_verifications[index - 1]
                    if batch_verifications is not None
                    else await self._verifier.verify(citation=record)
                )
                citation.verification_status = verification.status.value
                if verification.record is not None:
                    self._merge_resolved_record(citation, verification.record)
                for message in verification.messages:
                    if verification.status is not VerificationStatus.VERIFIED:
                        yield self._warning(run.node, "citation_verification", message)
            except Exception as exc:  # noqa: BLE001 - preserve partial search results
                citation.verification_status = VerificationStatus.WARNING.value
                yield self._warning(
                    run.node,
                    "verification_error",
                    f"Citation verification failed: {type(exc).__name__}",
                )

            document, text_warnings = await self._persist_document_text(
                session_id=run.session_id,
                citation=citation,
                record=record,
            )
            for warning in text_warnings:
                yield self._warning(run.node, "document_text", warning)

            finding, analysis_warnings = await self._analyze(
                record,
                citation.id,
                research_context={
                    "idea": idea,
                    "research_inputs": inputs.model_dump(mode="json"),
                },
                document=document,
                source_object_key=citation.text_object_key,
            )
            for warning in analysis_warnings:
                yield self._warning(run.node, "llm_fallback", warning)
            await self._upsert_finding(run.session_id, finding)
            await self._db.flush()
            # SQLAlchemy expires the on-update timestamp after flushing the
            # verification status; refresh before serializing inside SSE.
            await self._db.refresh(citation)
            yield self._event(
                CitationUpsertEvent(citation=self._citation_response(citation))
            )
            yield self._event(
                ProgressEvent(
                    node=run.node,
                    message=f"Analyzed Citation {index} of {len(unique_records)}",
                    pct=min(95, 10 + int(index / total * 85)),
                )
            )

        narrative = dict(run.context.get("working_draft", {}).get("narrative", {}))
        narrative.update(
            {
                "search_queries": queries,
                "query_language": "en",
                "query_plan": _query_plan(queries),
                "citation_count": len(unique_records),
                "candidate_count": len(records),
                "ranked_candidate_count": ranked_candidate_count,
                "reranked_candidate_count": rerank.candidate_count,
                "reranking_applied": rerank.applied,
                "analyzed_result_count": len(unique_records),
                "selection_rule": (
                    "llm_listwise_rerank" if rerank.applied else "top_relevance_score"
                ),
                "graph_expansion_enabled": isinstance(self._source, CitationGraphPort),
                "preferred_sources": preferred.model_dump(mode="json"),
            }
        )
        await self._set_narrative(run.session_id, narrative)
        yield self._event(DraftPatchEvent(node=run.node, narrative=narrative))

    async def _generate_research_inputs(
        self,
        context: dict[str, Any],
    ) -> tuple[dict[str, Any], list[str]]:
        try:
            idea = _idea_context(context)
            raw = await self._llm.complete(
                system=(
                    _idea_language_instruction(idea)
                    + "research-inputs: return only JSON in exactly this shape: "
                    '{"keywords":["specific scholarly noun phrase"],'
                    '"preferred_sources":{"peer_reviewed_papers":true,'
                    '"official_proceedings":true,"author_materials":true,'
                    '"sourced_surveys":true}}. Treat each supplied Card role differently. '
                    "Privately extract the population, context, artifact or task, intervention "
                    "or exposure, outcome, and relationship from Problem and Research Question "
                    "Cards. Return 5 to 8 established academic search concepts covering those "
                    "core roles. Do not output Constraint Card content as a keyword; constraints "
                    "are optional query filters handled later. Do not output Open Question Card "
                    "content as a keyword; open questions become separate exploratory queries. "
                    "Each keyword must be a self-contained noun phrase of 2 to 5 words commonly "
                    "found in scholarly titles or abstracts. Prefer canonical domain terms over "
                    "literal fragments from the Cards. Include a precise synonym only when it is "
                    "a genuinely different phrase used by scholars. Convert narrative wording "
                    "into research concepts; never copy adjacent words merely because they occur "
                    "together in a sentence. Do not output subject-verb clauses, temporal "
                    "fragments, or category labels joined by 'vs'. "
                    "Never output IDs, UUIDs, sentences, explanations, or generic standalone "
                    "terms such as paper, source, study, research, method, result, generated, "
                    "summary, statement, or plausible. Do not use markdown."
                ),
                prompt=json.dumps({"idea": idea}, default=str, ensure_ascii=False),
            )
            data = _research_inputs_from_model(raw, idea)
            return data.model_dump(mode="json"), []
        except Exception as exc:  # noqa: BLE001 - vendor-safe deterministic fallback
            try:
                current = ResearchInputs.model_validate(
                    context.get("working_draft", {}).get("narrative", {})
                )
            except ValidationError:
                current = ResearchInputs()
            if not current.keywords:
                current.keywords = _fallback_keywords(_idea_context(context))
            warnings = (
                [
                    (
                        "Research input generation used idea-derived keywords because "
                        f"the LLM provider failed: {_llm_failure_summary(exc)}"
                    )
                ]
                if isinstance(exc, LlmProviderError)
                else []
            )
            return current.model_dump(mode="json"), warnings

    async def _search_provider_queries(
        self,
        *,
        queries: list[str],
        preferences: SourcePreferences,
        limit: int,
    ) -> tuple[list[ScholarlyRecord], list[str]]:
        if not queries:
            return [], []
        if isinstance(self._source, MultiQueryScholarlySourcePort):
            try:
                records = await self._source.search_many(
                    queries=queries,
                    preferences=preferences,
                    limit=limit,
                )
            except BaseException as exc:  # noqa: BLE001 - normalized below
                failure = (
                    str(exc)
                    if isinstance(exc, ScholarlyProviderError)
                    else f"Scholarly provider failed: {type(exc).__name__}"
                )
                return [], [failure] * len(queries)
            for record in records:
                record.metadata.setdefault("discovery_queries", list(queries))
            return records, []

        search_results = await asyncio.gather(
            *(
                self._source.search(
                    query=query,
                    preferences=preferences,
                    limit=limit,
                )
                for query in queries
            ),
            return_exceptions=True,
        )
        records: list[ScholarlyRecord] = []
        failures: list[str] = []
        for query, result in zip(queries, search_results, strict=True):
            if isinstance(result, BaseException):
                failures.append(
                    str(result)
                    if isinstance(result, ScholarlyProviderError)
                    else f"Scholarly provider failed: {type(result).__name__}"
                )
                continue
            for record in result:
                discovery = record.metadata.setdefault("discovery_queries", [])
                if query not in discovery:
                    discovery.append(query)
            records.extend(result)
        return records, failures

    async def _generate_queries(
        self,
        inputs: ResearchInputs,
        idea: dict[str, Any],
    ) -> tuple[list[str], list[str]]:
        try:
            raw = await self._llm.complete(
                system=(
                    "research-query: return only JSON with a queries string array. "
                    "Write every query in English regardless of the input language. Translate "
                    "Vietnamese and other non-English concepts into canonical English academic "
                    "terminology while preserving acronyms and technical names. Queries are "
                    "retrieval keys, not user-facing prose; never emit a non-English query. "
                    "Create separate, concise scholarly queries for background, relationships, "
                    "solutions, and feasibility or gaps. Problem Cards provide core concepts. "
                    "Split each Research Question into the smallest useful relationship queries "
                    "instead of forcing all variables into one query. Treat Constraint Cards as "
                    "optional filters and include only externally searchable constraints when a "
                    "query genuinely needs narrowing; never include internal delivery limits. "
                    "Turn Open Question Cards into separate exploratory queries for evidence "
                    "gaps, conflicting findings, mechanisms, limitations, or measurement. Use "
                    "Return exactly four independent queries and preserve useful synonyms: "
                    "one core relationship query, one synonym or adjacent-method query, one "
                    "limitations or future-work query, and one survey or benchmark query. Use "
                    "OR only for precise synonyms and AND between concept groups. Prefer two or "
                    "three concept groups per query. Keep each query at no more than eight "
                    "content words; never concatenate the full idea into one query. Do not "
                    "replace distinctive concepts with "
                    "broad terms such as AI, paper, method, or research."
                ),
                prompt=json.dumps(
                    {
                        "idea": idea,
                        "concept_anchors": _idea_search_concepts(idea),
                        "inputs": inputs.model_dump(),
                    },
                    ensure_ascii=False,
                ),
            )
            payload = _json_value(raw, dict)
            model_queries = [
                str(item).strip()
                for item in payload.get("queries", [])
                if str(item).strip()
            ]
            if not model_queries:
                raise ValueError("No queries returned")
            normalized = _normalize_search_queries(model_queries, max_terms=8)
            if not normalized:
                raise ValueError("All generated queries exceeded the provider query budget")
            composed = _compose_search_queries(normalized, inputs, idea)
            english_queries: list[str] = []
            for query in composed:
                try:
                    english_queries.extend(
                        _normalize_search_queries([query], max_terms=8)
                    )
                except ValueError:
                    # Non-English confirmed Cards still inform the model prompt. They
                    # must not leak into provider queries when deterministic coverage
                    # expansion cannot translate them safely.
                    continue
            return _ensure_query_families(
                english_queries,
                limit=get_settings().research_search_query_limit,
            ), []
        except Exception as exc:  # noqa: BLE001 - deterministic fallback
            return _ensure_query_families(
                _english_query_fallback(inputs, idea),
                limit=get_settings().research_search_query_limit,
            ), [
                (
                    "English query generation used a conservative fallback: "
                    f"{_llm_failure_summary(exc)}"
                )
            ]

    async def _rerank_records(
        self,
        records: list[ScholarlyRecord],
        *,
        idea: dict[str, Any],
        inputs: ResearchInputs,
        queries: list[str],
        objective: str,
    ) -> _RerankOutcome:
        """Apply a bounded listwise LLM rerank with heuristic-order fallback."""
        settings = get_settings()
        limit = min(
            max(settings.research_rerank_candidate_limit, 5),
            len(records),
            50,
        )
        candidates = records[:limit]
        tail = records[limit:]
        for rank, record in enumerate(records, start=1):
            record.metadata["heuristic_rank"] = rank
            record.metadata["heuristic_retrieval_score"] = record.metadata.get(
                "retrieval_score"
            )
        if not settings.research_rerank_enabled or len(candidates) < 2:
            return _RerankOutcome(
                records=records,
                applied=False,
                candidate_count=0,
                warnings=[],
            )

        keyed = [(_record_result_key(record), record) for record in candidates]
        expected_keys = [key for key, _ in keyed]
        if len(set(expected_keys)) != len(expected_keys):
            return _RerankOutcome(
                records=records,
                applied=False,
                candidate_count=len(candidates),
                warnings=[
                    "Semantic reranking was skipped because candidate identifiers were not unique."
                ],
            )

        try:
            raw = await self._llm.complete(
                system=(
                    "research-rerank: return only JSON in exactly this shape: "
                    '{"rankings":[{"result_key":"...","relevance_score":0.0}]}. '
                    "Rerank every supplied scholarly candidate for the stated objective. "
                    "Use the confirmed Problem, Research Questions, Research Inputs, and "
                    "search queries. Prioritize direct coverage of the research relationship, "
                    "method, outcome, evaluation, and limitations. Prefer evidence-rich "
                    "candidates over broad keyword matches. Use only supplied metadata; do not "
                    "infer missing facts. Return every candidate result_key exactly once, no "
                    "unknown keys, ordered from most to least relevant. relevance_score must be "
                    "between 0 and 1. Do not use markdown or add explanations."
                ),
                prompt=json.dumps(
                    {
                        "objective": objective,
                        "idea": idea,
                        "research_inputs": inputs.model_dump(mode="json"),
                        "search_queries": queries,
                        "candidates": [
                            {
                                "result_key": key,
                                "title": record.title,
                                "abstract": str(record.abstract or "")[:1_200],
                                "year": record.year,
                                "venue": record.venue,
                                "heuristic_score": record.metadata.get(
                                    "retrieval_score"
                                ),
                                "discovery_types": record.metadata.get(
                                    "discovery_types", []
                                ),
                            }
                            for key, record in keyed
                        ],
                    },
                    default=str,
                    ensure_ascii=False,
                ),
            )
            response = _RerankResponse.model_validate(_json_value(raw, dict))
            returned_keys = [item.result_key for item in response.rankings]
            if len(set(returned_keys)) != len(returned_keys):
                raise ValueError("Reranker returned duplicate candidate identifiers")
            if set(returned_keys) != set(expected_keys):
                raise ValueError("Reranker did not return every supplied candidate")

            by_key = dict(keyed)
            ordered_items = sorted(
                enumerate(response.rankings),
                key=lambda item: (-item[1].relevance_score, item[0]),
            )
            reranked: list[ScholarlyRecord] = []
            for rank, (_, item) in enumerate(ordered_items, start=1):
                record = by_key[item.result_key]
                record.metadata["reranker"] = "llm_listwise"
                record.metadata["reranker_rank"] = rank
                record.metadata["reranker_score"] = round(item.relevance_score, 4)
                reranked.append(record)
            return _RerankOutcome(
                records=[*reranked, *tail],
                applied=True,
                candidate_count=len(candidates),
                warnings=[],
            )
        except Exception as exc:  # noqa: BLE001 - retrieval must survive reranker failure
            return _RerankOutcome(
                records=records,
                applied=False,
                candidate_count=len(candidates),
                warnings=[
                    (
                        "Semantic reranking used the heuristic order because the model output "
                        f"could not be validated: {_llm_failure_summary(exc)}"
                    )
                ],
            )

    async def _analyze(
        self,
        record: ScholarlyRecord,
        citation_id: UUID,
        *,
        research_context: dict[str, Any],
        document: DocumentText | None = None,
        source_object_key: str | None = None,
    ) -> tuple[RelatedWorkFindingCreate, list[str]]:
        citation_payload = self._record_payload(record)
        source_text = (
            document.text if document else record.abstract or record.title
        ).strip()
        source_location = _document_location(document, record)
        if document is not None and not _source_passage_candidates(source_text):
            # A downloaded landing page can contain only journal chrome. In that
            # case analyze the provider's abstract instead of treating HTML as evidence.
            source_text = (record.abstract or record.title).strip()
            source_location = _source_location(record)
        citation_payload["retrieved_text"] = _analysis_excerpt(
            source_text,
            research_context,
            limit=16_000,
        )
        citation_payload["retrieved_text_location"] = source_location
        idea = research_context.get("idea", {})
        try:
            raw = await self._llm.complete(
                system=(
                    _idea_language_instruction(idea)
                    + "research-analysis: return only one flat JSON object with exactly "
                    "these keys: what_was_done (non-empty string), "
                    "method_or_feedback (non-empty string describing the method, "
                    "feedback, or evaluation type), limitation (non-empty string), "
                    "relevance (non-empty string), supporting_passage (non-empty "
                    "verbatim span from the supplied retrieved_text), evidence "
                    "(an object with what_was_done, method_or_feedback, and limitation; "
                    "each value contains passage and location), and confidence "
                    "(number from 0 to 1). Do not rename or nest the keys. Assess "
                    "Use only retrieved_text for source assertions. For every evidence "
                    "item, passage must be a concise verbatim sentence or paragraph "
                    "that separately supports that assertion. Never use a document "
                    "type, section heading, navigation text, or the whole HTML/PDF as "
                    "evidence. Assess relevance "
                    "and limitation against the supplied Problem, Research "
                    "Questions, and Research Inputs. If the source does not state a "
                    "method or feedback type, use 'Not stated in the source metadata'."
                ),
                prompt=json.dumps(
                    {**research_context, "citation": citation_payload},
                    default=str,
                    ensure_ascii=False,
                ),
            )
            payload = _normalize_finding_payload(
                _json_value(raw, dict),
                record,
                source_text=source_text,
                source_location=source_location,
            )
            for key, item in payload["evidence"].items():
                item["passage"] = _verbatim_source_passage(
                    source_text,
                    item["passage"],
                    assertion=str(payload.get(key) or ""),
                )
                item["location"] = _passage_location(
                    source_text,
                    item["passage"],
                    source_location,
                )
            passage = payload["evidence"]["what_was_done"]["passage"]
            finding_location = payload["evidence"]["what_was_done"]["location"]
            payload["supporting_passage"] = passage
            grounding_status = _evidence_grounding_status(
                source_text, payload["evidence"]
            )
            warnings = []
            if grounding_status is not GroundingStatus.GROUNDED:
                warnings.append(
                    "Finding passage could not be matched exactly to the retrieved source text"
                )
            return (
                RelatedWorkFindingCreate(
                    citation_id=citation_id,
                    grounding_status=grounding_status,
                    source_object_key=source_object_key,
                    source_location=finding_location,
                    **payload,
                ),
                warnings,
            )
        except Exception as exc:  # noqa: BLE001 - deterministic grounded fallback
            passage = _verbatim_source_passage(
                source_text or record.title,
                record.abstract or "",
                assertion=record.title,
            )
            fallback_location = _passage_location(
                source_text or record.title,
                passage,
                source_location,
            )
            source_evidence = SourceEvidence(
                passage=passage,
                location=fallback_location,
            )
            return (
                RelatedWorkFindingCreate(
                    citation_id=citation_id,
                    what_was_done=f"Presents {record.title}.",
                    method_or_feedback="Not stated in the source metadata.",
                    limitation="The available metadata is insufficient for a detailed limitation analysis.",
                    relevance="Included by the configured scholarly search.",
                    supporting_passage=passage,
                    source_object_key=source_object_key,
                    source_location=fallback_location,
                    evidence={
                        "what_was_done": source_evidence,
                        "method_or_feedback": source_evidence,
                        "limitation": source_evidence,
                    },
                    confidence=0.4,
                    grounding_status=GroundingStatus.WARNING,
                ),
                [
                    (
                        "Finding analysis used source metadata because the model "
                        "response could not be used: "
                        f"{_llm_failure_summary(exc)}"
                    )
                ],
            )

    async def _generate_gaps(
        self,
        context: dict[str, Any],
    ) -> tuple[dict[str, Any], list[str]]:
        upstream = context.get("upstream", {})
        related_node = upstream.get(WorkflowNode.RELATED_WORK.value, {})
        related = related_node.get("projected", {})
        related_narrative = related_node.get("narrative", {})
        raw_research_inputs = upstream.get(WorkflowNode.RESEARCH_INPUTS.value, {}).get(
            "narrative", {}
        )
        try:
            inputs = ResearchInputs.model_validate(raw_research_inputs)
        except ValidationError:
            inputs = ResearchInputs()
        research_inputs = inputs.model_dump(mode="json")
        citations = sorted(
            _gap_citations(related.get("citations", [])),
            key=lambda item: (
                float(item.get("retrieval_score") or 0),
                -_positive_rank(item.get("relevance_rank")),
            ),
            reverse=True,
        )[:5]
        related_work = _gap_findings(
            related.get("related_work", []),
            citations,
        )
        evidence_check = _gap_evidence_check(citations, related_work)
        valid_keys = evidence_check.eligible_citation_keys
        eligible_citations = [
            item for item in citations if item.get("citation_key") in valid_keys
        ]
        eligible_findings = [
            item for item in related_work if item.get("citation_key") in valid_keys
        ]
        idea = _idea_context(context)
        warnings: list[str] = []
        statement = _fallback_gap_statement(eligible_findings)
        if valid_keys:
            try:
                analysis_raw = await self._llm.complete(
                    system=(
                        _idea_language_instruction(idea)
                        + "research-gap-analysis: perform private source-grounded analysis and "
                        "return only one JSON object with exactly these keys: prior_work, "
                        "limitation, importance, testability (non-empty strings), and "
                        "covered_citation_keys (string array). Read and compare EVERY item in "
                        "citations and related_work; each supplied citation must materially "
                        "inform at least one answer, and covered_citation_keys must contain "
                        "every required_citation_key. Answer: what prior research accomplished, "
                        "what remains limited across the body of work, why the limitation "
                        "matters, and what experiment can test it. Ground the analysis in the "
                        "supplied findings and evidence. Do not claim proven novelty. Do not "
                        "use markdown or add explanatory text outside JSON."
                    ),
                    prompt=json.dumps(
                        {
                            "idea": idea,
                            "research_inputs": research_inputs,
                            "citations": eligible_citations,
                            "related_work": eligible_findings,
                            "required_citation_keys": valid_keys,
                        },
                        default=str,
                        ensure_ascii=False,
                    ),
                )
                answers = _GapQuestionAnswers.model_validate(
                    _json_value(analysis_raw, dict)
                )
                if set(valid_keys) - set(answers.covered_citation_keys):
                    raise ValueError("Gap analysis did not cover every eligible source")
            except Exception as exc:  # noqa: BLE001 - conservative source-linked fallback
                warnings.append(
                    "Gap analysis used a conservative source-linked fallback: "
                    f"{_llm_failure_summary(exc)}"
                )
            else:
                try:
                    synthesis_raw = await self._llm.complete(
                        system=(
                            _idea_language_instruction(idea)
                            + "research-gap-synthesis: return only JSON with one non-empty "
                            "string field named statement. Synthesize the four private "
                            "analysis answers into one concise, coherent Gap Candidate of "
                            "2 to 4 sentences. State what existing approaches do and what "
                            "remains unclear or insufficient. Do not expose field labels, "
                            "source lists, or separate answers. Do not claim proven novelty."
                        ),
                        prompt=json.dumps(
                            {
                                "idea": idea,
                                "analysis": answers.model_dump(mode="json"),
                            },
                            default=str,
                            ensure_ascii=False,
                        ),
                    )
                    statement = _GapSynthesis.model_validate(
                        _json_value(synthesis_raw, dict)
                    ).statement
                except Exception as exc:  # noqa: BLE001 - preserve grounded analysis
                    statement = _gap_statement_from_answers(answers)
                    warnings.append(
                        "Gap synthesis used the validated source-grounded analysis "
                        "directly because the final model call failed: "
                        f"{_llm_failure_summary(exc)}"
                    )
        else:
            warnings.append(
                "Gap Candidate is not evidence-ready because no Citation is both "
                "verified and linked to a grounded Related Work finding."
            )

        source_preferences = SourcePreferences(
            peer_reviewed_papers=inputs.preferred_sources.peer_reviewed_papers,
            official_proceedings=inputs.preferred_sources.official_proceedings,
            author_materials=inputs.preferred_sources.author_materials,
            sourced_surveys=inputs.preferred_sources.sourced_surveys,
        )
        related_queries = _string_list(related_narrative.get("search_queries"))
        counter_search = await self._search_counter_evidence(
            idea=idea,
            inputs=inputs,
            provisional_statement=statement,
            related_work_queries=related_queries,
            preferences=source_preferences,
        )
        warnings.extend(counter_search.warnings)
        assessment, assessment_warnings = await self._assess_counter_evidence(
            idea=idea,
            provisional_statement=statement,
            records=counter_search.records,
        )
        warnings.extend(assessment_warnings)
        statement = assessment.statement

        audit_complete = bool(related_queries) and counter_search.complete
        audit = GapSearchAudit(
            related_work_queries=related_queries,
            counter_evidence_queries=counter_search.queries,
            providers=sorted(
                {
                    str(item.get("provider"))
                    for item in citations
                    if item.get("provider")
                }
                | {
                    record.provider
                    for record in counter_search.records
                    if record.provider
                }
            ),
            related_work_candidate_count=_nonnegative_int(
                related_narrative.get("ranked_candidate_count")
                or related_narrative.get("candidate_count")
            ),
            related_work_analyzed_count=len(citations),
            counter_evidence_candidate_count=counter_search.candidate_count,
            counter_evidence_analyzed_count=len(counter_search.records),
            counter_evidence_outcome=assessment.outcome,
            completed_at=datetime.now(UTC),
            complete=audit_complete,
        )
        evidence_ready = evidence_check.ready and audit_complete
        status_value = (
            GapStatus.CANDIDATE
            if evidence_ready
            and assessment.outcome
            in {
                CounterEvidenceOutcome.NO_DIRECT_COUNTER_EVIDENCE,
                CounterEvidenceOutcome.GAP_NARROWED,
            }
            else GapStatus.INSUFFICIENT_EVIDENCE
        )
        candidate = GapCardBody(
            statement=statement,
            supporting_citation_keys=valid_keys,
            status=status_value,
            search_audit=audit,
            evidence_check=evidence_check,
        )
        narrative = dict(context.get("working_draft", {}).get("narrative", {}))
        narrative["candidate"] = candidate.model_dump(mode="json")
        return narrative, warnings

    async def _search_counter_evidence(
        self,
        *,
        idea: dict[str, Any],
        inputs: ResearchInputs,
        provisional_statement: str,
        related_work_queries: list[str],
        preferences: SourcePreferences,
    ) -> _CounterEvidenceSearch:
        warnings: list[str] = []
        try:
            raw = await self._llm.complete(
                system=(
                    "research-counter-query: return only JSON with a queries string array. "
                    "Write exactly 4 concise English scholarly queries designed to falsify or "
                    "narrow the proposed Gap Candidate. Search for methods that already solve "
                    "the stated limitation, synonymous names for the proposed combination, "
                    "recent surveys, benchmarks, and conflicting findings. Do not treat an "
                    "empty result set as evidence of novelty. Keep each query at no more than "
                    "eight content words."
                ),
                prompt=json.dumps(
                    {
                        "idea": idea,
                        "research_inputs": inputs.model_dump(mode="json"),
                        "provisional_gap_candidate": provisional_statement,
                        "prior_queries": related_work_queries,
                    },
                    ensure_ascii=False,
                ),
            )
            payload = _json_value(raw, dict)
            model_queries = _normalize_search_queries(
                [
                    str(item).strip()
                    for item in payload.get("queries", [])
                    if str(item).strip()
                ],
                max_terms=8,
            )
        except Exception as exc:  # noqa: BLE001 - deterministic falsification fallback
            model_queries = []
            warnings.append(
                "Counter-evidence query generation used deterministic English queries: "
                f"{_llm_failure_summary(exc)}"
            )
        settings = get_settings()
        queries = _ensure_counter_query_families(
            model_queries,
            related_work_queries,
            limit=settings.research_counter_query_limit,
        )
        candidate_limit = min(max(settings.research_candidate_limit, 25), 100)
        records, provider_failures = await self._search_provider_queries(
            queries=queries,
            preferences=preferences,
            limit=candidate_limit,
        )
        failures = len(provider_failures)
        warnings.extend(
            f"Counter-evidence provider query failed: {failure}"
            for failure in provider_failures
        )
        for record in records:
            discovery_types = record.metadata.setdefault("discovery_types", [])
            if "counter_evidence" not in discovery_types:
                discovery_types.append("counter_evidence")

        unique = _deduplicate_records(records)
        ranked, _ = _rank_relevant_records(
            unique,
            inputs=inputs,
            idea={**idea, "open_questions": [provisional_statement]},
            queries=queries,
        )
        if ranked and isinstance(self._source, CitationGraphPort):
            try:
                expanded = await self._source.expand_related(
                    seeds=ranked[: settings.research_graph_seed_count],
                    limit=candidate_limit,
                )
            except Exception as exc:  # noqa: BLE001 - best-effort graph falsification
                warnings.append(
                    f"Counter-evidence citation graph expansion failed: {type(exc).__name__}"
                )
            else:
                unique = _deduplicate_records([*unique, *expanded])
                ranked, _ = _rank_relevant_records(
                    unique,
                    inputs=inputs,
                    idea={**idea, "open_questions": [provisional_statement]},
                    queries=queries,
                )
        rerank = await self._rerank_records(
            ranked,
            idea={**idea, "open_questions": [provisional_statement]},
            inputs=inputs,
            queries=queries,
            objective=(
                "Find the strongest counter-evidence that could falsify or narrow the "
                "provisional Gap Candidate."
            ),
        )
        warnings.extend(rerank.warnings)
        return _CounterEvidenceSearch(
            queries=queries,
            records=rerank.records[:5],
            candidate_count=len(unique),
            complete=bool(queries) and failures == 0,
            warnings=warnings,
        )

    async def _assess_counter_evidence(
        self,
        *,
        idea: dict[str, Any],
        provisional_statement: str,
        records: list[ScholarlyRecord],
    ) -> tuple[_CounterEvidenceAssessment, list[str]]:
        if not records:
            return (
                _CounterEvidenceAssessment(
                    outcome=CounterEvidenceOutcome.INCONCLUSIVE,
                    statement=provisional_statement,
                    assessment=(
                        "Counter-evidence search returned no analyzable results; this does "
                        "not establish novelty."
                    ),
                ),
                [
                    (
                        "Counter-evidence search was inconclusive; an empty result set is "
                        "not evidence that the Gap exists."
                    )
                ],
            )
        payloads = [_counter_record_payload(record) for record in records]
        required_keys = [item["result_key"] for item in payloads]
        try:
            raw = await self._llm.complete(
                system=(
                    _idea_language_instruction(idea)
                    + "research-counter-analysis: return only one JSON object with exactly "
                    "outcome, statement, assessment, and covered_result_keys. outcome must "
                    "be one of no_direct_counter_evidence, gap_narrowed, gap_not_supported, "
                    "or inconclusive. Read every supplied result and actively look for work "
                    "that already addresses the proposed limitation or uses synonymous "
                    "terminology. Revise the statement when the Gap must be narrowed. If a "
                    "result already addresses it, use gap_not_supported. Never infer novelty "
                    "from missing results or weak metadata. covered_result_keys must include "
                    "every required_result_key."
                ),
                prompt=json.dumps(
                    {
                        "idea": idea,
                        "provisional_gap_candidate": provisional_statement,
                        "counter_evidence_results": payloads,
                        "required_result_keys": required_keys,
                    },
                    default=str,
                    ensure_ascii=False,
                ),
            )
            assessment = _CounterEvidenceAssessment.model_validate(
                _json_value(raw, dict)
            )
            if set(required_keys) - set(assessment.covered_result_keys):
                raise ValueError(
                    "Counter-evidence analysis did not cover every top result"
                )
            return assessment, []
        except Exception as exc:  # noqa: BLE001 - absence must remain inconclusive
            return (
                _CounterEvidenceAssessment(
                    outcome=CounterEvidenceOutcome.INCONCLUSIVE,
                    statement=provisional_statement,
                    assessment="Counter-evidence analysis could not be validated.",
                ),
                [
                    (
                        "Counter-evidence analysis was inconclusive: "
                        f"{_llm_failure_summary(exc)}"
                    )
                ],
            )

    async def _persist_document_text(
        self,
        *,
        session_id: UUID,
        citation: Citation,
        record: ScholarlyRecord,
    ) -> tuple[DocumentText | None, list[str]]:
        cache_warning: str | None = None
        if citation.text_object_key and self._object_storage is not None:
            try:
                cached = await self._object_storage.get_bytes(
                    key=citation.text_object_key
                )
            except Exception as exc:  # noqa: BLE001 - re-download below
                cache_warning = (
                    "Could not read cached text from object storage; downloading again: "
                    f"{type(exc).__name__}"
                )
            else:
                return (
                    DocumentText(
                        text=cached.decode("utf-8", errors="replace"),
                        source_url=citation.text_source_url,
                        source_kind=citation.text_source_kind or "full_text",
                        original_content_type="text/plain",
                    ),
                    [],
                )
        if self._document_text_source is None:
            return None, []
        document = await self._document_text_source.fetch_text(record=record)
        if document is None:
            return None, [
                "No abstract or public full text was available for this Citation"
            ]
        warnings = list(document.warnings)
        if cache_warning:
            warnings.append(cache_warning)
        data = document.text.encode("utf-8")
        checksum = hashlib.sha256(data).hexdigest()
        citation.text_source_url = document.source_url
        citation.text_source_kind = document.source_kind
        citation.text_checksum = checksum
        citation.text_char_count = len(document.text)
        citation.text_retrieved_at = datetime.now(UTC)
        if self._object_storage is not None:
            key = f"research/{session_id}/citations/{citation.id}/{checksum}.txt"
            try:
                citation.text_object_key = await self._object_storage.put_bytes(
                    key=key,
                    data=data,
                    content_type="text/plain; charset=utf-8",
                )
            except Exception as exc:  # noqa: BLE001 - analysis can use in-memory text
                warnings.append(
                    f"Could not persist retrieved text to object storage: {type(exc).__name__}"
                )
        return document, warnings

    async def _upsert_citation(
        self,
        *,
        session_id: UUID,
        data: CitationCreate,
    ) -> tuple[Citation, bool]:
        doi = normalize_doi(data.doi)
        url = normalize_url(data.url)
        provider = data.provider.strip().casefold() if data.provider else None
        provider_source_id = (
            data.provider_source_id.strip() if data.provider_source_id else None
        )
        conditions = []
        if data.id is not None:
            conditions.append(Citation.id == data.id)
        if doi:
            conditions.append(Citation.doi == doi)
        if url:
            conditions.append(Citation.url == url)
        if provider and provider_source_id:
            conditions.append(
                (Citation.provider == provider)
                & (Citation.provider_source_id == provider_source_id)
            )
        row = None
        if conditions:
            row = await self._db.scalar(
                select(Citation).where(
                    Citation.session_id == session_id,
                    Citation.stage_revision_id.is_(None),
                    or_(*conditions),
                )
            )
        created = row is None
        values = {
            "citation_key": data.citation_key.strip(),
            "title": data.title.strip(),
            "authors": list(data.authors),
            "year": data.year,
            "venue": data.venue,
            "doi": doi,
            "url": url,
            "provider": provider,
            "provider_source_id": provider_source_id,
            "abstract": data.abstract,
            "retrieved_at": data.retrieved_at,
            "is_active": data.is_active,
            "pinned": data.pinned,
            "retrieval_score": data.retrieval_score,
            "text_object_key": data.text_object_key,
            "text_source_url": data.text_source_url,
            "text_source_kind": data.text_source_kind,
            "text_checksum": data.text_checksum,
            "text_char_count": data.text_char_count,
            "text_retrieved_at": data.text_retrieved_at,
            "verification_status": data.verification_status.value,
            "source_metadata": dict(data.metadata),
        }
        if row is None:
            row = Citation(
                id=data.id or uuid4(),
                session_id=session_id,
                **values,
            )
            self._db.add(row)
        else:
            for name, value in values.items():
                if name == "pinned" and row.pinned:
                    continue
                if (
                    name == "verification_status"
                    and value == VerificationStatus.PENDING.value
                    and row.verification_status != VerificationStatus.PENDING.value
                ):
                    continue
                if value is not None:
                    setattr(row, name, value)
        await self._db.flush()
        return row, created

    async def _upsert_finding(
        self,
        session_id: UUID,
        data: RelatedWorkFindingCreate,
    ) -> RelatedWorkFinding:
        row = await self._db.scalar(
            select(RelatedWorkFinding).where(
                RelatedWorkFinding.session_id == session_id,
                RelatedWorkFinding.stage_revision_id.is_(None),
                RelatedWorkFinding.citation_id == data.citation_id,
            )
        )
        values = data.model_dump(exclude={"id"})
        values["grounding_status"] = data.grounding_status.value
        if row is None:
            row = RelatedWorkFinding(
                id=data.id or uuid4(),
                session_id=session_id,
                **values,
            )
            self._db.add(row)
        else:
            for name, value in values.items():
                setattr(row, name, value)
        await self._db.flush()
        return row

    async def _load_owned_session(
        self,
        session_id: UUID,
        account_id: UUID,
    ) -> LoopSession:
        session = await self._db.scalar(
            select(LoopSession).where(
                LoopSession.id == session_id,
                LoopSession.account_id == account_id,
            )
        )
        if session is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Loop Session not found",
            )
        return session

    async def _assert_upstream_current(
        self,
        session_id: UUID,
        node: WorkflowNode,
    ) -> None:
        rows = await self._db.scalars(
            select(NodeHead).where(NodeHead.session_id == session_id)
        )
        heads = {WorkflowNode(row.node): row for row in rows.all()}
        if any(
            heads[parent].status != NodeHeadStatus.CURRENT.value
            for parent in ancestors(node)
        ):
            raise OperationalErrorException(
                status_code=status.HTTP_409_CONFLICT,
                code="upstream_not_current",
                detail="Upstream Node Heads must be current",
            )

    async def _claim_version(
        self,
        *,
        session: LoopSession,
        account_id: UUID,
        expected_version: int,
    ) -> int:
        result = await self._db.execute(
            update(LoopSession)
            .where(
                LoopSession.id == session.id,
                LoopSession.account_id == account_id,
                LoopSession.version == expected_version,
            )
            .values(version=LoopSession.version + 1, updated_at=func.now())
            .returning(LoopSession.version)
            .execution_options(synchronize_session=False)
        )
        row = result.one_or_none()
        if row is None:
            await self._db.refresh(session, attribute_names=["version"])
            raise OperationalErrorException(
                status_code=status.HTTP_409_CONFLICT,
                code="version_conflict",
                detail="Loop Session was changed by another request",
                current_version=session.version,
            )
        return row.version

    async def _working_citations(self, session_id: UUID) -> list[Citation]:
        rows = await self._db.scalars(
            select(Citation)
            .where(
                Citation.session_id == session_id,
                Citation.stage_revision_id.is_(None),
                Citation.is_active.is_(True),
            )
            .order_by(Citation.created_at, Citation.id)
        )
        return list(rows.all())

    async def _set_narrative(self, session_id: UUID, narrative: dict[str, Any]) -> None:
        await self._db.execute(
            update(LoopSession)
            .where(LoopSession.id == session_id)
            .values(working_draft_narrative=narrative, updated_at=func.now())
            .execution_options(synchronize_session=False)
        )

    def _citation_response(self, row: Citation) -> CitationResponse:
        return CitationResponse(
            id=row.id,
            citation_key=row.citation_key,
            session_id=row.session_id,
            stage_revision_id=row.stage_revision_id,
            title=row.title,
            authors=row.authors,
            year=row.year,
            venue=row.venue,
            doi=row.doi,
            url=row.url,
            provider=row.provider,
            provider_source_id=row.provider_source_id,
            abstract=row.abstract,
            retrieved_at=row.retrieved_at,
            is_active=row.is_active,
            pinned=row.pinned,
            retrieval_score=row.retrieval_score,
            text_object_key=row.text_object_key,
            text_source_url=row.text_source_url,
            text_source_kind=row.text_source_kind,
            text_checksum=row.text_checksum,
            text_char_count=row.text_char_count,
            text_retrieved_at=row.text_retrieved_at,
            verification_status=VerificationStatus(row.verification_status),
            metadata=row.source_metadata,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    def _record_create(self, record: ScholarlyRecord) -> CitationCreate:
        return CitationCreate(
            citation_key=citation_key(record.title, record.year),
            **self._record_payload(record),
        )

    def _record_payload(self, record: ScholarlyRecord) -> dict[str, Any]:
        return {
            "title": record.title,
            "authors": record.authors,
            "year": record.year,
            "venue": record.venue,
            "doi": record.doi,
            "url": record.url,
            "provider": record.provider,
            "provider_source_id": record.provider_source_id,
            "abstract": record.abstract,
            "retrieved_at": record.retrieved_at,
            "retrieval_score": record.metadata.get("retrieval_score"),
            "metadata": record.metadata,
        }

    def _merge_resolved_record(
        self,
        row: Citation,
        record: ScholarlyRecord,
    ) -> None:
        row.doi = normalize_doi(record.doi) or row.doi
        row.url = normalize_url(record.url) or row.url
        row.provider = record.provider or row.provider
        row.provider_source_id = record.provider_source_id or row.provider_source_id
        row.abstract = record.abstract or row.abstract
        row.source_metadata = {**record.metadata, **row.source_metadata}

    def _warning(self, node: ResearchNode, code: str, message: str) -> dict[str, Any]:
        return self._event(WarningEvent(node=node, code=code, message=message))

    @staticmethod
    def _event(event: Any) -> dict[str, Any]:
        return event.model_dump(mode="json")


def _json_value(raw: str, expected: type[dict | list]) -> Any:
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        cleaned = "\n".join(lines).strip()
    value = json.loads(cleaned)
    if not isinstance(value, expected):
        raise TypeError(f"Expected {expected.__name__} JSON")
    return value


def _research_inputs_from_model(raw: str, idea: dict[str, Any]) -> ResearchInputs:
    try:
        payload = _json_value(raw, dict)
    except (json.JSONDecodeError, TypeError):
        start = raw.find("{")
        end = raw.rfind("}")
        if start < 0 or end <= start:
            payload = {"keywords": _keyword_values(raw)}
        else:
            value = json.loads(raw[start : end + 1])
            if not isinstance(value, dict):
                raise TypeError("Expected a Research Inputs object")
            payload = value

    for wrapper in ("research_inputs", "researchInput", "result", "data", "output"):
        wrapped = payload.get(wrapper)
        if isinstance(wrapped, dict):
            payload = wrapped
            break

    raw_keywords = next(
        (
            payload[key]
            for key in (
                "keywords",
                "search_keywords",
                "related_keywords",
                "search_terms",
                "terms",
                "suggestions",
            )
            if key in payload
        ),
        [],
    )
    role_aware_keywords = _role_aware_keyword_values(payload)
    model_keywords = _clean_keywords(
        role_aware_keywords or _keyword_values(raw_keywords)
    )
    # Prefer a complete model-generated set without padding it to the maximum.
    # Deterministic extraction is a recovery path for sparse/invalid responses, not
    # a source of extra phrases once the model supplied five usable concepts.
    idea_keywords = _idea_search_concepts(idea)
    keywords = (
        model_keywords
        if len(model_keywords) >= 5
        else _clean_keywords([*model_keywords, *idea_keywords])
    )

    preferred = payload.get("preferred_sources")
    if not isinstance(preferred, dict):
        preferred = payload.get("preferredSources")
    preferred_payload = preferred if isinstance(preferred, dict) else {}
    defaults = PreferredSources()
    normalized_preferred = PreferredSources(
        peer_reviewed_papers=_boolean_value(
            preferred_payload.get("peer_reviewed_papers"),
            defaults.peer_reviewed_papers,
        ),
        official_proceedings=_boolean_value(
            preferred_payload.get("official_proceedings"),
            defaults.official_proceedings,
        ),
        author_materials=_boolean_value(
            preferred_payload.get("author_materials"),
            defaults.author_materials,
        ),
        sourced_surveys=_boolean_value(
            preferred_payload.get("sourced_surveys"),
            defaults.sourced_surveys,
        ),
    )
    return ResearchInputs(
        keywords=keywords[:8],
        preferred_sources=normalized_preferred,
    )


def _role_aware_keyword_values(payload: dict[str, Any]) -> list[str]:
    """Flatten core concept groups while keeping filters and exploration separate.

    Research Inputs deliberately retains its existing flat ``keywords`` contract for
    the current editor. The richer model response is used to choose those values:
    canonical Problem and Research Question concepts come first, followed by their
    scholarly synonyms. Constraint filters and Open Question concepts are consumed
    later by role-aware query generation from the confirmed Card snapshot.
    """

    core_groups: list[tuple[str, list[str]]] = []
    for key in ("problem_concepts", "research_question_concepts"):
        value = payload.get(key)
        if not isinstance(value, list):
            continue
        for item in value:
            if isinstance(item, str):
                core_groups.append((item, []))
                continue
            if not isinstance(item, dict):
                continue
            term = next(
                (
                    item[name]
                    for name in ("term", "canonical_term", "phrase", "keyword")
                    if isinstance(item.get(name), str)
                ),
                "",
            )
            synonyms = _keyword_values(item.get("synonyms", item.get("aliases", [])))
            if term:
                core_groups.append((term, synonyms))

    # Preserve coverage across Card roles before allowing synonyms from an early
    # concept to consume the bounded list shown in the existing frontend.
    canonical = [term for term, _ in core_groups]
    synonyms = [synonym for _, values in core_groups for synonym in values]
    return [*canonical, *synonyms]


def _keyword_values(value: object) -> list[str]:
    if isinstance(value, str):
        return [
            re.sub(
                r"^(?:(?:keywords?|search terms?)\s*:\s*|[-*•]|\d+[.)]\s*)",
                "",
                item,
                flags=re.IGNORECASE,
            ).strip()
            for item in re.split(r"[,;\n]", value)
            if item.strip()
        ]
    if not isinstance(value, list):
        return []
    values: list[str] = []
    for item in value:
        if isinstance(item, str):
            values.append(item)
            continue
        if not isinstance(item, dict):
            continue
        for key in ("keyword", "term", "phrase", "value", "name"):
            candidate = item.get(key)
            if isinstance(candidate, str):
                values.append(candidate)
                break
    return values


def _boolean_value(value: object, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str) and value.casefold() in {"true", "false"}:
        return value.casefold() == "true"
    return default


def _normalize_finding_payload(
    payload: dict[str, Any],
    record: ScholarlyRecord,
    *,
    source_text: str | None = None,
    source_location: str | None = None,
) -> dict[str, Any]:
    """Map common provider aliases and fill conservative source-backed defaults."""
    passage = (
        _first_text(
            payload,
            "supporting_passage",
            "supporting_passage_quote",
            "evidence",
            "passage",
            "quote",
        )
        or (source_text or record.abstract or record.title)[:500]
    )
    confidence: float | None = None
    raw_confidence = payload.get("confidence")
    if raw_confidence is not None:
        try:
            parsed_confidence = float(raw_confidence)
        except (TypeError, ValueError):
            pass
        else:
            if 0 <= parsed_confidence <= 1:
                confidence = parsed_confidence

    normalized = {
        "what_was_done": _first_text(
            payload,
            "what_was_done",
            "finding",
            "summary",
            "work_done",
            "contribution",
        )
        or f"Presents {record.title}.",
        "method_or_feedback": _first_text(
            payload,
            "method_or_feedback",
            "feedback_type",
            "feedback",
            "method",
            "evaluation_method",
        )
        or "Not stated in the source metadata.",
        "limitation": _first_text(
            payload,
            "limitation",
            "limitations",
            "weakness",
            "gap",
        )
        or "The source metadata does not state a detailed limitation.",
        "relevance": _first_text(payload, "relevance", "why_relevant")
        or "Included by the configured scholarly search.",
        "supporting_passage": passage,
        "confidence": confidence,
    }
    raw_evidence = payload.get("evidence")
    evidence_payload = raw_evidence if isinstance(raw_evidence, dict) else {}
    evidence_location = source_location or _source_location(record)
    normalized["evidence"] = {
        key: {
            "passage": (
                _first_text(value, "passage", "quote", "supporting_passage")
                if isinstance(value, dict)
                else None
            )
            or (passage if key == "what_was_done" else str(normalized[key])),
            "location": evidence_location,
        }
        for key in ("what_was_done", "method_or_feedback", "limitation")
        for value in [evidence_payload.get(key)]
    }
    return normalized


def _verbatim_source_passage(
    source_text: str,
    proposed: str,
    *,
    assertion: str = "",
) -> str:
    """Return one concise source-content span, never a document or page dump."""
    source_text = source_text.strip()
    if not source_text:
        return proposed.strip()
    target = proposed.strip()
    candidates = _source_passage_candidates(source_text)
    if target:
        folded_target = _comparison_text(target)
        for candidate in candidates:
            folded_candidate = _comparison_text(candidate)
            if folded_target and folded_target in folded_candidate:
                # Expand truncated model quotes to the complete source sentence/paragraph.
                if not re.search(r"[.!?][\"')\]]?$", target) and len(candidate) > len(target):
                    return candidate
                if _is_content_passage(target):
                    start = source_text.casefold().find(target.casefold())
                    if start >= 0:
                        return source_text[start : start + len(target)]
                return candidate

    if candidates:
        evidence_query = f"{target} {assertion}"
        target_tokens = _search_tokens(evidence_query)

        def score(candidate: str) -> tuple[float, int]:
            candidate_tokens = _search_tokens(candidate)
            overlap = len(target_tokens & candidate_tokens)
            similarity = SequenceMatcher(
                None,
                _comparison_text(evidence_query),
                _comparison_text(candidate),
            ).ratio()
            return overlap * 2 + similarity, -len(candidate)

        return max(candidates, key=score)
    # Metadata-only sources can be a title. Return one bounded line, never a
    # prefix spanning multiple HTML controls, sections, or PDF pages.
    lines = [" ".join(line.split()) for line in source_text.splitlines() if line.strip()]
    for line in lines:
        if _section_heading(line) is None and not _looks_like_page_chrome(line):
            return line[:300].strip()
    return (target or assertion or next(iter(lines), source_text))[:300].strip()


def _source_passage_candidates(source_text: str) -> list[str]:
    candidates: list[str] = []
    for line in source_text.splitlines():
        line = line.strip()
        if not line or re.fullmatch(r"\[(?:Page \d+|Section)\].*", line):
            continue
        chunks = (
            re.split(r"(?<=[.!?])\s+", line)
            if len(line) > 700
            else [line]
        )
        candidates.extend(chunk.strip() for chunk in chunks if _is_content_passage(chunk))
    return candidates


def _is_content_passage(value: str) -> bool:
    text = " ".join(value.split()).strip()
    words = re.findall(r"[^\W_]+", text, flags=re.UNICODE)
    if len(text) < 25 or len(text) > 700 or len(words) < 5:
        return False
    if _section_heading(text) is not None or text.count("|") >= 2:
        return False
    return not _looks_like_page_chrome(text)


def _looks_like_page_chrome(value: str) -> bool:
    folded = value.casefold()
    chrome_terms = (
        "username",
        "password",
        "remember me",
        "search scope",
        "journal content",
        "browse by",
        "font size",
        "login",
    )
    return sum(term in folded for term in chrome_terms) >= 3


def _comparison_text(value: str) -> str:
    return " ".join(re.findall(r"[^\W_]+", value.casefold(), flags=re.UNICODE))


def _gap_citations(citations: object) -> list[dict[str, Any]]:
    if not isinstance(citations, list):
        return []
    compact: list[dict[str, Any]] = []
    for item in citations:
        if not isinstance(item, dict):
            continue
        compact.append(
            {
                "id": item.get("id"),
                "citation_key": item.get("citation_key"),
                "title": item.get("title"),
                "year": item.get("year"),
                "venue": item.get("venue"),
                "abstract": str(item.get("abstract") or "")[:1_500],
                "verification_status": item.get("verification_status"),
                "provider": item.get("provider"),
                "retrieval_score": item.get("retrieval_score"),
                "relevance_rank": (
                    item.get("metadata", {}).get("relevance_rank")
                    if isinstance(item.get("metadata"), dict)
                    else None
                ),
            }
        )
    return compact


def _gap_findings(
    findings: object,
    citations: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if not isinstance(findings, list):
        return []
    keys_by_id = {
        item.get("id"): item.get("citation_key") for item in citations if item.get("id")
    }
    compact: list[dict[str, Any]] = []
    for item in findings:
        if not isinstance(item, dict):
            continue
        compact.append(
            {
                "citation_key": keys_by_id.get(item.get("citation_id")),
                "what_was_done": item.get("what_was_done"),
                "method_or_feedback": item.get("method_or_feedback"),
                "limitation": item.get("limitation"),
                "relevance": item.get("relevance"),
                "supporting_passage": str(item.get("supporting_passage") or "")[:500],
                "evidence": item.get("evidence"),
                "grounding_status": item.get("grounding_status"),
            }
        )
    return compact


def _gap_evidence_check(
    citations: list[dict[str, Any]],
    findings: list[dict[str, Any]],
) -> GapEvidenceCheck:
    verified = {
        str(item.get("citation_key"))
        for item in citations
        if item.get("citation_key")
        and str(item.get("verification_status")) == VerificationStatus.VERIFIED.value
    }
    grounded = {
        str(item.get("citation_key"))
        for item in findings
        if item.get("citation_key")
        and str(item.get("grounding_status")) == GroundingStatus.GROUNDED.value
    }
    eligible_set = verified & grounded
    eligible = [
        str(item.get("citation_key"))
        for item in citations
        if item.get("citation_key") and str(item.get("citation_key")) in eligible_set
    ]
    messages: list[str] = []
    if not verified:
        messages.append("No active Citation has verified source identity and metadata.")
    if not grounded:
        messages.append(
            "No Related Work finding has source-grounded evidence passages."
        )
    if verified and grounded and not eligible:
        messages.append(
            "Verified Citations and grounded findings do not refer to the same sources."
        )
    return GapEvidenceCheck(
        verified_citation_keys=[
            str(item.get("citation_key"))
            for item in citations
            if item.get("citation_key") and str(item.get("citation_key")) in verified
        ],
        grounded_citation_keys=[
            str(item.get("citation_key"))
            for item in citations
            if item.get("citation_key") and str(item.get("citation_key")) in grounded
        ],
        eligible_citation_keys=eligible,
        ready=bool(eligible),
        messages=messages,
    )


def _counter_record_payload(record: ScholarlyRecord) -> dict[str, Any]:
    return {
        "result_key": _record_result_key(record),
        "title": record.title,
        "authors": record.authors,
        "year": record.year,
        "venue": record.venue,
        "doi": record.doi,
        "provider": record.provider,
        "provider_source_id": record.provider_source_id,
        "abstract": str(record.abstract or "")[:1_500],
        "retrieval_score": record.metadata.get("retrieval_score"),
        "discovery_queries": record.metadata.get("discovery_queries", []),
    }


def _record_result_key(record: ScholarlyRecord) -> str:
    return str(
        normalize_doi(record.doi)
        or record.provider_source_id
        or normalize_url(record.url)
        or citation_key(record.title, record.year)
    )


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _nonnegative_int(value: object) -> int:
    if not isinstance(value, (int, float, str)) or not value:
        return 0
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def _positive_rank(value: object) -> int:
    if not isinstance(value, (int, float, str)) or not value:
        return 1_000_000
    try:
        return max(1, int(value))
    except (TypeError, ValueError):
        return 1_000_000


def _fallback_gap_statement(related_work: list[dict[str, Any]]) -> str:
    if not related_work:
        return (
            "The available Related Work does not yet provide enough source-grounded "
            "evidence to define a precise research gap. Additional scholarly sources "
            "and comparative analysis are required."
        )
    accomplishments = [
        str(item.get("what_was_done") or "").strip()
        for item in related_work
        if str(item.get("what_was_done") or "").strip()
    ]
    limitations = [
        str(item.get("limitation") or "").strip()
        for item in related_work
        if str(item.get("limitation") or "").strip()
    ]
    prior = (
        "; ".join(accomplishments) or "The reviewed studies propose related approaches"
    )
    remaining = "; ".join(limitations) or (
        "their combined limitations are not sufficiently established in the available metadata"
    )
    return (
        f"Across the reviewed Related Work, {prior}. However, {remaining}. "
        "It remains unclear whether a unified approach can address these limitations "
        "under a controlled comparative evaluation."
    )


def _gap_statement_from_answers(answers: _GapQuestionAnswers) -> str:
    """Keep validated source-grounded analysis when only synthesis fails."""

    return " ".join(
        (
            _as_sentence(answers.prior_work),
            _as_sentence(f"However, {answers.limitation}"),
            _as_sentence(answers.importance),
            _as_sentence(answers.testability),
        )
    )


def _as_sentence(value: str) -> str:
    text = value.strip()
    return text if text.endswith((".", "!", "?")) else f"{text}."


def _first_text(payload: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _deduplicate_records(records: list[ScholarlyRecord]) -> list[ScholarlyRecord]:
    found: dict[tuple[str, ...], ScholarlyRecord] = {}
    for record in records:
        doi = normalize_doi(record.doi)
        if doi:
            identity = ("doi", doi)
        elif record.title.strip():
            identity = (
                "title",
                _comparison_text(record.title),
                str(record.year or ""),
            )
        elif record.provider and record.provider_source_id:
            identity = (
                "provider",
                record.provider.casefold(),
                record.provider_source_id.casefold(),
            )
        elif record.url:
            identity = ("url", normalize_url(record.url) or record.url.casefold())
        else:
            identity = ("unknown", str(id(record)))
        existing = found.get(identity)
        if existing is not None:
            _merge_scholarly_records(existing, record)
            continue
        found[identity] = record
    return list(found.values())


def _merge_scholarly_records(
    target: ScholarlyRecord,
    incoming: ScholarlyRecord,
) -> None:
    target.authors = list(dict.fromkeys([*target.authors, *incoming.authors]))
    if len(incoming.abstract or "") > len(target.abstract or ""):
        target.abstract = incoming.abstract
    if not target.doi:
        target.doi = incoming.doi
    if not target.venue:
        target.venue = incoming.venue
    if not target.url or incoming.metadata.get("full_text_url"):
        target.url = incoming.url or target.url
    provider_ids = dict(target.metadata.get("provider_ids") or {})
    provider_ids.update(incoming.metadata.get("provider_ids") or {})
    if incoming.provider and incoming.provider_source_id:
        provider_ids[incoming.provider] = incoming.provider_source_id
    merged = {**incoming.metadata, **target.metadata, "provider_ids": provider_ids}
    for key in ("discovery_queries", "discovery_types", "citation_graph_seeds"):
        merged[key] = list(
            dict.fromkeys(
                [
                    *(target.metadata.get(key) or []),
                    *(incoming.metadata.get(key) or []),
                ]
            )
        )
    if incoming.metadata.get("full_text_url") and not merged.get("full_text_url"):
        merged["full_text_url"] = incoming.metadata["full_text_url"]
    target.metadata = merged


def _idea_context(context: dict[str, Any]) -> dict[str, Any]:
    decomposition = context.get("upstream", {}).get(
        WorkflowNode.IDEA_DECOMPOSITION.value, {}
    )
    cards = decomposition.get("card_snapshot", [])
    groups: dict[str, list[str]] = {
        "problems": [],
        "research_questions": [],
        "constraints": [],
        "open_questions": [],
    }
    group_by_kind = {
        "problem": "problems",
        "research_question": "research_questions",
        "constraint": "constraints",
        "open_question": "open_questions",
    }
    for card in cards:
        if not isinstance(card, dict):
            continue
        group = group_by_kind.get(str(card.get("kind") or ""))
        if group is None:
            continue
        body = card.get("body")
        groups[group].extend(_text_values(body))
    return {key: values for key, values in groups.items() if values}


def _idea_language_instruction(idea: object) -> str:
    """Keep generated Research content in the confirmed idea's language."""

    return (
        "Infer the primary language from the supplied idea and write every generated "
        "user-facing value in that same language. Preserve technical terms and verbatim "
        "source passages in their original language when translating them would reduce "
        "precision. JSON field names must remain exactly as specified. "
    )


_KEYWORD_STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "by",
    "can",
    "does",
    "each",
    "for",
    "from",
    "how",
    "in",
    "into",
    "is",
    "not",
    "of",
    "on",
    "or",
    "same",
    "than",
    "that",
    "the",
    "their",
    "this",
    "to",
    "under",
    "what",
    "when",
    "where",
    "which",
    "with",
    "các",
    "có",
    "của",
    "để",
    "được",
    "không",
    "là",
    "làm",
    "một",
    "những",
    "thế",
    "theo",
    "trong",
    "từ",
    "và",
    "với",
}

_LOW_VALUE_WORDS = {
    "analyze",
    "analyzes",
    "analyzing",
    "assess",
    "assesses",
    "assessing",
    "categorized",
    "categorize",
    "categorizes",
    "categorizing",
    "classified",
    "classify",
    "classifies",
    "classifying",
    "compare",
    "compares",
    "comparing",
    "contain",
    "contains",
    "evaluate",
    "evaluates",
    "evaluating",
    "generated",
    "get",
    "gets",
    "measure",
    "measures",
    "measuring",
    "method",
    "methods",
    "moment",
    "output",
    "outputs",
    "paper",
    "papers",
    "plausible",
    "research",
    "result",
    "results",
    "source",
    "sources",
    "statement",
    "statements",
    "studies",
    "study",
    "summaries",
    "summary",
}

_LOW_VALUE_PHRASES = {
    "llm-generated",
    "llm generated",
    "related work",
    "research idea",
    "source paper",
}


_NON_CONCEPT_KEYWORD_PATTERNS = (
    # Research instructions are actions, not the concepts being investigated.
    (
        r"^(?:analy[sz](?:e|es|ed|ing)|assess(?:es|ed|ing)?|"
        r"categori[sz](?:e|es|ed|ing)|classif(?:y|ies|ied|ying)|"
        r"compar(?:e|es|ed|ing)|determin(?:e|es|ed|ing)|"
        r"evaluat(?:e|es|ed|ing)|measur(?:e|es|ed|ing))\b"
    ),
    # Narrative subject-verb fragments are not useful scholarly search phrases.
    (
        r"^(?:a\s+)?(?:person|people|participant|participants|user|users)\s+"
        r"(?:feel|feels|get|gets|go|goes|spend|spends|use|uses)\b"
    ),
    # These usually survive when a time span or prose comparison was cut badly.
    r"\buntil\b",
    r"\bvs\.?\b",
    # A trailing prose predicate/category label leaves an incomplete phrase.
    r"\b(?:calming|categorized|classified|stressful)\s*$",
)


def _clean_keywords(values: list[str]) -> list[str]:
    cleaned: list[str] = []
    seen: set[str] = set()
    for raw in values:
        phrase = re.sub(r"\s+", " ", raw.strip(" \t\r\n`'\".,:;()[]{}"))
        folded = phrase.casefold()
        if not phrase or folded in seen or folded in _LOW_VALUE_PHRASES:
            continue
        if re.search(
            r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b",
            folded,
        ):
            continue
        if any(re.search(pattern, folded) for pattern in _NON_CONCEPT_KEYWORD_PATTERNS):
            continue
        words = re.findall(r"[^\W_]+", folded, flags=re.UNICODE)
        content_words = [
            word
            for word in words
            if word not in _KEYWORD_STOPWORDS and word not in _LOW_VALUE_WORDS
        ]
        # Generic words may still form a meaningful target artifact when combined
        # (for example, "paper summaries"); only reject them as standalone terms.
        if (not content_words and len(words) < 2) or len(words) > 6 or len(phrase) > 80:
            continue
        if len(words) == 1 and words[0] in _LOW_VALUE_WORDS:
            continue
        cleaned.append(phrase)
        seen.add(folded)
    return cleaned


def _fallback_keywords(idea: dict[str, Any]) -> list[str]:
    text = " ".join(_text_values(idea)).casefold()
    mapped: list[str] = []
    concept_patterns = (
        (r"\bllm\b.*\b(?:summar|summary)", "LLM paper summarization"),
        (
            r"\bunsupported\b.*\bclaims?\b|\bclaims?\b.*\bunsupported\b",
            "unsupported claim detection",
        ),
        (
            r"\bclaims?\b.*\bevidence\b|\bevidence\b.*\bclaims?\b",
            "claim-evidence verification",
        ),
        (r"\bclaims?\b.*\bverif", "claim verification"),
        (r"\bhallucinat", "hallucination reduction"),
        (
            r"\bprompts?\b.*\boptimi[sz]|\boptimi[sz].*\bprompts?\b",
            "prompt optimization",
        ),
        (r"\binference\s+budget\b", "inference budget"),
        (r"\bhuman[-\s]+in[-\s]+the[-\s]+loop\b", "human-in-the-loop verification"),
        (r"\bcitation[-\s]+ground", "citation-grounded generation"),
        (r"\bsource[-\s]+ground", "source-grounded generation"),
    )
    for pattern, phrase in concept_patterns:
        if re.search(pattern, text):
            mapped.append(phrase)

    extracted: list[str] = []
    # Split prose around actions and narrative glue before treating the remaining
    # spans as idea anchors. Single words are deliberately not emitted here: the
    # model can still suggest a genuine one-word technical term, while prose-derived
    # words such as "measure" or "moment" must not crowd out useful noun phrases.
    breakers = _KEYWORD_STOPWORDS | {
        "analyze",
        "analyzes",
        "analyzing",
        "assess",
        "assesses",
        "assessing",
        "calming",
        "categorized",
        "categorize",
        "categorizes",
        "categorizing",
        "check",
        "checking",
        "classified",
        "classify",
        "classifies",
        "classifying",
        "compare",
        "compared",
        "compares",
        "comparing",
        "contain",
        "contains",
        "determine",
        "determines",
        "determining",
        "evaluate",
        "evaluates",
        "evaluating",
        "get",
        "gets",
        "getting",
        "measure",
        "measures",
        "measuring",
        "moment",
        "reduce",
        "reduces",
        "stressful",
        "until",
        "use",
        "uses",
        "user",
        "users",
        "vs",
    }
    for value in _text_values(idea):
        words = re.findall(r"[^\W_][\w-]*", value.casefold(), flags=re.UNICODE)
        segment: list[str] = []
        for word in [*words, ""]:
            if not word or word in breakers:
                if 2 <= len(segment) <= 5:
                    extracted.append(" ".join(segment))
                # Long spans are prose, not reliable noun phrases. In particular,
                # sliding n-grams produce fragments such as "giáo viên mất" and
                # "mất quá nhiều" that look like keywords but have no search value.
                segment = []
            else:
                segment.append(word)

    keywords = _clean_keywords([*mapped, *extracted])
    return keywords[:8] or ["related work discovery"]


def _idea_search_concepts(idea: dict[str, Any]) -> list[str]:
    """Return core Problem/RQ phrases that must survive keyword generation."""
    core_idea = {
        key: idea.get(key, [])
        for key in ("problems", "research_questions")
        if idea.get(key)
    }
    if not _text_values(core_idea):
        return []
    return [
        keyword
        for keyword in _fallback_keywords(core_idea)
        if keyword.casefold() != "related work discovery"
    ]


def _idea_exploratory_concepts(idea: dict[str, Any]) -> list[str]:
    open_questions = {"open_questions": idea.get("open_questions", [])}
    if not _text_values(open_questions):
        return []
    return [
        keyword
        for keyword in _fallback_keywords(open_questions)
        if keyword.casefold() != "related work discovery"
    ]


def _compose_search_queries(
    model_queries: list[str],
    inputs: ResearchInputs,
    idea: dict[str, Any],
) -> list[str]:
    """Build role-aware fallbacks without turning every concept into a lone query."""
    anchors = _idea_search_concepts(idea)
    confirmed = _clean_keywords(inputs.keywords)
    exploratory = _idea_exploratory_concepts(idea)
    queries: list[str] = []
    seen: set[str] = set()

    for raw in model_queries:
        query = re.sub(r"\s+", " ", raw.strip())
        folded = query.casefold()
        if not query or folded in seen:
            continue
        queries.append(query)
        seen.add(folded)

    # Model queries may use useful scholarly synonyms. Deterministic fallbacks still
    # cover confirmed/core concepts, but pair them with another core concept so they
    # retain research intent instead of becoming broad one-keyword searches.
    core_concepts = _clean_keywords([*anchors, *confirmed])
    for concept in _clean_keywords([*anchors, *confirmed]):
        concept_tokens = _search_tokens(concept)
        covered = any(
            _matched_concept_indexes([concept_tokens], _search_tokens(query))
            for query in queries
        )
        if covered:
            continue
        partner = next(
            (
                candidate
                for candidate in core_concepts
                if candidate.casefold() != concept.casefold()
            ),
            None,
        )
        query = _paired_query(concept, partner)
        folded = query.casefold()
        if folded not in seen:
            queries.append(query)
            seen.add(folded)

    # Open Questions are exploration branches rather than mandatory primary-query
    # filters. Add a focused fallback only when the model did not cover the concept.
    primary_anchor = core_concepts[0] if core_concepts else None
    for concept in exploratory:
        concept_tokens = _search_tokens(concept)
        if any(
            _matched_concept_indexes([concept_tokens], _search_tokens(query))
            for query in queries
        ):
            continue
        query = _paired_query(primary_anchor, concept)
        folded = query.casefold()
        if folded not in seen:
            queries.append(query)
            seen.add(folded)

    return queries or ["related work"]


def _normalize_search_queries(
    values: list[str],
    *,
    max_terms: int | None = None,
) -> list[str]:
    queries: list[str] = []
    seen: set[str] = set()
    for raw in values:
        query = re.sub(r"\s+", " ", raw.strip())
        folded = query.casefold()
        if not query or folded in seen:
            continue
        vietnamese_chars = (
            "ăằắặẳẵâầấậẩẫđêềếệểễôồốộổỗơờớợởỡưừứựửữàáạảãèéẹẻẽìíịỉĩòóọỏõùúụủũỳýỵỷỹ"
        )
        vietnamese_words = {
            "kiem",
            "chung",
            "tuyen",
            "nghien",
            "cuu",
            "tai",
            "lieu",
            "khong",
            "duoc",
            "trong",
            "cua",
        }
        query_words = set(re.findall(r"[^\W_]+", folded, flags=re.UNICODE))
        if (
            any(char in vietnamese_chars for char in folded)
            or len(query_words & vietnamese_words) >= 2
        ):
            raise ValueError("The query model returned Vietnamese instead of English")
        if max_terms is not None and len(_search_tokens(query)) > max_terms:
            continue
        queries.append(query)
        seen.add(folded)
    return queries


def _ensure_query_families(
    queries: list[str],
    *,
    limit: int | None = None,
) -> list[str]:
    """Guarantee useful discovery branches within the provider request budget."""

    normalized = _normalize_search_queries(queries)
    base = normalized[0] if normalized else "scholarly evidence review"
    anchor = _query_anchor(base)
    branches = (
        f'"{anchor}" AND (survey OR review)',
        f'"{anchor}" AND (limitation OR challenge)',
        f'"{anchor}" AND (benchmark OR evaluation)',
    )
    candidates = _normalize_search_queries([*(normalized or [base]), *branches])
    return _limit_query_families(
        candidates,
        limit=limit,
        family_order=("survey", "limitation", "evaluation", "core"),
        prefix_count=len(normalized or [base]),
    )


def _ensure_counter_query_families(
    model_queries: list[str],
    related_work_queries: list[str],
    *,
    limit: int | None = None,
) -> list[str]:
    normalized = _normalize_search_queries(model_queries)
    anchors = _normalize_search_queries(related_work_queries)
    base = next(iter(normalized or anchors), "scholarly evidence review")
    anchor = _query_anchor(base)
    branches = (
        f'"{anchor}" AND (survey OR review)',
        f'"{anchor}" AND (benchmark OR replication)',
        f'"{anchor}" AND (limitation OR conflicting)',
    )
    candidates = _normalize_search_queries([*(normalized or [base]), *branches])
    return _limit_query_families(
        candidates,
        limit=limit,
        family_order=("evaluation", "limitation", "survey", "core"),
        prefix_count=len(normalized or [base]),
    )


def _limit_query_families(
    queries: list[str],
    *,
    limit: int | None,
    family_order: tuple[str, ...],
    prefix_count: int,
) -> list[str]:
    if limit is None:
        return queries
    bounded_limit = max(limit, 1)
    if len(queries) <= bounded_limit:
        return queries

    selected = queries[: min(prefix_count, bounded_limit)]
    if len(selected) >= bounded_limit:
        return selected
    for family in family_order:
        candidate = next(
            (
                query
                for query in queries[prefix_count:]
                if query not in selected and _query_family(query) == family
            ),
            None,
        )
        if candidate is not None:
            selected.append(candidate)
        if len(selected) >= bounded_limit:
            return selected
    for query in queries:
        if query not in selected:
            selected.append(query)
        if len(selected) >= bounded_limit:
            break
    return selected


def _query_family(query: str) -> str:
    folded = query.casefold()
    if any(term in folded for term in ("limitation", "challenge", "conflicting")):
        return "limitation"
    if any(term in folded for term in ("survey", "review")):
        return "survey"
    if any(
        term in folded
        for term in ("benchmark", "evaluation", "comparison", "replication")
    ):
        return "evaluation"
    return "core"


def _query_anchor(query: str) -> str:
    quoted = re.findall(r'"([^"\n]+)"', query)
    if quoted:
        return quoted[0]
    words = re.findall(r"[^\W_]+", query, flags=re.UNICODE)
    content = [word for word in words if word.casefold() not in {"and", "or", "not"}]
    return " ".join(content[:4]) or "scholarly evidence"


def _english_query_fallback(
    inputs: ResearchInputs,
    idea: dict[str, Any],
) -> list[str]:
    """Keep provider queries English even when translation generation is unavailable."""
    candidates = _clean_keywords(
        [*inputs.keywords, *_idea_search_concepts(idea)]
    )
    focused: list[str] = []
    for candidate in candidates:
        try:
            normalized = _normalize_search_queries([candidate], max_terms=6)
        except ValueError:
            continue
        if normalized and normalized[0].casefold() not in {
            value.casefold() for value in focused
        }:
            focused.append(normalized[0])
        if len(focused) >= 2:
            return focused
    return focused or ["scholarly evidence review", "systematic literature review"]


def _paired_query(first: str | None, second: str | None) -> str:
    concepts = [item for item in (first, second) if item]
    if len(concepts) < 2:
        return concepts[0] if concepts else "related work"
    return " AND ".join(f'"{item}"' for item in concepts)


def _search_token(value: str) -> str:
    token = value.casefold()
    if len(token) > 4 and token.endswith("ies"):
        return f"{token[:-3]}y"
    if len(token) > 4 and token.endswith("s") and not token.endswith("ss"):
        return token[:-1]
    return token


def _search_tokens(value: str) -> set[str]:
    return {
        _search_token(token)
        for token in re.findall(r"[^\W_]+", value.casefold(), flags=re.UNICODE)
        if token not in _KEYWORD_STOPWORDS
    }


def _concept_groups(values: list[str]) -> list[set[str]]:
    groups: list[set[str]] = []
    seen: set[frozenset[str]] = set()
    for value in values:
        tokens = _search_tokens(value)
        frozen = frozenset(tokens)
        if not tokens or frozen in seen:
            continue
        groups.append(tokens)
        seen.add(frozen)
    return groups


def _query_concepts(queries: list[str]) -> list[str]:
    concepts: list[str] = []
    for query in queries:
        concepts.extend(
            part.strip(" \t\r\n\"'()")
            for part in re.split(r"\b(?:AND|OR)\b", query, flags=re.IGNORECASE)
            if part.strip(" \t\r\n\"'()")
        )
    return concepts


def _concept_match_count(groups: list[set[str]], text_tokens: set[str]) -> int:
    return len(_matched_concept_indexes(groups, text_tokens))


def _matched_concept_indexes(groups: list[set[str]], text_tokens: set[str]) -> set[int]:
    matches: set[int] = set()
    for index, group in enumerate(groups):
        overlap = len(group & text_tokens)
        required = len(group) if len(group) <= 2 else max(2, round(len(group) * 0.67))
        if overlap >= required:
            matches.add(index)
    return matches


def _rank_relevant_records(
    records: list[ScholarlyRecord],
    *,
    inputs: ResearchInputs,
    idea: dict[str, Any],
    queries: list[str] | None = None,
) -> tuple[list[ScholarlyRecord], int]:
    """Rank by concept coverage and reject idea-mismatched provider results."""
    query_concepts = _query_concepts(queries or [])
    idea_groups = _concept_groups(query_concepts or _idea_search_concepts(idea))
    all_groups = _concept_groups(
        query_concepts
        or [*_idea_search_concepts(idea), *_clean_keywords(inputs.keywords)]
    )
    scored: list[tuple[tuple[float, ...], int, set[int], ScholarlyRecord]] = []
    discarded = 0
    for index, record in enumerate(records):
        title_tokens = _search_tokens(record.title)
        text_tokens = title_tokens | _search_tokens(record.abstract or "")
        matched_idea = _matched_concept_indexes(idea_groups, text_tokens)
        # Provider search can be semantic, so a returned English paper need not repeat
        # every generated query term verbatim. English-query matches drive ranking;
        # retain provider candidates and let the final top-five cutoff decide.
        if idea_groups and not matched_idea and not queries:
            discarded += 1
            continue
        concept_matches = _concept_match_count(all_groups, text_tokens)
        covered_tokens = (
            len(set().union(*all_groups) & text_tokens) if all_groups else 0
        )
        title_hits = len(set().union(*all_groups) & title_tokens) if all_groups else 0
        query_hits = len(record.metadata.get("discovery_queries") or [])
        graph_hits = len(record.metadata.get("citation_graph_seeds") or [])
        denominator = max(len(all_groups) * 2 + 4, 1)
        retrieval_score = min(
            1.0,
            (
                len(matched_idea) * 2
                + concept_matches
                + min(title_hits, 2)
                + min(query_hits, 2) * 0.5
                + min(graph_hits, 1) * 0.5
            )
            / denominator,
        )
        record.metadata["retrieval_score"] = round(retrieval_score, 4)
        record.metadata["matched_concept_indexes"] = sorted(matched_idea)
        scored.append(
            (
                (
                    len(matched_idea),
                    concept_matches,
                    title_hits,
                    query_hits,
                    graph_hits,
                    covered_tokens,
                ),
                -index,
                matched_idea,
                record,
            )
        )
    scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return [item[3] for item in scored], discarded


def _query_plan(queries: list[str]) -> list[dict[str, str]]:
    plan: list[dict[str, str]] = []
    for index, query in enumerate(queries):
        folded = query.casefold()
        if any(word in folded for word in ("survey", "review", "benchmark")):
            kind = "survey"
        elif any(word in folded for word in ("limitation", "challenge", "future work")):
            kind = "limitations"
        elif index == 0:
            kind = "core_topic"
        else:
            kind = "relationship"
        plan.append({"id": f"q{index + 1}", "kind": kind, "text": query})
    return plan


def _text_values(value: object) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [text for item in value.values() for text in _text_values(item)]
    if isinstance(value, list):
        return [text for item in value for text in _text_values(item)]
    return []


def _llm_failure_summary(exc: Exception) -> str:
    if isinstance(exc, ValidationError):
        return "the model response did not match the required fields"
    if isinstance(exc, (json.JSONDecodeError, TypeError, ValueError)):
        return "the model response was not valid structured JSON"
    if not isinstance(exc, LlmProviderError):
        return type(exc).__name__
    details = []
    if exc.status_code is not None:
        details.append(f"HTTP {exc.status_code}")
    if exc.code:
        details.append(exc.code)
    suffix = f" ({'; '.join(details)})" if details else ""
    return f"{exc}{suffix}"


def _grounding_status(source_text: str, passage: str) -> GroundingStatus:
    if not passage:
        return GroundingStatus.REJECTED
    if passage.casefold() in source_text.casefold():
        return GroundingStatus.GROUNDED
    return GroundingStatus.WARNING


def _source_location(record: ScholarlyRecord) -> str:
    return "Abstract" if record.abstract else "Title"


def _document_location(
    document: DocumentText | None,
    record: ScholarlyRecord,
) -> str:
    if document is None:
        return _source_location(record)
    return {
        "abstract": "Abstract",
        "full_text_pdf": "Source passage",
        "full_text_html": "Source passage",
        "full_text": "Source passage",
    }.get(document.source_kind, document.source_kind)


def _analysis_excerpt(
    source_text: str,
    research_context: dict[str, Any],
    *,
    limit: int,
) -> str:
    """Keep broad context plus method/limitation passages within the LLM budget."""
    if len(source_text) <= limit:
        return source_text
    idea_tokens = _search_tokens(" ".join(_text_values(research_context)))
    section_terms = {
        "abstract",
        "introduction",
        "related",
        "method",
        "methodology",
        "experiment",
        "evaluation",
        "limitation",
        "discussion",
        "future",
        "conclusion",
    }
    paragraphs = [
        item.strip() for item in re.split(r"\n\s*\n", source_text) if item.strip()
    ]
    scored = sorted(
        enumerate(paragraphs),
        key=lambda item: (
            len(_search_tokens(item[1]) & section_terms),
            len(_search_tokens(item[1]) & idea_tokens),
            -item[0],
        ),
        reverse=True,
    )
    selected: list[tuple[int, str]] = []
    size = 0
    for index, paragraph in scored:
        if size + len(paragraph) > limit - 4_000:
            continue
        selected.append((index, paragraph))
        size += len(paragraph) + 2
        if size >= limit - 4_000:
            break
    tail = "\n\n".join(text for _, text in sorted(selected))
    return f"{source_text[:4_000]}\n\n{tail}"[:limit]


def _passage_location(
    source_text: str,
    passage: str,
    fallback: str,
) -> str:
    position = source_text.casefold().find(passage.casefold())
    if position < 0:
        return fallback
    prefix_lines = source_text[:position].splitlines()
    for line in reversed(prefix_lines[-80:]):
        candidate = line.strip()
        if re.fullmatch(r"\[Page \d+\]", candidate):
            return candidate.strip("[]")
        heading = _section_heading(candidate)
        if heading is not None:
            return heading
    return fallback


def _section_heading(value: str) -> str | None:
    candidate = " ".join(value.split()).strip()
    if candidate.startswith("[Section]"):
        heading = candidate.removeprefix("[Section]").strip()
        return heading or None
    if not 2 <= len(candidate) <= 100 or len(candidate.split()) > 10:
        return None
    if re.search(r"[,;!?]", candidate):
        return None
    without_number = re.sub(
        r"^(?:(?:\d+(?:\.\d+)*)|(?:[IVXLCDM]+))[.)]?\s+",
        "",
        candidate,
        flags=re.IGNORECASE,
    ).strip(" .:-")
    known = {
        "abstract",
        "introduction",
        "background",
        "related work",
        "method",
        "methods",
        "methodology",
        "materials and methods",
        "research methodology",
        "experimental setup",
        "evaluation",
        "result",
        "results",
        "limitation",
        "limitations",
        "discussion",
        "future work",
        "conclusion",
        "conclusions",
    }
    return candidate if without_number.casefold() in known else None


def _evidence_grounding_status(
    source_text: str,
    evidence: dict[str, dict[str, str]],
) -> GroundingStatus:
    statuses = [
        _grounding_status(source_text, item.get("passage", ""))
        for item in evidence.values()
    ]
    if statuses and all(item is GroundingStatus.GROUNDED for item in statuses):
        return GroundingStatus.GROUNDED
    if any(item is GroundingStatus.REJECTED for item in statuses):
        return GroundingStatus.REJECTED
    return GroundingStatus.WARNING
