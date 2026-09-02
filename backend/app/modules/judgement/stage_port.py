"""Judgement StagePort: freeze Judge Issues (and Conference scores) onto Stage Revisions."""

from typing import Any
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.judgement.catalog import JUDGE_NODES, Severity
from app.modules.judgement.composer import CLUSTER_CONSENSUS, CLUSTER_DISAGREEMENT
from app.modules.judgement.models import (
    AggregatorIssue,
    AggregatorScore,
    ConferenceScore,
    HandlingOption,
    JudgeIssue,
)
from app.modules.judgement.schemas import grounds_payload
from app.modules.loop.catalog import WorkflowNode


def _issue_payload(row: JudgeIssue) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "finding_kind": row.finding_kind,
        "severity": row.severity,
        "reason": row.reason,
        "suggestion": row.suggestion,
        "target_card_id": str(row.target_card_id) if row.target_card_id else None,
        "grounds": grounds_payload(row.grounds),
        "sort_index": row.sort_index,
    }


def _aggregator_issue_payload(row: AggregatorIssue) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "finding_kind": row.finding_kind,
        "severity": row.severity,
        "reason": row.reason,
        "suggestion": row.suggestion,
        "target_card_id": str(row.target_card_id) if row.target_card_id else None,
        "source_node": row.source_node,
        "cluster": row.cluster,
        "grounds": grounds_payload(row.grounds),
        "sort_index": row.sort_index,
    }


def _option_payload(row: HandlingOption) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "finding_kind": row.finding_kind,
        "source_node": row.source_node,
        "label": row.label,
        "target_node": row.target_node,
        "prose": row.prose,
        "sort_index": row.sort_index,
    }


def _score_payload(row: ConferenceScore | AggregatorScore) -> dict[str, int]:
    return {
        "originality": row.originality,
        "significance": row.significance,
        "soundness": row.soundness,
        "clarity": row.clarity,
        "reproducibility": row.reproducibility,
    }


def _clone_issue(row: JudgeIssue, revision_id: UUID | None) -> JudgeIssue:
    return JudgeIssue(
        id=row.id,
        session_id=row.session_id,
        stage_revision_id=revision_id,
        node=row.node,
        finding_kind=row.finding_kind,
        severity=row.severity,
        reason=row.reason,
        suggestion=row.suggestion,
        target_card_id=row.target_card_id,
        grounds=grounds_payload(row.grounds),
        sort_index=row.sort_index,
    )


def _clone_score(row: ConferenceScore, revision_id: UUID | None) -> ConferenceScore:
    return ConferenceScore(
        session_id=row.session_id,
        stage_revision_id=revision_id,
        originality=row.originality,
        significance=row.significance,
        soundness=row.soundness,
        clarity=row.clarity,
        reproducibility=row.reproducibility,
    )


def _clone_aggregator_issue(
    row: AggregatorIssue, revision_id: UUID | None
) -> AggregatorIssue:
    return AggregatorIssue(
        id=row.id,
        session_id=row.session_id,
        stage_revision_id=revision_id,
        source_node=row.source_node,
        source_issue_id=row.source_issue_id,
        finding_kind=row.finding_kind,
        severity=row.severity,
        reason=row.reason,
        suggestion=row.suggestion,
        target_card_id=row.target_card_id,
        grounds=grounds_payload(row.grounds),
        cluster=row.cluster,
        sort_index=row.sort_index,
    )


def _clone_option(row: HandlingOption, revision_id: UUID | None) -> HandlingOption:
    return HandlingOption(
        id=row.id,
        session_id=row.session_id,
        stage_revision_id=revision_id,
        aggregator_issue_id=row.aggregator_issue_id,
        finding_kind=row.finding_kind,
        source_node=row.source_node,
        label=row.label,
        target_node=row.target_node,
        prose=row.prose,
        sort_index=row.sort_index,
    )


def _clone_aggregator_score(
    row: AggregatorScore, revision_id: UUID | None
) -> AggregatorScore:
    return AggregatorScore(
        session_id=row.session_id,
        stage_revision_id=revision_id,
        originality=row.originality,
        significance=row.significance,
        soundness=row.soundness,
        clarity=row.clarity,
        reproducibility=row.reproducibility,
    )


