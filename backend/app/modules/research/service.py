"""Research application services and in-request generation workflow."""

from __future__ import annotations

import json
import re
from collections.abc import AsyncIterator
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any
from uuid import UUID, uuid4

from fastapi import HTTPException, status
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

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
    CitationVerifier,
    ScholarlyProviderError,
    ScholarlyRecord,
    ScholarlySourcePort,
    SourcePreferences,
)
from app.modules.research.schemas import (
    CitationCreate,
    CitationResponse,
    CitationUpsertEvent,
    DoneEvent,
    DraftPatchEvent,
    ErrorEvent,
    GapCardBody,
    GroundingStatus,
    ProgressEvent,
    RelatedWorkFindingCreate,
    RelatedWorkFindingResponse,
    ResearchGenerateRequest,
    ResearchInputs,
    ResearchNode,
    VerificationStatus,
    WarningEvent,
)
from app.ports.llm import LlmPort, LlmProviderError


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


class ResearchService:
    def __init__(
        self,
        db: AsyncSession,
        *,
        source: ScholarlySourcePort,
        verifier: CitationVerifier,
        llm: LlmPort,
    ) -> None:
        self._db = db
        self._source = source
        self._verifier = verifier
        self._llm = llm

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
                    .where(
                        RelatedWorkFinding.session_id == session_id,
                        RelatedWorkFinding.stage_revision_id.is_(None),
                    )
                    .order_by(RelatedWorkFinding.created_at, RelatedWorkFinding.id)
                )
            ).all()
        )
        return [RelatedWorkFindingResponse.model_validate(row) for row in rows]

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
        records: list[ScholarlyRecord] = []
        provider_failures: list[str] = []
        attempted_queries = 0
        candidate_limit = min(max(run.body.max_results * 3, 10), 25)
        for query in queries:
            attempted_queries += 1
            try:
                found = await self._source.search(
                    query=query,
                    preferences=source_preferences,
                    limit=candidate_limit,
                )
            except ScholarlyProviderError as exc:
                provider_failures.append(str(exc))
                continue
            except Exception as exc:  # noqa: BLE001 - isolate unknown provider failures
                provider_failures.append(
                    f"Scholarly provider failed: {type(exc).__name__}"
                )
                continue
            records.extend(found)

        if attempted_queries and len(provider_failures) == attempted_queries:
            raise ResearchGenerationError(provider_failures[-1])
        for failure in provider_failures:
            yield self._warning(run.node, "provider_error", failure)

        unique_records = _deduplicate_records(records)
        ranked_records, discarded_count = _rank_relevant_records(
            unique_records,
            inputs=inputs,
            idea=idea,
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
        unique_records = ranked_records[: run.body.max_results]

        # A new search replaces the previous working set. Frozen Related Work
        # revisions remain untouched and can still be reopened through StagePort.
        await self._db.execute(
            delete(RelatedWorkFinding).where(
                RelatedWorkFinding.session_id == run.session_id,
                RelatedWorkFinding.stage_revision_id.is_(None),
            )
        )
        await self._db.execute(
            delete(Citation).where(
                Citation.session_id == run.session_id,
                Citation.stage_revision_id.is_(None),
            )
        )
        total = max(len(unique_records), 1)
        for index, record in enumerate(unique_records, start=1):
            data = self._record_create(record)
            citation, _ = await self._upsert_citation(
                session_id=run.session_id,
                data=data,
            )
            try:
                verification = await self._verifier.verify(citation=record)
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

            finding, analysis_warnings = await self._analyze(
                record,
                citation.id,
                research_context={
                    "idea": idea,
                    "research_inputs": inputs.model_dump(mode="json"),
                },
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
                "citation_count": len(unique_records),
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
                    "research-inputs: return only JSON in exactly this shape: "
                    '{"keywords":["specific scholarly search phrase"],'
                    '"preferred_sources":{"peer_reviewed_papers":true,'
                    '"official_proceedings":true,"author_materials":true,'
                    '"sourced_surveys":true}}. Suggest 4 to 7 unique English noun '
                    "phrases, each 2 to 5 words, directly useful for finding Related "
                    "Work for the supplied decomposed research idea. First identify the "
                    "idea's distinctive concept anchors: its target artifact or task, "
                    "proposed intervention or mechanism, measured outcome, and constraints. "
                    "Every distinctive anchor must appear verbatim or through a precise "
                    "scholarly synonym in at least one keyword; never generalize it away. "
                    "Prefer established technical concepts, intervention names, outcomes, and "
                    "evaluation concepts. Every item must stand alone as a noun phrase that a "
                    "researcher could paste into a scholarly search engine. Convert narrative "
                    "wording into the corresponding research concept; do not copy instructions, "
                    "sentence fragments, subject-verb clauses, temporal fragments, or category "
                    "labels joined by 'vs'. "
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

    async def _generate_queries(
        self,
        inputs: ResearchInputs,
        idea: dict[str, Any],
    ) -> tuple[list[str], list[str]]:
        try:
            raw = await self._llm.complete(
                system=(
                    "research-query: return only JSON with a queries string array. "
                    "Create precise scholarly queries from the confirmed keywords and "
                    "idea concept anchors. Across the query set, preserve every distinctive "
                    "artifact, intervention, mechanism, outcome, and constraint; do not "
                    "replace them with broad terms such as AI, paper, method, or research. "
                    "Do not target a fixed query count; return as many queries as needed "
                    "to cover every confirmed keyword and distinctive idea concept."
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
            return _compose_search_queries(model_queries, inputs, idea), []
        except Exception as exc:  # noqa: BLE001 - deterministic fallback
            return _compose_search_queries([], inputs, idea), [
                (
                    "Query generation used the confirmed keywords: "
                    f"{_llm_failure_summary(exc)}"
                )
            ]

    async def _analyze(
        self,
        record: ScholarlyRecord,
        citation_id: UUID,
        *,
        research_context: dict[str, Any],
    ) -> tuple[RelatedWorkFindingCreate, list[str]]:
        citation_payload = self._record_payload(record)
        try:
            raw = await self._llm.complete(
                system=(
                    "research-analysis: return only one flat JSON object with exactly "
                    "these keys: what_was_done (non-empty string), "
                    "method_or_feedback (non-empty string describing the method, "
                    "feedback, or evaluation type), limitation (non-empty string), "
                    "relevance (non-empty string), supporting_passage (non-empty "
                    "verbatim span from the supplied citation abstract), evidence "
                    "(an object with what_was_done, method_or_feedback, and limitation; "
                    "each value contains passage and location), and confidence "
                    "(number from 0 to 1). Do not rename or nest the keys. Assess "
                    "relevance and limitation against the supplied Problem, Research "
                    "Questions, and Research Inputs. If the source does not state a "
                    "method or feedback type, use 'Not stated in the source metadata'."
                ),
                prompt=json.dumps(
                    {**research_context, "citation": citation_payload},
                    default=str,
                    ensure_ascii=False,
                ),
            )
            payload = _normalize_finding_payload(_json_value(raw, dict), record)
            for item in payload["evidence"].values():
                item["passage"] = _verbatim_source_passage(record, item["passage"])
            passage = payload["evidence"]["what_was_done"]["passage"]
            payload["supporting_passage"] = passage
            grounding_status = _evidence_grounding_status(record, payload["evidence"])
            warnings = []
            if grounding_status is not GroundingStatus.GROUNDED:
                warnings.append(
                    "Finding passage could not be matched exactly to the retrieved source text"
                )
            return (
                RelatedWorkFindingCreate(
                    citation_id=citation_id,
                    grounding_status=grounding_status,
                    **payload,
                ),
                warnings,
            )
        except Exception as exc:  # noqa: BLE001 - deterministic grounded fallback
            passage = record.abstract or record.title
            source_evidence = {
                "passage": passage[:500],
                "location": _source_location(record),
            }
            return (
                RelatedWorkFindingCreate(
                    citation_id=citation_id,
                    what_was_done=f"Presents {record.title}.",
                    method_or_feedback="Not stated in the source metadata.",
                    limitation="The available metadata is insufficient for a detailed limitation analysis.",
                    relevance="Included by the configured scholarly search.",
                    supporting_passage=passage[:500],
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
        related = upstream.get(WorkflowNode.RELATED_WORK.value, {}).get("projected", {})
        raw_research_inputs = upstream.get(WorkflowNode.RESEARCH_INPUTS.value, {}).get(
            "narrative", {}
        )
        try:
            research_inputs = ResearchInputs.model_validate(
                raw_research_inputs
            ).model_dump(mode="json")
        except ValidationError:
            research_inputs = ResearchInputs().model_dump(mode="json")
        citations = _gap_citations(related.get("citations", []))
        valid_keys = [
            item["citation_key"] for item in citations if item.get("citation_key")
        ]
        related_work = _gap_findings(
            related.get("related_work", []),
            citations,
        )
        try:
            analysis_raw = await self._llm.complete(
                system=(
                    "research-gap-analysis: perform private source-grounded analysis and "
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
                        "idea": _idea_context(context),
                        "research_inputs": research_inputs,
                        "citations": citations,
                        "related_work": related_work,
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
                raise ValueError("Gap analysis did not cover every Related Work source")
        except Exception as exc:  # noqa: BLE001 - conservative source-linked fallback
            candidate = GapCardBody(
                statement=_fallback_gap_statement(related_work),
                supporting_citation_keys=valid_keys,
            )
            warnings = [
                (
                    "Gap analysis used a conservative source-linked fallback: "
                    f"{_llm_failure_summary(exc)}"
                )
            ]
        else:
            try:
                synthesis_raw = await self._llm.complete(
                    system=(
                        "research-gap-synthesis: return only JSON with one non-empty string "
                        "field named statement. Synthesize the four private analysis answers "
                        "into one concise, coherent Gap Candidate of 2 to 4 sentences. State "
                        "what existing approaches do and what remains unclear or insufficient. "
                        "Do not expose the questions, field labels, source list, bullet points, "
                        "or separate answers. Do not claim proven novelty and do not use markdown."
                    ),
                    prompt=json.dumps(
                        {
                            "idea": _idea_context(context),
                            "analysis": answers.model_dump(mode="json"),
                        },
                        default=str,
                        ensure_ascii=False,
                    ),
                )
                synthesis = _GapSynthesis.model_validate(
                    _json_value(synthesis_raw, dict)
                )
                statement = synthesis.statement
                warnings = []
            except Exception as exc:  # noqa: BLE001 - preserve valid private analysis
                statement = _gap_statement_from_answers(answers)
                warnings = [
                    (
                        "Gap synthesis used the validated source-grounded analysis "
                        "directly because the final model call failed: "
                        f"{_llm_failure_summary(exc)}"
                    )
                ]
            candidate = GapCardBody(
                statement=statement,
                supporting_citation_keys=valid_keys,
            )
        narrative = dict(context.get("working_draft", {}).get("narrative", {}))
        narrative["candidate"] = candidate.model_dump(mode="json")
        return narrative, warnings

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
        row.source_metadata = record.metadata or row.source_metadata

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
    model_keywords = _clean_keywords(_keyword_values(raw_keywords))
    # Idea-derived anchors come first so a syntactically valid but generic model
    # response cannot crowd out the concepts that distinguish this research idea.
    idea_keywords = _idea_search_concepts(idea)
    keywords = _clean_keywords([*idea_keywords, *model_keywords])

    preferred = payload.get("preferred_sources")
    if not isinstance(preferred, dict):
        preferred = payload.get("preferredSources")
    preferred_payload = preferred if isinstance(preferred, dict) else {}
    defaults = ResearchInputs().preferred_sources.model_dump()
    normalized_preferred = {
        key: _boolean_value(preferred_payload.get(key), default)
        for key, default in defaults.items()
    }
    return ResearchInputs(
        keywords=keywords[:8],
        preferred_sources=normalized_preferred,
    )


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
        or (record.abstract or record.title)[:500]
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
    source_location = _source_location(record)
    normalized["evidence"] = {
        key: {
            "passage": (
                _first_text(value, "passage", "quote", "supporting_passage")
                if isinstance(value, dict)
                else None
            )
            or passage,
            "location": source_location,
        }
        for key in ("what_was_done", "method_or_feedback", "limitation")
        for value in [evidence_payload.get(key)]
    }
    return normalized


def _verbatim_source_passage(
    record: ScholarlyRecord,
    proposed: str,
) -> str:
    """Return an exact source span, repairing harmless model paraphrases."""
    source_text = (record.abstract or record.title).strip()
    if not source_text:
        return proposed.strip()
    target = proposed.strip()
    if target:
        start = source_text.casefold().find(target.casefold())
        if start >= 0:
            return source_text[start : start + len(target)]

    sentences = [
        sentence.strip()
        for sentence in re.split(r"(?<=[.!?])\s+|\n+", source_text)
        if sentence.strip()
    ]
    if target and sentences:
        normalized_target = _comparison_text(target)
        best = max(
            sentences,
            key=lambda sentence: SequenceMatcher(
                None,
                normalized_target,
                _comparison_text(sentence),
            ).ratio(),
        )
        similarity = SequenceMatcher(
            None,
            normalized_target,
            _comparison_text(best),
        ).ratio()
        if similarity >= 0.45:
            return best
    return source_text[:500]


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
            }
        )
    return compact


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
    found: set[tuple[str, ...]] = set()
    unique: list[ScholarlyRecord] = []
    for record in records:
        doi = normalize_doi(record.doi)
        if doi:
            identity = ("doi", doi)
        elif record.provider and record.provider_source_id:
            identity = (
                "provider",
                record.provider.casefold(),
                record.provider_source_id.casefold(),
            )
        elif record.url:
            identity = ("url", normalize_url(record.url) or record.url.casefold())
        else:
            identity = ("title", record.title.casefold(), str(record.year))
        if identity in found:
            continue
        found.add(identity)
        unique.append(record)
    return unique


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
                elif len(segment) > 5:
                    extracted.extend(
                        " ".join(segment[index : index + 3])
                        for index in range(0, len(segment) - 2, 2)
                    )
                segment = []
            else:
                segment.append(word)

    keywords = _clean_keywords([*mapped, *extracted])
    return keywords[:8] or ["related work discovery"]


def _idea_search_concepts(idea: dict[str, Any]) -> list[str]:
    """Return idea-derived phrases that must survive keyword/query generation."""
    if not _text_values(idea):
        return []
    return [
        keyword
        for keyword in _fallback_keywords(idea)
        if keyword.casefold() != "related work discovery"
    ]


def _compose_search_queries(
    model_queries: list[str],
    inputs: ResearchInputs,
    idea: dict[str, Any],
) -> list[str]:
    """Cover every confirmed concept without coupling query count to result count."""
    anchors = _idea_search_concepts(idea)
    confirmed = _clean_keywords(inputs.keywords)
    queries: list[str] = []
    seen: set[str] = set()

    for raw in model_queries:
        query = re.sub(r"\s+", " ", raw.strip())
        folded = query.casefold()
        if not query or folded in seen:
            continue
        queries.append(query)
        seen.add(folded)

    # Model queries may use useful scholarly synonyms, but deterministic fallbacks
    # make coverage explicit: each idea anchor and Account-confirmed keyword must be
    # represented by at least one query before candidates are retrieved and ranked.
    for concept in _clean_keywords([*anchors, *confirmed]):
        concept_tokens = _search_tokens(concept)
        covered = any(
            _matched_concept_indexes([concept_tokens], _search_tokens(query))
            for query in queries
        )
        if covered:
            continue
        folded = concept.casefold()
        if folded not in seen:
            queries.append(concept)
            seen.add(folded)

    return queries or ["related work"]


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
) -> tuple[list[ScholarlyRecord], int]:
    """Rank by concept coverage and reject idea-mismatched provider results."""
    idea_groups = _concept_groups(_idea_search_concepts(idea))
    all_groups = _concept_groups(
        [*_idea_search_concepts(idea), *_clean_keywords(inputs.keywords)]
    )
    scored: list[tuple[tuple[int, int, int, int], int, set[int], ScholarlyRecord]] = []
    discarded = 0
    for index, record in enumerate(records):
        title_tokens = _search_tokens(record.title)
        text_tokens = title_tokens | _search_tokens(record.abstract or "")
        matched_idea = _matched_concept_indexes(idea_groups, text_tokens)
        if idea_groups and not matched_idea:
            discarded += 1
            continue
        concept_matches = _concept_match_count(all_groups, text_tokens)
        covered_tokens = (
            len(set().union(*all_groups) & text_tokens) if all_groups else 0
        )
        title_hits = len(set().union(*all_groups) & title_tokens) if all_groups else 0
        scored.append(
            (
                (len(matched_idea), concept_matches, title_hits, covered_tokens),
                -index,
                matched_idea,
                record,
            )
        )
    scored.sort(key=lambda item: (item[0], item[1]), reverse=True)

    # Put at least one strong result for each idea anchor near the front when
    # the provider supplied such coverage; then fill by overall relevance.
    remaining = list(scored)
    ordered: list[tuple[tuple[int, int, int, int], int, set[int], ScholarlyRecord]] = []
    uncovered = set(range(len(idea_groups)))
    while uncovered and remaining:
        best = max(
            remaining,
            key=lambda item: (len(item[2] & uncovered), item[0], item[1]),
        )
        newly_covered = best[2] & uncovered
        if not newly_covered:
            break
        ordered.append(best)
        remaining.remove(best)
        uncovered -= newly_covered
    ordered.extend(remaining)
    return [item[3] for item in ordered], discarded


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


def _grounding_status(record: ScholarlyRecord, passage: str) -> GroundingStatus:
    if not passage:
        return GroundingStatus.REJECTED
    source_text = record.abstract or record.title
    if passage.casefold() in source_text.casefold():
        return GroundingStatus.GROUNDED
    return GroundingStatus.WARNING


def _source_location(record: ScholarlyRecord) -> str:
    return "Abstract" if record.abstract else "Title"


def _evidence_grounding_status(
    record: ScholarlyRecord,
    evidence: dict[str, dict[str, str]],
) -> GroundingStatus:
    statuses = [
        _grounding_status(record, item.get("passage", "")) for item in evidence.values()
    ]
    if statuses and all(item is GroundingStatus.GROUNDED for item in statuses):
        return GroundingStatus.GROUNDED
    if any(item is GroundingStatus.REJECTED for item in statuses):
        return GroundingStatus.REJECTED
    return GroundingStatus.WARNING
