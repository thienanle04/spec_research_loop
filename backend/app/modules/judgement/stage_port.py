"""Judgement StagePort: freeze Judge Issues (and Conference scores) onto Stage Revisions."""

from typing import Any
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.judgement.catalog import JUDGE_NODES
from app.modules.judgement.models import ConferenceScore, JudgeIssue
from app.modules.loop.catalog import WorkflowNode


def _issue_payload(row: JudgeIssue) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "finding_kind": row.finding_kind,
        "severity": row.severity,
        "reason": row.reason,
        "suggestion": row.suggestion,
        "target_card_id": str(row.target_card_id) if row.target_card_id else None,
        "sort_index": row.sort_index,
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
        issues = await self._issues(
            session_id=session_id, node=node, revision_id=revision_id
        )
        payload: dict[str, Any] = {
            "issues": [_issue_payload(row) for row in issues]
        }
        if node == WorkflowNode.CONFERENCE_JUDGE.value:
            score = await self._score(session_id=session_id, revision_id=revision_id)
            payload["scores"] = (
                None
                if score is None
                else {
                    "originality": score.originality,
                    "significance": score.significance,
                    "soundness": score.soundness,
                    "clarity": score.clarity,
                    "reproducibility": score.reproducibility,
                }
            )
        return payload

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
