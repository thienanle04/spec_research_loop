"""Research implementation of the shared StagePort."""

from typing import Any
from uuid import UUID

from fastapi import status
from pydantic import ValidationError
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import OperationalErrorException
from app.modules.loop.catalog import CardKind, WorkflowNode
from app.modules.loop.models import Card, NodeHead, StageRevision
from app.modules.research.models import Citation, RelatedWorkFinding
from app.modules.research.schemas import GapCardBody


def _citation_payload(row: Citation) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "citation_key": row.citation_key,
        "title": row.title,
        "authors": row.authors,
        "year": row.year,
        "venue": row.venue,
        "doi": row.doi,
        "url": row.url,
        "provider": row.provider,
        "provider_source_id": row.provider_source_id,
        "abstract": row.abstract,
        "retrieved_at": row.retrieved_at.isoformat() if row.retrieved_at else None,
        "is_active": row.is_active,
        "pinned": row.pinned,
        "retrieval_score": row.retrieval_score,
        "text_object_key": row.text_object_key,
        "text_source_url": row.text_source_url,
        "text_source_kind": row.text_source_kind,
        "text_checksum": row.text_checksum,
        "text_char_count": row.text_char_count,
        "text_retrieved_at": (
            row.text_retrieved_at.isoformat() if row.text_retrieved_at else None
        ),
        "verification_status": row.verification_status,
        "metadata": row.source_metadata,
    }


def _finding_payload(row: RelatedWorkFinding) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "citation_id": str(row.citation_id),
        "what_was_done": row.what_was_done,
        "method_or_feedback": row.method_or_feedback,
        "limitation": row.limitation,
        "relevance": row.relevance,
        "supporting_passage": row.supporting_passage,
        "source_object_key": row.source_object_key,
        "source_location": row.source_location,
        "evidence": row.evidence,
        "confidence": row.confidence,
        "grounding_status": row.grounding_status,
    }


def _clone_citation(row: Citation, revision_id: UUID | None) -> Citation:
    return Citation(
        id=row.id,
        citation_key=row.citation_key,
        session_id=row.session_id,
        stage_revision_id=revision_id,
        title=row.title,
        authors=list(row.authors),
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
        verification_status=row.verification_status,
        source_metadata=dict(row.source_metadata),
    )


def _clone_finding(
    row: RelatedWorkFinding, revision_id: UUID | None
) -> RelatedWorkFinding:
    return RelatedWorkFinding(
        id=row.id,
        session_id=row.session_id,
        stage_revision_id=revision_id,
        citation_id=row.citation_id,
        what_was_done=row.what_was_done,
        method_or_feedback=row.method_or_feedback,
        limitation=row.limitation,
        relevance=row.relevance,
        supporting_passage=row.supporting_passage,
        source_object_key=row.source_object_key,
        source_location=row.source_location,
        evidence=dict(row.evidence),
        confidence=row.confidence,
        grounding_status=row.grounding_status,
    )


