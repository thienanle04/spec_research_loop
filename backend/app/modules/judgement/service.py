"""Judgement generate, Judge Run reads, and SSE."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import attributes

from app.adapters.llm import get_llm_port
from app.core.errors import OperationalErrorException
from app.modules.judgement.catalog import (
    FINDING_KIND_FLOOR,
    FIVE_JUDGE_NODES,
    GENERATABLE_JUDGE_NODES,
    JUDGE_NODES,
    FindingKind,
    Severity,
)
from app.modules.judgement.composer import (
    ComposedReport,
    apply_handling_option_phrasing,
    compose_from_view,
    needs_handling_option_phrasing,
    plant_handling_options,
)
from app.modules.judgement.inflight import aggregator_phrasing_lock
from app.modules.judgement.issues import merge_issues, normalize_llm_issues
from app.modules.judgement.models import (
    AggregatorIssue,
    AggregatorScore,
    ConferenceScore,
    HandlingOption,
    JudgeIssue,
)
from app.modules.judgement.schemas import (
    AggregatorLlmResponse,
    ClusterMap,
    ConferenceLlmResponse,
    ConferenceScores,
    DoneEvent,
    DraftPatchEvent,
    ErrorEvent,
    HandlingOptionResponse,
    JudgeIssueDraft,
    JudgeIssueResponse,
    JudgeLlmResponse,
    JudgementGenerateRequest,
    JudgementNode,
    JudgeRunResponse,
    ProgressEvent,
    ReadinessState,
    grounds_payload,
    parse_grounds,
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
    def __init__(self, db: AsyncSession, llm: LlmPort | None = None) -> None:
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
        raw_scores = payload.get("scores")
        issues = [_issue_response(item) for item in payload.get("issues", [])]
        clusters = payload.get("clusters")
        options = payload.get("handling_options")
        readiness = payload.get("readiness")
        return JudgeRunResponse(
            node=node,
            issues=issues,
            scores=(
                ConferenceScores.model_validate(raw_scores)
                if raw_scores is not None
                else None
            ),
            clusters=(
                ClusterMap(
                    consensus=[_issue_response(item) for item in clusters.get("consensus", [])],
                    disagreement=[
                        _issue_response(item) for item in clusters.get("disagreement", [])
                    ],
                )
                if isinstance(clusters, dict)
                else None
            ),
            handling_options=(
                [
                    HandlingOptionResponse(
                        id=UUID(item["id"]),
                        finding_kind=item["finding_kind"],
                        source_node=item["source_node"],
                        label=item["label"],
                        target_node=item["target_node"],
                        prose=item["prose"],
                        aggregator_issue_id=(
                            UUID(item["aggregator_issue_id"])
                            if item.get("aggregator_issue_id")
                            else None
                        ),
                    )
                    for item in options
                ]
                if isinstance(options, list)
                else None
            ),
            readiness=ReadinessState(readiness) if isinstance(readiness, str) else None,
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
        await self._assert_five_judge_heads_current(session_id, workflow_node)
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

    async def begin_pending_generation(
        self,
        *,
        session_id: UUID,
        account_id: UUID,
        body: JudgementGenerateRequest,
    ) -> list[GenerationRun]:
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
        rows = await self._db.scalars(
            select(NodeHead).where(NodeHead.session_id == session_id)
        )
        heads = {WorkflowNode(row.node): row for row in rows.all()}
        pending = [
            node
            for node in FIVE_JUDGE_NODES
            if heads[node].status_enum()
            in (NodeHeadStatus.EMPTY, NodeHeadStatus.STALE)
        ]
        if not pending:
            raise OperationalErrorException(
                status_code=status.HTTP_409_CONFLICT,
                code="no_pending_judges",
                detail="No empty or Stale Judges to run",
            )
        needs_ack = any(
            heads[node].status_enum() is NodeHeadStatus.STALE
            and not heads[node].generated_since_prepare
            for node in pending
        )
        if needs_ack and not body.stale_reaccept:
            raise OperationalErrorException(
                status_code=status.HTTP_409_CONFLICT,
                code="stale_reaccept_required",
                detail=(
                    "Generating Stale Judges without a post-prepare run "
                    "requires stale_reaccept"
                ),
            )
        for node in pending:
            await self._assert_upstream_current(session_id, node)
        loop = LoopService(self._db)
        views: list[tuple[WorkflowNode, dict[str, Any]]] = []
        for node in pending:
            view = await loop.project_prompt_view(
                session_id=session_id,
                account_id=account_id,
                node=node,
            )
            views.append((node, view))
        version = await self._claim_version(
            session=session,
            account_id=account_id,
            expected_version=body.expected_version,
        )
        return [
            GenerationRun(
                session_id=session_id,
                account_id=account_id,
                node=node,
                version=version,
                view=view,
            )
            for node, view in views
        ]

    async def generate(self, run: GenerationRun) -> AsyncIterator[dict[str, Any]]:
        if run.node is WorkflowNode.AGGREGATOR:
            async for event in self._run_aggregator(run):
                yield event
            return
        try:
            yield _starting_event(run)
            llm = self._llm if self._llm is not None else self._port_for(run.node)
            await self._complete_and_persist(run, llm)
            await self._db.commit()
            async for event in self._result_events(run):
                yield event
        except Exception as exc:  # noqa: BLE001 - stream converts failures to typed events
            await self._db.rollback()
            yield _failure_event(run, exc)
            return
        if run.node in FIVE_JUDGE_NODES:
            async for event in self._generate_aggregator_if_five_current(run):
                yield event

    async def generate_pending(
        self, runs: list[GenerationRun]
    ) -> AsyncIterator[dict[str, Any]]:
        for run in runs:
            yield _starting_event(run)

        async def _invoke(
            run: GenerationRun,
        ) -> tuple[GenerationRun, Any, BaseException | None]:
            try:
                parsed = await self._complete_llm(run, self._port_for(run.node))
            except Exception as exc:  # noqa: BLE001 - per-Judge failure stays on that node
                return run, None, exc
            return run, parsed, None

        try:
            completed = await asyncio.gather(*[_invoke(run) for run in runs])
            last_success: GenerationRun | None = None
            for run, parsed, error in completed:
                if error is not None:
                    yield _failure_event(run, error)
                    continue
                await self._persist_completed(run, parsed)
                await self._confirm_completed_judge(run)
                await self._db.commit()
                async for event in self._result_events(run):
                    yield event
                last_success = run
        except Exception as exc:  # noqa: BLE001 - stream converts failures to typed events
            await self._db.rollback()
            yield _failure_event(runs[0], exc)
            return
        if last_success is not None:
            async for event in self._generate_aggregator_if_five_current(last_success):
                yield event

    def _port_for(self, node: WorkflowNode) -> LlmPort:
        return get_llm_port(node.value)

    async def _complete_llm(self, run: GenerationRun, llm: LlmPort) -> Any:
        if run.node is WorkflowNode.AGGREGATOR:
            raise RuntimeError("Aggregator generate uses _run_aggregator")
        if run.node is WorkflowNode.CONFERENCE_JUDGE:
            parsed = await llm.complete_structured(
                system=_judge_system(run.node),
                prompt=_prompt_payload(run.view),
                schema=ConferenceLlmResponse,
            )
            return ("conference", parsed.scores)
        parsed = await llm.complete_structured(
            system=_judge_system(run.node),
            prompt=_prompt_payload(run.view),
            schema=JudgeLlmResponse,
        )
        llm_issues = normalize_llm_issues(parsed.issues)
        verifier_issues = _verifier_issues(run.node, run.view)
        return ("issues", merge_issues(llm_issues, verifier_issues))

    async def _persist_completed(self, run: GenerationRun, parsed: Any) -> None:
        kind = parsed[0]
        if kind == "conference":
            await self._replace_working_issues(
                session_id=run.session_id, node=run.node, issues=[]
            )
            await self._replace_working_scores(
                session_id=run.session_id, scores=parsed[1]
            )
            return
        await self._replace_working_issues(
            session_id=run.session_id, node=run.node, issues=parsed[1]
        )

    async def _complete_and_persist(self, run: GenerationRun, llm: LlmPort) -> None:
        parsed = await self._complete_llm(run, llm)
        await self._persist_completed(run, parsed)
        await self._confirm_completed_judge(run)

    async def _confirm_completed_judge(self, run: GenerationRun) -> None:
        if run.node not in FIVE_JUDGE_NODES:
            await self._mark_generated_since_prepare(run.session_id, run.node.value)
            return
        await LoopService(self._db).confirm_generated_judge(
            session_id=run.session_id,
            account_id=run.account_id,
            node=run.node,
        )

    async def _run_aggregator(
        self, run: GenerationRun, *, emit_starting: bool = True
    ) -> AsyncIterator[dict[str, Any]]:
        epoch = aggregator_phrasing_lock.bump_epoch(run.session_id)
        acquired = False
        try:
            while not await aggregator_phrasing_lock.acquire(run.session_id):
                await asyncio.sleep(0.05)
            acquired = True
            if emit_starting:
                yield _starting_event(run)
            report = compose_from_view(run.view)
            await self._replace_working_aggregator(
                session_id=run.session_id, report=report
            )
            await self._mark_generated_since_prepare(
                run.session_id, run.node.value
            )
            await self._db.commit()
            yield await self._draft_patch_event(run)
            if needs_handling_option_phrasing(report.issues):
                llm = (
                    self._llm
                    if self._llm is not None
                    else self._port_for(WorkflowNode.AGGREGATOR)
                )
                try:
                    parsed = await llm.complete_structured(
                        system=_aggregator_system(),
                        prompt=_prompt_payload(run.view),
                        schema=AggregatorLlmResponse,
                    )
                    if aggregator_phrasing_lock.epoch(run.session_id) == epoch:
                        await self._apply_working_option_phrasing(
                            session_id=run.session_id,
                            drafts=parsed.options,
                            issues=report.issues,
                        )
                        await self._db.commit()
                except Exception:  # noqa: BLE001 - templates remain; generate succeeds
                    await self._db.rollback()
            yield await self._draft_patch_event(run)
            yield ProgressEvent(
                node=JudgementNode(run.node.value),
                message=f"{_judge_label(run.node)} complete",
                pct=100,
            ).model_dump(mode="json")
            yield DoneEvent(
                node=JudgementNode(run.node.value),
                version=run.version,
            ).model_dump(mode="json")
        except Exception as exc:  # noqa: BLE001 - compose failure is not Confirm
            await self._db.rollback()
            yield _failure_event(run, exc)
        finally:
            if acquired:
                await aggregator_phrasing_lock.release(run.session_id)

    async def _draft_patch_event(self, run: GenerationRun) -> dict[str, Any]:
        stored = await self.get_run(
            session_id=run.session_id,
            account_id=run.account_id,
            node=JudgementNode(run.node.value),
        )
        return DraftPatchEvent(
            node=JudgementNode(run.node.value),
            issues=stored.issues,
            scores=stored.scores,
            clusters=stored.clusters,
            handling_options=stored.handling_options,
            readiness=stored.readiness,
        ).model_dump(mode="json")

    async def _apply_working_option_phrasing(
        self,
        *,
        session_id: UUID,
        drafts: list[Any],
        issues: list,
    ) -> None:
        rows = list(
            await self._db.scalars(
                select(HandlingOption)
                .where(
                    HandlingOption.session_id == session_id,
                    HandlingOption.stage_revision_id.is_(None),
                )
                .order_by(HandlingOption.sort_index, HandlingOption.id)
            )
        )
        planted = [
            {
                "id": str(row.id),
                "finding_kind": row.finding_kind,
                "source_node": row.source_node,
                "label": row.label,
                "target_node": row.target_node,
                "prose": row.prose,
            }
            for row in rows
        ]
        updated = apply_handling_option_phrasing(planted, drafts, issues)
        by_id = {item["id"]: item for item in updated}
        for row in rows:
            item = by_id.get(str(row.id))
            if item is None:
                continue
            row.label = item["label"]
            row.prose = item["prose"]
        await self._db.flush()

    async def _generate_aggregator_if_five_current(
        self, source: GenerationRun
    ) -> AsyncIterator[dict[str, Any]]:
        agg_run: GenerationRun | None = None
        try:
            if not await self._five_judge_heads_are_current(source.session_id):
                return
            session = await self._load_owned_session(
                source.session_id, source.account_id
            )
            await self._assert_upstream_current(
                source.session_id, WorkflowNode.AGGREGATOR
            )
            view = await LoopService(self._db).project_prompt_view(
                session_id=source.session_id,
                account_id=source.account_id,
                node=WorkflowNode.AGGREGATOR,
            )
            version = await self._claim_version(
                session=session,
                account_id=source.account_id,
                expected_version=session.version,
            )
            agg_run = GenerationRun(
                session_id=source.session_id,
                account_id=source.account_id,
                node=WorkflowNode.AGGREGATOR,
                version=version,
                view=view,
            )
            yield _starting_event(agg_run)
            async for event in self._run_aggregator(agg_run, emit_starting=False):
                yield event
        except Exception as exc:  # noqa: BLE001 - Aggregator failure is not Confirm
            await self._db.rollback()
            failed = agg_run or GenerationRun(
                session_id=source.session_id,
                account_id=source.account_id,
                node=WorkflowNode.AGGREGATOR,
                version=source.version,
                view={},
            )
            yield _failure_event(failed, exc)

    async def _result_events(
        self, run: GenerationRun
    ) -> AsyncIterator[dict[str, Any]]:
        stored = await self.get_run(
            session_id=run.session_id,
            account_id=run.account_id,
            node=JudgementNode(run.node.value),
        )
        yield DraftPatchEvent(
            node=JudgementNode(run.node.value),
            issues=stored.issues,
            scores=stored.scores,
            clusters=stored.clusters,
            handling_options=stored.handling_options,
            readiness=stored.readiness,
        ).model_dump(mode="json")
        yield ProgressEvent(
            node=JudgementNode(run.node.value),
            message=f"{_judge_label(run.node)} complete",
            pct=100,
        ).model_dump(mode="json")
        yield DoneEvent(
            node=JudgementNode(run.node.value),
            version=run.version,
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
                    grounds=grounds_payload(item.grounds),
                    sort_index=index,
                )
                for index, item in enumerate(issues)
            ]
        )
        await self._db.flush()

    async def _replace_working_scores(
        self, *, session_id: UUID, scores: ConferenceScores
    ) -> None:
        await self._db.execute(
            delete(ConferenceScore).where(
                ConferenceScore.session_id == session_id,
                ConferenceScore.stage_revision_id.is_(None),
            )
        )
        self._db.add(
            ConferenceScore(
                session_id=session_id,
                originality=scores.originality,
                significance=scores.significance,
                soundness=scores.soundness,
                clarity=scores.clarity,
                reproducibility=scores.reproducibility,
            )
        )
        await self._db.flush()

    async def _replace_working_aggregator(
        self,
        *,
        session_id: UUID,
        report: ComposedReport,
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
        issue_rows: list[AggregatorIssue] = []
        for index, item in enumerate(report.issues):
            issue_rows.append(
                AggregatorIssue(
                    session_id=session_id,
                    source_node=item.source_node,
                    source_issue_id=item.source_issue_id,
                    finding_kind=item.finding_kind,
                    severity=item.severity,
                    reason=item.reason,
                    suggestion=item.suggestion,
                    target_card_id=item.target_card_id,
                    grounds=item.grounds,
                    cluster=item.cluster,
                    sort_index=index,
                )
            )
        self._db.add_all(issue_rows)
        await self._db.flush()
        option_rows: list[HandlingOption] = []
        sort_index = 0
        for row, item in zip(issue_rows, report.issues, strict=True):
            for option in plant_handling_options([item]):
                option_rows.append(
                    HandlingOption(
                        session_id=session_id,
                        aggregator_issue_id=row.id,
                        finding_kind=option["finding_kind"],
                        source_node=option["source_node"],
                        label=option["label"],
                        target_node=option["target_node"],
                        prose=option["prose"],
                        sort_index=sort_index,
                    )
                )
                sort_index += 1
        self._db.add_all(option_rows)
        if report.scores is not None:
            self._db.add(
                AggregatorScore(
                    session_id=session_id,
                    originality=report.scores["originality"],
                    significance=report.scores["significance"],
                    soundness=report.scores["soundness"],
                    clarity=report.scores["clarity"],
                    reproducibility=report.scores["reproducibility"],
                )
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

    async def _five_judge_heads_are_current(self, session_id: UUID) -> bool:
        rows = await self._db.scalars(
            select(NodeHead).where(NodeHead.session_id == session_id)
        )
        heads = {WorkflowNode(row.node): row for row in rows.all()}
        return all(
            heads[judge].status == NodeHeadStatus.CURRENT.value
            for judge in FIVE_JUDGE_NODES
        )

    async def _assert_five_judge_heads_current(
        self, session_id: UUID, node: WorkflowNode
    ) -> None:
        if node is not WorkflowNode.AGGREGATOR:
            return
        if not await self._five_judge_heads_are_current(session_id):
            raise OperationalErrorException(
                status_code=status.HTTP_409_CONFLICT,
                code="judge_heads_not_current",
                detail="Aggregator generate requires all five Judge Node Heads to be current",
            )

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


def _issue_response(item: dict[str, Any]) -> JudgeIssueResponse:
    raw_card = item.get("target_card_id")
    raw_id = item["id"]
    return JudgeIssueResponse(
        id=UUID(raw_id),
        finding_kind=item["finding_kind"],
        severity=item["severity"],
        reason=item.get("reason") or "",
        suggestion=item.get("suggestion") or "",
        target_card_id=UUID(raw_card) if raw_card else None,
        source_node=item.get("source_node"),
        cluster=item.get("cluster"),
        grounds=parse_grounds(item.get("grounds")),
    )


def _starting_event(run: GenerationRun) -> dict[str, Any]:
    return ProgressEvent(
        node=JudgementNode(run.node.value),
        message=f"Starting {_judge_label(run.node)}",
        pct=0,
    ).model_dump(mode="json")


def _failure_event(run: GenerationRun, exc: BaseException) -> dict[str, Any]:
    return ErrorEvent(
        node=JudgementNode(run.node.value),
        code="generation_failed",
        message=f"Judge generation failed: {type(exc).__name__}",
    ).model_dump(mode="json")


def _prompt_payload(view: dict[str, Any]) -> str:
    return json.dumps(view, ensure_ascii=False, sort_keys=True)


def _judge_label(node: WorkflowNode) -> str:
    return node.value.replace("_", " ").title()


def _kind_lines(kinds: tuple[FindingKind, ...]) -> str:
    return "\n".join(
        f"- {kind.value}: Severity floor {FINDING_KIND_FLOOR[kind].value}"
        for kind in kinds
    )


def _judge_independence_rules() -> str:
    return (
        "Evaluate independently. Do not use another Judge Run. "
        "Do not invent Finding Kinds; unknown tags are dropped. "
        "You may raise Severity above the floor, never lower it. "
        "Do not drop or lower verifier-emitted Issues. "
        "Do not invent Other as a Finding Kind."
    )


def _judge_system(node: WorkflowNode) -> str:
    if node is WorkflowNode.CONFERENCE_JUDGE:
        return (
            "You are the Conference Judge for a Valid Spec Version. "
            "Emit criterion scores only for originality, significance, soundness, "
            "clarity, and reproducibility. Do not emit Judge Issues or Finding Kinds. "
            "Evaluate independently. Do not use another Judge Run."
        )
    catalogs: dict[WorkflowNode, tuple[FindingKind, ...]] = {
        WorkflowNode.GAP_JUDGE: (
            FindingKind.GAP_UNSUPPORTED_BY_SOURCES,
            FindingKind.GAP_ALREADY_ADDRESSED,
            FindingKind.GAP_UNTESTABLE,
        ),
        WorkflowNode.CONTRIBUTION_JUDGE: (
            FindingKind.CONTRIBUTION_NOT_NOVEL,
            FindingKind.CONTRIBUTION_OVERCLAIMED,
        ),
        WorkflowNode.EVIDENCE_JUDGE: (FindingKind.UNSUPPORTED_CITATION,),
        WorkflowNode.EXPERIMENT_JUDGE: (
            FindingKind.CLAIM_BROADER_THAN_EXPERIMENT,
            FindingKind.EXPERIMENT_INSUFFICIENT_FOR_CLAIM,
        ),
    }
    kinds = catalogs.get(node, catalogs[WorkflowNode.GAP_JUDGE])
    extra = ""
    if node is WorkflowNode.GAP_JUDGE:
        extra = (
            f" Verifiers may emit {FindingKind.GAP_UNSUPPORTED_BY_SOURCES.value} "
            f"at floor {Severity.CRITICAL.value}; do not drop that Issue."
        )
    elif node is WorkflowNode.CONTRIBUTION_JUDGE:
        extra = (
            f" {FindingKind.CONTRIBUTION_OVERCLAIMED.value} means the contribution "
            "is broader than the gap, problem, or related work. "
            "Do not evaluate Claim Cards."
        )
    elif node is WorkflowNode.EVIDENCE_JUDGE:
        extra = (
            f" Verifiers may emit {FindingKind.UNSUPPORTED_CITATION.value} "
            f"at floor {Severity.CRITICAL.value}; do not drop that Issue."
        )
    return (
        f"You are the {_judge_label(node)} for a Valid Spec Version. "
        "Emit Judge Issues using only these Finding Kinds:\n"
        f"{_kind_lines(kinds)}\n"
        f"{_judge_independence_rules()}"
        f"{extra}"
    )


def _aggregator_system() -> str:
    return (
        "You phrase Handling Options only for the Aggregator Report. "
        "You are not a sixth Judge. Do not change Severity. "
        "Do not invent a majority verdict. "
        "Do not invent Other; Other is an Account-supplied Handling Option. "
        "Do not drop verifier Issues from the composed report. "
        "Phrase options for CRITICAL and MAJOR Issues only."
    )


def _verifier_issues(node: WorkflowNode, view: dict[str, Any]) -> list[JudgeIssueDraft]:
    if node is WorkflowNode.GAP_JUDGE:
        return gap_unsupported_by_sources(view)
    if node is WorkflowNode.EVIDENCE_JUDGE:
        return unsupported_citation(view)
    return []