class JudgementStagePort:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def fingerprint(self, *, session_id: UUID, node: str) -> dict[str, Any]:
        if WorkflowNode(node) not in JUDGE_NODES:
            return {}
        return await self._project_rows(session_id=session_id, node=node, revision_id=None)

    async def freeze(self, *, session_id: UUID, node: str, revision_id: UUID) -> None:
        if WorkflowNode(node) not in JUDGE_NODES:
            return
        if node == WorkflowNode.AGGREGATOR.value:
            await self._freeze_aggregator(session_id, revision_id)
            return
        issues = await self._issues(
            session_id=session_id, node=node, revision_id=None
        )
        self._db.add_all([_clone_issue(row, revision_id) for row in issues])
        if node == WorkflowNode.CONFERENCE_JUDGE.value:
            score = await self._score(session_id=session_id, revision_id=None)
            if score is not None:
                self._db.add(_clone_score(score, revision_id))
        await self._db.flush()

    async def reset_working(
        self,
        *,
        session_id: UUID,
        node: str,
        from_revision_id: UUID | None,
    ) -> None:
        if WorkflowNode(node) not in JUDGE_NODES:
            return
        if node == WorkflowNode.AGGREGATOR.value:
            await self._reset_aggregator(session_id, from_revision_id)
            return
        await self._db.execute(
            delete(JudgeIssue).where(
                JudgeIssue.session_id == session_id,
                JudgeIssue.node == node,
                JudgeIssue.stage_revision_id.is_(None),
            )
        )
        if node == WorkflowNode.CONFERENCE_JUDGE.value:
            await self._db.execute(
                delete(ConferenceScore).where(
                    ConferenceScore.session_id == session_id,
                    ConferenceScore.stage_revision_id.is_(None),
                )
            )
        if from_revision_id is None:
            return
        issues = await self._issues(
            session_id=session_id, node=node, revision_id=from_revision_id
        )
        self._db.add_all([_clone_issue(row, None) for row in issues])
        if node == WorkflowNode.CONFERENCE_JUDGE.value:
            score = await self._score(
                session_id=session_id, revision_id=from_revision_id
            )
            if score is not None:
                self._db.add(_clone_score(score, None))
        await self._db.flush()

    async def project(
        self,
        *,
        session_id: UUID,
        node: str,
        revision_id: UUID | None,
    ) -> dict[str, Any]:
        if WorkflowNode(node) not in JUDGE_NODES:
            return {}
        return await self._project_rows(
            session_id=session_id, node=node, revision_id=revision_id
        )

    async def _project_rows(
        self,
        *,
        session_id: UUID,
        node: str,
        revision_id: UUID | None,
    ) -> dict[str, Any]:
        if node == WorkflowNode.AGGREGATOR.value:
            return await self._project_aggregator(
                session_id=session_id, revision_id=revision_id
            )
        issues = await self._issues(
            session_id=session_id, node=node, revision_id=revision_id
        )
        payload: dict[str, Any] = {
            "issues": [_issue_payload(row) for row in issues]
        }
        if node == WorkflowNode.CONFERENCE_JUDGE.value:
            score = await self._score(session_id=session_id, revision_id=revision_id)
            payload["scores"] = None if score is None else _score_payload(score)
        return payload

    async def _project_aggregator(
        self, *, session_id: UUID, revision_id: UUID | None
    ) -> dict[str, Any]:
        issues = await self._aggregator_issues(
            session_id=session_id, revision_id=revision_id
        )
        options = await self._options(session_id=session_id, revision_id=revision_id)
        score = await self._aggregator_score(
            session_id=session_id, revision_id=revision_id
        )
        payloads = [_aggregator_issue_payload(row) for row in issues]
        consensus = [
            item for item in payloads if item["cluster"] == CLUSTER_CONSENSUS
        ]
        disagreement = [
            item for item in payloads if item["cluster"] == CLUSTER_DISAGREEMENT
        ]
        readiness = (
            "blocked"
            if any(item["severity"] == Severity.CRITICAL.value for item in payloads)
            else "ready"
        )
        return {
            "issues": payloads,
            "clusters": {"consensus": consensus, "disagreement": disagreement},
            "handling_options": [_option_payload(row) for row in options],
            "scores": None if score is None else _score_payload(score),
            "readiness": readiness,
        }

    async def _freeze_aggregator(self, session_id: UUID, revision_id: UUID) -> None:
        issues = await self._aggregator_issues(
            session_id=session_id, revision_id=None
        )
        options = await self._options(session_id=session_id, revision_id=None)
        score = await self._aggregator_score(session_id=session_id, revision_id=None)
        self._db.add_all(
            [_clone_aggregator_issue(row, revision_id) for row in issues]
        )
        self._db.add_all([_clone_option(row, revision_id) for row in options])
        if score is not None:
            self._db.add(_clone_aggregator_score(score, revision_id))
        await self._db.flush()

    async def _reset_aggregator(
        self, session_id: UUID, from_revision_id: UUID | None
    ) -> None:
        await self._db.execute(
            delete(AggregatorIssue).where(
                AggregatorIssue.session_id == session_id,
                AggregatorIssue.stage_revision_id.is_(None),
            )
        )
        await self._db.execute(
            delete(HandlingOption).where(
                HandlingOption.session_id == session_id,
                HandlingOption.stage_revision_id.is_(None),
            )
        )
        await self._db.execute(
            delete(AggregatorScore).where(
                AggregatorScore.session_id == session_id,
                AggregatorScore.stage_revision_id.is_(None),
            )
        )
        if from_revision_id is None:
            return
        issues = await self._aggregator_issues(
            session_id=session_id, revision_id=from_revision_id
        )
        options = await self._options(
            session_id=session_id, revision_id=from_revision_id
        )
        score = await self._aggregator_score(
            session_id=session_id, revision_id=from_revision_id
        )
        self._db.add_all([_clone_aggregator_issue(row, None) for row in issues])
        self._db.add_all([_clone_option(row, None) for row in options])
        if score is not None:
            self._db.add(_clone_aggregator_score(score, None))
        await self._db.flush()

    async def _issues(
        self,
        *,
        session_id: UUID,
        node: str,
        revision_id: UUID | None,
    ) -> list[JudgeIssue]:
        revision_filter = (
            JudgeIssue.stage_revision_id.is_(None)
            if revision_id is None
            else JudgeIssue.stage_revision_id == revision_id
        )
        rows = await self._db.scalars(
            select(JudgeIssue)
            .where(
                JudgeIssue.session_id == session_id,
                JudgeIssue.node == node,
                revision_filter,
            )
            .order_by(JudgeIssue.sort_index, JudgeIssue.id)
        )
        return list(rows.all())

    async def _aggregator_issues(
        self, *, session_id: UUID, revision_id: UUID | None
    ) -> list[AggregatorIssue]:
        revision_filter = (
            AggregatorIssue.stage_revision_id.is_(None)
            if revision_id is None
            else AggregatorIssue.stage_revision_id == revision_id
        )
        rows = await self._db.scalars(
            select(AggregatorIssue)
            .where(
                AggregatorIssue.session_id == session_id,
                revision_filter,
            )
            .order_by(AggregatorIssue.sort_index, AggregatorIssue.id)
        )
        return list(rows.all())

    async def _options(
        self, *, session_id: UUID, revision_id: UUID | None
    ) -> list[HandlingOption]:
        revision_filter = (
            HandlingOption.stage_revision_id.is_(None)
            if revision_id is None
            else HandlingOption.stage_revision_id == revision_id
        )
        rows = await self._db.scalars(
            select(HandlingOption)
            .where(
                HandlingOption.session_id == session_id,
                revision_filter,
            )
            .order_by(HandlingOption.sort_index, HandlingOption.id)
        )
        return list(rows.all())

    async def _score(
        self, *, session_id: UUID, revision_id: UUID | None
    ) -> ConferenceScore | None:
        revision_filter = (
            ConferenceScore.stage_revision_id.is_(None)
            if revision_id is None
            else ConferenceScore.stage_revision_id == revision_id
        )
        return await self._db.scalar(
            select(ConferenceScore).where(
                ConferenceScore.session_id == session_id,
                revision_filter,
            )
        )

    async def _aggregator_score(
        self, *, session_id: UUID, revision_id: UUID | None
    ) -> AggregatorScore | None:
        revision_filter = (
            AggregatorScore.stage_revision_id.is_(None)
            if revision_id is None
            else AggregatorScore.stage_revision_id == revision_id
        )
        return await self._db.scalar(
            select(AggregatorScore).where(
                AggregatorScore.session_id == session_id,
                revision_filter,
            )
        )