class ResearchStagePort:
    """Snapshots research typed rows in the LoopService transaction."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def fingerprint(self, *, session_id: UUID, node: str) -> dict[str, Any]:
        if node == WorkflowNode.GAP.value:
            card = await self._db.scalar(
                select(Card).where(
                    Card.session_id == session_id,
                    Card.kind == CardKind.GAP.value,
                )
            )
            try:
                candidate = GapCardBody.model_validate(card.body if card else {})
            except ValidationError as exc:
                raise OperationalErrorException(
                    status_code=status.HTTP_409_CONFLICT,
                    code="gap_evidence_not_ready",
                    detail=(
                        "Gap Candidate must include a valid source-verification and "
                        "counter-evidence search audit before Confirm."
                    ),
                ) from exc
            if not candidate.is_confirmable():
                raise OperationalErrorException(
                    status_code=status.HTTP_409_CONFLICT,
                    code="gap_evidence_not_ready",
                    detail=(
                        "Gap Candidate needs verified Citations, grounded findings, and a "
                        "conclusive counter-evidence search before Confirm."
                    ),
                )
            related_head = await self._db.scalar(
                select(NodeHead).where(
                    NodeHead.session_id == session_id,
                    NodeHead.node == WorkflowNode.RELATED_WORK.value,
                )
            )
            revision_id = related_head.stage_revision_id if related_head else None
            if revision_id is None:
                raise OperationalErrorException(
                    status_code=status.HTTP_409_CONFLICT,
                    code="gap_evidence_not_ready",
                    detail="Gap Candidate has no confirmed Related Work revision.",
                )
            citations = await self._citations(
                session_id=session_id,
                revision_id=revision_id,
            )
            findings = await self._findings(
                session_id=session_id,
                revision_id=revision_id,
            )
            verified = {
                row.citation_key
                for row in citations
                if row.verification_status == "verified"
            }
            citation_keys = {row.id: row.citation_key for row in citations}
            grounded = {
                citation_keys[row.citation_id]
                for row in findings
                if row.grounding_status == "grounded"
                and row.citation_id in citation_keys
            }
            actual_eligible = verified & grounded
            if not set(candidate.supporting_citation_keys) <= actual_eligible:
                raise OperationalErrorException(
                    status_code=status.HTTP_409_CONFLICT,
                    code="gap_evidence_not_ready",
                    detail=(
                        "Gap supporting Citations must be verified and linked to grounded "
                        "findings in the confirmed Related Work revision."
                    ),
                )
            related_revision = await self._db.scalar(
                select(StageRevision).where(StageRevision.id == revision_id)
            )
            confirmed_queries = (
                related_revision.narrative.get("search_queries", [])
                if related_revision is not None
                else []
            )
            if candidate.search_audit.related_work_queries != confirmed_queries:
                raise OperationalErrorException(
                    status_code=status.HTTP_409_CONFLICT,
                    code="gap_evidence_not_ready",
                    detail=(
                        "Gap search audit does not match the confirmed Related Work queries."
                    ),
                )
            return {"candidate": candidate.model_dump(mode="json")}
        if node != WorkflowNode.RELATED_WORK.value:
            return {}
        return await self._project_rows(session_id=session_id, revision_id=None)

    async def freeze(self, *, session_id: UUID, node: str, revision_id: UUID) -> None:
        if node != WorkflowNode.RELATED_WORK.value:
            return
        citations = await self._citations(session_id=session_id, revision_id=None)
        findings = await self._findings(session_id=session_id, revision_id=None)
        self._db.add_all([_clone_citation(row, revision_id) for row in citations])
        await self._db.flush()
        self._db.add_all([_clone_finding(row, revision_id) for row in findings])
        await self._db.flush()

    async def reset_working(
        self,
        *,
        session_id: UUID,
        node: str,
        from_revision_id: UUID | None,
    ) -> None:
        if node != WorkflowNode.RELATED_WORK.value:
            return
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
        if from_revision_id is None:
            return
        citations = await self._citations(
            session_id=session_id,
            revision_id=from_revision_id,
        )
        findings = await self._findings(
            session_id=session_id,
            revision_id=from_revision_id,
        )
        self._db.add_all([_clone_citation(row, None) for row in citations])
        await self._db.flush()
        self._db.add_all([_clone_finding(row, None) for row in findings])
        await self._db.flush()

    async def project(
        self,
        *,
        session_id: UUID,
        node: str,
        revision_id: UUID | None,
    ) -> dict[str, Any]:
        if node != WorkflowNode.RELATED_WORK.value:
            return {}
        return await self._project_rows(session_id=session_id, revision_id=revision_id)

    async def _project_rows(
        self,
        *,
        session_id: UUID,
        revision_id: UUID | None,
    ) -> dict[str, Any]:
        citations = await self._citations(
            session_id=session_id, revision_id=revision_id
        )
        findings = await self._findings(session_id=session_id, revision_id=revision_id)
        return {
            "citations": [_citation_payload(row) for row in citations],
            "related_work": [_finding_payload(row) for row in findings],
        }

    async def _citations(
        self,
        *,
        session_id: UUID,
        revision_id: UUID | None,
    ) -> list[Citation]:
        revision_filter = (
            Citation.stage_revision_id.is_(None)
            if revision_id is None
            else Citation.stage_revision_id == revision_id
        )
        rows = await self._db.scalars(
            select(Citation)
            .where(
                Citation.session_id == session_id,
                revision_filter,
                Citation.is_active.is_(True),
            )
            .order_by(Citation.id)
        )
        return list(rows.all())

    async def _findings(
        self,
        *,
        session_id: UUID,
        revision_id: UUID | None,
    ) -> list[RelatedWorkFinding]:
        revision_filter = (
            RelatedWorkFinding.stage_revision_id.is_(None)
            if revision_id is None
            else RelatedWorkFinding.stage_revision_id == revision_id
        )
        citation_revision_filter = (
            Citation.stage_revision_id.is_(None)
            if revision_id is None
            else Citation.stage_revision_id == revision_id
        )
        rows = await self._db.scalars(
            select(RelatedWorkFinding)
            .join(
                Citation,
                (Citation.session_id == RelatedWorkFinding.session_id)
                & (Citation.id == RelatedWorkFinding.citation_id)
                & citation_revision_filter,
            )
            .where(
                RelatedWorkFinding.session_id == session_id,
                revision_filter,
                Citation.is_active.is_(True),
            )
            .order_by(RelatedWorkFinding.id)
        )
        return list(rows.all())
