"""Judgement generate, Judge Run reads, and SSE."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import attributes

from app.core.errors import OperationalErrorException
from app.modules.judgement.catalog import (
    GENERATABLE_JUDGE_NODES,
    JUDGE_NODES,
)
from app.modules.judgement.issues import merge_issues, normalize_llm_issues
from app.modules.judgement.models import JudgeIssue
from app.modules.judgement.schemas import (
    DoneEvent,
    DraftPatchEvent,
    ErrorEvent,
    JudgeIssueDraft,
    JudgeIssueResponse,
    JudgeLlmResponse,
    JudgementGenerateRequest,
    JudgementNode,
    JudgeRunResponse,
    ProgressEvent,
)
from app.modules.judgement.verifiers import (
    gap_unsupported_by_sources,
    unsupported_citation,
)
from app.modules.loop.catalog import NodeHeadStatus, WorkflowNode, ancestors
from app.modules.loop.deps import get_stage_ports
from app.modules.loop.models import LoopSession, NodeHead
from app.modules.loop.service import LoopService
from app.ports.llm import LlmPort


@dataclass
class GenerationRun:
    session_id: UUID
    account_id: UUID
    node: WorkflowNode
    version: int
    view: dict[str, Any]


class JudgementService:
    def __init__(self, db: AsyncSession, llm: LlmPort) -> None:
        self._db = db
        self._llm = llm

    async def get_run(
        self,
        *,
        session_id: UUID,
        account_id: UUID,
        node: JudgementNode,
        stage_revision_id: UUID | None = None,
    ) -> JudgeRunResponse:
        await self._load_owned_session(session_id, account_id)
        port = get_stage_ports(self._db)[node.value]
        payload = await port.project(
            session_id=session_id,
            node=node.value,
            revision_id=stage_revision_id,
        )
        return JudgeRunResponse(
            node=node,
            issues=[
                JudgeIssueResponse(
                    id=UUID(item["id"]),
                    finding_kind=item["finding_kind"],
                    severity=item["severity"],
                    reason=item["reason"],
                    suggestion=item["suggestion"],
                    target_card_id=(
                        UUID(item["target_card_id"])
                        if item.get("target_card_id")
                        else None
                    ),
                )
                for item in payload.get("issues", [])
            ],
        )

    async def begin_generation(
        self,
        *,
        session_id: UUID,
        account_id: UUID,
        node: JudgementNode,
        body: JudgementGenerateRequest,
    ) -> GenerationRun:
        workflow_node = WorkflowNode(node.value)
        if workflow_node not in GENERATABLE_JUDGE_NODES:
            raise OperationalErrorException(
                status_code=status.HTTP_409_CONFLICT,
                code="judge_generate_unavailable",
                detail="Generate is not available for this Judge in this ticket",
            )
        session = await self._load_owned_session(session_id, account_id)
        if session.valid_spec_version_id is None:
            raise OperationalErrorException(
                status_code=status.HTTP_409_CONFLICT,
                code="valid_spec_version_required",
                detail="Generate requires a Valid Spec Version",
            )
        working = WorkflowNode(session.working_draft_node)
        if working not in JUDGE_NODES:
            raise OperationalErrorException(
                status_code=status.HTTP_409_CONFLICT,
                code="invalid_working_draft_target",
                detail=(
                    "generate must target an Independent judges Workflow Node "
                    "or run after that Loop Stage is prepared"
                ),
            )
        await self._assert_upstream_current(session_id, workflow_node)
        await self._assert_stale_reaccept(
            session_id, workflow_node, body.stale_reaccept
        )
        view = await LoopService(self._db).project_prompt_view(
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
            node=workflow_node,
            version=version,
            view=view,
        )

    async def generate(self, run: GenerationRun) -> AsyncIterator[dict[str, Any]]:
        try:
            label = _judge_label(run.node)
            yield ProgressEvent(
                node=JudgementNode(run.node.value),
                message=f"Starting {label}",
                pct=0,
            ).model_dump(mode="json")
            parsed = await self._llm.complete_structured(
                system=_judge_system(run.node),
                prompt=_prompt_payload(run.view),
                schema=JudgeLlmResponse,
            )
            llm_issues = normalize_llm_issues(parsed.issues)
            verifier_issues = _verifier_issues(run.node, run.view)
            issues = merge_issues(llm_issues, verifier_issues)
            await self._replace_working_issues(
                session_id=run.session_id, node=run.node, issues=issues
            )
            await self._mark_generated_since_prepare(run.session_id, run.node.value)
            await self._db.commit()
            stored = await self.get_run(
                session_id=run.session_id,
                account_id=run.account_id,
                node=JudgementNode(run.node.value),
            )
            yield DraftPatchEvent(
                node=JudgementNode(run.node.value),
                issues=stored.issues,
            ).model_dump(mode="json")
            yield ProgressEvent(
                node=JudgementNode(run.node.value),
                message=f"{label} complete",
                pct=100,
            ).model_dump(mode="json")
            yield DoneEvent(
                node=JudgementNode(run.node.value),
                version=run.version,
            ).model_dump(mode="json")
        except Exception as exc:  # noqa: BLE001 - stream converts failures to typed events
            await self._db.rollback()
            yield ErrorEvent(
                node=JudgementNode(run.node.value),
                code="generation_failed",
                message=f"Judge generation failed: {type(exc).__name__}",
            ).model_dump(mode="json")

    async def _replace_working_issues(
        self,
        *,
        session_id: UUID,
        node: WorkflowNode,
        issues: list,
    ) -> None:
        await self._db.execute(
            delete(JudgeIssue).where(
                JudgeIssue.session_id == session_id,
                JudgeIssue.node == node.value,
                JudgeIssue.stage_revision_id.is_(None),
            )
        )
        self._db.add_all(
            [
                JudgeIssue(
                    session_id=session_id,
                    node=node.value,
                    finding_kind=item.finding_kind,
                    severity=item.severity,
                    reason=item.reason,
                    suggestion=item.suggestion,
                    target_card_id=item.target_card_id,
                    sort_index=index,
                )
                for index, item in enumerate(issues)
            ]
        )
        await self._db.flush()

    async def _load_owned_session(
        self, session_id: UUID, account_id: UUID
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
        self, session_id: UUID, node: WorkflowNode
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

    async def _assert_stale_reaccept(
        self, session_id: UUID, node: WorkflowNode, stale_reaccept: bool
    ) -> None:
        head = await self._db.scalar(
            select(NodeHead).where(
                NodeHead.session_id == session_id, NodeHead.node == node.value
            )
        )
        if head is None:
            return
        if (
            head.status_enum() is NodeHeadStatus.STALE
            and not head.generated_since_prepare
            and not stale_reaccept
        ):
            raise OperationalErrorException(
                status_code=status.HTTP_409_CONFLICT,
                code="stale_reaccept_required",
                detail=(
                    "Generating a Stale Judge without a post-prepare run "
                    "requires stale_reaccept"
                ),
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
        attributes.set_committed_value(session, "version", row.version)
        return row.version


def _prompt_payload(view: dict[str, Any]) -> str:
    return json.dumps(view, ensure_ascii=False, sort_keys=True)


def _judge_label(node: WorkflowNode) -> str:
    return node.value.replace("_", " ").title()


def _judge_system(node: WorkflowNode) -> str:
    if node is WorkflowNode.EVIDENCE_JUDGE:
        return "judge-evidence"
    return "judge-gap"


def _verifier_issues(node: WorkflowNode, view: dict[str, Any]) -> list[JudgeIssueDraft]:
    if node is WorkflowNode.GAP_JUDGE:
        return gap_unsupported_by_sources(view)
    if node is WorkflowNode.EVIDENCE_JUDGE:
        return unsupported_citation(view)
    return []
