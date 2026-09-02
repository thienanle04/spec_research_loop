"""Research application services and in-request generation workflow."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime
from difflib import SequenceMatcher
from typing import Any, Literal
from uuid import UUID, uuid4

from fastapi import HTTPException, status
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import OperationalErrorException
from app.modules.loop.catalog import CardKind, NodeHeadStatus, WorkflowNode, ancestors
from app.modules.loop.models import Card, LoopSession, NodeHead, StageRevision
from app.modules.loop.service import LoopService
from app.modules.research.models import Citation, RelatedWorkFinding
from app.modules.research.normalization import (
    citation_key,
    normalize_doi,
    normalize_url,
    utf8_safe_text,
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
    CounterEvidenceContentBasis,
    CounterEvidenceOutcome,
    CounterEvidenceRelevance,
    CounterEvidenceResult,
    CounterEvidenceSupport,
    DoneEvent,
    DraftPatchEvent,
    ErrorEvent,
    GapCardBody,
    GapClaimAssessment,
    GapClaimEvidence,
    GapClaimKind,
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

logger = logging.getLogger(__name__)


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


class _GapClaim(BaseModel):
    claim_id: str = Field(min_length=1)
    kind: GapClaimKind
    statement: str = Field(min_length=1)
    supporting_citation_keys: list[str] = Field(min_length=1)
    supporting_evidence: list[GapClaimEvidence] = Field(default_factory=list)


class _GapQuestionAnswers(BaseModel):
    """Internal analysis used to produce the single user-facing Gap statement."""

    prior_work: str = Field(min_length=1)
    limitation: str = Field(min_length=1)
    importance: str = Field(min_length=1)
    testability: str = Field(min_length=1)
    covered_citation_keys: list[str] = Field(min_length=1)
    claims: list[_GapClaim] = Field(default_factory=list)


class _GapSynthesis(BaseModel):
    statement: str = Field(min_length=1)


class _GapClaimSupportItem(BaseModel):
    claim_id: str = Field(min_length=1)
    support_status: CounterEvidenceSupport
    atomicity_status: Literal["atomic", "compound", "uncertain"] = "uncertain"
    evidence_span: str = ""
    unsupported_fragments: list[str] = Field(default_factory=list)


class _GapClaimSupportResponse(BaseModel):
    assessments: list[_GapClaimSupportItem] = Field(min_length=1)


class _GapClaimNarrowing(BaseModel):
    claim_id: str = Field(min_length=1)
    can_narrow: bool
    statement: str = ""
    evidence_span: str = ""


class _CounterEvidenceFinding(BaseModel):
    result_key: str = Field(min_length=1)
    claim_ids: list[str] = Field(default_factory=list)
    impact: CounterEvidenceOutcome
    rationale: str = Field(min_length=1)
    supporting_passage: str = ""
    source_location: str = ""
    relevance_status: CounterEvidenceRelevance
    content_basis: CounterEvidenceContentBasis = (
        CounterEvidenceContentBasis.METADATA_ONLY
    )
    grounding_status: GroundingStatus = GroundingStatus.PENDING
    support_status: CounterEvidenceSupport = CounterEvidenceSupport.PENDING


class _CounterEvidenceClaimAssessment(BaseModel):
    claim_id: str = Field(min_length=1)
    outcome: CounterEvidenceOutcome
    assessment: str = Field(min_length=1)
    revised_statement: str | None = None
    counter_evidence_result_keys: list[str] = Field(default_factory=list)


class _CounterEvidenceAssessment(BaseModel):
    outcome: CounterEvidenceOutcome
    statement: str = Field(min_length=1)
    assessment: str = Field(min_length=1)
    covered_result_keys: list[str] = Field(default_factory=list)
    findings: list[_CounterEvidenceFinding] = Field(default_factory=list)
    claim_assessments: list[_CounterEvidenceClaimAssessment] = Field(
        default_factory=list
    )


class _CounterSourceClaimFinding(BaseModel):
    claim_id: str = Field(min_length=1)
    impact: CounterEvidenceOutcome
    rationale: str = Field(min_length=1)
    revised_statement: str | None = None


class _CounterSourceAssessment(BaseModel):
    result_key: str = Field(min_length=1)
    impact: CounterEvidenceOutcome
    rationale: str = Field(min_length=1)
    relevance_status: CounterEvidenceRelevance
    supporting_passage: str = ""
    source_location: str = ""
    claim_findings: list[_CounterSourceClaimFinding] = Field(default_factory=list)


class _CounterSupportItem(BaseModel):
    result_key: str = Field(min_length=1)
    support_status: CounterEvidenceSupport


class _CounterSupportResponse(BaseModel):
    assessments: list[_CounterSupportItem] = Field(min_length=1)


class _RerankItem(BaseModel):
    result_key: str = Field(min_length=1)
    relevance_score: float = Field(ge=0, le=1)


class _RerankResponse(BaseModel):
    rankings: list[_RerankItem] = Field(min_length=1)


class _SearchFacet(BaseModel):
    id: str = Field(min_length=1, max_length=80)
    objective: str = Field(min_length=1, max_length=300)
    anchors: list[str] = Field(min_length=1)
    # A facet may be evaluation-only. In tool-oriented search, only the named-tool
    # facet contributes provider queries; the other facets score candidate relevance.
    queries: list[str] = Field(default_factory=list)
    min_results: int = Field(default=2, ge=1, le=2)
    tool_names: list[str] = Field(default_factory=list)
    candidate_work_titles: list[str] = Field(default_factory=list)


class _SearchPlan(BaseModel):
    facets: list[_SearchFacet] = Field(min_length=1, max_length=4)

    @property
    def queries(self) -> list[str]:
        return list(
            dict.fromkeys(query for facet in self.facets for query in facet.queries)
        )


class _DiscoveryExpansion(BaseModel):
    tool_discovery_keywords: list[str] = Field(default_factory=list)
    supporting_context_keywords: list[str] = Field(default_factory=list)
    tools_and_frameworks: list[str] = Field(default_factory=list)
    techniques: list[str] = Field(default_factory=list, max_length=8)
    candidate_work_titles: list[str] = Field(default_factory=list, max_length=6)
    aliases: list[str] = Field(default_factory=list, max_length=8)


_IMPLEMENTATION_TOOLS_FACET = "implementation_tools"
_ABSTRACT_ONLY_FINDING_WARNING = (
    "Finding is grounded only in the provider abstract; full text is required "
    "before it can support a Gap Candidate."
)

# Conservative, topic-triggered discovery aliases. These names are search leads,
# never accepted as Citation evidence until a provider returns a verifiable record.
_KNOWN_RESEARCH_TOOLS: tuple[tuple[frozenset[str], tuple[str, ...]], ...] = (
    (
        frozenset(
            {
                "feedback",
                "gradient",
                "iterative",
                "optimization",
                "optimize",
                "prompt",
                "refinement",
            }
        ),
        ("DSPy", "TextGrad", "OPRO", "ProTeGi"),
    ),
    (
        frozenset({"judge", "evaluator", "evaluation", "grading"}),
        ("G-Eval", "Prometheus"),
    ),
)


@dataclass(slots=True)
class _CounterEvidenceSearch:
    queries: list[str]
    records: list[ScholarlyRecord]
    selected_records: list[ScholarlyRecord]
    candidate_records: list[ScholarlyRecord]
    candidate_count: int
    complete: bool
    warnings: list[str]


@dataclass(slots=True)
class _CounterEvidenceMaterial:
    record: ScholarlyRecord
    source_text: str
    source_kind: str
    source_location: str
    source_object_key: str | None = None


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
        stage_revision_id: UUID | None = None,
    ) -> list[CitationResponse]:
        await self._load_owned_session(session_id, account_id)
        if stage_revision_id is None:
            rows = await self._working_citations(session_id)
        else:
            await self._assert_session_revision(session_id, stage_revision_id)
            rows = await self._revision_citations(session_id, stage_revision_id)
        return [self._citation_response(row) for row in rows]

    async def list_findings(
        self,
        *,
        session_id: UUID,
        account_id: UUID,
        stage_revision_id: UUID | None = None,
    ) -> list[RelatedWorkFindingResponse]:
        await self._load_owned_session(session_id, account_id)
        revision_filter = (
            RelatedWorkFinding.stage_revision_id.is_(None)
            if stage_revision_id is None
            else RelatedWorkFinding.stage_revision_id == stage_revision_id
        )
        citation_revision_filter = (
            Citation.stage_revision_id.is_(None)
            if stage_revision_id is None
            else Citation.stage_revision_id == stage_revision_id
        )
        if stage_revision_id is not None:
            await self._assert_session_revision(session_id, stage_revision_id)
        rows = list(
            (
                await self._db.scalars(
                    select(RelatedWorkFinding)
                    .join(
                        Citation,
                        (Citation.session_id == RelatedWorkFinding.session_id)
                        & citation_revision_filter
                        & (Citation.id == RelatedWorkFinding.citation_id),
                    )
                    .where(
                        RelatedWorkFinding.session_id == session_id,
                        revision_filter,
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
            if run.node is ResearchNode.RELATED_WORK:
                await self._delete_working_related_work(run.session_id)
                await self._set_narrative(run.session_id, run.node.value, {})
                await self._db.commit()
            elif run.node is ResearchNode.GAP:
                await self._delete_working_gap(run.session_id)
                await self._set_narrative(run.session_id, run.node.value, {})
                await self._db.commit()

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
                await self._set_narrative(run.session_id, run.node.value, narrative)
                yield self._event(DraftPatchEvent(node=run.node, narrative=narrative))
            elif run.node is ResearchNode.RELATED_WORK:
                async for event in self._generate_related_work(run):
                    if event.get("type") == "citation_upsert":
                        citation_count += 1
                    yield event
            else:
                narrative, warnings = await self._generate_gaps(
                    run.context,
                    session_id=run.session_id,
                )
                for warning in warnings:
                    yield self._warning(run.node, "llm_fallback", warning)
                await self._set_narrative(run.session_id, run.node.value, narrative)
                yield self._event(DraftPatchEvent(node=run.node, narrative=narrative))

            await self._mark_generated_since_prepare(run.session_id, run.node.value)
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
        except Exception as exc:
            await self._db.rollback()
            logger.exception(
                "Research generation failed for node=%s session_id=%s",
                run.node.value,
                run.session_id,
            )
            message = (
                str(exc)
                if isinstance(exc, ResearchGenerationError)
                else (
                    "Research generation failed because malformed Unicode text "
                    "could not be encoded; retry after the source text is normalized"
                    if isinstance(exc, UnicodeEncodeError)
                    else f"Research generation failed: {type(exc).__name__}"
                )
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
        upstream = _dict_payload(run.context.get("upstream"))
        inputs_node = _dict_payload(
            upstream.get(WorkflowNode.RESEARCH_INPUTS.value)
        )
        inputs_payload = _dict_payload(inputs_node.get("narrative"))
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
        output_language = _idea_output_language(idea)
        yield self._event(
            ProgressEvent(
                node=run.node,
                message="Expanding confirmed keywords into named research leads",
                pct=5,
            )
        )
        discovery, discovery_warnings = await self._generate_discovery_expansion(
            inputs,
            idea,
        )
        search_plan, query_warnings = await self._generate_search_plan(
            inputs,
            idea,
            discovery=discovery,
        )
        queries = search_plan.queries
        for warning in [*discovery_warnings, *query_warnings]:
            yield self._warning(run.node, "llm_fallback", warning)
        yield self._event(
            ProgressEvent(
                node=run.node,
                message=(
                    f"Searching {len(queries)} queries derived from confirmed keywords "
                    "and named research leads"
                ),
                pct=10,
            )
        )

        preferred = inputs.preferred_sources
        source_preferences = SourcePreferences(
            peer_reviewed_papers=preferred.peer_reviewed_papers,
            official_proceedings=preferred.official_proceedings,
            author_materials=preferred.author_materials,
            sourced_surveys=preferred.sourced_surveys,
        )
        settings = get_settings()
        citation_target = (
            len(discovery.tools_and_frameworks)
            if discovery.tools_and_frameworks
            else (run.body.max_results or max(len(queries), 1))
        )
        candidate_limit = min(
            max(settings.research_candidate_limit, citation_target * 5), 100
        )
        records, provider_failures = await self._search_provider_queries(
            queries=queries,
            preferences=source_preferences,
            limit=candidate_limit,
        )
        retrieved_candidate_count = len(records)

        if queries and provider_failures and not records:
            raise ResearchGenerationError(provider_failures[-1])
        for failure in provider_failures:
            yield self._warning(run.node, "provider_error", failure)

        _tag_search_facets(records, search_plan)
        unique_records = _deduplicate_records(records)
        ranked_records, discarded_count = _rank_relevant_records(
            unique_records,
            inputs=inputs,
            idea=idea,
            queries=queries,
        )
        evaluation_context = {
            "tool_discovery_keywords": discovery.tool_discovery_keywords,
            "supporting_context_keywords": discovery.supporting_context_keywords,
            "tools_and_frameworks": discovery.tools_and_frameworks,
            "techniques": discovery.techniques,
            "aliases": discovery.aliases,
            "candidate_work_titles": discovery.candidate_work_titles,
            "facets": [
                {
                    "id": facet.id,
                    "objective": facet.objective,
                    "anchors": facet.anchors,
                }
                for facet in search_plan.facets
            ],
        }
        rerank = await self._rerank_records(
            ranked_records,
            idea=idea,
            inputs=inputs,
            queries=queries,
            evaluation_context=evaluation_context,
            objective=(
                "For each discovered tool/framework, choose the single paper about that "
                "tool that is most relevant to the confirmed Idea. Use the conceptual "
                "facets only as relevance criteria, not as additional retrieval targets."
                if discovery.tools_and_frameworks
                else "Find the most useful sources for a source-grounded Related Work comparison."
            ),
        )
        for warning in rerank.warnings:
            yield self._warning(run.node, "rerank_fallback", warning)
        ranked_records = rerank.records

        follow_up_queries: dict[str, list[str]] = {}
        missing_facets = _missing_search_facets(ranked_records, search_plan)
        if missing_facets and not discovery.tools_and_frameworks:
            follow_up_queries = _facet_follow_up_queries(
                missing_facets,
                existing_queries=queries,
            )
            if follow_up_queries:
                _extend_search_plan(search_plan, follow_up_queries)
                queries = search_plan.queries
                follow_up_records, follow_up_failures = (
                    await self._search_provider_queries(
                        queries=[
                            query
                            for facet_queries in follow_up_queries.values()
                            for query in facet_queries
                        ],
                        preferences=source_preferences,
                        limit=candidate_limit,
                    )
                )
                for failure in follow_up_failures:
                    yield self._warning(run.node, "provider_error", failure)
                if follow_up_records:
                    retrieved_candidate_count += len(follow_up_records)
                    _tag_search_facets(follow_up_records, search_plan)
                    unique_records = _deduplicate_records(
                        [*unique_records, *follow_up_records]
                    )
                    ranked_records, follow_up_discarded = _rank_relevant_records(
                        unique_records,
                        inputs=inputs,
                        idea=idea,
                        queries=queries,
                    )
                    discarded_count += follow_up_discarded
                    rerank = await self._rerank_records(
                        ranked_records,
                        idea=idea,
                        inputs=inputs,
                        queries=queries,
                        evaluation_context=evaluation_context,
                        objective=(
                            "Select evidence for every SearchPlan facet, prioritizing direct "
                            "method, evaluation, task/domain, and failure-mitigation coverage."
                        ),
                    )
                    for warning in rerank.warnings:
                        yield self._warning(run.node, "rerank_fallback", warning)
                    ranked_records = rerank.records

        # Citation-graph expansion must start from semantically reranked seeds. Using
        # broad provider/heuristic seeds here amplifies an early query translation error.
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
                retrieved_candidate_count += len(expanded)
                _tag_search_facets(expanded, search_plan)
                unique_records = _deduplicate_records([*unique_records, *expanded])
                ranked_records, graph_discarded = _rank_relevant_records(
                    unique_records,
                    inputs=inputs,
                    idea=idea,
                    queries=queries,
                )
                discarded_count += graph_discarded
                if expanded:
                    rerank = await self._rerank_records(
                        ranked_records,
                        idea=idea,
                        inputs=inputs,
                        queries=queries,
                        evaluation_context=evaluation_context,
                        objective=(
                            "Find the most useful sources for a source-grounded Related "
                            "Work comparison after citation-graph expansion."
                        ),
                    )
                    for warning in rerank.warnings:
                        yield self._warning(run.node, "rerank_fallback", warning)
                    ranked_records = rerank.records
        ranked_records = _facet_balanced_records(ranked_records, search_plan)
        ranked_records = _diversify_records_by_research_work(
            ranked_records,
            tool_names=discovery.tools_and_frameworks,
            tool_relevance_keywords=discovery.tool_discovery_keywords,
        )
        ranked_candidate_count = len(ranked_records)

        prepared_records: list[
            tuple[ScholarlyRecord, Citation, DocumentText, list[str]]
        ] = []
        skipped_inaccessible_count = 0
        require_full_text = get_settings().research_require_downloadable_full_text
        verification_by_record_id: dict[int, VerificationResult] = {}
        if isinstance(self._verifier, BatchCitationVerifier):
            # Resolve a bounded backfill window before downloading. Federated
            # verification can add an OpenAlex OA/PDF URL to a Semantic Scholar
            # discovery record; resolving after download would lose that full text.
            resolution_window = [
                record for record in ranked_records if not _record_has_full_text(record)
            ][: citation_target * 2]
            try:
                early_verifications = await self._verifier.verify_many(
                    citations=resolution_window
                )
            except Exception as exc:  # noqa: BLE001 - retrieval still has discovery data
                yield self._warning(
                    run.node,
                    "verification_error",
                    "Pre-download Citation resolution was deferred: "
                    + (
                        str(exc)
                        if isinstance(exc, ScholarlyProviderError)
                        else type(exc).__name__
                    ),
                )
            else:
                for record, verification in zip(
                    resolution_window,
                    early_verifications,
                    strict=True,
                ):
                    verification_by_record_id[id(record)] = verification
                    if verification.record is not None:
                        _merge_scholarly_records(record, verification.record)
        for record in ranked_records:
            if len(prepared_records) >= citation_target:
                break
            data = self._record_create(record)
            citation, _ = await self._upsert_citation(
                session_id=run.session_id,
                data=data,
            )
            citation.is_active = True
            document, text_warnings = await self._persist_document_text(
                session_id=run.session_id,
                citation=citation,
                record=record,
            )
            if document is None or not _is_usable_research_document(
                document,
                require_downloadable_full_text=require_full_text,
            ):
                citation.is_active = False
                skipped_inaccessible_count += 1
                continue
            record.metadata["relevance_rank"] = len(prepared_records) + 1
            prepared_records.append((record, citation, document, text_warnings))

        unique_records = [record for record, _, _, _ in prepared_records]
        total = max(len(unique_records), 1)
        unresolved_records = [
            record
            for record in unique_records
            if id(record) not in verification_by_record_id
        ]
        if unresolved_records and isinstance(self._verifier, BatchCitationVerifier):
            try:
                later_verifications = await self._verifier.verify_many(
                    citations=unresolved_records
                )
            except Exception as exc:  # noqa: BLE001 - preserve search without a burst
                for record in unresolved_records:
                    verification_by_record_id[id(record)] = VerificationResult(
                        status=VerificationStatus.WARNING
                    )
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
            else:
                verification_by_record_id.update(
                    {
                        id(record): verification
                        for record, verification in zip(
                            unresolved_records,
                            later_verifications,
                            strict=True,
                        )
                    }
                )
        abstract_only_finding_count = 0
        for index, (record, citation, document, text_warnings) in enumerate(
            prepared_records,
            start=1,
        ):
            try:
                verification = verification_by_record_id.get(id(record))
                if verification is None:
                    verification = await self._verifier.verify(citation=record)
                    verification_by_record_id[id(record)] = verification
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

            for warning in text_warnings:
                yield self._warning(run.node, "document_text", warning)

            finding, analysis_warnings = await self._analyze(
                record,
                citation.id,
                research_context={
                    "idea": idea,
                    "research_inputs": inputs.model_dump(mode="json"),
                    "output_language": output_language,
                },
                document=document,
                source_object_key=citation.text_object_key,
            )
            citation.source_metadata = {
                **(citation.source_metadata or {}),
                "research_work_name": record.metadata.get("research_work_name"),
                "research_work_key": record.metadata.get("research_work_key"),
            }
            for warning in analysis_warnings:
                if warning == _ABSTRACT_ONLY_FINDING_WARNING:
                    abstract_only_finding_count += 1
                else:
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

        if skipped_inaccessible_count:
            skipped_reason = (
                "because no downloadable full text could be retrieved after "
                "cross-provider resolution. Metadata, DOI, and abstract pages do "
                "not count while strict full-text mode is enabled."
                if require_full_text
                else "because no analyzable text could be retrieved from a paper, "
                "metadata/DOI page, or provider abstract."
            )
            yield self._warning(
                run.node,
                "full_text_unavailable",
                (
                    f"Skipped {skipped_inaccessible_count} scholarly candidate(s) "
                    f"{skipped_reason}"
                ),
            )

        if abstract_only_finding_count:
            yield self._warning(
                run.node,
                "abstract_only_findings",
                (
                    f"{abstract_only_finding_count} Citation(s) could only be analyzed "
                    "from provider abstracts. They remain useful for Related Work, but "
                    "cannot support a Gap Candidate until full text is retrieved."
                ),
            )

        narrative = {
            "search_queries": queries,
            "query_language": "en",
            "output_language": output_language,
            "query_plan": search_plan.model_dump(mode="json"),
            "discovery_leads": discovery.model_dump(mode="json"),
            "discovery_leads_status": "unverified_search_leads",
            "tool_coverage": _selected_tool_coverage(
                prepared_records,
                discovery.tools_and_frameworks,
            ),
            "query_families": _query_plan(queries),
            "facet_coverage": _search_facet_coverage(unique_records, search_plan),
            "adaptive_search_rounds": 1 if follow_up_queries else 0,
            "missing_facets": [
                facet.id
                for facet in _missing_search_facets(unique_records, search_plan)
            ],
            "citation_count": len(unique_records),
            "citation_target": citation_target,
            "candidate_count": retrieved_candidate_count,
            "ranked_candidate_count": ranked_candidate_count,
            "discarded_candidate_count": discarded_count,
            "reranked_candidate_count": rerank.candidate_count,
            "reranking_applied": rerank.applied,
            "analyzed_result_count": len(unique_records),
            "abstract_only_finding_count": abstract_only_finding_count,
            "skipped_inaccessible_count": skipped_inaccessible_count,
            "selection_rule": (
                "one_best_citation_per_discovered_tool_llm_listwise"
                if discovery.tools_and_frameworks and rerank.applied
                else (
                    "one_best_citation_per_discovered_tool_heuristic"
                    if discovery.tools_and_frameworks
                    else (
                        "quality_diversity_portfolio_llm_listwise"
                        if rerank.applied
                        else "quality_diversity_portfolio_heuristic"
                    )
                )
            ),
            "graph_expansion_enabled": isinstance(self._source, CitationGraphPort),
            "preferred_sources": preferred.model_dump(mode="json"),
        }
        await self._set_narrative(run.session_id, run.node.value, narrative)
        yield self._event(DraftPatchEvent(node=run.node, narrative=narrative))

    async def _generate_research_inputs(
        self,
        context: dict[str, Any],
    ) -> tuple[dict[str, Any], list[str]]:
        try:
            idea = _idea_context(context)
            raw = await self._llm.complete(
                system=(
                    "research-inputs: return only JSON in exactly this shape: "
                    '{"keywords":["specific scholarly noun phrase"],'
                    '"preferred_sources":{"peer_reviewed_papers":true,'
                    '"official_proceedings":true,"author_materials":true,'
                    '"sourced_surveys":true}}. Write every keyword in English regardless '
                    "of the input idea's language. Translate Vietnamese and other non-English "
                    "concepts into canonical English academic terminology while preserving "
                    "acronyms and technical names. Never emit a non-English keyword. "
                    "Treat each supplied Card role differently. "
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
                working_draft = _dict_payload(context.get("working_draft"))
                current = ResearchInputs.model_validate(
                    _dict_payload(working_draft.get("narrative"))
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
                # search_many coalesces the logical query set into one provider
                # operation, so report its failure once rather than once per query.
                return [], [failure]
            for record in records:
                record.metadata.setdefault(
                    "discovery_queries",
                    _matching_record_queries(record, queries),
                )
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
        discovery, discovery_warnings = await self._generate_discovery_expansion(
            inputs,
            idea,
        )
        plan, plan_warnings = await self._generate_search_plan(
            inputs,
            idea,
            discovery=discovery,
        )
        return plan.queries, [*discovery_warnings, *plan_warnings]

    async def _generate_discovery_expansion(
        self,
        inputs: ResearchInputs,
        idea: dict[str, Any],
    ) -> tuple[_DiscoveryExpansion, list[str]]:
        """Expand confirmed concepts into unverified named search leads."""
        try:
            raw = await self._llm.complete(
                system=(
                    "research-discovery: return only one JSON object with exactly "
                    "tool_discovery_keywords, supporting_context_keywords, "
                    "tools_and_frameworks, techniques, candidate_work_titles, and aliases; "
                    "every value is an array of strings. First partition every confirmed "
                    "keyword into exactly one keyword group. tool_discovery_keywords must "
                    "contain only exact confirmed keyword strings that directly express the "
                    "central intervention, mechanism, or technical approach in the Research "
                    "Question. supporting_context_keywords must contain all remaining keywords, "
                    "including task/domain, dataset, outcome, metric, failure mode, evaluation "
                    "criterion, or secondary context. Starting from the "
                    "confirmed Research Input keywords and Idea, propose concrete named "
                    "tools/frameworks, canonical technique names, likely exact scholarly "
                    "work titles, and precise academic aliases that can improve retrieval. "
                    "Use English search terminology and preserve official capitalization. "
                    "Generate tools/frameworks only from tool_discovery_keywords. Never use a "
                    "supporting_context_keyword to propose an additional tool. Use supporting "
                    "keywords only to judge which paper about each tool best matches the Idea. "
                    "Prefer established names directly connected to the central mechanism; "
                    "omit uncertain or merely generic items. Candidate titles are search "
                    "leads only: do not invent authors, years, venues, DOI, URL, findings, "
                    "or citation metadata, and do not claim that any lead exists. "
                    "Return every directly relevant, established tool/framework you can "
                    "identify; do not target or pad to a predetermined count."
                ),
                prompt=json.dumps(
                    {
                        "idea": idea,
                        "confirmed_keywords": inputs.keywords,
                        "concept_anchors": _idea_search_concepts(idea),
                    },
                    ensure_ascii=False,
                ),
            )
            return _discovery_expansion_from_payload(
                _json_value(raw, dict),
                inputs=inputs,
                idea=idea,
            ), []
        except Exception as exc:  # noqa: BLE001 - safe deterministic fallback
            return _fallback_discovery_expansion(inputs, idea), [
                (
                    "Named research lead expansion used a conservative fallback: "
                    f"{_llm_failure_summary(exc)}"
                )
            ]

    async def _generate_search_plan(
        self,
        inputs: ResearchInputs,
        idea: dict[str, Any],
        *,
        discovery: _DiscoveryExpansion | None = None,
    ) -> tuple[_SearchPlan, list[str]]:
        """Create evaluation facets and derive retrieval from discovered tools."""
        discovery = discovery or _DiscoveryExpansion()
        # This limit only bounds the model-authored evaluation plan. Once named tools
        # exist, provider query count is derived exactly from that tool list.
        planning_limit = max(
            len(discovery.tools_and_frameworks),
            len(_clean_keywords(inputs.keywords)) * 4,
            1,
        )
        try:
            raw = await self._llm.complete(
                system=(
                    "research-query: return only JSON with a facets array. Each facet must "
                    "contain id, objective, anchors, queries, and min_results. Produce three "
                    "or four mutually distinct facets that collectively cover every confirmed "
                    "Research Input keyword. Group synonyms and overlapping problem terms into "
                    "one facet; keep implementation tools, evaluation, task/domain, and "
                    "failure/mitigation dimensions separate when present. When the Idea concerns "
                    "a method that has named implementations, the first facet must use id "
                    "implementation_tools and include concrete, established tool/framework/technique "
                    "names as anchors (for prompt optimization consider DSPy, TextGrad, OPRO, and "
                    "ProTeGi). Its queries must each name at least one concrete implementation; do "
                    "not emit a tools/frameworks-only generic query. Set min_results to 2. Give every facet "
                    "exactly two independent scholarly queries: one direct method or relationship "
                    "query and one adjacent-method, evaluation, limitation, survey, or benchmark "
                    "query. Do not repeat the same broad query across facets. "
                    "Use the supplied discovery_leads as unverified evaluation context. When "
                    "named tools/frameworks exist, the provider will receive exactly one exact-name "
                    "query per tool; candidate titles, techniques, aliases, and conceptual facets "
                    "must only help evaluate which returned paper is most relevant to the Idea. "
                    "Never treat a discovery lead as a verified Citation. "
                    "Write every query in English regardless of the input language. Translate "
                    "Vietnamese and other non-English concepts into canonical English academic "
                    "terminology while preserving acronyms and technical names. Queries are "
                    "retrieval keys, not user-facing prose; never emit a non-English query. "
                    "Problem Cards provide core concepts. "
                    "Split each Research Question into the smallest useful relationship queries "
                    "instead of forcing all variables into one query. Treat Constraint Cards as "
                    "optional filters and include only externally searchable constraints when a "
                    "query genuinely needs narrowing; never include internal delivery limits. "
                    "Turn Open Question Cards into separate exploratory queries for evidence "
                    "gaps, conflicting findings, mechanisms, limitations, or measurement. Use "
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
                        "discovery_leads": (
                            discovery.model_dump(mode="json") if discovery else {}
                        ),
                    },
                    ensure_ascii=False,
                ),
            )
            try:
                payload = _json_value(raw, dict)
                plan = _search_plan_from_payload(
                    payload,
                    inputs=inputs,
                    idea=idea,
                    limit=planning_limit,
                    tool_discovery_keywords=discovery.tool_discovery_keywords,
                )
            except (
                ValidationError,
                json.JSONDecodeError,
                TypeError,
                ValueError,
            ) as exc:
                repaired_raw = await self._llm.complete(
                    system=(
                        "research-query-repair: repair the previous response into exactly "
                        "one valid JSON object. Return either {\"facets\":[{\"id\":\"...\","
                        "\"objective\":\"...\",\"anchors\":[\"...\"],\"queries\":[\"...\"],"
                        "\"min_results\":2}]} or the legacy {\"queries\":[\"...\"]} "
                        "shape. Preserve English scholarly terminology, confirmed keyword "
                        "coverage, named tools, and candidate work titles from the request. "
                        "Every keyword named in validation_error must appear directly in at "
                        "least one anchor or query; keep conceptual anchors at six words or "
                        "fewer. Candidate work titles are evaluation context and do not "
                        "substitute for a missing short concept anchor. "
                        "Do not include markdown, reasoning, comments, or text outside JSON."
                    ),
                    prompt=json.dumps(
                        {
                            "validation_error": _structured_failure_detail(exc),
                            "previous_response": raw[-12_000:],
                            "confirmed_keywords": inputs.keywords,
                            "idea": idea,
                            "discovery_leads": (
                                discovery.model_dump(mode="json")
                                if discovery
                                else {}
                            ),
                        },
                        ensure_ascii=False,
                    ),
                )
                payload = _json_value(repaired_raw, dict)
                plan = _search_plan_from_payload(
                    payload,
                    inputs=inputs,
                    idea=idea,
                    limit=planning_limit,
                    tool_discovery_keywords=discovery.tool_discovery_keywords,
                )
            return _enrich_search_plan_with_discovery(
                plan,
                discovery,
            ), []
        except Exception as exc:  # noqa: BLE001 - deterministic fallback
            plan = _fallback_search_plan(
                inputs,
                idea,
                limit=planning_limit,
                tool_discovery_keywords=discovery.tool_discovery_keywords,
            )
            return _enrich_search_plan_with_discovery(
                plan,
                discovery,
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
        evaluation_context: dict[str, Any] | None = None,
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
                records=_portfolio_order_records(records, queries=queries),
                applied=False,
                candidate_count=0,
                warnings=[],
            )

        keyed = [(_record_result_key(record), record) for record in candidates]
        expected_keys = [key for key, _ in keyed]
        if len(set(expected_keys)) != len(expected_keys):
            return _RerankOutcome(
                records=_portfolio_order_records(records, queries=queries),
                applied=False,
                candidate_count=len(candidates),
                warnings=[
                    "Semantic reranking was skipped because candidate identifiers were not unique."
                ],
            )

        rerank_system = (
            "research-rerank: return only JSON in exactly this shape: "
            '{"rankings":[{"result_key":"...","relevance_score":0.0}]}. '
            "Rerank every supplied scholarly candidate for the stated objective. "
            "Use the confirmed Problem, Research Questions, Research Inputs, and supplied "
            "evaluation_context. Treat techniques, aliases, candidate titles, and facets as "
            "ranking criteria only; they must not imply that another search was performed. "
            "Prioritize direct coverage of the research relationship, "
            "method, outcome, evaluation, and limitations. Prefer evidence-rich "
            "candidates over broad keyword matches. When candidates are equally relevant, "
            "strongly prefer papers that explicitly present, evaluate, compare, or apply a "
            "named implementation tool, framework, or technique over concept-only discussion. "
            "For a tool-specific objective, compare papers belonging to the same named tool "
            "against the confirmed Idea and its evaluation facets; do not let a globally popular "
            "tool displace the best available paper for another discovered tool. "
            "Within papers for the same tool, treat evaluation_context.tool_discovery_keywords "
            "as direct relevance criteria. supporting_context_keywords may add context, but "
            "must not redefine which tools belong to the candidate set. "
            "A name appearing only in a discovery query is not enough; use the supplied title, "
            "abstract, tool_mentions, and search_facets. Use explicit publication type, "
            "peer-review, and full-text availability only as tie-breakers; weak topical "
            "coverage must never be rescued by venue or publication metadata. Use only "
            "supplied metadata and never infer venue prestige or missing facts. Return "
            "every candidate result_key exactly once, no "
            "unknown keys, ordered from most to least relevant. relevance_score must be "
            "between 0 and 1. Do not use markdown, reasoning, or explanations."
        )
        rerank_request = {
            "objective": objective,
            "idea": idea,
            "research_inputs": inputs.model_dump(mode="json"),
            "search_queries": queries,
            "evaluation_context": evaluation_context or {},
            "candidates": [
                {
                    "result_key": key,
                    "title": record.title,
                    "abstract": str(record.abstract or "")[:1_200],
                    "year": record.year,
                    "venue": record.venue,
                    "heuristic_score": record.metadata.get("retrieval_score"),
                    "publication_types": sorted(_publication_kinds(record)),
                    "is_peer_reviewed": _explicit_peer_review_status(record),
                    "has_full_text": _record_has_full_text(record),
                    "discovery_queries": record.metadata.get("discovery_queries", []),
                    "discovery_types": record.metadata.get("discovery_types", []),
                    "search_facets": record.metadata.get("search_facets", []),
                    "tool_mentions": record.metadata.get(
                        "implementation_tool_mentions", []
                    ),
                    "queried_tool_names": record.metadata.get(
                        "queried_tool_names", []
                    ),
                }
                for key, record in keyed
            ],
        }
        try:
            raw = await self._llm.complete(
                system=rerank_system,
                prompt=json.dumps(
                    rerank_request,
                    default=str,
                    ensure_ascii=False,
                ),
            )
            try:
                response = _validated_rerank_response(raw, expected_keys)
            except (
                ValidationError,
                json.JSONDecodeError,
                TypeError,
                ValueError,
            ) as exc:
                # A reasoning model can ignore JSON-only instructions, truncate the
                # object, or omit a candidate. Give it one bounded correction attempt
                # before falling back to the deterministic retrieval order.
                repaired_raw = await self._llm.complete(
                    system=(
                        "research-rerank-repair: correct the previous reranking response. "
                        "Return only one valid JSON object with a rankings array. Return "
                        "every required_result_key exactly once, no unknown or duplicate "
                        "keys, and a relevance_score from 0 to 1 for every item. Do not use "
                        "markdown, reasoning, or explanations."
                    ),
                    prompt=json.dumps(
                        {
                            "required_result_keys": expected_keys,
                            "validation_error": str(exc)[:2_000],
                            "previous_response": raw[-12_000:],
                            "original_request": rerank_request,
                        },
                        default=str,
                        ensure_ascii=False,
                    ),
                )
                response = _validated_rerank_response(repaired_raw, expected_keys)

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
                records=_portfolio_order_records(
                    [*reranked, *tail],
                    queries=queries,
                ),
                applied=True,
                candidate_count=len(candidates),
                warnings=[],
            )
        except Exception as exc:  # noqa: BLE001 - retrieval must survive reranker failure
            return _RerankOutcome(
                records=_portfolio_order_records(records, queries=queries),
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
        configured_output_language = research_context.get("output_language")
        output_language: Literal["en", "vi"] = (
            configured_output_language
            if configured_output_language in {"en", "vi"}
            else _idea_output_language(idea)
        )
        analysis_prompt = json.dumps(
            {**research_context, "citation": citation_payload},
            default=str,
            ensure_ascii=False,
        )
        analysis_contract = (
            "research-analysis: return only one flat JSON object with exactly "
            "these keys: study_name (non-empty string naming the specific research "
            "work, tool, framework, or technique—not the article title; use its "
            "canonical short name such as DSPy, TextGrad, ProTeGi, or SAPO and no "
            "more than six words), "
            "what_was_done (non-empty string), "
            "method_or_feedback (non-empty string describing the method, "
            "feedback, or evaluation type), limitation (non-empty string), "
            "relevance (non-empty string), supporting_passage (non-empty "
            "verbatim span from the supplied retrieved_text), evidence "
            "(an object with what_was_done, method_or_feedback, and limitation; "
            "each value contains passage and location), and confidence "
            "(number from 0 to 1). Do not rename or nest the keys. "
            "Use only retrieved_text for source assertions. For every evidence "
            "item, passage must be a concise verbatim sentence or paragraph "
            "that separately supports that assertion. Never use a document "
            "type, section heading, navigation text, or the whole HTML/PDF as "
            "evidence. The limitation must contain exactly one atomic, "
            "source-stated limitation, and evidence.limitation.passage must "
            "entail every asserted clause. Do not combine a supported limitation "
            "with another cost, mechanism, scope, metric, or application unless "
            "the same passage explicitly supports it. Never infer that a method "
            "lacks a feature merely because the source does not mention that "
            "feature. If the source states several limitations, select the single "
            "most relevant one. Assess relevance "
            "and limitation against the supplied Problem, Research "
            "Questions, and Research Inputs. If the source does not state a "
            "method or feedback type, say so in the required output language. "
            "When citation.metadata.implementation_tool_mentions is non-empty and "
            "retrieved_text supports the name, what_was_done and method_or_feedback "
            "must explicitly name the tool/framework/technique and explain its role; "
            "do not replace it with a generic phrase such as method or framework."
        )
        try:
            raw = await self._llm.complete(
                system=_idea_language_instruction(idea) + analysis_contract,
                prompt=analysis_prompt,
            )
            payload = _normalize_finding_payload(
                _json_value(raw, dict),
                record,
                source_text=source_text,
                source_location=source_location,
                output_language=output_language,
            )
            mismatched_fields = _finding_language_mismatches(
                payload,
                output_language=output_language,
            )
            if mismatched_fields:
                raw = await self._llm.complete(
                    system=(
                        _idea_language_instruction(idea)
                        + "research-analysis-language-repair: The previous response used "
                        "the wrong language in these user-facing fields: "
                        f"{', '.join(mismatched_fields)}. Rewrite all user-facing prose "
                        "in the required output language. Keep the paper title, technical "
                        "terms, acronyms, JSON keys, and every verbatim evidence passage "
                        "unchanged. "
                        + analysis_contract
                    ),
                    prompt=json.dumps(
                        {
                            **research_context,
                            "citation": citation_payload,
                            "previous_finding": payload,
                        },
                        default=str,
                        ensure_ascii=False,
                    ),
                )
                payload = _normalize_finding_payload(
                    _json_value(raw, dict),
                    record,
                    source_text=source_text,
                    source_location=source_location,
                    output_language=output_language,
                )
                remaining_mismatches = _finding_language_mismatches(
                    payload,
                    output_language=output_language,
                )
                if remaining_mismatches:
                    raise ValueError(
                        "The model did not follow the required output language"
                    )
            proposed_study_name = str(payload.pop("study_name", "")).strip()
            record.metadata["research_work_name"] = _normalized_study_name(
                proposed_study_name,
                record,
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
            if (
                document is not None
                and document.source_kind == "abstract"
                and grounding_status is GroundingStatus.GROUNDED
                and get_settings().research_require_downloadable_full_text
            ):
                grounding_status = GroundingStatus.WARNING
                warnings.append(
                    _ABSTRACT_ONLY_FINDING_WARNING
                )
            if (
                grounding_status is not GroundingStatus.GROUNDED
                and (document is None or document.source_kind != "abstract")
            ):
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
            record.metadata["research_work_name"] = (
                _record_research_work_name(record) or "Unnamed approach"
            )
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
            fallback = _finding_fallback_text(output_language)
            return (
                RelatedWorkFindingCreate(
                    citation_id=citation_id,
                    what_was_done=fallback["what_was_done"].format(
                        title=record.title
                    ),
                    method_or_feedback=fallback["method_or_feedback"],
                    limitation=fallback["limitation"],
                    relevance=fallback["relevance"],
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
        *,
        session_id: UUID | None = None,
    ) -> tuple[dict[str, Any], list[str]]:
        upstream = _dict_payload(context.get("upstream"))
        related_node = _dict_payload(upstream.get(WorkflowNode.RELATED_WORK.value))
        related = _dict_payload(related_node.get("projected"))
        related_narrative = _dict_payload(related_node.get("narrative"))
        research_inputs_node = _dict_payload(
            upstream.get(WorkflowNode.RESEARCH_INPUTS.value)
        )
        raw_research_inputs = _dict_payload(research_inputs_node.get("narrative"))
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
        initially_eligible_keys = list(valid_keys)
        eligible_citations = [
            item for item in citations if item.get("citation_key") in valid_keys
        ]
        eligible_findings = [
            item for item in related_work if item.get("citation_key") in valid_keys
        ]
        idea = _idea_context(context)
        warnings: list[str] = []
        answers: _GapQuestionAnswers | None = None
        source_claim_candidates, claim_preparation_warnings = _fallback_gap_claims(
            eligible_findings,
            valid_keys,
        )
        warnings.extend(claim_preparation_warnings)
        source_claims, claim_support_warnings = (
            await self._validate_gap_claim_support(
                idea=idea,
                claim_candidates=source_claim_candidates,
            )
        )
        warnings.extend(claim_support_warnings)
        supported_key_set = {
            key for claim in source_claims for key in claim.supporting_citation_keys
        }
        if supported_key_set != set(valid_keys):
            valid_keys = [key for key in valid_keys if key in supported_key_set]
            eligible_citations = [
                item
                for item in eligible_citations
                if item.get("citation_key") in supported_key_set
            ]
            eligible_findings = [
                item
                for item in eligible_findings
                if item.get("citation_key") in supported_key_set
            ]
            evidence_check.eligible_citation_keys = valid_keys
            evidence_check.ready = bool(valid_keys)
            evidence_check.messages.append(
                "Some grounded Related Work limitations were excluded because their "
                "passages were unsupported or could not be semantically validated."
            )
        eligible_findings = _related_work_with_validated_limitations(
            eligible_findings,
            source_claims,
        )
        gap_claims = source_claims
        provisional_statement = _fallback_gap_statement(eligible_findings)
        if valid_keys and source_claims:
            try:
                analysis_raw = await self._llm.complete(
                    system=(
                        _idea_language_instruction(idea)
                        + "research-gap-analysis: perform private source-grounded analysis and "
                        "return only one JSON object with exactly these keys: prior_work, "
                        "limitation, importance, testability (non-empty strings), and "
                        "covered_citation_keys (a string array), and claims (an array of 1 to 5 "
                        "independently falsifiable claim objects copied from claim_candidates). "
                        "Each claim must contain "
                        "claim_id, kind, statement, and supporting_citation_keys. kind must be "
                        "one of existing_capability, unresolved_limitation, technical_mechanism, "
                        "human_evaluation, or domain_scope. Do not combine a technical mechanism, "
                        "user-interface effect, and high-risk domain into one claim. "
                        "Do not invent, merge, expand, quantify, or paraphrase a claim. Select "
                        "only complete objects from claim_candidates so every claim retains an "
                        "eligible Citation and its exact limitation passage. Use claims for "
                        "independently testable Gap-bearing assertions; keep "
                        "descriptive prior-work context in prior_work rather than inventing a "
                        "novelty claim from it. Read and "
                        "compare EVERY item "
                        "in citations and related_work; "
                        "each supplied citation must materially "
                        "inform at least one answer, and covered_citation_keys must contain "
                        "every required_citation_key. Answer: what prior research accomplished, "
                        "what remains limited across the body of work, why the limitation "
                        "matters, and what experiment can test it. Ground the analysis in the "
                        "supplied findings and evidence. Do not claim proven novelty. Do not "
                        "use markdown or add explanatory "
                        "text outside JSON."
                    ),
                    prompt=json.dumps(
                        {
                            "idea": idea,
                            "research_inputs": research_inputs,
                            "citations": eligible_citations,
                            "related_work": eligible_findings,
                            "claim_candidates": [
                                item.model_dump(mode="json") for item in source_claims
                            ],
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
                gap_claims = _gap_claims_from_answers(answers, source_claims)
                provisional_statement = _gap_statement_from_answers(answers)
            except Exception as exc:  # noqa: BLE001 - conservative source-linked fallback
                answers = None
                warnings.append(
                    "Gap analysis used a conservative source-linked fallback: "
                    f"{_llm_failure_summary(exc)}"
                )
        else:
            if initially_eligible_keys:
                warnings.append(
                    "Gap Candidate is not evidence-ready because no atomic limitation "
                    "remained after semantic passage validation."
                )
            else:
                warnings.append(
                    "Gap Candidate is not evidence-ready because no Citation is both "
                    "verified and linked to a grounded Related Work limitation passage."
                )

        source_preferences = SourcePreferences(
            peer_reviewed_papers=inputs.preferred_sources.peer_reviewed_papers,
            official_proceedings=inputs.preferred_sources.official_proceedings,
            author_materials=inputs.preferred_sources.author_materials,
            sourced_surveys=inputs.preferred_sources.sourced_surveys,
        )
        related_queries = _string_list(related_narrative.get("search_queries"))
        if gap_claims and valid_keys:
            counter_search = await self._search_counter_evidence(
                idea=idea,
                inputs=inputs,
                provisional_statement=provisional_statement,
                gap_claims=gap_claims,
                related_work_citations=eligible_citations,
                related_work_queries=related_queries,
                preferences=source_preferences,
            )
            warnings.extend(counter_search.warnings)
            (
                selected_counter_records,
                counter_materials,
                assessment,
                audit_warnings,
            ) = await self._audit_counter_evidence_with_backfill(
                idea=idea,
                provisional_statement=provisional_statement,
                gap_claims=gap_claims,
                counter_search=counter_search,
                session_id=session_id,
            )
            warnings.extend(audit_warnings)
        else:
            counter_search = _CounterEvidenceSearch(
                queries=[],
                records=[],
                selected_records=[],
                candidate_records=[],
                candidate_count=0,
                complete=False,
                warnings=[],
            )
            selected_counter_records = []
            counter_materials = []
            assessment = _CounterEvidenceAssessment(
                outcome=CounterEvidenceOutcome.INCONCLUSIVE,
                statement=provisional_statement,
                assessment=(
                    "Counter-evidence search was skipped because no semantically "
                    "supported atomic Gap claim remained."
                ),
            )
            warnings.append(
                "Skipped counter-evidence search because no semantically supported "
                "atomic Gap claim remained."
            )
        counter_search.records = selected_counter_records
        counter_search.selected_records = selected_counter_records
        claim_assessments = _gap_claim_assessments(
            gap_claims,
            assessment.claim_assessments,
        )
        statement = assessment.statement
        if answers is not None and assessment.outcome in {
            CounterEvidenceOutcome.INCONCLUSIVE,
            CounterEvidenceOutcome.NO_DIRECT_COUNTER_EVIDENCE,
            CounterEvidenceOutcome.GAP_NARROWED,
        }:
            try:
                synthesis_raw = await self._llm.complete(
                    system=(
                        _idea_language_instruction(idea)
                        + "research-gap-synthesis: return only JSON with one non-empty "
                        "string field named statement. Produce one concise, coherent Gap "
                        "Candidate with exactly 2 sentences. Sentence 1 must summarize what "
                        "existing approaches can already do, grounded in analysis.prior_work. "
                        "Sentence 2 must begin with the language-equivalent of 'It remains "
                        "unclear' (use 'Chưa rõ' in Vietnamese) and state one testable unknown: "
                        "whether the proposed mechanism or comparison can address the validated "
                        "limitation and improve the intended outcome under the stated evaluation "
                        "constraint. Use the idea and analysis.testability to make that relation "
                        "specific, but do not present the proposed contribution as established. "
                        "For no_direct_counter_evidence and gap_narrowed claims, synthesize only "
                        "supported claim assessments and use each narrowed claim's revised "
                        "statement. For inconclusive claims, retain their source-grounded "
                        "limitation as a possibility expressed by 'Chưa rõ'/'It remains unclear'; "
                        "do not put counter-evidence status, audit disclaimers, or novelty "
                        "warnings in the Gap statement because the UI displays them separately. "
                        "Do not reintroduce unsupported claims, expose field labels or source "
                        "lists, append a separate experiment plan, or claim proven novelty."
                    ),
                    prompt=json.dumps(
                        {
                            "idea": idea,
                            "analysis": answers.model_dump(mode="json"),
                            "claim_assessments": [
                                item.model_dump(mode="json")
                                for item in claim_assessments
                            ],
                            "counter_evidence_outcome": assessment.outcome.value,
                            "counter_evidence_assessment": assessment.assessment,
                        },
                        default=str,
                        ensure_ascii=False,
                    ),
                )
                synthesized_statement = _GapSynthesis.model_validate(
                    _json_value(synthesis_raw, dict)
                ).statement
                statement = _validate_gap_statement_style(synthesized_statement)
            except Exception as exc:  # noqa: BLE001 - preserve grounded analysis
                statement = _two_sentence_gap_fallback(
                    idea,
                    answers,
                    gap_claims,
                    eligible_findings,
                )
                warnings.append(
                    "Gap synthesis used the validated source-grounded analysis "
                    "directly because the final model call failed: "
                    f"{_llm_failure_summary(exc)}"
                )
        elif assessment.outcome is CounterEvidenceOutcome.INCONCLUSIVE:
            statement = _two_sentence_gap_fallback(
                idea,
                answers,
                gap_claims,
                eligible_findings,
            )
        counter_results = _counter_evidence_results(
            selected_counter_records,
            assessment.findings,
            counter_materials,
        )

        audit_complete = bool(related_queries) and counter_search.complete
        audit = GapSearchAudit(
            assessed_statement=statement,
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
            counter_evidence_assessment=assessment.assessment,
            counter_evidence_results=counter_results,
            claim_assessments=claim_assessments,
            completed_at=datetime.now(UTC),
            complete=audit_complete,
        )
        candidate = GapCardBody(
            statement=statement,
            supporting_citation_keys=valid_keys,
            status=GapStatus.INSUFFICIENT_EVIDENCE,
            search_audit=audit,
            evidence_check=evidence_check,
        )
        if candidate.is_evidence_ready():
            candidate.status = GapStatus.CANDIDATE
        narrative = {"candidate": candidate.model_dump(mode="json")}
        return narrative, warnings

    async def _validate_gap_claim_support(
        self,
        *,
        idea: dict[str, Any],
        claim_candidates: list[_GapClaim],
    ) -> tuple[list[_GapClaim], list[str]]:
        """Keep only Related Work limitations entailed by their cited passages."""

        if not claim_candidates:
            return [], []
        required_ids = [item.claim_id for item in claim_candidates]
        request = {
            "required_claim_ids": required_ids,
            "claim_candidates": [
                item.model_dump(mode="json") for item in claim_candidates
            ],
        }
        instruction = (
            _idea_language_instruction(idea)
            + "research-gap-claim-support-check: independently verify whether "
            "each atomic claim statement is semantically supported by its supplied "
            "Related Work evidence passage. Return only JSON with assessments, "
            "containing exactly one object per required claim_id with claim_id and "
            "support_status. support_status must be supported, unsupported, or "
            "uncertain. Cross-language paraphrases may be supported. Exact passage "
            "presence alone is not sufficient. Mark unsupported if the statement "
            "adds a number, configuration constant, dataset property, causal claim, "
            "mechanism, comparison, or scope not present in the passage. Mark "
            "uncertain when the passage is too weak or ambiguous."
        )
        validation_failures: list[str] = []
        try:
            raw = await self._llm.complete(
                system=instruction,
                prompt=json.dumps(request, default=str, ensure_ascii=False),
            )
            parsed = _validated_gap_claim_support_response(raw, required_ids)
        except Exception as first_exc:  # noqa: BLE001 - bounded repair follows
            validation_failures.append(_structured_failure_detail(first_exc))
            try:
                repaired_raw = await self._llm.complete(
                    system=(
                        _idea_language_instruction(idea)
                        + "research-gap-claim-support-repair: repair the previous response. "
                        "Return only JSON with assessments and exactly one object per "
                        "required claim_id. Each object must contain claim_id and "
                        "support_status using supported, unsupported, or uncertain."
                    ),
                    prompt=json.dumps(
                        {
                            **request,
                            "validation_error": validation_failures[-1],
                            "previous_response": str(locals().get("raw", ""))[-8_000:],
                        },
                        default=str,
                        ensure_ascii=False,
                    ),
                )
                parsed = _validated_gap_claim_support_response(
                    repaired_raw,
                    required_ids,
                )
            except Exception as repair_exc:  # noqa: BLE001 - per-item recovery follows
                validation_failures.append(_structured_failure_detail(repair_exc))

                async def assess_one(claim: _GapClaim) -> object:
                    return await self._llm.complete(
                        system=(
                            _idea_language_instruction(idea)
                            + "research-gap-claim-support-item-check: assess exactly one "
                            "claim and return JSON with claim_id and support_status. "
                            "support_status must be supported, unsupported, or uncertain."
                        ),
                        prompt=json.dumps(
                            {
                                "required_claim_ids": [claim.claim_id],
                                "claim_candidate": claim.model_dump(mode="json"),
                            },
                            default=str,
                            ensure_ascii=False,
                        ),
                    )

                responses = await asyncio.gather(
                    *(assess_one(item) for item in claim_candidates),
                    return_exceptions=True,
                )
                recovered: list[_GapClaimSupportItem] = []
                failed_ids: list[str] = []
                for claim, response in zip(
                    claim_candidates,
                    responses,
                    strict=True,
                ):
                    try:
                        if isinstance(response, BaseException):
                            raise response
                        item_response = _validated_gap_claim_support_response(
                            str(response),
                            [claim.claim_id],
                        )
                        recovered.extend(item_response.assessments)
                    except Exception:  # noqa: BLE001 - one item remains uncertain
                        failed_ids.append(claim.claim_id)
                        recovered.append(
                            _GapClaimSupportItem(
                                claim_id=claim.claim_id,
                                support_status=CounterEvidenceSupport.UNCERTAIN,
                            )
                        )
                parsed = _GapClaimSupportResponse(assessments=recovered)
                validation_failures.append(
                    "per-claim recovery left "
                    f"{len(failed_ids)}/{len(required_ids)} claim(s) uncertain"
                )

        bulk_statuses = {
            item.claim_id: item.support_status for item in parsed.assessments
        }
        direct_confirmation_candidates = [
            item
            for item in claim_candidates
            if bulk_statuses[item.claim_id] is CounterEvidenceSupport.SUPPORTED
            and _claim_statement_precheck(item.statement)
        ]

        narrowing_candidates = [
            item
            for item in claim_candidates
            if bulk_statuses[item.claim_id] is not CounterEvidenceSupport.SUPPORTED
            or not _claim_statement_precheck(item.statement)
        ]

        async def narrow_one(claim: _GapClaim) -> object:
            return await self._llm.complete(
                system=(
                    _idea_language_instruction(idea)
                    + "research-gap-claim-narrowing: recover at most one atomic, "
                    "source-stated limitation from exactly one rejected or uncertain "
                    "Related Work claim and its supplied evidence passage. Return only "
                    "JSON with claim_id, can_narrow, statement, and evidence_span. Keep "
                    "claim_id unchanged. Set can_narrow=true only when the passage "
                    "explicitly states a limitation, challenge, boundary, cost, bias, or "
                    "evaluation omission. When true, statement must express only that one "
                    "limitation in the idea's primary language, and evidence_span must be "
                    "one exact contiguous verbatim span from the supplied passage that "
                    "entails every clause in statement. Remove unsupported mechanisms, "
                    "comparisons, metrics, domains, applications, and claims based only on "
                    "source non-mention. Do not preserve the original wording when it is "
                    "broader than the passage. Set can_narrow=false with empty statement "
                    "and evidence_span when no source-stated limitation can be recovered."
                ),
                prompt=json.dumps(
                    {"claim_candidate": claim.model_dump(mode="json")},
                    default=str,
                    ensure_ascii=False,
                ),
            )

        narrowing_responses = await asyncio.gather(
            *(narrow_one(item) for item in narrowing_candidates),
            return_exceptions=True,
        )
        narrowed_by_id: dict[str, _GapClaim] = {}
        narrowing_failures: list[str] = []
        for claim, response in zip(
            narrowing_candidates,
            narrowing_responses,
            strict=True,
        ):
            try:
                if isinstance(response, BaseException):
                    raise response
                narrowed = _GapClaimNarrowing.model_validate(
                    _json_value(str(response), dict)
                )
                if narrowed.claim_id != claim.claim_id:
                    raise ValueError("Gap claim narrowing changed claim_id")
                if not narrowed.can_narrow:
                    continue
                if not narrowed.statement.strip() or not _claim_statement_precheck(
                    narrowed.statement
                ):
                    raise ValueError("Narrowed Gap claim is empty or non-atomic")
                normalized_span = " ".join(
                    narrowed.evidence_span.casefold().split()
                )
                if not normalized_span or not any(
                    normalized_span
                    in " ".join(evidence.passage.casefold().split())
                    for evidence in claim.supporting_evidence
                ):
                    raise ValueError(
                        "Narrowed Gap claim evidence_span is not verbatim source evidence"
                    )
                narrowed_by_id[claim.claim_id] = claim.model_copy(
                    update={"statement": narrowed.statement.strip()}
                )
            except Exception as exc:  # noqa: BLE001 - fail closed per claim
                narrowing_failures.append(
                    f"{claim.claim_id}: {_structured_failure_detail(exc)}"
                )

        confirmation_candidates = [
            *direct_confirmation_candidates,
            *[
                narrowed_by_id[item.claim_id]
                for item in narrowing_candidates
                if item.claim_id in narrowed_by_id
            ],
        ]
        effective_by_id = {
            item.claim_id: item for item in confirmation_candidates
        }

        async def confirm_one(claim: _GapClaim) -> object:
            return await self._llm.complete(
                system=(
                    _idea_language_instruction(idea)
                    + "research-gap-claim-support-confirmation: adversarially verify "
                    "exactly one proposed atomic Gap claim against only its supplied "
                    "Related Work passage. Return only JSON with assessments containing "
                    "one object with claim_id, support_status, atomicity_status, "
                    "evidence_span, and unsupported_fragments. support_status must be "
                    "supported, unsupported, or uncertain. atomicity_status must be "
                    "atomic, compound, or uncertain. evidence_span must be a verbatim "
                    "span from the supplied passage that entails the complete claim; an "
                    "empty or merely topically related span is insufficient. List every "
                    "claim fragment not entailed by the passage in unsupported_fragments. "
                    "Mark compound when the statement joins independently testable "
                    "limitations. Mark unsupported when any asserted mechanism, modality, "
                    "scope, comparison, or application is absent from the passage. Never "
                    "infer that a method lacks a feature merely because the supplied "
                    "passage does not mention it. Cross-language paraphrases may be "
                    "supported, but the evidence_span must remain verbatim source text."
                ),
                prompt=json.dumps(
                    {
                        "required_claim_ids": [claim.claim_id],
                        "claim_candidates": [claim.model_dump(mode="json")],
                    },
                    default=str,
                    ensure_ascii=False,
                ),
            )

        confirmation_responses = await asyncio.gather(
            *(confirm_one(item) for item in confirmation_candidates),
            return_exceptions=True,
        )
        confirmations: dict[str, _GapClaimSupportItem] = {}
        confirmation_failures: list[str] = []
        for claim, response in zip(
            confirmation_candidates,
            confirmation_responses,
            strict=True,
        ):
            try:
                if isinstance(response, BaseException):
                    raise response
                confirmed = _validated_gap_claim_support_response(
                    str(response),
                    [claim.claim_id],
                )
                confirmations[claim.claim_id] = confirmed.assessments[0]
            except Exception as exc:  # noqa: BLE001 - fail closed per claim
                confirmation_failures.append(
                    f"{claim.claim_id}: {_structured_failure_detail(exc)}"
                )

        statuses: dict[str, CounterEvidenceSupport] = {}
        for claim in claim_candidates:
            bulk_status = bulk_statuses[claim.claim_id]
            effective = effective_by_id.get(claim.claim_id)
            if effective is None:
                statuses[claim.claim_id] = (
                    bulk_status
                    if _claim_statement_precheck(claim.statement)
                    else CounterEvidenceSupport.UNSUPPORTED
                )
                continue
            confirmation = confirmations.get(claim.claim_id)
            statuses[claim.claim_id] = (
                _strict_claim_support_status(effective, confirmation)
                if confirmation is not None
                else CounterEvidenceSupport.UNCERTAIN
            )
        supported = [
            effective_by_id[item.claim_id]
            for item in claim_candidates
            if statuses[item.claim_id] is CounterEvidenceSupport.SUPPORTED
            and item.claim_id in effective_by_id
        ]
        unsupported_count = sum(
            status is CounterEvidenceSupport.UNSUPPORTED
            for status in statuses.values()
        )
        uncertain_count = sum(
            status is CounterEvidenceSupport.UNCERTAIN
            for status in statuses.values()
        )
        warnings: list[str] = []
        if narrowed_by_id:
            warnings.append(
                f"Narrowed {len(narrowed_by_id)} Related Work limitation(s) to "
                "atomic claims entailed by their source passages."
            )
        if unsupported_count:
            warnings.append(
                f"Excluded {unsupported_count} atomic Gap claim candidate(s) whose "
                "Related Work passages did not semantically support the limitation."
            )
        if uncertain_count:
            warnings.append(
                f"Excluded {uncertain_count} atomic Gap claim candidate(s) because "
                "semantic passage support could not be determined conclusively."
            )
        if validation_failures:
            warnings.insert(
                0,
                "Atomic Gap claim support used structured-output recovery: "
                + " | ".join(dict.fromkeys(validation_failures)),
            )
        if confirmation_failures:
            warnings.append(
                "Atomic Gap claim confirmation failed closed for "
                f"{len(confirmation_failures)}/{len(confirmation_candidates)} claim(s): "
                + " | ".join(confirmation_failures)
            )
        if narrowing_failures:
            warnings.append(
                "Gap claim narrowing failed closed for "
                f"{len(narrowing_failures)}/{len(narrowing_candidates)} claim(s): "
                + " | ".join(narrowing_failures)
            )
        return supported, warnings

    async def _search_counter_evidence(
        self,
        *,
        idea: dict[str, Any],
        inputs: ResearchInputs,
        provisional_statement: str,
        gap_claims: list[_GapClaim] | None = None,
        related_work_citations: list[dict[str, Any]] | None = None,
        related_work_queries: list[str],
        preferences: SourcePreferences,
    ) -> _CounterEvidenceSearch:
        warnings: list[str] = []
        claim_query_count = min(max(len(gap_claims or []), 4), 5)
        try:
            raw = await self._llm.complete(
                system=(
                    "research-counter-query: return only JSON with a queries string array. "
                    f"Write exactly {claim_query_count} concise English scholarly queries. "
                    "Write at least one claim-specific query for every supplied atomic Gap "
                    "claim before adding a cross-claim survey query. Each query must be designed "
                    "to falsify or narrow that claim. Search for methods that already solve "
                    "the stated limitation, synonymous names for the proposed combination, "
                    "recent surveys, benchmarks, and conflicting findings. Use only the "
                    "confirmed Citation method hints for exact method-name searches; do not "
                    "promote implementation constants such as MAX_RETRY or ambiguous acronyms "
                    "such as CoT into standalone queries. Do not treat an empty result set as "
                    "evidence of novelty. Keep each query at no more than "
                    "eight content words."
                ),
                prompt=json.dumps(
                    {
                        "idea": idea,
                        "research_inputs": inputs.model_dump(mode="json"),
                        "provisional_gap_candidate": provisional_statement,
                        "gap_claims": [
                            item.model_dump(mode="json") for item in (gap_claims or [])
                        ],
                        "confirmed_citation_method_hints": _citation_method_queries(
                            related_work_citations or []
                        ),
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
        exact_method_queries = _citation_method_queries(related_work_citations or [])
        queries = _ensure_counter_query_families(
            model_queries,
            related_work_queries,
            exact_method_queries=exact_method_queries,
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
            f"Counter-evidence provider search failed: {failure}"
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
            require_domain_match=True,
        )
        citation_seeds = _citation_seed_records(related_work_citations or [])
        if (ranked or citation_seeds) and isinstance(self._source, CitationGraphPort):
            try:
                graph_seeds = _deduplicate_records([*citation_seeds, *ranked])
                expanded = await self._source.expand_related(
                    seeds=graph_seeds[: settings.research_graph_seed_count],
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
                    require_domain_match=True,
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
        selected_records = await self._select_counter_evidence_records(
            rerank.records,
            limit=5,
        )
        rejected_count = sum(
            1
            for record in rerank.records
            if record.metadata.get("counter_verification_status")
            == VerificationStatus.REJECTED.value
        )
        if rejected_count:
            warnings.append(
                f"Rejected and backfilled {rejected_count} counter-evidence source(s) "
                "whose identity could not be verified."
            )
        if len(selected_records) < 5 and len(rerank.records) >= 5:
            warnings.append(
                "Fewer than five counter-evidence sources remained after verification."
            )
        return _CounterEvidenceSearch(
            queries=queries,
            records=selected_records,
            selected_records=selected_records,
            candidate_records=rerank.records,
            candidate_count=len(rerank.records),
            complete=bool(queries) and failures == 0,
            warnings=warnings,
        )

    async def _select_counter_evidence_records(
        self,
        records: list[ScholarlyRecord],
        *,
        limit: int,
    ) -> list[ScholarlyRecord]:
        """Verify in rank order and backfill rejected counter-evidence sources."""
        selected: list[ScholarlyRecord] = []
        cursor = 0
        while len(selected) < limit and cursor < len(records):
            batch_size = min(limit - len(selected), len(records) - cursor)
            batch = records[cursor : cursor + batch_size]
            cursor += batch_size
            await self._verify_counter_evidence(batch)
            selected.extend(
                record
                for record in batch
                if record.metadata.get("counter_verification_status")
                != VerificationStatus.REJECTED.value
            )
        return selected

    async def _audit_counter_evidence_with_backfill(
        self,
        *,
        idea: dict[str, Any],
        provisional_statement: str,
        gap_claims: list[_GapClaim],
        counter_search: _CounterEvidenceSearch,
        session_id: UUID | None,
    ) -> tuple[
        list[ScholarlyRecord],
        list[_CounterEvidenceMaterial],
        _CounterEvidenceAssessment,
        list[str],
    ]:
        """Audit a bounded portfolio and replace unusable source assessments."""

        selected = list(counter_search.selected_records)
        selected_keys = {_record_result_key(record) for record in selected}
        remaining = [
            record
            for record in counter_search.candidate_records
            if _record_result_key(record) not in selected_keys
        ]
        warnings: list[str] = []
        materials: list[_CounterEvidenceMaterial] = []
        material_cache: dict[
            str, tuple[_CounterEvidenceMaterial, list[str]]
        ] = {}
        assessment = _CounterEvidenceAssessment(
            outcome=CounterEvidenceOutcome.INCONCLUSIVE,
            statement=provisional_statement,
            assessment="Counter-evidence analysis was not completed.",
        )

        max_backfill_rounds = 1
        # Audit the initial portfolio, then allow one replacement round so a noisy
        # top-five can recover without repeatedly extending the interactive request.
        for backfill_round in range(max_backfill_rounds + 1):
            materials, material_warnings = await self._counter_evidence_materials(
                selected,
                session_id=session_id,
                cache=material_cache,
            )
            assessment, assessment_warnings = await self._assess_counter_evidence(
                idea=idea,
                provisional_statement=provisional_statement,
                records=selected,
                materials=materials,
                gap_claims=gap_claims,
            )
            round_warnings = [*material_warnings, *assessment_warnings]
            warnings.extend(
                warning
                for warning in round_warnings
                if "structured-output recovery" in warning
                or "semantic support could not" in warning
            )

            failed_keys = {
                finding.result_key
                for finding in assessment.findings
                if finding.grounding_status is not GroundingStatus.GROUNDED
                or finding.relevance_status is not CounterEvidenceRelevance.RELEVANT
                or finding.support_status is not CounterEvidenceSupport.SUPPORTED
            }
            if not failed_keys:
                warnings.extend(round_warnings)
                break

            retained = [
                record
                for record in selected
                if _record_result_key(record) not in failed_keys
            ]
            needed = min(len(failed_keys), max(5 - len(retained), 0))
            replacements: list[ScholarlyRecord] = []
            if (
                needed > 0
                and backfill_round < max_backfill_rounds
                and remaining
            ):
                replacements = await self._select_counter_evidence_records(
                    remaining,
                    limit=needed,
                )
                attempted_keys = {
                    _record_result_key(record)
                    for record in remaining
                    if "counter_verification_status" in record.metadata
                }
                remaining = [
                    record
                    for record in remaining
                    if _record_result_key(record) not in attempted_keys
                ]

            if not replacements:
                cleanup_warnings = await self._delete_counter_material_objects(
                    materials,
                    result_keys=failed_keys,
                )
                warnings.extend(cleanup_warnings)
                selected = retained
                materials, material_warnings = await self._counter_evidence_materials(
                    selected,
                    session_id=session_id,
                    cache=material_cache,
                )
                assessment, assessment_warnings = await self._assess_counter_evidence(
                    idea=idea,
                    provisional_statement=provisional_statement,
                    records=selected,
                    materials=materials,
                    gap_claims=gap_claims,
                )
                warnings.extend(material_warnings)
                warnings.extend(assessment_warnings)
                warnings.append(
                    f"Excluded {len(failed_keys)} counter-evidence source(s) that "
                    "were not directly relevant, exactly grounded, and semantically "
                    "supported; final "
                    f"portfolio contains {len(selected)} source(s)."
                )
                break

            cleanup_warnings = await self._delete_counter_material_objects(
                materials,
                result_keys=failed_keys,
            )
            warnings.extend(cleanup_warnings)
            selected = [*retained, *replacements]
            warnings.append(
                f"Backfilled {len(replacements)} counter-evidence source(s) whose "
                "assessments were not directly relevant, exactly grounded, and "
                "semantically supported."
            )

        return selected, materials, assessment, list(dict.fromkeys(warnings))

    async def _delete_counter_material_objects(
        self,
        materials: list[_CounterEvidenceMaterial],
        *,
        result_keys: set[str],
    ) -> list[str]:
        if self._object_storage is None:
            return []
        warnings: list[str] = []
        for material in materials:
            object_key = material.source_object_key
            if (
                object_key is None
                or _record_result_key(material.record) not in result_keys
            ):
                continue
            try:
                await self._object_storage.delete_bytes(key=object_key)
            except Exception as exc:  # noqa: BLE001 - cleanup is best effort
                warnings.append(
                    "Superseded counter-evidence source text could not be removed: "
                    f"{type(exc).__name__}."
                )
        return warnings

    async def _verify_counter_evidence(
        self,
        records: list[ScholarlyRecord],
    ) -> None:
        """Verify top metadata-only results without fetching or analyzing full text."""
        if not records:
            return
        try:
            if isinstance(self._verifier, BatchCitationVerifier):
                verifications = await self._verifier.verify_many(citations=records)
            else:
                verifications = [
                    await self._verifier.verify(citation=record) for record in records
                ]
            if len(verifications) != len(records):
                raise ValueError(
                    "Counter-evidence verification coverage was incomplete"
                )
        except Exception as exc:  # noqa: BLE001 - retain retrieved metadata with a warning
            message = (
                "Counter-evidence source identity could not be rechecked: "
                f"{_llm_failure_summary(exc)}"
            )
            for record in records:
                record.metadata["counter_verification_status"] = (
                    VerificationStatus.WARNING.value
                )
                record.metadata["counter_verification_messages"] = [message]
            return

        for record, verification in zip(records, verifications, strict=True):
            if verification.record is not None:
                _merge_verified_counter_record(record, verification.record)
            record.metadata["counter_verification_status"] = verification.status.value
            record.metadata["counter_verification_messages"] = list(
                verification.messages
            )

    async def _counter_evidence_materials(
        self,
        records: list[ScholarlyRecord],
        *,
        session_id: UUID | None = None,
        cache: dict[str, tuple[_CounterEvidenceMaterial, list[str]]] | None = None,
    ) -> tuple[list[_CounterEvidenceMaterial], list[str]]:
        material_cache = cache if cache is not None else {}
        missing_records: dict[str, ScholarlyRecord] = {}
        for record in records:
            result_key = _record_result_key(record)
            if result_key not in material_cache:
                missing_records.setdefault(result_key, record)

        async def load_material(
            record: ScholarlyRecord,
        ) -> tuple[_CounterEvidenceMaterial, list[str]]:
            warnings: list[str] = []
            document: DocumentText | None = None
            if self._document_text_source is not None:
                try:
                    document = await self._document_text_source.fetch_text(
                        record=record
                    )
                except Exception as exc:  # noqa: BLE001 - abstract fallback remains useful
                    warnings.append(
                        "Counter-evidence full text could not be fetched for "
                        f"{record.title}: {_llm_failure_summary(exc)}"
                    )
            if document is not None and document.text.strip():
                source_text = utf8_safe_text(document.text)
                source_object_key = await self._persist_counter_evidence_text(
                    session_id=session_id,
                    record=record,
                    source_text=source_text,
                )
                return (
                    _CounterEvidenceMaterial(
                        record=record,
                        source_text=source_text[:24_000],
                        source_kind=document.source_kind,
                        source_location=_document_location(document, record),
                        source_object_key=source_object_key,
                    ),
                    warnings,
                )
            abstract = utf8_safe_text((record.abstract or "").strip())
            if abstract:
                source_object_key = await self._persist_counter_evidence_text(
                    session_id=session_id,
                    record=record,
                    source_text=abstract,
                )
                return (
                    _CounterEvidenceMaterial(
                        record=record,
                        source_text=abstract,
                        source_kind="abstract",
                        source_location="Abstract",
                        source_object_key=source_object_key,
                    ),
                    warnings,
                )
            warnings.append(
                "Counter-evidence content was unavailable for "
                f"{record.title}; its impact remains inconclusive."
            )
            return (
                _CounterEvidenceMaterial(
                    record=record,
                    source_text="",
                    source_kind="metadata_only",
                    source_location="Metadata only",
                ),
                warnings,
            )

        loaded = await asyncio.gather(
            *(load_material(record) for record in missing_records.values())
        )
        warnings: list[str] = []
        for result_key, (material, material_warnings) in zip(
            missing_records,
            loaded,
            strict=True,
        ):
            material_cache[result_key] = (material, material_warnings)
        requested_keys = list(
            dict.fromkeys(_record_result_key(record) for record in records)
        )
        for result_key in requested_keys:
            warnings.extend(material_cache[result_key][1])
        materials = [
            material_cache[_record_result_key(record)][0] for record in records
        ]
        return materials, warnings

    async def _persist_counter_evidence_text(
        self,
        *,
        session_id: UUID | None,
        record: ScholarlyRecord,
        source_text: str,
    ) -> str | None:
        if session_id is None or self._object_storage is None:
            return None
        data = utf8_safe_text(source_text).encode("utf-8")
        checksum = hashlib.sha256(data).hexdigest()
        result_digest = hashlib.sha256(
            _record_result_key(record).encode("utf-8")
        ).hexdigest()[:16]
        key = (
            f"research/{session_id}/gap/counter-evidence/"
            f"{result_digest}/{checksum}.txt"
        )
        try:
            stored_key = await self._object_storage.put_bytes(
                key=key,
                data=data,
                content_type="text/plain; charset=utf-8",
            )
        except Exception as exc:
            raise ResearchGenerationError(
                "Counter-evidence source text could not be persisted to object "
                f"storage for {record.title}: {type(exc).__name__}"
            ) from exc
        return stored_key

    async def _assess_counter_evidence(
        self,
        *,
        idea: dict[str, Any],
        provisional_statement: str,
        records: list[ScholarlyRecord],
        materials: list[_CounterEvidenceMaterial] | None = None,
        gap_claims: list[_GapClaim] | None = None,
    ) -> tuple[_CounterEvidenceAssessment, list[str]]:
        if not records:
            return (
                _CounterEvidenceAssessment(
                    outcome=CounterEvidenceOutcome.INCONCLUSIVE,
                    statement=provisional_statement,
                    assessment=(
                        "No counter-evidence source met the relevance and source-support "
                        "checks. The limitations below remain plausible, but unconfirmed."
                    ),
                ),
                [
                    (
                        "No sufficiently relevant counter-evidence was available to "
                        "confirm or rule out the potential Gap."
                    )
                ],
            )
        material_by_key = {
            _record_result_key(item.record): item for item in (materials or [])
        }
        payloads = []
        for record in records:
            payload = _counter_record_payload(record)
            material = material_by_key.get(payload["result_key"])
            payload.update(
                {
                    "source_text": material.source_text if material else "",
                    "source_kind": material.source_kind
                    if material
                    else "metadata_only",
                    "source_location": (
                        material.source_location if material else "Metadata only"
                    ),
                }
            )
            payloads.append(payload)
        required_keys = [item["result_key"] for item in payloads]
        required_claim_ids = [item.claim_id for item in (gap_claims or [])]
        counter_system = (
            _idea_language_instruction(idea)
            + "research-counter-analysis: return only one JSON object with exactly "
            "outcome, statement, assessment, covered_result_keys, findings, and "
            "claim_assessments. "
            "Use exactly this shape: "
            '{"outcome":"inconclusive","statement":"...","assessment":"...",'
            '"covered_result_keys":["..."],"findings":[{"result_key":"...",'
            '"impact":"inconclusive","relevance_status":"relevant",'
            '"rationale":"...","claim_ids":["c1"],'
            '"supporting_passage":"...","source_location":"Abstract"}],'
            '"claim_assessments":[{"claim_id":"c1","outcome":"inconclusive",'
            '"assessment":"...","revised_statement":null,'
            '"counter_evidence_result_keys":["..."]}]}. '
            "findings must contain exactly one object per result with result_key, "
            "claim_ids, impact, relevance_status, a concise source-specific rationale, "
            "an exact verbatim supporting_passage from source_text, and source_location. "
            "relevance_status must be relevant, irrelevant, or uncertain. Mark relevant "
            "only when the source directly concerns LLM reasoning or Chain of Thought and "
            "can test or materially contextualize at least one supplied Gap claim. Shared "
            "tokens such as retry, critic, verifier, CoT, or an acronym with a different "
            "meaning are not sufficient. Mark different domains and different acronym "
            "senses irrelevant. claim_assessments "
            "must contain exactly one assessment per supplied Gap claim. outcome and each impact "
            "must be one of no_direct_counter_evidence, gap_narrowed, "
            "gap_not_supported, or inconclusive. Read every supplied result and "
            "actively look for work that already addresses the proposed limitation or "
            "uses synonymous terminology. Revise the statement when the Gap must be "
            "narrowed. If a result already addresses it, use gap_not_supported. Never "
            "infer novelty from missing results or weak metadata. Treat warning "
            "verification as lower confidence and never rely on rejected results. "
            "When source_text is empty, use inconclusive and an empty supporting passage. "
            "covered_result_keys and the finding result_keys must include every "
            "required_result_key exactly once. Every finding.claim_ids must contain "
            "every required_claim_id, and every claim assessment must contain every "
            "required_result_key in counter_evidence_result_keys. Do not use markdown, reasoning, or "
            "explanations."
        )
        counter_request = {
            "idea": idea,
            "provisional_gap_candidate": provisional_statement,
            "gap_claims": [item.model_dump(mode="json") for item in (gap_claims or [])],
            "counter_evidence_results": payloads,
            "required_result_keys": required_keys,
            "required_claim_ids": required_claim_ids,
        }
        try:
            raw = await self._llm.complete(
                system=counter_system,
                prompt=json.dumps(
                    counter_request,
                    default=str,
                    ensure_ascii=False,
                ),
            )
            normalization_warning = ""
            try:
                assessment = _validated_counter_evidence_assessment(
                    raw,
                    required_keys,
                    required_claim_ids,
                )
            except (
                ValidationError,
                json.JSONDecodeError,
                TypeError,
                ValueError,
            ) as exc:
                repaired_raw = await self._llm.complete(
                    system=(
                        _idea_language_instruction(idea)
                        + "research-counter-analysis-repair: correct the previous "
                        "counter-evidence response. Return only one valid JSON object "
                        "with exactly outcome, statement, assessment, "
                        "covered_result_keys, findings, and claim_assessments. Use exactly "
                        "this shape: "
                        '{"outcome":"inconclusive","statement":"...",'
                        '"assessment":"...","covered_result_keys":["..."],'
                        '"findings":[{"result_key":"...","claim_ids":["c1"],'
                        '"impact":"inconclusive","relevance_status":"relevant",'
                        '"rationale":"...",'
                        '"supporting_passage":"...","source_location":"Abstract"}],'
                        '"claim_assessments":[{"claim_id":"c1",'
                        '"outcome":"inconclusive","assessment":"...",'
                        '"revised_statement":null,'
                        '"counter_evidence_result_keys":["..."]}]}. Each finding must have '
                        "result_key, claim_ids, impact, relevance_status, rationale, "
                        "supporting_passage, and source_location. relevance_status must be "
                        "relevant, irrelevant, or uncertain and must reject different domains "
                        "or ambiguous acronym matches. Return every required key "
                        "exactly once in covered_result_keys and findings. outcome and "
                        "impact must use only no_direct_counter_evidence, gap_narrowed, "
                        "gap_not_supported, or inconclusive. Make outcome consistent "
                        "with findings and return every required claim exactly once in "
                        "claim_assessments. Every finding.claim_ids must contain every "
                        "required_claim_id, and every claim assessment must reference every "
                        "required_result_key. Make the global outcome consistent with the "
                        "claim and finding impacts. Do not use markdown, reasoning, or "
                        "explanations."
                    ),
                    prompt=json.dumps(
                        {
                            "required_result_keys": required_keys,
                            "validation_error": str(exc)[:2_000],
                            "previous_response": raw[-12_000:],
                            "original_request": counter_request,
                        },
                        default=str,
                        ensure_ascii=False,
                    ),
                )
                try:
                    assessment = _validated_counter_evidence_assessment(
                        repaired_raw,
                        required_keys,
                        required_claim_ids,
                    )
                except (
                    ValidationError,
                    json.JSONDecodeError,
                    TypeError,
                    ValueError,
                ):
                    assessment, recovery_warnings = (
                        await self._recover_counter_evidence_by_source(
                            idea=idea,
                            provisional_statement=provisional_statement,
                            payloads=payloads,
                            gap_claims=gap_claims or [],
                        )
                    )
                    recovered_count = sum(
                        item.grounding_status is GroundingStatus.PENDING
                        and bool(item.supporting_passage)
                        for item in assessment.findings
                    )
                    if recovery_warnings:
                        normalization_warning = (
                            "Bulk counter-evidence response remained structurally "
                            "incomplete after repair; analysis continued independently "
                            f"per source ({recovered_count}/{len(required_keys)} source "
                            "response(s) recovered). "
                            f"{' '.join(recovery_warnings)}"
                        )
                    else:
                        # The alternate source-level path fully recovered the audit.
                        # Do not surface an internal bulk-format failure to the user.
                        normalization_warning = ""
                else:
                    normalization_warning = ""
            grounded, grounding_warnings = _ground_counter_evidence_assessment(
                assessment,
                materials or [],
                gap_claims or [],
            )
            supported, support_warnings = await self._validate_counter_support(
                idea=idea,
                assessment=grounded,
                materials=materials or [],
                gap_claims=gap_claims or [],
            )
            if normalization_warning:
                grounding_warnings.insert(0, normalization_warning)
            return supported, [*grounding_warnings, *support_warnings]
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

    async def _validate_counter_support(
        self,
        *,
        idea: dict[str, Any],
        assessment: _CounterEvidenceAssessment,
        materials: list[_CounterEvidenceMaterial],
        gap_claims: list[_GapClaim],
    ) -> tuple[_CounterEvidenceAssessment, list[str]]:
        """Check that each source-specific rationale follows from retrieved content."""

        material_by_key = {
            _record_result_key(item.record): item for item in materials
        }
        eligible = [
            finding
            for finding in assessment.findings
            if finding.grounding_status is GroundingStatus.GROUNDED
            and finding.relevance_status is CounterEvidenceRelevance.RELEVANT
            and (material := material_by_key.get(finding.result_key)) is not None
            and bool(material.source_text)
        ]
        statuses: dict[str, CounterEvidenceSupport] = {}
        warnings: list[str] = []
        if eligible:
            required_keys = [item.result_key for item in eligible]
            finding_payloads = [
                {
                    **item.model_dump(mode="json"),
                    "source_text": material_by_key[item.result_key].source_text,
                    "source_kind": material_by_key[item.result_key].source_kind,
                }
                for item in eligible
            ]
            request = {
                "required_result_keys": required_keys,
                "gap_claims": [
                    item.model_dump(mode="json") for item in gap_claims
                ],
                "findings": finding_payloads,
            }
            validation_failures: list[str] = []
            try:
                raw = await self._llm.complete(
                    system=(
                        _idea_language_instruction(idea)
                        + "research-counter-support-check: independently verify whether "
                        "each source-specific rationale and impact are semantically supported "
                        "by the supplied source_text and linked atomic Gap claims. Return only "
                        "JSON with assessments, containing exactly one object per required "
                        "result_key with result_key and support_status. support_status must be "
                        "supported, unsupported, or uncertain. Exact quote presence alone is "
                        "not enough. Use unsupported when the rationale introduces a fact, "
                        "mechanism, number, comparison, or conclusion absent from source_text, "
                        "or when the quoted passage is unrelated to the rationale. Use uncertain "
                        "when an abstract is too limited to justify a paper-wide absence claim. "
                        "Use supported only when the supplied content warrants the stated impact."
                    ),
                    prompt=json.dumps(request, default=str, ensure_ascii=False),
                )
                parsed = _validated_counter_support_response(
                    raw,
                    required_keys,
                )
            except Exception as first_exc:  # noqa: BLE001 - bounded repair follows
                validation_failures.append(_structured_failure_detail(first_exc))
                try:
                    repaired_raw = await self._llm.complete(
                        system=(
                            _idea_language_instruction(idea)
                            + "research-counter-support-repair: repair the previous "
                            "response. Return only JSON with assessments and exactly one "
                            "object per required_result_key. Each object must contain "
                            "result_key and support_status using supported, unsupported, "
                            "or uncertain."
                        ),
                        prompt=json.dumps(
                            {
                                **request,
                                "validation_error": validation_failures[-1],
                                "previous_response": str(locals().get("raw", ""))[
                                    -8_000:
                                ],
                            },
                            default=str,
                            ensure_ascii=False,
                        ),
                    )
                    parsed = _validated_counter_support_response(
                        repaired_raw,
                        required_keys,
                    )
                except Exception as repair_exc:  # noqa: BLE001 - item recovery
                    validation_failures.append(
                        _structured_failure_detail(repair_exc)
                    )

                    async def assess_one(payload: dict[str, Any]) -> object:
                        return await self._llm.complete(
                            system=(
                                _idea_language_instruction(idea)
                                + "research-counter-support-item-check: assess exactly "
                                "one source finding and return JSON with result_key and "
                                "support_status. support_status must be supported, "
                                "unsupported, or uncertain."
                            ),
                            prompt=json.dumps(
                                {
                                    "required_result_keys": [payload["result_key"]],
                                    "gap_claims": request["gap_claims"],
                                    "finding": payload,
                                },
                                default=str,
                                ensure_ascii=False,
                            ),
                        )

                    responses = await asyncio.gather(
                        *(assess_one(item) for item in finding_payloads),
                        return_exceptions=True,
                    )
                    recovered: list[_CounterSupportItem] = []
                    failed_keys: list[str] = []
                    for payload, response in zip(
                        finding_payloads,
                        responses,
                        strict=True,
                    ):
                        result_key = str(payload["result_key"])
                        try:
                            if isinstance(response, BaseException):
                                raise response
                            item_response = _validated_counter_support_response(
                                str(response),
                                [result_key],
                            )
                            recovered.extend(item_response.assessments)
                        except Exception:  # noqa: BLE001 - item stays uncertain
                            failed_keys.append(result_key)
                            recovered.append(
                                _CounterSupportItem(
                                    result_key=result_key,
                                    support_status=CounterEvidenceSupport.UNCERTAIN,
                                )
                            )
                    parsed = _CounterSupportResponse(assessments=recovered)
                    validation_failures.append(
                        "per-source recovery left "
                        f"{len(failed_keys)}/{len(required_keys)} source(s) uncertain"
                    )
            statuses = {
                item.result_key: item.support_status for item in parsed.assessments
            }
            if validation_failures:
                warnings.append(
                    "Counter-evidence semantic support used structured-output "
                    "recovery: "
                    + " | ".join(dict.fromkeys(validation_failures))
                )

        unsupported_keys: list[str] = []
        uncertain_keys: list[str] = []
        for finding in assessment.findings:
            finding.support_status = statuses.get(
                finding.result_key,
                CounterEvidenceSupport.UNCERTAIN,
            )
            if finding.support_status is not CounterEvidenceSupport.SUPPORTED:
                finding.impact = CounterEvidenceOutcome.INCONCLUSIVE
                if finding.support_status is CounterEvidenceSupport.UNSUPPORTED:
                    unsupported_keys.append(finding.result_key)
                else:
                    uncertain_keys.append(finding.result_key)

        findings_by_key = {
            finding.result_key: finding for finding in assessment.findings
        }
        for claim in assessment.claim_assessments:
            linked = [
                findings_by_key[key]
                for key in claim.counter_evidence_result_keys
                if key in findings_by_key
            ]
            if not linked or any(
                item.support_status is not CounterEvidenceSupport.SUPPORTED
                for item in linked
            ):
                claim.outcome = CounterEvidenceOutcome.INCONCLUSIVE
        impacts = (
            {item.outcome for item in assessment.claim_assessments}
            if assessment.claim_assessments
            else {item.impact for item in assessment.findings}
        )
        assessment.outcome = _aggregate_counter_outcome(impacts)
        if unsupported_keys:
            warnings.append(
                f"{len(unsupported_keys)} counter-evidence rationale(s) were not "
                "semantically supported by retrieved source content and were downgraded "
                f"to inconclusive: {', '.join(unsupported_keys)}."
            )
        if uncertain_keys:
            warnings.append(
                f"{len(uncertain_keys)} counter-evidence rationale(s) could not be "
                "semantically validated conclusively and were downgraded to "
                f"inconclusive: {', '.join(uncertain_keys)}."
            )
        return assessment, warnings

    async def _recover_counter_evidence_by_source(
        self,
        *,
        idea: dict[str, Any],
        provisional_statement: str,
        payloads: list[dict[str, Any]],
        gap_claims: list[_GapClaim],
    ) -> tuple[_CounterEvidenceAssessment, list[str]]:
        """Recover a failed bulk audit with bounded source-level completions."""

        claim_ids = [item.claim_id for item in gap_claims]
        system = (
            _idea_language_instruction(idea)
            + "research-counter-source-analysis: analyze exactly one supplied source. "
            "Return only JSON with result_key, impact, relevance_status, rationale, "
            "supporting_passage, source_location, and claim_findings. Use this shape: "
            '{"result_key":"...","impact":"inconclusive",'
            '"relevance_status":"relevant","rationale":"...",'
            '"supporting_passage":"exact quote","source_location":"Abstract",'
            '"claim_findings":[{"claim_id":"c1","impact":"inconclusive",'
            '"rationale":"...","revised_statement":null}]}. '
            "Evaluate every supplied Gap claim against this source and return every "
            "required claim_id exactly once. impact must be one of "
            "no_direct_counter_evidence, gap_narrowed, gap_not_supported, or "
            "inconclusive. relevance_status must be relevant, irrelevant, or uncertain. "
            "Mark relevant only if the source directly concerns LLM reasoning or Chain of "
            "Thought and can assess at least one Gap claim; reject different domains and "
            "ambiguous acronym matches. Copy one exact, contiguous supporting passage from "
            "source_text. If source_text is empty or no passage supports the analysis, "
            "use inconclusive and an empty passage. Never infer novelty from absence. "
            "Do not use markdown or explanatory text outside JSON."
        )

        async def analyze_source(payload: dict[str, Any]) -> object:
            return await self._llm.complete(
                system=system,
                prompt=json.dumps(
                    {
                        "provisional_gap_candidate": provisional_statement,
                        "gap_claims": [
                            item.model_dump(mode="json") for item in gap_claims
                        ],
                        "counter_evidence_result": payload,
                        "required_result_key": payload["result_key"],
                        "required_claim_ids": claim_ids,
                    },
                    default=str,
                    ensure_ascii=False,
                ),
            )

        responses = await asyncio.gather(
            *(analyze_source(payload) for payload in payloads),
            return_exceptions=True,
        )
        source_assessments: list[_CounterSourceAssessment] = []
        failed_keys: list[str] = []
        for payload, response in zip(payloads, responses, strict=True):
            result_key = str(payload["result_key"])
            try:
                if isinstance(response, BaseException):
                    raise response
                parsed = _CounterSourceAssessment.model_validate(
                    _json_value(str(response), dict)
                )
                if parsed.result_key != result_key:
                    raise ValueError("Source analysis returned the wrong result_key")
                returned_claim_ids = [item.claim_id for item in parsed.claim_findings]
                if len(set(returned_claim_ids)) != len(returned_claim_ids) or set(
                    returned_claim_ids
                ) != set(claim_ids):
                    raise ValueError("Source analysis did not cover every Gap claim")
                if parsed.impact is not _aggregate_counter_outcome(
                    {item.impact for item in parsed.claim_findings}
                    if parsed.claim_findings
                    else {parsed.impact}
                ):
                    raise ValueError("Source outcome was inconsistent with claim impacts")
            except Exception:  # noqa: BLE001 - one source must not discard the audit
                failed_keys.append(result_key)
                parsed = _CounterSourceAssessment(
                    result_key=result_key,
                    impact=CounterEvidenceOutcome.INCONCLUSIVE,
                    relevance_status=CounterEvidenceRelevance.UNCERTAIN,
                    rationale=(
                        "This source could not be analyzed with the required structured "
                        "fields."
                    ),
                    claim_findings=[
                        _CounterSourceClaimFinding(
                            claim_id=claim_id,
                            impact=CounterEvidenceOutcome.INCONCLUSIVE,
                            rationale=(
                                "This claim could not be validated against this source."
                            ),
                        )
                        for claim_id in claim_ids
                    ],
                )
            source_assessments.append(parsed)

        findings = [
            _CounterEvidenceFinding(
                result_key=item.result_key,
                claim_ids=[claim.claim_id for claim in item.claim_findings],
                impact=item.impact,
                relevance_status=item.relevance_status,
                rationale=item.rationale,
                supporting_passage=item.supporting_passage,
                source_location=item.source_location,
            )
            for item in source_assessments
        ]
        claim_assessments: list[_CounterEvidenceClaimAssessment] = []
        for claim in gap_claims:
            source_findings = [
                next(
                    item
                    for item in source.claim_findings
                    if item.claim_id == claim.claim_id
                )
                for source in source_assessments
            ]
            outcome = _aggregate_counter_outcome(
                {item.impact for item in source_findings}
            )
            revised = next(
                (
                    item.revised_statement.strip()
                    for item in source_findings
                    if item.impact is CounterEvidenceOutcome.GAP_NARROWED
                    and item.revised_statement
                    and item.revised_statement.strip()
                ),
                None,
            )
            if outcome is CounterEvidenceOutcome.GAP_NARROWED and not revised:
                outcome = CounterEvidenceOutcome.INCONCLUSIVE
            claim_assessments.append(
                _CounterEvidenceClaimAssessment(
                    claim_id=claim.claim_id,
                    outcome=outcome,
                    assessment=" ".join(
                        dict.fromkeys(item.rationale for item in source_findings)
                    ),
                    revised_statement=revised,
                    counter_evidence_result_keys=[
                        item.result_key for item in source_assessments
                    ],
                )
            )

        impacts = (
            {item.outcome for item in claim_assessments}
            if claim_assessments
            else {item.impact for item in findings}
        )
        assessment = _CounterEvidenceAssessment(
            outcome=_aggregate_counter_outcome(impacts),
            statement=provisional_statement,
            assessment=(
                "Counter-evidence was analyzed independently per source after the "
                "combined response could not be validated."
            ),
            covered_result_keys=[item.result_key for item in source_assessments],
            findings=findings,
            claim_assessments=claim_assessments,
        )
        warnings = (
            [
                (
                    f"{len(failed_keys)} source-level counter-evidence response(s) "
                    "still lacked the required fields and remain inconclusive."
                )
            ]
            if failed_keys
            else []
        )
        return assessment, warnings

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
        document.text = utf8_safe_text(document.text)
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

    async def _mark_generated_since_prepare(
        self, session_id: UUID, node: str
    ) -> None:
        await self._db.execute(
            update(NodeHead)
            .where(NodeHead.session_id == session_id, NodeHead.node == node)
            .values(generated_since_prepare=True)
            .execution_options(synchronize_session=False)
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

    async def _revision_citations(
        self, session_id: UUID, stage_revision_id: UUID
    ) -> list[Citation]:
        rows = await self._db.scalars(
            select(Citation)
            .where(
                Citation.session_id == session_id,
                Citation.stage_revision_id == stage_revision_id,
                Citation.is_active.is_(True),
            )
            .order_by(Citation.created_at, Citation.id)
        )
        return list(rows.all())

    async def _assert_session_revision(
        self, session_id: UUID, stage_revision_id: UUID
    ) -> None:
        revision = await self._db.scalar(
            select(StageRevision.id).where(
                StageRevision.id == stage_revision_id,
                StageRevision.session_id == session_id,
            )
        )
        if revision is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Stage Revision not found",
            )

    async def _delete_working_related_work(self, session_id: UUID) -> None:
        object_keys = {
            key
            for key in (
                await self._db.scalars(
                    select(Citation.text_object_key).where(
                        Citation.session_id == session_id,
                        Citation.stage_revision_id.is_(None),
                        Citation.text_object_key.is_not(None),
                    )
                )
            ).all()
            if key
        }
        if object_keys:
            referenced_keys = {
                key
                for key in (
                    await self._db.scalars(
                        select(Citation.text_object_key).where(
                            Citation.session_id == session_id,
                            Citation.stage_revision_id.is_not(None),
                            Citation.text_object_key.in_(object_keys),
                        )
                    )
                ).all()
                if key
            }
            await self._delete_object_keys(object_keys - referenced_keys)
        await self._db.execute(
            delete(RelatedWorkFinding).where(
                RelatedWorkFinding.session_id == session_id,
                RelatedWorkFinding.stage_revision_id.is_(None),
            )
        )
        await self._db.execute(
            delete(Citation).where(
                Citation.session_id == session_id,
                Citation.stage_revision_id.is_(None),
            )
        )

    async def _delete_working_gap(self, session_id: UUID) -> None:
        saved_narratives = await self._db.scalar(
            select(LoopSession.working_draft_narratives).where(
                LoopSession.id == session_id
            )
        )
        gap_narrative = dict(saved_narratives or {}).get(ResearchNode.GAP.value, {})
        object_keys = _counter_evidence_object_keys(gap_narrative)
        if object_keys:
            revision_narratives = (
                await self._db.scalars(
                    select(StageRevision.narrative).where(
                        StageRevision.session_id == session_id,
                        StageRevision.node == ResearchNode.GAP.value,
                    )
                )
            ).all()
            referenced_keys = {
                key
                for narrative in revision_narratives
                for key in _counter_evidence_object_keys(narrative)
            }
            await self._delete_object_keys(object_keys - referenced_keys)
        await self._db.execute(
            delete(Card).where(
                Card.session_id == session_id,
                Card.kind == CardKind.GAP.value,
            )
        )

    async def _delete_object_keys(self, keys: set[str]) -> None:
        if self._object_storage is None:
            return
        for key in sorted(keys):
            await self._object_storage.delete_bytes(key=key)

    async def _set_narrative(
        self,
        session_id: UUID,
        node: str,
        narrative: dict[str, Any],
    ) -> None:
        saved_narratives = await self._db.scalar(
            select(LoopSession.working_draft_narratives).where(
                LoopSession.id == session_id
            )
        )
        next_saved_narratives = dict(saved_narratives or {})
        next_saved_narratives[node] = narrative
        await self._db.execute(
            update(LoopSession)
            .where(LoopSession.id == session_id)
            .values(
                working_draft_narrative=narrative,
                working_draft_narratives=next_saved_narratives,
                updated_at=func.now(),
            )
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
    candidates: list[str] = []

    # Reasoning-capable OpenAI-compatible models may put a valid answer after a
    # <think> block or inside a fenced block despite the JSON-only instruction.
    # Prefer those answer-shaped regions before scanning the entire response.
    think_end = cleaned.rfind("</think>")
    if think_end >= 0:
        candidates.append(cleaned[think_end + len("</think>") :].strip())
    candidates.extend(
        match.group(1).strip()
        for match in re.finditer(
            r"```(?:json)?\s*([\s\S]*?)```",
            cleaned,
            flags=re.IGNORECASE,
        )
    )
    candidates.append(cleaned)

    decoder = json.JSONDecoder()
    decode_error: json.JSONDecodeError | None = None
    seen: set[str] = set()
    opener = "{" if expected is dict else "["
    for candidate in candidates:
        if not candidate or candidate in seen:
            continue
        seen.add(candidate)
        try:
            value = json.loads(candidate)
        except json.JSONDecodeError as exc:
            decode_error = exc
        else:
            if isinstance(value, expected):
                return value

        # Accept a valid JSON value surrounded by prose/reasoning, while still
        # requiring the decoded value to have the caller's expected container type.
        for match in re.finditer(re.escape(opener), candidate):
            try:
                value, _ = decoder.raw_decode(candidate[match.start() :])
            except json.JSONDecodeError as exc:
                decode_error = exc
                continue
            if isinstance(value, expected):
                return value

    if decode_error is not None:
        raise decode_error
    raise TypeError(f"Expected {expected.__name__} JSON")


def _normalized_support_items(
    raw: str,
    *,
    identifier_field: str,
    required_identifiers: list[str],
) -> list[dict[str, Any]]:
    """Normalize common structured-output wrappers and support-status aliases."""

    try:
        value: object = _json_value(raw, list)
    except (json.JSONDecodeError, TypeError):
        value = _json_value(raw, dict)

    def unwrap(candidate: object) -> list[object]:
        if isinstance(candidate, list):
            return candidate
        if not isinstance(candidate, dict):
            return []
        if any(
            key in candidate
            for key in (
                identifier_field,
                "claim_id",
                "result_key",
                "id",
                "key",
            )
        ):
            return [candidate]
        if any(
            key in candidate
            for key in (
                "support_status",
                "status",
                "support",
                "verdict",
                "entailed",
                "is_supported",
                "supported",
            )
        ):
            return [candidate]
        for wrapper in (
            "assessments",
            "results",
            "items",
            "data",
            "output",
            "response",
        ):
            if wrapper in candidate:
                unwrapped = unwrap(candidate[wrapper])
                if unwrapped:
                    return unwrapped
        if candidate and all(not isinstance(item, (dict, list)) for item in candidate.values()):
            return [
                {identifier_field: key, "support_status": status}
                for key, status in candidate.items()
            ]
        return []

    items = unwrap(value)
    normalized: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        identifier = next(
            (
                str(item[key]).strip()
                for key in (
                    identifier_field,
                    "claim_id",
                    "result_key",
                    "id",
                    "key",
                )
                if item.get(key) is not None and str(item[key]).strip()
            ),
            "",
        )
        if not identifier and len(required_identifiers) == 1:
            identifier = required_identifiers[0]
        raw_status = next(
            (
                item[key]
                for key in (
                    "support_status",
                    "status",
                    "support",
                    "verdict",
                    "entailed",
                    "is_supported",
                    "supported",
                )
                if key in item
            ),
            None,
        )
        status = _normalized_support_status(raw_status)
        if identifier:
            normalized_item: dict[str, Any] = {
                identifier_field: identifier,
                "support_status": status.value,
            }
            if identifier_field == "claim_id":
                atomicity = next(
                    (
                        item[key]
                        for key in (
                            "atomicity_status",
                            "atomicity",
                            "is_atomic",
                            "atomic",
                        )
                        if key in item
                    ),
                    None,
                )
                evidence_span = next(
                    (
                        str(item[key]).strip()
                        for key in (
                            "evidence_span",
                            "supporting_span",
                            "exact_evidence",
                            "quote",
                        )
                        if item.get(key) is not None and str(item[key]).strip()
                    ),
                    "",
                )
                normalized_item.update(
                    {
                        "atomicity_status": _normalized_atomicity_status(atomicity),
                        "evidence_span": evidence_span,
                        "unsupported_fragments": _string_list(
                            item.get("unsupported_fragments")
                        ),
                    }
                )
            normalized.append(normalized_item)
    return normalized


def _normalized_atomicity_status(value: object) -> str:
    if value is True:
        return "atomic"
    if value is False:
        return "compound"
    folded = re.sub(r"[^a-z]+", "_", str(value or "").casefold()).strip("_")
    if folded in {"atomic", "single", "one_claim", "indivisible"}:
        return "atomic"
    if folded in {"compound", "composite", "multiple", "not_atomic"}:
        return "compound"
    return "uncertain"


def _normalized_support_status(value: object) -> CounterEvidenceSupport:
    if value is True:
        return CounterEvidenceSupport.SUPPORTED
    if value is False:
        return CounterEvidenceSupport.UNSUPPORTED
    folded = re.sub(r"[^a-z]+", "_", str(value or "").casefold()).strip("_")
    if folded in {
        "supported",
        "support",
        "yes",
        "true",
        "entailed",
        "directly_supported",
    }:
        return CounterEvidenceSupport.SUPPORTED
    if folded in {
        "unsupported",
        "not_supported",
        "no",
        "false",
        "contradicted",
        "not_entailed",
    }:
        return CounterEvidenceSupport.UNSUPPORTED
    return CounterEvidenceSupport.UNCERTAIN


def _validated_gap_claim_support_response(
    raw: str,
    required_claim_ids: list[str],
) -> _GapClaimSupportResponse:
    response = _GapClaimSupportResponse.model_validate(
        {
            "assessments": _normalized_support_items(
                raw,
                identifier_field="claim_id",
                required_identifiers=required_claim_ids,
            )
        }
    )
    returned_ids = [item.claim_id for item in response.assessments]
    if len(set(returned_ids)) != len(returned_ids):
        raise ValueError("Gap claim support check returned duplicate claim identifiers")
    if set(returned_ids) != set(required_claim_ids):
        raise ValueError("Gap claim support check did not cover every candidate")
    return response


def _validated_counter_support_response(
    raw: str,
    required_result_keys: list[str],
) -> _CounterSupportResponse:
    response = _CounterSupportResponse.model_validate(
        {
            "assessments": _normalized_support_items(
                raw,
                identifier_field="result_key",
                required_identifiers=required_result_keys,
            )
        }
    )
    returned_keys = [item.result_key for item in response.assessments]
    if len(set(returned_keys)) != len(returned_keys):
        raise ValueError("Counter support check returned duplicate source identifiers")
    if set(returned_keys) != set(required_result_keys):
        raise ValueError("Counter support check did not cover every required source")
    return response


def _validated_rerank_response(
    raw: str,
    expected_keys: list[str],
) -> _RerankResponse:
    response = _RerankResponse.model_validate(_json_value(raw, dict))
    returned_keys = [item.result_key for item in response.rankings]
    if len(set(returned_keys)) != len(returned_keys):
        raise ValueError("Reranker returned duplicate candidate identifiers")
    if set(returned_keys) != set(expected_keys):
        raise ValueError("Reranker did not return every supplied candidate")
    return response


def _portfolio_order_records(
    records: list[ScholarlyRecord],
    *,
    queries: list[str],
) -> list[ScholarlyRecord]:
    """Order candidates as a relevant, evidence-rich, non-redundant portfolio.

    The LLM/heuristic rank remains the dominant signal. The greedy portfolio pass
    adds bounded bonuses for explicit source quality and new query/publication
    coverage, while penalizing near-duplicates. It orders the full candidate list
    so both Related Work document backfill and counter-evidence verification backfill
    use the same policy.
    """
    if len(records) < 2:
        for rank, record in enumerate(records, start=1):
            _set_portfolio_metadata(
                record,
                rank=rank,
                score=_record_relevance_score(record, rank - 1, len(records)),
                evidence_quality=_record_evidence_quality(record),
                query_coverage=_record_query_coverage(record, queries),
                redundancy=0.0,
            )
        return list(records)

    record_count = len(records)
    remaining = list(range(record_count))
    selected_indexes: list[int] = []
    covered_queries: set[int] = set()
    covered_kinds: set[str] = set()
    covered_venues: set[str] = set()
    ordered: list[ScholarlyRecord] = []
    relevance_by_index = {
        index: _record_relevance_score(record, index, record_count)
        for index, record in enumerate(records)
    }
    quality_by_index = {
        index: _record_evidence_quality(record) for index, record in enumerate(records)
    }
    queries_by_index = {
        index: _record_query_coverage(record, queries)
        for index, record in enumerate(records)
    }
    kinds_by_index = {
        index: _publication_kinds(record) for index, record in enumerate(records)
    }
    venues_by_index = {
        index: _comparison_text(record.venue or "")
        for index, record in enumerate(records)
    }
    similarity_by_pair: dict[tuple[int, int], float] = {}

    def similarity(first_index: int, second_index: int) -> float:
        pair: tuple[int, int] = (
            (first_index, second_index)
            if first_index <= second_index
            else (second_index, first_index)
        )
        cached = similarity_by_pair.get(pair)
        if cached is None:
            cached = _record_content_similarity(
                records[first_index], records[second_index]
            )
            similarity_by_pair[pair] = cached
        return cached

    while remaining:
        best_position = 0
        best_details: tuple[float, float, set[int], float] | None = None
        best_key: tuple[float, float, int] | None = None
        for position, original_index in enumerate(remaining):
            relevance = relevance_by_index[original_index]
            evidence_quality = quality_by_index[original_index]
            query_coverage = queries_by_index[original_index]
            new_query_fraction = len(query_coverage - covered_queries) / max(
                len(queries), 1
            )
            kinds = kinds_by_index[original_index]
            kind_bonus = 1.0 if kinds - covered_kinds else 0.0
            venue = venues_by_index[original_index]
            venue_bonus = 1.0 if venue and venue not in covered_venues else 0.0
            redundancy = max(
                (
                    similarity(original_index, selected_index)
                    for selected_index in selected_indexes
                ),
                default=0.0,
            )
            score = (
                0.72 * relevance
                + 0.12 * evidence_quality
                + 0.10 * new_query_fraction
                + 0.035 * kind_bonus
                + 0.015 * venue_bonus
                - 0.18 * redundancy
            )
            # Stable deterministic tie-breaking preserves the semantic/heuristic order.
            key = (score, relevance, -original_index)
            if best_key is None or key > best_key:
                best_key = key
                best_position = position
                best_details = (
                    score,
                    evidence_quality,
                    query_coverage,
                    redundancy,
                )

        original_index = remaining.pop(best_position)
        chosen = records[original_index]
        assert best_details is not None
        score, evidence_quality, query_coverage, redundancy = best_details
        ordered.append(chosen)
        selected_indexes.append(original_index)
        covered_queries.update(query_coverage)
        covered_kinds.update(kinds_by_index[original_index])
        venue = venues_by_index[original_index]
        if venue:
            covered_venues.add(venue)
        _set_portfolio_metadata(
            chosen,
            rank=len(ordered),
            score=score,
            evidence_quality=evidence_quality,
            query_coverage=query_coverage,
            redundancy=redundancy,
        )
    return ordered


def _set_portfolio_metadata(
    record: ScholarlyRecord,
    *,
    rank: int,
    score: float,
    evidence_quality: float,
    query_coverage: set[int],
    redundancy: float,
) -> None:
    record.metadata["portfolio_rank"] = rank
    record.metadata["portfolio_score"] = round(score, 4)
    record.metadata["portfolio_evidence_quality"] = round(evidence_quality, 4)
    record.metadata["portfolio_query_indexes"] = sorted(query_coverage)
    record.metadata["portfolio_redundancy"] = round(redundancy, 4)
    record.metadata["portfolio_publication_kinds"] = sorted(_publication_kinds(record))
    record.metadata["selection_rule"] = "quality_diversity_portfolio"


def _record_relevance_score(
    record: ScholarlyRecord,
    original_index: int,
    record_count: int,
) -> float:
    for key in ("reranker_score", "retrieval_score"):
        value = record.metadata.get(key)
        if isinstance(value, (int, float)):
            return min(max(float(value), 0.0), 1.0)
    # Preserve the existing order when neither ranking layer emitted a score.
    return max(0.5, 1.0 - original_index / max(record_count, 1) * 0.5)


def _record_evidence_quality(record: ScholarlyRecord) -> float:
    """Score explicit evidence availability/completeness, never inferred prestige."""
    score = 0.0
    abstract_length = len((record.abstract or "").strip())
    if abstract_length:
        score += 0.2
        score += min(abstract_length / 1_500, 1.0) * 0.15
    if record.venue:
        score += 0.1
    if record.doi:
        score += 0.1
    if record.provider and record.provider_source_id:
        score += 0.1
    if _record_has_full_text(record):
        score += 0.15
    peer_reviewed = _explicit_peer_review_status(record)
    if peer_reviewed is True:
        score += 0.15
    kinds = _publication_kinds(record)
    if kinds & {"review", "survey", "systematicreview", "meta-analysis"}:
        score += 0.05
    return min(score, 1.0)


def _record_has_full_text(record: ScholarlyRecord) -> bool:
    metadata = record.metadata
    open_access = metadata.get("openAccessPdf") or {}
    best_location = metadata.get("best_oa_location") or {}
    primary_location = metadata.get("primary_location") or {}
    return bool(
        metadata.get("full_text_url")
        or metadata.get("open_access_pdf_url")
        or (open_access.get("url") if isinstance(open_access, dict) else None)
        or (best_location.get("pdf_url") if isinstance(best_location, dict) else None)
        or (
            primary_location.get("pdf_url")
            if isinstance(primary_location, dict)
            else None
        )
    )


def _explicit_peer_review_status(record: ScholarlyRecord) -> bool | None:
    explicit = record.metadata.get("is_peer_reviewed")
    if isinstance(explicit, bool):
        return explicit
    kinds = _publication_kinds(record)
    if kinds & {"journal", "journalarticle", "conference", "proceedingsarticle"}:
        return True
    if kinds & {"preprint", "posted-content"}:
        return False
    return None


def _publication_kinds(record: ScholarlyRecord) -> set[str]:
    metadata = record.metadata
    raw_values: list[object] = [
        metadata.get("type"),
        metadata.get("source_type"),
    ]
    publication_types = metadata.get("publicationTypes") or []
    if isinstance(publication_types, list):
        raw_values.extend(publication_types)
    primary_location = metadata.get("primary_location") or {}
    if isinstance(primary_location, dict):
        source = primary_location.get("source") or {}
        if isinstance(source, dict):
            raw_values.append(source.get("type"))
    return {
        re.sub(r"[^a-z0-9-]+", "", str(value).casefold())
        for value in raw_values
        if value
    }


def _record_query_coverage(
    record: ScholarlyRecord,
    queries: list[str],
) -> set[int]:
    discoveries = {
        _comparison_text(item)
        for item in _string_list(record.metadata.get("discovery_queries"))
    }
    text_tokens = _search_tokens(f"{record.title} {record.abstract or ''}")
    covered: set[int] = set()
    for index, query in enumerate(queries):
        if _comparison_text(query) in discoveries:
            covered.add(index)
            continue
        query_tokens = _search_tokens(query)
        if not query_tokens:
            continue
        overlap = len(query_tokens & text_tokens)
        required = 1 if len(query_tokens) == 1 else min(2, len(query_tokens))
        if overlap >= required:
            covered.add(index)
    return covered


def _record_content_similarity(
    first: ScholarlyRecord,
    second: ScholarlyRecord,
) -> float:
    first_title = _search_tokens(first.title)
    second_title = _search_tokens(second.title)
    title_union = first_title | second_title
    title_jaccard = (
        len(first_title & second_title) / len(title_union) if title_union else 0.0
    )
    title_sequence = SequenceMatcher(
        None,
        _comparison_text(first.title),
        _comparison_text(second.title),
    ).ratio()
    first_abstract = _search_tokens((first.abstract or "")[:1_500])
    second_abstract = _search_tokens((second.abstract or "")[:1_500])
    abstract_union = first_abstract | second_abstract
    abstract_jaccard = (
        len(first_abstract & second_abstract) / len(abstract_union)
        if abstract_union
        else 0.0
    )
    title_similarity = max(title_jaccard, title_sequence)
    return min(1.0, 0.7 * title_similarity + 0.3 * abstract_jaccard)


def _validated_counter_evidence_assessment(
    raw: str,
    required_keys: list[str],
    required_claim_ids: list[str] | None = None,
) -> _CounterEvidenceAssessment:
    assessment = _CounterEvidenceAssessment.model_validate(_json_value(raw, dict))
    if set(assessment.covered_result_keys) != set(required_keys):
        raise ValueError("Counter-evidence analysis did not cover every top result")
    finding_keys = [item.result_key for item in assessment.findings]
    if len(set(finding_keys)) != len(finding_keys):
        raise ValueError("Counter-evidence analysis returned duplicate findings")
    if set(finding_keys) != set(required_keys):
        raise ValueError("Counter-evidence analysis did not assess every top result")
    required_claim_ids = required_claim_ids or []
    if required_claim_ids:
        claim_ids = [item.claim_id for item in assessment.claim_assessments]
        if len(set(claim_ids)) != len(claim_ids):
            raise ValueError("Counter-evidence analysis returned duplicate Gap claims")
        if set(claim_ids) != set(required_claim_ids):
            raise ValueError("Counter-evidence analysis did not assess every Gap claim")
        if any(
            set(item.claim_ids) != set(required_claim_ids)
            for item in assessment.findings
        ):
            raise ValueError(
                "Every counter-evidence finding must assess every Gap claim"
            )
        if any(
            set(item.counter_evidence_result_keys) != set(required_keys)
            for item in assessment.claim_assessments
        ):
            raise ValueError(
                "Every Gap claim must reference every counter-evidence result"
            )
        impacts = {item.outcome for item in assessment.claim_assessments}
    else:
        impacts = {item.impact for item in assessment.findings}
    expected_outcome = _aggregate_counter_outcome(impacts)
    if assessment.outcome is not expected_outcome:
        raise ValueError(
            "Counter-evidence outcome was inconsistent with source findings"
        )
    return assessment


def _aggregate_counter_outcome(
    impacts: set[CounterEvidenceOutcome],
) -> CounterEvidenceOutcome:
    if CounterEvidenceOutcome.GAP_NOT_SUPPORTED in impacts:
        return CounterEvidenceOutcome.GAP_NOT_SUPPORTED
    if CounterEvidenceOutcome.GAP_NARROWED in impacts:
        return CounterEvidenceOutcome.GAP_NARROWED
    if impacts == {CounterEvidenceOutcome.NO_DIRECT_COUNTER_EVIDENCE}:
        return CounterEvidenceOutcome.NO_DIRECT_COUNTER_EVIDENCE
    return CounterEvidenceOutcome.INCONCLUSIVE


def _ground_counter_evidence_assessment(
    assessment: _CounterEvidenceAssessment,
    materials: list[_CounterEvidenceMaterial],
    gap_claims: list[_GapClaim],
) -> tuple[_CounterEvidenceAssessment, list[str]]:
    warnings: list[str] = []
    ungrounded_keys: list[str] = []
    nonrelevant_keys: list[str] = []
    material_by_key = {_record_result_key(item.record): item for item in materials}
    findings_by_key: dict[str, _CounterEvidenceFinding] = {}
    for finding in assessment.findings:
        material = material_by_key.get(finding.result_key)
        if material is None or not material.source_text:
            finding.content_basis = CounterEvidenceContentBasis.METADATA_ONLY
            finding.grounding_status = GroundingStatus.REJECTED
        else:
            finding.content_basis = (
                CounterEvidenceContentBasis.ABSTRACT
                if material.source_kind == "abstract"
                else CounterEvidenceContentBasis.FULL_TEXT
            )
            finding.grounding_status = _grounding_status(
                material.source_text,
                finding.supporting_passage,
            )
            finding.source_location = _passage_location(
                material.source_text,
                finding.supporting_passage,
                material.source_location,
            )
        if finding.grounding_status is not GroundingStatus.GROUNDED:
            finding.impact = CounterEvidenceOutcome.INCONCLUSIVE
            ungrounded_keys.append(finding.result_key)
        if finding.relevance_status is not CounterEvidenceRelevance.RELEVANT:
            finding.impact = CounterEvidenceOutcome.INCONCLUSIVE
            nonrelevant_keys.append(finding.result_key)
        findings_by_key[finding.result_key] = finding

    if ungrounded_keys:
        warnings.append(
            f"{len(ungrounded_keys)} counter-evidence source assessment(s) lacked an "
            "exact grounded passage and were downgraded to inconclusive: "
            f"{', '.join(ungrounded_keys)}."
        )

    if nonrelevant_keys:
        warnings.append(
            f"{len(nonrelevant_keys)} counter-evidence source assessment(s) were not "
            "directly relevant to the Gap claims and were downgraded to "
            f"inconclusive: {', '.join(nonrelevant_keys)}."
        )

    claims_by_id = {item.claim_id: item for item in gap_claims}
    for claim_assessment in assessment.claim_assessments:
        linked_findings = [
            findings_by_key[key]
            for key in claim_assessment.counter_evidence_result_keys
            if key in findings_by_key
        ]
        if not linked_findings or any(
            item.grounding_status is not GroundingStatus.GROUNDED
            or item.relevance_status is not CounterEvidenceRelevance.RELEVANT
            for item in linked_findings
        ):
            claim_assessment.outcome = CounterEvidenceOutcome.INCONCLUSIVE
        original = claims_by_id.get(claim_assessment.claim_id)
        if claim_assessment.outcome is CounterEvidenceOutcome.GAP_NARROWED:
            revised = (claim_assessment.revised_statement or "").strip()
            if (
                original is None
                or not revised
                or _comparison_text(revised) == _comparison_text(original.statement)
            ):
                claim_assessment.outcome = CounterEvidenceOutcome.INCONCLUSIVE
                warnings.append(
                    "A narrowed Gap claim did not provide a material revision; its "
                    "assessment was downgraded to inconclusive."
                )

    impacts = (
        {item.outcome for item in assessment.claim_assessments}
        if assessment.claim_assessments
        else {item.impact for item in assessment.findings}
    )
    assessment.outcome = _aggregate_counter_outcome(impacts)
    return assessment, warnings


def _is_usable_research_document(
    document: DocumentText | None,
    *,
    require_downloadable_full_text: bool,
) -> bool:
    if document is None:
        return False
    if require_downloadable_full_text and document.source_kind == "abstract":
        return False
    return bool(document.text.strip())


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
    output_language: Literal["en", "vi"] = "en",
) -> dict[str, Any]:
    """Map common provider aliases and fill conservative source-backed defaults."""
    fallback = _finding_fallback_text(output_language)
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
        "study_name": _first_text(
            payload,
            "study_name",
            "work_name",
            "tool_name",
            "framework_name",
            "technique_name",
        )
        or _record_research_work_name(record)
        or "Unnamed approach",
        "what_was_done": _first_text(
            payload,
            "what_was_done",
            "finding",
            "summary",
            "work_done",
            "contribution",
        )
        or fallback["what_was_done"].format(title=record.title),
        "method_or_feedback": _first_text(
            payload,
            "method_or_feedback",
            "feedback_type",
            "feedback",
            "method",
            "evaluation_method",
        )
        or fallback["method_or_feedback"],
        "limitation": _first_text(
            payload,
            "limitation",
            "limitations",
            "weakness",
            "gap",
        )
        or fallback["limitation"],
        "relevance": _first_text(payload, "relevance", "why_relevant")
        or fallback["relevance"],
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
                if not re.search(r"[.!?][\"')\]]?$", target) and len(candidate) > len(
                    target
                ):
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
    lines = [
        " ".join(line.split()) for line in source_text.splitlines() if line.strip()
    ]
    for line in lines:
        if _section_heading(line) is None and not _looks_like_page_chrome(line):
            return line[:300].strip()
    return (target or assertion or next(iter(lines), source_text))[:300].strip()


def _source_passage_candidates(source_text: str) -> list[str]:
    candidates: list[str] = []
    block_lines: list[str] = []

    def flush_block() -> None:
        if not block_lines:
            return
        block = "\n".join(block_lines).strip()
        block_lines.clear()
        initial_candidate_count = len(candidates)

        # PDF extractors normally emit one line per visual row. Splitting those
        # rows independently produces fragments that can start or end midway
        # through a sentence (or even a hyphenated word). Build logical source
        # sentences across rows while retaining the exact source substring so
        # the resulting evidence can still be verified verbatim.
        start = 0
        found_sentence_end = False
        for match in re.finditer(r"[.!?](?:[\"')\]]+)?(?=\s|$)", block):
            found_sentence_end = True
            candidate = block[start : match.end()].strip()
            if _is_content_passage(candidate):
                candidates.append(candidate)
            start = match.end()
            while start < len(block) and block[start].isspace():
                start += 1

        remainder = block[start:].strip()
        if _is_content_passage(remainder):
            candidates.append(remainder)

        # Keep a bounded fallback for source text without sentence punctuation.
        # This is deliberately secondary to logical sentences.
        if not found_sentence_end and len(candidates) == initial_candidate_count:
            candidates.extend(
                line for line in block.splitlines() if _is_content_passage(line)
            )

    for raw_line in source_text.splitlines():
        line = raw_line.strip()
        if (
            not line
            or re.fullmatch(r"\[(?:Page \d+|Section)\].*", line)
            or _section_heading(line) is not None
        ):
            flush_block()
            continue
        block_lines.append(line)
    flush_block()
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


def _dict_payload(value: object) -> dict[str, Any]:
    """Narrow an untrusted JSON/context value to a mapping."""
    return value if isinstance(value, dict) else {}


def _gap_citations(citations: object) -> list[dict[str, Any]]:
    if not isinstance(citations, list):
        return []
    compact: list[dict[str, Any]] = []
    for item in citations:
        if not isinstance(item, dict):
            continue
        metadata = _dict_payload(item.get("metadata"))
        compact.append(
            {
                "id": item.get("id"),
                "citation_key": item.get("citation_key"),
                "title": item.get("title"),
                "authors": _string_list(item.get("authors")),
                "year": item.get("year"),
                "venue": item.get("venue"),
                "doi": item.get("doi"),
                "url": item.get("url"),
                "provider_source_id": item.get("provider_source_id"),
                "abstract": str(item.get("abstract") or "")[:1_500],
                "verification_status": item.get("verification_status"),
                "provider": item.get("provider"),
                "retrieval_score": item.get("retrieval_score"),
                "relevance_rank": metadata.get("relevance_rank"),
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
                "source_location": item.get("source_location"),
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
        and _gap_limitation_evidence(item) is not None
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
        "url": record.url,
        "provider": record.provider,
        "provider_source_id": record.provider_source_id,
        "abstract": str(record.abstract or "")[:1_500],
        "retrieval_score": record.metadata.get("retrieval_score"),
        "reranker_score": record.metadata.get("reranker_score"),
        "discovery_queries": record.metadata.get("discovery_queries", []),
        "verification_status": record.metadata.get(
            "counter_verification_status", VerificationStatus.PENDING.value
        ),
        "verification_messages": record.metadata.get(
            "counter_verification_messages", []
        ),
    }


def _counter_evidence_object_keys(narrative: object) -> set[str]:
    if not isinstance(narrative, dict):
        return set()
    candidate = narrative.get("candidate")
    if not isinstance(candidate, dict):
        return set()
    audit = candidate.get("search_audit")
    if not isinstance(audit, dict):
        return set()
    results = audit.get("counter_evidence_results")
    if not isinstance(results, list):
        return set()
    return {
        key
        for item in results
        if isinstance(item, dict)
        and isinstance((key := item.get("source_object_key")), str)
        and key.strip()
    }


def _counter_evidence_results(
    records: list[ScholarlyRecord],
    findings: list[_CounterEvidenceFinding],
    materials: list[_CounterEvidenceMaterial],
) -> list[CounterEvidenceResult]:
    findings_by_key = {item.result_key: item for item in findings}
    materials_by_key = {
        _record_result_key(item.record): item for item in materials
    }
    results: list[CounterEvidenceResult] = []
    for record in records:
        result_key = _record_result_key(record)
        finding = findings_by_key.get(result_key)
        material = materials_by_key.get(result_key)
        verification_messages = list(
            dict.fromkeys(
                _string_list(record.metadata.get("counter_verification_messages"))
            )
        )

        results.append(
            CounterEvidenceResult(
                result_key=result_key,
                title=record.title,
                authors=record.authors,
                year=record.year,
                venue=record.venue,
                doi=record.doi,
                url=record.url,
                provider=record.provider,
                provider_source_id=record.provider_source_id,
                abstract=record.abstract,
                retrieval_score=record.metadata.get("retrieval_score"),
                reranker_score=record.metadata.get("reranker_score"),
                discovery_queries=_string_list(
                    record.metadata.get("discovery_queries")
                ),
                verification_status=record.metadata.get(
                    "counter_verification_status", VerificationStatus.PENDING.value
                ),
                verification_messages=verification_messages,
                content_basis=(
                    finding.content_basis
                    if finding is not None
                    else CounterEvidenceContentBasis.METADATA_ONLY
                ),
                source_object_key=(
                    material.source_object_key if material is not None else None
                ),
                evidence_passage=(
                    finding.supporting_passage or None if finding is not None else None
                ),
                evidence_location=(
                    finding.source_location or None if finding is not None else None
                ),
                grounding_status=(
                    finding.grounding_status
                    if finding is not None
                    else GroundingStatus.PENDING
                ),
                relevance_status=(
                    finding.relevance_status
                    if finding is not None
                    else CounterEvidenceRelevance.PENDING
                ),
                support_status=(
                    finding.support_status
                    if finding is not None
                    else CounterEvidenceSupport.PENDING
                ),
                impact=(
                    finding.impact
                    if finding is not None
                    else CounterEvidenceOutcome.INCONCLUSIVE
                ),
                rationale=(
                    finding.rationale
                    if finding is not None
                    else "This result was not included in the validated content assessment."
                ),
            )
        )
    return results


def _merge_verified_counter_record(
    record: ScholarlyRecord,
    resolved: ScholarlyRecord,
) -> None:
    """Apply provider-resolved metadata while retaining discovery/rerank provenance."""
    original_metadata = dict(record.metadata)
    for field_name in (
        "title",
        "authors",
        "year",
        "venue",
        "doi",
        "url",
        "provider",
        "provider_source_id",
        "abstract",
        "retrieved_at",
    ):
        value = getattr(resolved, field_name)
        if value not in (None, "", []):
            setattr(record, field_name, value)
    record.metadata = {**resolved.metadata, **original_metadata}


def _record_result_key(record: ScholarlyRecord) -> str:
    return utf8_safe_text(
        str(
            normalize_doi(record.doi)
            or record.provider_source_id
            or normalize_url(record.url)
            or citation_key(record.title, record.year)
        )
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
            _as_sentence(answers.limitation),
            _as_sentence(answers.importance),
            _as_sentence(answers.testability),
        )
    )


def _two_sentence_gap_fallback(
    idea: dict[str, Any],
    answers: _GapQuestionAnswers | None,
    claims: list[_GapClaim],
    related_work: list[dict[str, Any]],
) -> str:
    vietnamese = _idea_output_language(idea) == "vi"
    limitations = [claim.statement.strip().rstrip(".!?") for claim in claims]
    if limitations:
        if len(limitations) == 1:
            limitation_text = limitations[0]
        else:
            limitation_text = "; ".join(
                f"({index}) {limitation}"
                for index, limitation in enumerate(limitations, start=1)
            )
        prior_work = answers.prior_work.strip() if answers is not None else ""
        if not prior_work:
            accomplishments = [
                str(item.get("what_was_done") or "").strip()
                for item in related_work
                if str(item.get("what_was_done") or "").strip()
            ]
            prior_work = "; ".join(accomplishments)
        if vietnamese:
            prior_sentence = _as_sentence(
                prior_work or "Các nghiên cứu hiện tại đã đề xuất các phương pháp liên quan"
            )
            return (
                f"{prior_sentence} Chưa rõ liệu một cách tiếp cận có thể khắc phục "
                f"hạn chế “{limitation_text}” trong một đánh giá có kiểm soát hay không."
            )
        prior_sentence = _as_sentence(
            prior_work or "Existing studies have proposed related approaches"
        )
        return (
            f"{prior_sentence} It remains unclear whether an approach can address the "
            f"limitation “{limitation_text}” under a controlled evaluation."
        )
    if vietnamese:
        return (
            "Related Work chưa cung cấp hạn chế nào được hỗ trợ đủ rõ để hình thành "
            "một Gap cụ thể. Cần xem lại nguồn hoặc bổ sung tài liệu trước khi tạo "
            "Contribution Direction."
        )
    return (
        "The Related Work does not yet provide a clearly supported limitation for a "
        "specific Gap. Review or add sources before generating a Contribution Direction."
    )


def _validate_gap_statement_style(statement: str) -> str:
    normalized = " ".join(statement.split()).strip()
    sentences = [
        item.strip()
        for item in re.split(r"(?<=[.!?])\s+", normalized)
        if item.strip()
    ]
    if len(sentences) != 2:
        raise ValueError("Gap statement must contain exactly two sentences")
    uncertainty = sentences[1].casefold()
    if "chưa rõ" not in uncertainty and "unclear" not in uncertainty:
        raise ValueError("Gap statement must express the testable unknown explicitly")
    return normalized


def _gap_claims_from_answers(
    answers: _GapQuestionAnswers,
    source_claims: list[_GapClaim],
) -> list[_GapClaim]:
    """Accept only atomic claims copied from grounded Related Work limitations."""

    if not answers.claims:
        return source_claims
    claims = answers.claims[:5]
    identifiers = [item.claim_id for item in claims]
    if len(set(identifiers)) != len(identifiers):
        raise ValueError("Gap analysis returned duplicate atomic claim identifiers")
    source_by_id = {item.claim_id: item for item in source_claims}
    selected: list[_GapClaim] = []
    for claim in claims:
        source = source_by_id.get(claim.claim_id)
        if (
            source is None
            or claim.kind is not source.kind
            or _comparison_text(claim.statement)
            != _comparison_text(source.statement)
            or set(claim.supporting_citation_keys)
            != set(source.supporting_citation_keys)
        ):
            raise ValueError(
                "Atomic Gap claims must be copied from grounded claim candidates"
            )
        selected.append(source)
    covered = {
        key for claim in selected for key in claim.supporting_citation_keys
    }
    required = {
        key for claim in source_claims for key in claim.supporting_citation_keys
    }
    if covered != required:
        raise ValueError("Atomic Gap claims did not retain every eligible source")
    return selected


def _fallback_gap_claims(
    related_work: list[dict[str, Any]],
    valid_citation_keys: list[str],
) -> tuple[list[_GapClaim], list[str]]:
    claims: list[_GapClaim] = []
    warnings: list[str] = []
    valid = set(valid_citation_keys)
    split_count = 0
    nonmention_count = 0
    narrowed_scope_count = 0
    for item in related_work:
        limitation = str(item.get("limitation") or "").strip()
        key = str(item.get("citation_key") or "").strip()
        if not limitation or key not in valid:
            continue
        claim_evidence = _gap_limitation_evidence(item)
        if claim_evidence is None:
            continue
        fragments = _atomic_limitation_fragments(limitation)
        if len(fragments) > 1:
            split_count += 1
        for fragment in fragments:
            fragment, scope_narrowed = _normalize_gap_claim_statement(
                fragment,
                claim_evidence.passage,
            )
            if scope_narrowed:
                narrowed_scope_count += 1
            if _is_nonmention_inference(fragment):
                nonmention_count += 1
            claims.append(
                _GapClaim(
                    claim_id=f"c{len(claims) + 1}",
                    kind=GapClaimKind.UNRESOLVED_LIMITATION,
                    statement=fragment,
                    supporting_citation_keys=[key],
                    supporting_evidence=[claim_evidence],
                )
            )
            if len(claims) == 5:
                break
        if len(claims) == 5:
            break
    if split_count:
        warnings.append(
            f"Split {split_count} composite Related Work limitation(s) into atomic "
            "claim candidates before semantic validation."
        )
    if nonmention_count:
        warnings.append(
            f"Flagged {nonmention_count} Gap claim candidate(s) that inferred a "
            "missing capability only from source non-mention for source-grounded narrowing."
        )
    if narrowed_scope_count:
        warnings.append(
            f"Narrowed {narrowed_scope_count} Gap claim candidate(s) by removing "
            "clinical scope that was not explicit in the supporting passage."
        )
    return claims, warnings


def _atomic_limitation_fragments(statement: str) -> list[str]:
    """Split only explicit prose boundaries; semantic splitting remains model-checked."""

    fragments = re.split(
        r"\s*(?:;|\n+)\s*|(?<=[.!?])\s+(?=[A-ZÀ-Ỹ])",
        statement.strip(),
    )
    return [fragment.strip() for fragment in fragments if fragment.strip()]


_CLINICAL_SCOPE_TERMS = re.compile(
    r"\b(?:clinical|clinic|healthcare|patient|lâm\s*sàng|y\s*tế|bệnh\s*nhân)\b",
    re.IGNORECASE,
)
_UNANCHORED_CLINICAL_QUALIFIERS = (
    re.compile(r"\s+trong\s+thực\s+tế\s+lâm\s*sàng\b", re.IGNORECASE),
    re.compile(
        r"\s+in\s+(?:real[-\s]world\s+)?clinical\s+(?:practice|settings?)\b",
        re.IGNORECASE,
    ),
)


def _normalize_gap_claim_statement(
    statement: str,
    supporting_passage: str,
) -> tuple[str, bool]:
    """Apply conservative presentation and scope normalization before validation."""

    normalized = statement.strip()
    scope_narrowed = False
    if not _CLINICAL_SCOPE_TERMS.search(supporting_passage):
        for pattern in _UNANCHORED_CLINICAL_QUALIFIERS:
            narrowed = pattern.sub("", normalized)
            if narrowed != normalized:
                normalized = narrowed
                scope_narrowed = True
    normalized = re.sub(r"\s+([,.;:])", r"\1", normalized).strip()
    if normalized:
        normalized = normalized[0].upper() + normalized[1:]
    return normalized, scope_narrowed


_NONMENTION_INFERENCE_PATTERNS = (
    re.compile(
        r"\b(?:does|do|did)\s+not\s+(?:mention|discuss|describe|report)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:not|never)\s+(?:mentioned|discussed|described|reported)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:không|chưa)\s+(?:đề\s*cập|nhắc\s*(?:đến|tới)|mô\s*tả|báo\s*cáo)\b",
        re.IGNORECASE,
    ),
)


def _is_nonmention_inference(statement: str) -> bool:
    return any(pattern.search(statement) for pattern in _NONMENTION_INFERENCE_PATTERNS)


def _claim_statement_precheck(statement: str) -> bool:
    return (
        len(_atomic_limitation_fragments(statement)) == 1
        and not _is_nonmention_inference(statement)
    )


def _strict_claim_support_status(
    claim: _GapClaim,
    assessment: _GapClaimSupportItem,
) -> CounterEvidenceSupport:
    if assessment.support_status is not CounterEvidenceSupport.SUPPORTED:
        return assessment.support_status
    if assessment.atomicity_status == "compound" or assessment.unsupported_fragments:
        return CounterEvidenceSupport.UNSUPPORTED
    if assessment.atomicity_status != "atomic" or not assessment.evidence_span.strip():
        return CounterEvidenceSupport.UNCERTAIN
    normalized_span = " ".join(assessment.evidence_span.casefold().split())
    passage_contains_span = any(
        normalized_span in " ".join(evidence.passage.casefold().split())
        for evidence in claim.supporting_evidence
    )
    if not passage_contains_span:
        return CounterEvidenceSupport.UNCERTAIN
    return CounterEvidenceSupport.SUPPORTED


def _related_work_with_validated_limitations(
    related_work: list[dict[str, Any]],
    claims: list[_GapClaim],
) -> list[dict[str, Any]]:
    """Prevent rejected limitation fragments from leaking into analysis fallbacks."""

    statements_by_key: dict[str, list[str]] = {}
    for claim in claims:
        for key in claim.supporting_citation_keys:
            statements_by_key.setdefault(key, []).append(claim.statement)
    sanitized: list[dict[str, Any]] = []
    for finding in related_work:
        key = str(finding.get("citation_key") or "").strip()
        statements = statements_by_key.get(key, [])
        if not statements:
            continue
        sanitized.append({**finding, "limitation": " ".join(statements)})
    return sanitized


def _gap_limitation_evidence(
    finding: dict[str, Any],
) -> GapClaimEvidence | None:
    key = str(finding.get("citation_key") or "").strip()
    evidence = _dict_payload(finding.get("evidence"))
    limitation_evidence = _dict_payload(evidence.get("limitation"))
    passage = str(
        limitation_evidence.get("passage")
        or finding.get("supporting_passage")
        or ""
    ).strip()
    location = str(
        limitation_evidence.get("location")
        or finding.get("source_location")
        or ""
    ).strip()
    if not key or not passage or not location:
        return None
    return GapClaimEvidence(
        citation_key=key,
        passage=passage,
        location=location,
    )


def _gap_claim_assessments(
    claims: list[_GapClaim],
    assessments: list[_CounterEvidenceClaimAssessment],
) -> list[GapClaimAssessment]:
    assessments_by_id = {item.claim_id: item for item in assessments}
    persisted: list[GapClaimAssessment] = []
    for claim in claims:
        assessment = assessments_by_id.get(claim.claim_id)
        if assessment is None:
            persisted.append(
                GapClaimAssessment(
                    claim_id=claim.claim_id,
                    kind=claim.kind,
                    statement=claim.statement,
                    supporting_citation_keys=claim.supporting_citation_keys,
                    supporting_evidence=claim.supporting_evidence,
                    outcome=CounterEvidenceOutcome.INCONCLUSIVE,
                    assessment=(
                        "Not enough verified counter-evidence was available to determine "
                        "whether this limitation remains unresolved."
                    ),
                )
            )
            continue
        statement = (
            assessment.revised_statement.strip()
            if assessment.outcome is CounterEvidenceOutcome.GAP_NARROWED
            and assessment.revised_statement
            else claim.statement
        )
        persisted.append(
            GapClaimAssessment(
                claim_id=claim.claim_id,
                kind=claim.kind,
                statement=statement,
                supporting_citation_keys=claim.supporting_citation_keys,
                supporting_evidence=claim.supporting_evidence,
                counter_evidence_result_keys=(assessment.counter_evidence_result_keys),
                outcome=assessment.outcome,
                assessment=assessment.assessment,
            )
        )
    return persisted


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
    for key in (
        "discovery_queries",
        "discovery_types",
        "citation_graph_seeds",
        "search_facets",
    ):
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
    upstream = _dict_payload(context.get("upstream"))
    decomposition = _dict_payload(
        upstream.get(WorkflowNode.IDEA_DECOMPOSITION.value)
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

    output_language = _idea_output_language(idea)
    language_name = "Vietnamese" if output_language == "vi" else "English"
    return (
        "The supplied Research Idea's primary language has already been determined. "
        f"Required output language: {language_name} ({output_language}). Do not infer "
        "the output language again from paper titles, abstracts, retrieved source text, "
        "or English search keywords. Treat this as a hard constraint and write every "
        "generated user-facing value in that same language. Keep paper titles, technical "
        "terms, acronyms, and verbatim evidence passages in their original language. "
        "JSON field names must remain exactly as specified. "
    )


_VIETNAMESE_CHARACTERS = frozenset(
    "ăằắặẳẵâầấậẩẫđêềếệểễôồốộổỗơờớợởỡưừứựửữ"
    "àáạảãèéẹẻẽìíịỉĩòóọỏõùúụủũỳýỵỷỹ"
)
_VIETNAMESE_LANGUAGE_WORDS = frozenset(
    {
        "các",
        "cho",
        "chưa",
        "có",
        "của",
        "đánh",
        "để",
        "được",
        "giá",
        "không",
        "một",
        "nghiên",
        "những",
        "phương",
        "quả",
        "sử",
        "thống",
        "trong",
        "từ",
        "và",
        "với",
        # Common unaccented forms from manually entered Research Ideas.
        "cac",
        "chua",
        "co",
        "cua",
        "danh",
        "de",
        "duoc",
        "gia",
        "khong",
        "mot",
        "nghien",
        "nhung",
        "phuong",
        "qua",
        "su",
        "thong",
        "tu",
        "va",
        "voi",
    }
)
_ENGLISH_LANGUAGE_WORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "by",
        "for",
        "from",
        "in",
        "is",
        "of",
        "on",
        "or",
        "that",
        "the",
        "this",
        "to",
        "uses",
        "was",
        "were",
        "with",
    }
)


def _language_tokens(value: str) -> list[str]:
    return re.findall(r"[^\W_]+", value.casefold(), flags=re.UNICODE)


def _idea_output_language(idea: object) -> Literal["en", "vi"]:
    """Determine one stable output language from confirmed Research Idea text only."""

    text = " ".join(_text_values(idea)).casefold()
    tokens = _language_tokens(text)
    vietnamese_word_count = sum(
        token in _VIETNAMESE_LANGUAGE_WORDS for token in tokens
    )
    if any(character in _VIETNAMESE_CHARACTERS for character in text):
        return "vi"
    if vietnamese_word_count >= 2:
        return "vi"
    return "en"


def _text_uses_wrong_language(
    value: str,
    *,
    output_language: Literal["en", "vi"],
) -> bool:
    """Flag clear prose mismatches without rejecting titles or technical phrases."""

    tokens = _language_tokens(value)
    if len(tokens) < 4:
        return False
    folded = value.casefold()
    vietnamese_characters = any(
        character in _VIETNAMESE_CHARACTERS for character in folded
    )
    vietnamese_words = sum(
        token in _VIETNAMESE_LANGUAGE_WORDS for token in tokens
    )
    english_words = sum(token in _ENGLISH_LANGUAGE_WORDS for token in tokens)
    if output_language == "vi":
        return not vietnamese_characters and vietnamese_words < 2 and english_words >= 2
    return vietnamese_characters or (vietnamese_words >= 3 and english_words < 2)


def _finding_language_mismatches(
    payload: dict[str, Any],
    *,
    output_language: Literal["en", "vi"],
) -> list[str]:
    return [
        field
        for field in ("what_was_done", "method_or_feedback", "limitation", "relevance")
        if _text_uses_wrong_language(
            str(payload.get(field) or ""),
            output_language=output_language,
        )
    ]


def _finding_fallback_text(
    output_language: Literal["en", "vi"],
) -> dict[str, str]:
    if output_language == "vi":
        return {
            "what_was_done": "Trình bày nghiên cứu {title}.",
            "method_or_feedback": "Nguồn không nêu rõ phương pháp hoặc hình thức phản hồi.",
            "limitation": "Metadata nguồn chưa đủ để phân tích chi tiết một hạn chế.",
            "relevance": "Được chọn bởi quy trình tìm kiếm học thuật đã cấu hình.",
        }
    return {
        "what_was_done": "Presents {title}.",
        "method_or_feedback": "Not stated in the source metadata.",
        "limitation": "The source metadata is insufficient for a detailed limitation analysis.",
        "relevance": "Included by the configured scholarly search.",
    }


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


def _search_plan_from_payload(
    payload: dict[str, Any],
    *,
    inputs: ResearchInputs,
    idea: dict[str, Any],
    limit: int,
    tool_discovery_keywords: list[str] | None = None,
) -> _SearchPlan:
    raw_facets = payload.get("facets")
    facets: list[_SearchFacet] = []
    if isinstance(raw_facets, list):
        for index, raw_facet in enumerate(raw_facets[:4], start=1):
            if not isinstance(raw_facet, dict):
                continue
            anchors = _clean_keywords(_string_list(raw_facet.get("anchors")))
            raw_id = re.sub(
                r"[^a-z0-9]+",
                "_",
                str(raw_facet.get("id") or f"facet_{index}").casefold(),
            ).strip("_")
            raw_id = _canonical_search_facet_id(raw_id)
            queries = _facet_seed_queries(
                raw_id or f"facet_{index}",
                anchors,
                _normalize_search_queries(
                    _string_list(raw_facet.get("queries")),
                    max_terms=8,
                ),
            ) if anchors else []
            if not anchors or not queries:
                continue
            objective = str(raw_facet.get("objective") or "").strip()
            facets.append(
                _SearchFacet(
                    id=raw_id or f"facet_{index}",
                    objective=objective or f"Find evidence for {anchors[0]}",
                    anchors=anchors,
                    queries=queries,
                    min_results=2,
                    tool_names=(
                        _implementation_tool_names(anchors)
                        if raw_id == _IMPLEMENTATION_TOOLS_FACET
                        else []
                    ),
                )
            )
    if facets:
        if len({facet.id for facet in facets}) != len(facets):
            raise ValueError("SearchPlan returned duplicate facet identifiers")
        confirmed_keywords: list[str] = []
        for keyword in _clean_keywords(inputs.keywords):
            try:
                confirmed_keywords.extend(
                    _normalize_search_queries([keyword], max_terms=8)
                )
            except ValueError:
                continue
        uncovered = [
            keyword
            for keyword in confirmed_keywords
            if not any(
                _search_tokens(keyword) & _search_tokens(search_term)
                for facet in facets
                for search_term in [*facet.anchors, *facet.queries]
            )
        ]
        if uncovered:
            raise ValueError(
                "SearchPlan did not cover confirmed Research Input(s): "
                + ", ".join(uncovered)
            )
        if len(confirmed_keywords) >= 4 and len(facets) < 3:
            raise ValueError("SearchPlan collapsed a multi-dimensional Idea too aggressively")
        return _bounded_search_plan(_SearchPlan(facets=facets), limit=limit)

    legacy_queries = _string_list(payload.get("queries"))
    if not legacy_queries:
        raise ValueError("The query model returned neither facets nor queries")
    normalized = _normalize_search_queries(legacy_queries, max_terms=8)
    if not normalized:
        raise ValueError("All generated queries exceeded the provider query budget")
    return _fallback_search_plan(
        inputs,
        idea,
        limit=limit,
        model_queries=normalized,
        tool_discovery_keywords=tool_discovery_keywords,
    )


def _discovery_expansion_from_payload(
    payload: dict[str, Any],
    *,
    inputs: ResearchInputs,
    idea: dict[str, Any],
) -> _DiscoveryExpansion:
    tool_keywords, supporting_keywords = _discovery_keyword_partition(
        payload,
        inputs=inputs,
    )
    model_tools = _clean_discovery_leads(
        _string_list(payload.get("tools_and_frameworks")),
        max_items=None,
        max_chars=80,
    )
    model_tools = _filter_known_tools_by_discovery_keywords(
        model_tools,
        tool_keywords,
    )
    known_tools = _known_research_tools(tool_keywords)
    techniques = _clean_discovery_leads(
        _string_list(payload.get("techniques")),
        max_items=8,
        max_chars=100,
    )
    work_titles = _clean_discovery_leads(
        _string_list(payload.get("candidate_work_titles")),
        max_items=6,
        max_chars=200,
        min_words=3,
    )
    aliases = _clean_discovery_leads(
        _string_list(payload.get("aliases")),
        max_items=8,
        max_chars=100,
    )
    expansion = _DiscoveryExpansion(
        tool_discovery_keywords=tool_keywords,
        supporting_context_keywords=supporting_keywords,
        tools_and_frameworks=list(dict.fromkeys([*model_tools, *known_tools])),
        techniques=techniques,
        candidate_work_titles=work_titles,
        aliases=aliases,
    )
    if not any(expansion.model_dump().values()):
        raise ValueError("The discovery model returned no usable research leads")
    return expansion


def _fallback_discovery_expansion(
    inputs: ResearchInputs,
    idea: dict[str, Any],
) -> _DiscoveryExpansion:
    concepts = [*inputs.keywords, *_idea_search_concepts(idea)]
    tool_keywords, supporting_keywords = _discovery_keyword_partition(
        {},
        inputs=inputs,
    )
    techniques: list[str] = []
    for concept in concepts:
        try:
            techniques.extend(_normalize_search_queries([concept], max_terms=8))
        except ValueError:
            continue
    if not techniques:
        techniques = _english_query_fallback(inputs, idea)
    return _DiscoveryExpansion(
        tool_discovery_keywords=tool_keywords,
        supporting_context_keywords=supporting_keywords,
        tools_and_frameworks=_known_research_tools(tool_keywords),
        techniques=list(dict.fromkeys(techniques))[:8],
    )


def _discovery_keyword_partition(
    payload: dict[str, Any],
    *,
    inputs: ResearchInputs,
) -> tuple[list[str], list[str]]:
    """Separate tool-generating mechanisms from context used only for reranking."""

    confirmed = _clean_keywords(inputs.keywords)
    confirmed_by_key = {keyword.casefold(): keyword for keyword in confirmed}
    selected = _clean_discovery_leads(
        _string_list(payload.get("tool_discovery_keywords")),
        max_items=None,
        max_chars=100,
    )
    tool_keywords = list(
        dict.fromkeys(
            confirmed_by_key[keyword.casefold()]
            for keyword in selected
            if keyword.casefold() in confirmed_by_key
        )
    )
    if not tool_keywords:
        # Conservative fallback: only a keyword that activates a known tool family
        # may generate tools. Task/domain and outcome keywords stay ranking-only.
        tool_keywords = [
            keyword for keyword in confirmed if _known_research_tools([keyword])
        ]
    tool_keys = {keyword.casefold() for keyword in tool_keywords}
    supporting_keywords = [
        keyword for keyword in confirmed if keyword.casefold() not in tool_keys
    ]
    return tool_keywords, supporting_keywords


def _filter_known_tools_by_discovery_keywords(
    tools: list[str],
    tool_keywords: list[str],
) -> list[str]:
    """Reject known-family tools when only a supporting keyword activates them."""

    allowed_known = {
        tool.casefold() for tool in _known_research_tools(tool_keywords)
    }
    all_known = {
        tool.casefold()
        for _, names in _KNOWN_RESEARCH_TOOLS
        for tool in names
    }
    return [
        tool
        for tool in tools
        if tool.casefold() not in all_known or tool.casefold() in allowed_known
    ]


def _clean_discovery_leads(
    values: list[str],
    *,
    max_items: int | None,
    max_chars: int,
    min_words: int = 1,
) -> list[str]:
    cleaned: list[str] = []
    seen: set[str] = set()
    for value in values:
        lead = re.sub(r"\s+", " ", value.strip(" \t\r\n`'\""))
        folded = lead.casefold()
        words = re.findall(r"[^\W_]+", lead, flags=re.UNICODE)
        if (
            not lead
            or folded in seen
            or len(lead) > max_chars
            or len(words) < min_words
        ):
            continue
        cleaned.append(lead)
        seen.add(folded)
        if max_items is not None and len(cleaned) >= max_items:
            break
    return cleaned


def _enrich_search_plan_with_discovery(
    plan: _SearchPlan,
    discovery: _DiscoveryExpansion,
) -> _SearchPlan:
    tools = discovery.tools_and_frameworks
    work_titles = discovery.candidate_work_titles
    if not tools:
        return plan

    facets = list(plan.facets)
    implementation = next(
        (facet for facet in facets if facet.id == _IMPLEMENTATION_TOOLS_FACET),
        None,
    )
    if implementation is None:
        if len(facets) >= 4:
            replace_index = next(
                (
                    index
                    for index, facet in enumerate(facets)
                    if facet.id == "optimization_method"
                ),
                len(facets) - 1,
            )
            facets.pop(replace_index)
        seed_anchor = next(
            iter(discovery.techniques or discovery.aliases or tools or work_titles)
        )
        implementation = _SearchFacet(
            id=_IMPLEMENTATION_TOOLS_FACET,
            objective=(
                "Verify named tools, frameworks, techniques, and candidate scholarly works"
            ),
            anchors=[seed_anchor],
            queries=[_quoted_search_lead(seed_anchor)],
            min_results=2,
        )
        facets.insert(0, implementation)

    implementation.tool_names = list(
        dict.fromkeys([*tools, *implementation.tool_names])
    )
    implementation.candidate_work_titles = list(
        dict.fromkeys([*work_titles, *implementation.candidate_work_titles])
    )
    implementation.anchors = list(
        dict.fromkeys(
            [
                *implementation.anchors,
                *implementation.tool_names,
                *implementation.candidate_work_titles,
            ]
        )
    )
    # Provider calls are dynamic and strictly one-per-tool. Candidate work titles,
    # techniques, aliases, and conceptual facets remain in the plan as evaluation
    # context, but they must not create additional provider queries.
    implementation.queries = list(
        dict.fromkeys(_quoted_search_lead(tool) for tool in tools)
    )
    for facet in facets:
        if facet is not implementation:
            facet.queries = []
    return _SearchPlan(facets=facets)


def _quoted_search_lead(value: str) -> str:
    lead = re.sub(r'["\r\n]+', " ", value)
    lead = re.sub(r"\s+", " ", lead).strip()
    return f'"{lead[:200]}"'


def _canonical_search_facet_id(facet_id: str) -> str:
    if any(
        token in facet_id
        for token in ("tool", "framework", "implementation", "technique")
    ):
        return _IMPLEMENTATION_TOOLS_FACET
    return facet_id


def _known_research_tools(concepts: list[str]) -> list[str]:
    concept_tokens = _search_tokens(" ".join(concepts))
    tools: list[str] = []
    for triggers, names in _KNOWN_RESEARCH_TOOLS:
        if concept_tokens & triggers:
            tools.extend(names)
    return list(dict.fromkeys(tools))


def _implementation_tool_names(anchors: list[str]) -> list[str]:
    known_by_name = {
        name.casefold(): name
        for _, names in _KNOWN_RESEARCH_TOOLS
        for name in names
    }
    matched: list[str] = []
    for anchor in anchors:
        canonical = known_by_name.get(anchor.casefold())
        candidate = canonical or anchor.strip()
        words = re.findall(r"[^\W_]+", candidate, flags=re.UNICODE)
        looks_named = (
            1 <= len(words) <= 3
            and len(candidate) <= 40
            and any(character.isupper() for character in candidate)
            and candidate.casefold()
            not in {"ai", "llm", "nlp", "rag", "api", "framework", "tool"}
        )
        if (canonical or looks_named) and candidate not in matched:
            matched.append(candidate)
    return matched


def _tool_name_appears(tool_name: str, text: str) -> bool:
    return bool(
        re.search(
            rf"(?<!\w){re.escape(tool_name)}(?!\w)",
            text,
            flags=re.IGNORECASE,
        )
    )


def _fallback_search_plan(
    inputs: ResearchInputs,
    idea: dict[str, Any],
    *,
    limit: int,
    model_queries: list[str] | None = None,
    tool_discovery_keywords: list[str] | None = None,
) -> _SearchPlan:
    raw_concepts = _clean_keywords(
        [*inputs.keywords, *_idea_search_concepts(idea)]
    )
    concepts: list[str] = []
    for concept in raw_concepts:
        try:
            concepts.extend(_normalize_search_queries([concept], max_terms=8))
        except ValueError:
            continue
    if not concepts:
        concepts = _normalize_search_queries(
            model_queries or _english_query_fallback(inputs, idea),
            max_terms=8,
        )

    buckets: dict[str, list[str]] = {
        "optimization_method": [],
        "evaluation_verification": [],
        "task_domain": [],
        "failure_mitigation": [],
    }
    patterns = {
        "optimization_method": {
            "feedback",
            "gradient",
            "iterative",
            "optimization",
            "optimize",
            "prompt",
            "refinement",
        },
        "evaluation_verification": {
            "critic",
            "evaluation",
            "ground",
            "judge",
            "score",
            "truth",
            "verification",
        },
        "task_domain": {
            "biomedical",
            "dataset",
            "extraction",
            "information",
            "relation",
            "scientific",
        },
        "failure_mitigation": {
            "error",
            "fabrication",
            "factuality",
            "hallucination",
            "mitigation",
            "unsupported",
        },
    }
    unassigned: list[str] = []
    for concept in concepts:
        tokens = _search_tokens(concept)
        best = max(patterns, key=lambda key: len(tokens & patterns[key]))
        if tokens & patterns[best]:
            buckets[best].append(concept)
        else:
            unassigned.append(concept)

    active = {key: values for key, values in buckets.items() if values}
    for concept in unassigned:
        if len(active) < 4:
            active[f"topic_{len(active) + 1}"] = [concept]
        else:
            min(active.values(), key=len).append(concept)
    if not active:
        active = {"core_topic": concepts[:2]}

    known_tools = _known_research_tools(
        tool_discovery_keywords
        if tool_discovery_keywords is not None
        else concepts
    )
    tool_source_facet = next(
        (
            facet_id
            for facet_id in ("optimization_method", "evaluation_verification")
            if active.get(facet_id)
        ),
        None,
    )
    if known_tools and tool_source_facet:
        method_anchors = active[tool_source_facet]
        if len(active) >= 4:
            active.pop(tool_source_facet)
        active = {
            _IMPLEMENTATION_TOOLS_FACET: [*method_anchors, *known_tools],
            **active,
        }

    objectives = {
        _IMPLEMENTATION_TOOLS_FACET: (
            "Find papers that present, evaluate, compare, or apply named implementations"
        ),
        "optimization_method": "Find automatic and iterative optimization methods",
        "evaluation_verification": "Find evaluator and ground-truth verification methods",
        "task_domain": "Find methods and benchmarks in the target task or domain",
        "failure_mitigation": "Find evidence about the target failure and its mitigation",
    }
    normalized_model = _normalize_search_queries(model_queries or [], max_terms=8)
    facets: list[_SearchFacet] = []
    for facet_id, anchors in list(active.items())[:4]:
        matched_model_queries = [
            query
            for query in normalized_model
            if any(_search_tokens(anchor) & _search_tokens(query) for anchor in anchors)
        ]
        queries = _facet_seed_queries(
            facet_id,
            anchors,
            matched_model_queries,
        )
        facets.append(
            _SearchFacet(
                id=facet_id,
                objective=objectives.get(
                    facet_id,
                    f"Find direct scholarly evidence for {anchors[0]}",
                ),
                anchors=anchors,
                queries=queries,
                min_results=2,
                tool_names=(
                    _implementation_tool_names(anchors)
                    if facet_id == _IMPLEMENTATION_TOOLS_FACET
                    else []
                ),
            )
        )
    return _bounded_search_plan(_SearchPlan(facets=facets), limit=limit)


def _facet_seed_queries(
    facet_id: str,
    anchors: list[str],
    model_queries: list[str],
) -> list[str]:
    primary = _query_anchor(anchors[0])
    if facet_id == _IMPLEMENTATION_TOOLS_FACET:
        tool_names = _implementation_tool_names(anchors)
        # Exact implementation names maximize recall for seminal papers whose title
        # and abstract may never use the broader concept label (for example DSPy's
        # paper describes self-improving pipelines, not "prompt optimization").
        tool_queries = [f'"{tool_name}"' for tool_name in tool_names[:2]]
        queries = _normalize_search_queries(
            [*tool_queries, *model_queries],
            max_terms=8,
        )
        return queries or [f'"{primary}" AND (framework OR implementation)']
    partner = _query_anchor(anchors[1]) if len(anchors) > 1 else ""
    direct = f'"{primary}"' + (f' AND "{partner}"' if partner else "")
    branch_terms = {
        "optimization_method": "textual feedback method",
        "evaluation_verification": "benchmark reliability",
        "task_domain": "methods benchmark",
        "failure_mitigation": "mitigation evaluation",
    }.get(facet_id, "survey review")
    generated = [direct, f'"{primary}" AND ({branch_terms.replace(" ", " OR ")})']
    queries = _normalize_search_queries(
        [generated[0], *model_queries, generated[1]],
        max_terms=8,
    )
    return queries or ["scholarly evidence review"]


def _bounded_search_plan(plan: _SearchPlan, *, limit: int) -> _SearchPlan:
    budget = max(limit, 1)
    selected: dict[str, list[str]] = {facet.id: [] for facet in plan.facets}
    seen: set[str] = set()
    max_depth = max(len(facet.queries) for facet in plan.facets)
    for depth in range(max_depth):
        for facet in plan.facets:
            facet_limit = (
                max(
                    4,
                    len(facet.tool_names) * 2
                    + len(facet.candidate_work_titles),
                )
                if facet.id == _IMPLEMENTATION_TOOLS_FACET
                else 2
            )
            if len(selected[facet.id]) >= facet_limit:
                continue
            if depth >= len(facet.queries):
                continue
            query = facet.queries[depth]
            folded = query.casefold()
            if folded in seen:
                continue
            selected[facet.id].append(query)
            seen.add(folded)
            if len(seen) >= budget:
                break
        if len(seen) >= budget:
            break
    facets = [
        facet.model_copy(update={"queries": selected[facet.id]})
        for facet in plan.facets
        if selected[facet.id]
    ]
    return _SearchPlan(facets=facets)


def _tag_search_facets(records: list[ScholarlyRecord], plan: _SearchPlan) -> None:
    facet_by_query = {
        query.casefold(): facet.id
        for facet in plan.facets
        for query in facet.queries
    }
    for record in records:
        matched = set(_string_list(record.metadata.get("search_facets")))
        record_text = f"{record.title} {record.abstract or ''}"
        text_tokens = _search_tokens(record_text)
        tool_names = list(
            dict.fromkeys(
                tool_name
                for facet in plan.facets
                if facet.id == _IMPLEMENTATION_TOOLS_FACET
                for tool_name in (
                    facet.tool_names or _implementation_tool_names(facet.anchors)
                )
            )
        )
        tool_mentions = [
            tool_name
            for tool_name in tool_names
            if _tool_name_appears(tool_name, record_text)
        ]
        merged_tool_mentions = list(
            dict.fromkeys(
                [
                    *_string_list(
                        record.metadata.get("implementation_tool_mentions")
                    ),
                    *tool_mentions,
                ]
            )
        )
        discovery_queries = {
            query.casefold()
            for query in _string_list(record.metadata.get("discovery_queries"))
        }
        queried_tool_names = [
            tool_name
            for tool_name in tool_names
            if _quoted_search_lead(tool_name).casefold() in discovery_queries
        ]
        record.metadata["discovery_tool_names"] = tool_names
        record.metadata["queried_tool_names"] = queried_tool_names
        record.metadata["implementation_tool_mentions"] = merged_tool_mentions
        record.metadata["tool_specific_evidence"] = bool(merged_tool_mentions)
        for query in _string_list(record.metadata.get("discovery_queries")):
            facet_id = facet_by_query.get(query.casefold())
            if facet_id:
                matched.add(facet_id)
        for facet in plan.facets:
            anchors = (
                facet.tool_names or _implementation_tool_names(facet.anchors)
                if facet.id == _IMPLEMENTATION_TOOLS_FACET
                else facet.anchors
            )
            if any(
                _matched_concept_indexes([_search_tokens(anchor)], text_tokens)
                for anchor in anchors
            ):
                matched.add(facet.id)
        record.metadata["search_facets"] = sorted(matched)


def _search_facet_coverage(
    records: list[ScholarlyRecord],
    plan: _SearchPlan,
) -> dict[str, int]:
    return {
        facet.id: sum(
            facet.id in _string_list(record.metadata.get("search_facets"))
            and (
                facet.id != _IMPLEMENTATION_TOOLS_FACET
                or bool(_record_candidate_tool_names(record))
            )
            for record in records
        )
        for facet in plan.facets
    }


def _missing_search_facets(
    records: list[ScholarlyRecord],
    plan: _SearchPlan,
) -> list[_SearchFacet]:
    coverage = _search_facet_coverage(records, plan)
    return [
        facet
        for facet in plan.facets
        if coverage.get(facet.id, 0) < facet.min_results
    ]


def _facet_follow_up_queries(
    facets: list[_SearchFacet],
    *,
    existing_queries: list[str],
) -> dict[str, list[str]]:
    seen = {query.casefold() for query in existing_queries}
    result: dict[str, list[str]] = {}
    for facet in facets:
        anchor = _query_anchor(facet.anchors[0])
        if facet.id == _IMPLEMENTATION_TOOLS_FACET:
            tool_names = facet.tool_names or _implementation_tool_names(facet.anchors)
            candidates = _normalize_search_queries(
                [f'"{tool_name}"' for tool_name in tool_names[2:]]
                or [
                    (
                        f'"{tool_names[0]}" AND (comparison OR benchmark)'
                        if tool_names
                        else f'"{anchor}" AND (implementation OR framework)'
                    )
                ],
                max_terms=8,
            )
        else:
            candidates = _normalize_search_queries(
                [
                    f'"{anchor}" AND (framework OR method)',
                    f'"{anchor}" AND (comparison OR benchmark)',
                    f'"{anchor}" AND (limitations OR evidence)',
                ],
                max_terms=8,
            )
        query = next((item for item in candidates if item.casefold() not in seen), None)
        if query is None:
            continue
        result[facet.id] = [query]
        seen.add(query.casefold())
    return result


def _extend_search_plan(
    plan: _SearchPlan,
    queries_by_facet: dict[str, list[str]],
) -> None:
    for facet in plan.facets:
        facet.queries = list(
            dict.fromkeys([*facet.queries, *queries_by_facet.get(facet.id, [])])
        )


def _facet_balanced_records(
    records: list[ScholarlyRecord],
    plan: _SearchPlan,
) -> list[ScholarlyRecord]:
    remaining = list(records)
    selected: list[ScholarlyRecord] = []
    selected_counts = {facet.id: 0 for facet in plan.facets}
    while remaining:
        progressed = False
        for facet in plan.facets:
            if selected_counts[facet.id] >= facet.min_results:
                continue
            position = next(
                (
                    index
                    for index, record in enumerate(remaining)
                    if facet.id
                    in _string_list(record.metadata.get("search_facets"))
                    and (
                        facet.id != _IMPLEMENTATION_TOOLS_FACET
                        or bool(_record_candidate_tool_names(record))
                    )
                ),
                None,
            )
            if position is None:
                continue
            record = remaining.pop(position)
            selected.append(record)
            for matched_id in _string_list(record.metadata.get("search_facets")):
                if matched_id in selected_counts:
                    selected_counts[matched_id] += 1
            record.metadata["facet_selection"] = "coverage_quota"
            progressed = True
        if not progressed:
            break
    return [*selected, *remaining]


def _diversify_records_by_research_work(
    records: list[ScholarlyRecord],
    *,
    tool_names: list[str] | None = None,
    tool_relevance_keywords: list[str] | None = None,
) -> list[ScholarlyRecord]:
    """Keep at most one article per work and reserve the best hit per named tool."""

    selected: list[ScholarlyRecord] = []
    selected_ids: set[int] = set()
    seen_work_keys: set[str] = set()
    seen_tool_keys: set[str] = set()

    def add(record: ScholarlyRecord, *, tool_quota: str | None = None) -> bool:
        mention_keys = {
            mention.casefold()
            for mention in _string_list(
                record.metadata.get("implementation_tool_mentions")
            )
        }
        work_name = tool_quota or _record_research_work_name(record)
        key = _comparison_text(work_name) if work_name else None
        quota_key = tool_quota.casefold() if tool_quota else None
        if (
            id(record) in selected_ids
            or (key and key in seen_work_keys)
            or (quota_key and quota_key in seen_tool_keys)
            or bool(mention_keys & seen_tool_keys)
        ):
            record.metadata["work_selection"] = "same_work_excluded"
            return False
        if work_name and key:
            record.metadata["research_work_name"] = work_name
            record.metadata["research_work_key"] = key
            seen_work_keys.add(key)
        record.metadata["work_selection"] = (
            "named_tool_quota" if tool_quota else "unique_work_priority"
        )
        if tool_quota:
            record.metadata["tool_quota_name"] = tool_quota
            record.metadata["selected_tool_name"] = tool_quota
            seen_tool_keys.add(tool_quota.casefold())
        else:
            seen_tool_keys.update(mention_keys)
        selected.append(record)
        selected_ids.add(id(record))
        return True

    # Records are already semantically reranked. The explicit rank key protects
    # per-tool choice from the later facet-balancing reorder.
    for tool_name in tool_names or []:
        candidates = [
            record
            for record in records
            if any(
                mention.casefold() == tool_name.casefold()
                for mention in _record_candidate_tool_names(record)
            )
        ]
        for candidate in sorted(
            candidates,
            key=lambda record: _tool_candidate_rank(
                record,
                tool_name,
                relevance_keywords=tool_relevance_keywords,
            ),
        ):
            if add(candidate, tool_quota=tool_name):
                break

    if tool_names:
        for record in records:
            if id(record) not in selected_ids and any(
                mention.casefold() in seen_tool_keys
                for mention in _string_list(
                    record.metadata.get("implementation_tool_mentions")
                )
            ):
                record.metadata["work_selection"] = "same_work_excluded"
        return selected

    for record in records:
        add(record)
    return selected


def _record_semantic_rank(record: ScholarlyRecord) -> tuple[int, int, int]:
    reranker_rank = record.metadata.get("reranker_rank")
    heuristic_rank = record.metadata.get("heuristic_rank")
    return (
        int(reranker_rank) if isinstance(reranker_rank, int) else 1_000_000,
        int(heuristic_rank) if isinstance(heuristic_rank, int) else 1_000_000,
        int(record.metadata.get("portfolio_rank") or 1_000_000),
    )


def _record_candidate_tool_names(record: ScholarlyRecord) -> list[str]:
    return list(
        dict.fromkeys(
            [
                *_string_list(record.metadata.get("implementation_tool_mentions")),
                *_string_list(record.metadata.get("queried_tool_names")),
            ]
        )
    )


def _tool_candidate_rank(
    record: ScholarlyRecord,
    tool_name: str,
    *,
    relevance_keywords: list[str] | None = None,
) -> tuple[int, int, int, int, int, int]:
    explicit_mentions = _string_list(
        record.metadata.get("implementation_tool_mentions")
    )
    mention_count = len(explicit_mentions)
    keyword_groups = _concept_groups(_clean_keywords(relevance_keywords or []))
    text_tokens = _search_tokens(f"{record.title} {record.abstract or ''}")
    matched_keyword_indexes = _matched_concept_indexes(
        keyword_groups,
        text_tokens,
    )
    record.metadata["matched_tool_relevance_keyword_indexes"] = sorted(
        matched_keyword_indexes
    )
    record.metadata["tool_relevance_keyword_match_count"] = len(
        matched_keyword_indexes
    )
    has_explicit_mention = any(
        mention.casefold() == tool_name.casefold() for mention in explicit_mentions
    )
    return (
        0 if has_explicit_mention else 1,
        -len(matched_keyword_indexes),
        mention_count or 1_000_000,
        *_record_semantic_rank(record),
    )


def _selected_tool_coverage(
    prepared_records: list[tuple[ScholarlyRecord, Citation, DocumentText, list[str]]],
    tool_names: list[str],
) -> list[dict[str, Any]]:
    coverage: list[dict[str, Any]] = []
    for tool_name in tool_names:
        match = next(
            (
                (record, citation)
                for record, citation, _, _ in prepared_records
                if str(record.metadata.get("selected_tool_name") or "").casefold()
                == tool_name.casefold()
            ),
            None,
        )
        coverage.append(
            {
                "tool": tool_name,
                "status": "matched_citation" if match else "not_found",
                "citation_key": match[1].citation_key if match else None,
                "article_title": match[0].title if match else None,
            }
        )
    return coverage


def _record_research_work_name(record: ScholarlyRecord) -> str | None:
    mentions = _string_list(record.metadata.get("implementation_tool_mentions"))
    if mentions:
        folded_title = record.title.casefold()
        return min(
            mentions,
            key=lambda name: (
                folded_title.find(name.casefold())
                if name.casefold() in folded_title
                else len(folded_title) + mentions.index(name)
            ),
        )
    explicit = str(record.metadata.get("research_work_name") or "").strip()
    if explicit:
        return explicit
    prefix, separator, _ = record.title.partition(":")
    prefix_words = re.findall(r"[^\W_]+", prefix, flags=re.UNICODE)
    if separator and 1 <= len(prefix_words) <= 6 and len(prefix) <= 60:
        return prefix.strip()
    return None


def _normalized_study_name(candidate: str, record: ScholarlyRecord) -> str:
    """Prefer a canonical method/tool identifier and reject article-title labels."""

    work_name = _record_research_work_name(record)
    if _string_list(record.metadata.get("implementation_tool_mentions")) and work_name:
        return work_name
    cleaned = re.sub(r"\s+", " ", candidate).strip(" \t\r\n`'\".,:;")
    words = re.findall(r"[^\W_]+", cleaned, flags=re.UNICODE)
    if (
        cleaned
        and _comparison_text(cleaned) != _comparison_text(record.title)
        and len(words) <= 6
        and len(cleaned) <= 60
    ):
        return cleaned
    identifier = _record_method_identifier(record)
    return identifier or work_name or "Unnamed approach"


def _record_method_identifier(record: ScholarlyRecord) -> str | None:
    ignored = {
        "AI",
        "API",
        "BERT",
        "GPT",
        "LLM",
        "LLMS",
        "NER",
        "NLP",
        "PDF",
        "RAG",
        "RE",
    }
    text = f"{record.title} {record.abstract or ''}"
    identifiers = re.findall(r"\b[A-Z][A-Z0-9-]{2,}\b", text)
    return next((item for item in identifiers if item.upper() not in ignored), None)


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
    exact_method_queries: list[str] | None = None,
    limit: int | None = None,
) -> list[str]:
    normalized = _normalize_search_queries(model_queries)
    anchors = _normalize_search_queries(related_work_queries)
    exact = _normalize_search_queries(exact_method_queries or [])
    base = next(iter(exact or normalized or anchors), "scholarly evidence review")
    anchor = _query_anchor(base)
    branches = (
        f'"{anchor}" AND (survey OR review)',
        f'"{anchor}" AND (benchmark OR replication)',
        f'"{anchor}" AND (limitation OR conflicting)',
    )
    prefix = [*exact, *normalized]
    candidates = _normalize_search_queries([*(prefix or [base]), *branches])
    return _limit_query_families(
        candidates,
        limit=limit,
        family_order=("evaluation", "limitation", "survey", "core"),
        prefix_count=len(prefix or [base]),
    )


def _citation_method_queries(
    citations: list[dict[str, Any]],
    *,
    limit: int = 2,
) -> list[str]:
    """Extract method identifiers only from confirmed scholarly Citation titles."""

    ignored = {
        "AI",
        "CHAIN-OF-THOUGHT",
        "COT",
        "LLM",
        "LLMS",
        "NLP",
        "RAG",
    }
    queries: list[str] = []
    seen: set[str] = set()
    for citation in citations:
        title = str(citation.get("title") or "")
        identifiers = re.findall(
            r"\b(?:[A-Z]{3,}(?:-[A-Z0-9]+)*|"
            r"[A-Z][A-Za-z0-9]+(?:-[A-Za-z0-9]+)+|"
            r"[A-Z][a-z0-9]+(?:[A-Z][A-Za-z0-9]+)+)\b",
            title,
        )
        for identifier in identifiers:
            folded = identifier.casefold()
            if (
                identifier.upper() in ignored
                or "_" in identifier
                or folded in seen
            ):
                continue
            queries.append(f'"{identifier}"')
            seen.add(folded)
            if len(queries) >= limit:
                return queries
    return queries


def _citation_seed_records(
    citations: list[dict[str, Any]],
) -> list[ScholarlyRecord]:
    seeds: list[ScholarlyRecord] = []
    for citation in citations:
        title = str(citation.get("title") or "").strip()
        if not title:
            continue
        metadata = citation.get("metadata")
        seeds.append(
            ScholarlyRecord(
                title=title,
                authors=_string_list(citation.get("authors")),
                year=(
                    int(citation["year"])
                    if isinstance(citation.get("year"), int)
                    else None
                ),
                venue=str(citation.get("venue") or "") or None,
                doi=str(citation.get("doi") or "") or None,
                url=str(citation.get("url") or "") or None,
                provider=str(citation.get("provider") or "") or None,
                provider_source_id=(
                    str(citation.get("provider_source_id") or "") or None
                ),
                abstract=str(citation.get("abstract") or "") or None,
                metadata=dict(metadata) if isinstance(metadata, dict) else {},
            )
        )
    return seeds


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
    candidates = _clean_keywords([*inputs.keywords, *_idea_search_concepts(idea)])
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


_QUERY_FAMILY_TOKENS = {
    "approach",
    "benchmark",
    "challenge",
    "comparison",
    "competing",
    "conflicting",
    "equivalent",
    "evaluation",
    "finding",
    "limitation",
    "method",
    "replication",
    "review",
    "study",
    "survey",
}

_AMBIGUOUS_QUERY_TOKENS = {
    "cot",
    "max",
    "min",
    "retry",
}


def _domain_query_concepts(queries: list[str]) -> list[str]:
    concepts: list[str] = []
    for concept in _query_concepts(queries):
        domain_tokens = [
            token
            for raw_token in re.findall(
                r"[^\W_]+", concept.casefold(), flags=re.UNICODE
            )
            if (token := _search_token(raw_token)) not in _KEYWORD_STOPWORDS
            and token not in _QUERY_FAMILY_TOKENS
            and token not in _AMBIGUOUS_QUERY_TOKENS
        ]
        if domain_tokens:
            concepts.append(" ".join(domain_tokens))
    return concepts


def _matching_record_queries(
    record: ScholarlyRecord,
    queries: list[str],
) -> list[str]:
    text_tokens = _search_tokens(f"{record.title} {record.abstract or ''}")
    matches: list[str] = []
    for query in queries:
        groups = _concept_groups(_domain_query_concepts([query]))
        if groups and _matched_concept_indexes(groups, text_tokens):
            matches.append(query)
    return matches


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
    require_domain_match: bool = False,
) -> tuple[list[ScholarlyRecord], int]:
    """Rank by concept coverage and reject idea-mismatched provider results."""
    query_concepts = _domain_query_concepts(queries or [])
    idea_concepts = _clean_keywords(_idea_search_concepts(idea))
    input_concepts = _clean_keywords(inputs.keywords)
    idea_groups = _concept_groups(idea_concepts)
    input_groups = _concept_groups(input_concepts)
    query_groups = _concept_groups(query_concepts)
    all_groups = _concept_groups(
        [*idea_concepts, *input_concepts, *query_concepts]
    )
    scored: list[tuple[tuple[float, ...], int, ScholarlyRecord]] = []
    discarded = 0
    for index, record in enumerate(records):
        title_tokens = _search_tokens(record.title)
        text_tokens = title_tokens | _search_tokens(record.abstract or "")
        matched_idea = _matched_concept_indexes(idea_groups, text_tokens)
        matched_inputs = _matched_concept_indexes(input_groups, text_tokens)
        matched_query = _matched_concept_indexes(query_groups, text_tokens)
        matched_all = _matched_concept_indexes(all_groups, text_tokens)
        tool_specific_match = bool(
            record.metadata.get("implementation_tool_mentions")
            and _IMPLEMENTATION_TOOLS_FACET
            in _string_list(record.metadata.get("search_facets"))
        )
        # Confirmed Idea and Research Inputs are both trusted anchors. Generated
        # queries may broaden recall, but cannot become the sole Related Work gate.
        # Counter-evidence searches deliberately add their claim-specific query.
        idea_is_english = _idea_output_language(idea) == "en"
        if require_domain_match:
            has_required_match = bool(matched_idea or matched_query)
        elif idea_groups:
            has_required_match = (
                bool(matched_idea or matched_inputs or tool_specific_match)
                if idea_is_english
                else bool(matched_idea or matched_inputs or matched_query)
            )
        elif input_groups:
            has_required_match = bool(matched_inputs or tool_specific_match)
        else:
            # Legacy/incomplete sessions may not yet contain a confirmed Idea or
            # Research Inputs. Generated queries can still score provider results,
            # but must not become an accidental hard filter on their own.
            has_required_match = True
        if (idea_groups or input_groups or query_groups) and not has_required_match:
            discarded += 1
            continue
        concept_matches = _concept_match_count(all_groups, text_tokens)
        covered_tokens = (
            len(set().union(*all_groups) & text_tokens) if all_groups else 0
        )
        title_hits = len(set().union(*all_groups) & title_tokens) if all_groups else 0
        query_hits = len(record.metadata.get("discovery_queries") or [])
        graph_hits = len(record.metadata.get("citation_graph_seeds") or [])
        denominator = max(
            len(idea_groups) * 3
            + len(input_groups) * 2
            + len(query_groups) * 2
            + 8,
            1,
        )
        retrieval_score = min(
            1.0,
            (
                len(matched_idea) * 3
                + len(matched_inputs) * 2
                + len(matched_query) * 2
                + int(tool_specific_match) * 4
                + concept_matches
                + min(title_hits, 2)
                + min(query_hits, 2) * 0.5
                + min(graph_hits, 1) * 0.5
            )
            / denominator,
        )
        record.metadata["retrieval_score"] = round(retrieval_score, 4)
        record.metadata["matched_idea_concept_indexes"] = sorted(matched_idea)
        record.metadata["matched_input_concept_indexes"] = sorted(matched_inputs)
        record.metadata["matched_query_concept_indexes"] = sorted(matched_query)
        record.metadata["matched_concept_indexes"] = sorted(matched_all)
        record.metadata["tool_specific_relevance"] = tool_specific_match
        scored.append(
            (
                (
                    int(tool_specific_match),
                    len(matched_idea),
                    len(matched_inputs),
                    len(matched_query),
                    concept_matches,
                    title_hits,
                    query_hits,
                    graph_hits,
                    covered_tokens,
                ),
                -index,
                record,
            )
        )
    scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return [item[2] for item in scored], discarded


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
    if isinstance(exc, (json.JSONDecodeError, TypeError)):
        return "the model response was not valid structured JSON"
    if isinstance(exc, ValueError):
        return "the model response did not satisfy the structured response constraints"
    if not isinstance(exc, LlmProviderError):
        return type(exc).__name__
    details = []
    if exc.status_code is not None:
        details.append(f"HTTP {exc.status_code}")
    if exc.code:
        details.append(exc.code)
    suffix = f" ({'; '.join(details)})" if details else ""
    return f"{exc}{suffix}"


def _structured_failure_detail(exc: Exception) -> str:
    """Return bounded schema diagnostics without exposing the model response."""

    if isinstance(exc, ValidationError):
        details = []
        for error in exc.errors()[:3]:
            location = ".".join(str(item) for item in error.get("loc", ()))
            message = str(error.get("msg") or error.get("type") or "invalid field")
            details.append(f"{location or 'response'}: {message}")
        return "schema validation failed (" + "; ".join(details) + ")"
    if isinstance(exc, json.JSONDecodeError):
        return f"invalid JSON at line {exc.lineno}, column {exc.colno}"
    if isinstance(exc, (TypeError, ValueError)):
        return str(exc)[:300] or type(exc).__name__
    return _llm_failure_summary(exc)


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
