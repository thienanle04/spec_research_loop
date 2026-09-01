"""Loop Session orchestration."""

from __future__ import annotations

import hashlib
import json
from typing import Any
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import attributes, selectinload

from app.core.errors import OperationalErrorException
from app.modules.loop.catalog import (
    CARD_KIND_OWNERS,
    FIVE_JUDGE_NODES,
    HANDLING_OPTION_TARGETS,
    LOOP_STAGE_NODES,
    WORKFLOW_NODES,
    CardKind,
    DecisionKind,
    LoopStage,
    NodeHeadStatus,
    WorkflowNode,
    ancestors,
    descendants,
    owned_kinds,
    prepare_landing,
    upstream_of_stage,
)
from app.modules.loop.deps import get_stage_ports
from app.modules.loop.export_scratch import project_paper_document
from app.modules.loop.interpretation_turns import (
    apply_account_reply_patch,
    interpretation_confirmable,
)
from app.modules.loop.models import (
    Card,
    Decision,
    ExportScratch,
    ExportScratchSnapshot,
    LoopSession,
    NodeHead,
    SpecVersion,
    StageRevision,
)
from app.modules.loop.prompt_view import prompt_view
from app.modules.loop.schemas import (
    CardBatchMutationResponse,
    CardMutationResponse,
    CardResponse,
    DecisionResponse,
    ExportScratchResponse,
    ExportScratchSnapshotResponse,
    HeadRevisionResponse,
    LoopSessionResponse,
    LoopSessionSummary,
    NodeHeadResponse,
    ReadinessSummary,
    SpecArtifactResponse,
    SpecVersionResponse,
    StageRevisionResponse,
)
from app.ports.stage import StagePort


def _freeze_hash(
    narrative: dict[str, Any],
    cards: list[dict[str, Any]],
    typed_data: Any,
) -> str:
    payload = {"cards": cards, "narrative": narrative, "typed_data": typed_data}
    canonical = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _card_snapshot(cards: list[Card]) -> list[dict[str, Any]]:
    items = [
        {"body": card.body, "id": str(card.id), "kind": card.kind} for card in cards
    ]
    return sorted(items, key=lambda item: item["id"])


def _head_revision(
    head: NodeHead, revisions: dict[UUID, StageRevision]
) -> HeadRevisionResponse | None:
    if head.stage_revision_id is None:
        return None
    revision = revisions.get(head.stage_revision_id)
    if revision is None:
        return None
    return HeadRevisionResponse(
        narrative=dict(revision.narrative),
        card_snapshot=list(revision.card_snapshot),
    )


def _card_ids_for_option(
    issues: list[dict[str, Any]], option: dict[str, Any]
) -> list[str]:
    finding_kind = option.get("finding_kind")
    source_node = option.get("source_node")
    ids: list[str] = []
    seen: set[str] = set()
    for item in issues:
        if not isinstance(item, dict):
            continue
        if item.get("finding_kind") != finding_kind:
            continue
        if item.get("source_node") != source_node:
            continue
        card_id = item.get("target_card_id")
        if isinstance(card_id, str) and card_id and card_id not in seen:
            seen.add(card_id)
            ids.append(card_id)
    return ids


class LoopService:
    def __init__(
        self, db: AsyncSession, stage_ports: dict[str, StagePort] | None = None
    ) -> None:
        self._db = db
        self._ports = stage_ports or get_stage_ports(db)

    async def create_session(
        self, *, account_id: UUID, title: str | None
    ) -> LoopSessionResponse:
        session = LoopSession(
            account_id=account_id,
            title=title,
            working_draft_node=WorkflowNode.IDEA_INTERPRETATION.value,
            working_draft_narrative={},
            working_draft_narratives={WorkflowNode.IDEA_INTERPRETATION.value: {}},
        )
        self._db.add(session)
        await self._db.flush()
        for node in WORKFLOW_NODES:
            self._db.add(
                NodeHead(
                    session_id=session.id,
                    node=node.value,
                    status=NodeHeadStatus.EMPTY.value,
                )
            )
        await self._db.commit()
        return await self.get_session(session_id=session.id, account_id=account_id)

    async def list_sessions(self, *, account_id: UUID) -> list[LoopSessionSummary]:
        result = await self._db.scalars(
            select(LoopSession)
            .where(LoopSession.account_id == account_id)
            .order_by(LoopSession.updated_at.desc(), LoopSession.id.desc())
        )
        return [LoopSessionSummary.model_validate(row) for row in result.all()]

    async def get_session(
        self,
        *,
        session_id: UUID,
        account_id: UUID,
        spec_version_id: UUID | None = None,
    ) -> LoopSessionResponse:
        session = await self._load_session(session_id, account_id)
        return await self._to_response(session, spec_version_id=spec_version_id)

    async def get_readiness(
        self, *, session_id: UUID, account_id: UUID
    ) -> ReadinessSummary:
        session = await self._load_session(session_id, account_id)
        return await self._readiness(session)

    async def patch_title(
        self,
        *,
        session_id: UUID,
        account_id: UUID,
        title: str | None,
    ) -> LoopSessionResponse:
        updated = await self._db.execute(
            update(LoopSession)
            .where(
                LoopSession.id == session_id,
                LoopSession.account_id == account_id,
            )
            .values(
                title=title,
                updated_at=func.now(),
            )
            .returning(LoopSession.id)
            .execution_options(synchronize_session=False)
        )
        if updated.one_or_none() is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Loop Session not found"
            )
        await self._db.commit()
        return await self.get_session(session_id=session_id, account_id=account_id)

    async def patch_working_draft(
        self,
        *,
        session_id: UUID,
        account_id: UUID,
        node: WorkflowNode | None,
        narrative: dict[str, Any] | None,
        expected_version: int,
    ) -> LoopSessionResponse:
        if node is None and narrative is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Provide node and/or narrative",
            )
        session = await self._load_session(session_id, account_id)
        if session.version != expected_version:
            raise OperationalErrorException(
                status_code=status.HTTP_409_CONFLICT,
                code="version_conflict",
                detail="Loop Session was changed by another request",
                current_version=session.version,
            )
        heads = {head.node_enum(): head for head in session.node_heads}
        next_node = session.working_draft_node
        next_narrative = dict(session.working_draft_narrative)
        saved_narratives = dict(session.working_draft_narratives)
        saved_narratives[session.working_draft_node] = next_narrative
        if node is not None:
            for ancestor in ancestors(node):
                if heads[ancestor].status_enum() != NodeHeadStatus.CURRENT:
                    raise OperationalErrorException(
                        status_code=status.HTTP_409_CONFLICT,
                        code="upstream_not_current",
                        detail="Upstream Node Heads must be current",
                    )
            working = WorkflowNode(session.working_draft_node)
            independent_judges = LOOP_STAGE_NODES[LoopStage.INDEPENDENT_JUDGES]
            independent_judges_dashboard = (
                working in independent_judges and node in independent_judges
            )
            if (
                heads[node].status_enum() != NodeHeadStatus.CURRENT
                and not independent_judges_dashboard
            ):
                raise OperationalErrorException(
                    status_code=status.HTTP_409_CONFLICT,
                    code="invalid_working_draft_target",
                    detail="Working Draft can only move to a current Workflow Node",
                )
            next_node = node.value
            saved_narrative = saved_narratives.get(next_node)
            revision_id = heads[node].stage_revision_id
            if isinstance(saved_narrative, dict):
                next_narrative = dict(saved_narrative)
            elif revision_id is not None:
                revision = next(
                    (
                        item
                        for item in session.stage_revisions
                        if item.id == revision_id
                    ),
                    None,
                )
                if revision is not None:
                    next_narrative = dict(revision.narrative)
        if narrative is not None:
            if (
                WorkflowNode(next_node) is WorkflowNode.IDEA_INTERPRETATION
                and "turns" in session.working_draft_narrative
            ):
                next_narrative = apply_account_reply_patch(
                    dict(session.working_draft_narrative),
                    narrative,
                )
            else:
                next_narrative = narrative
        saved_narratives[next_node] = next_narrative
        updated = await self._db.execute(
            update(LoopSession)
            .where(
                LoopSession.id == session_id,
                LoopSession.account_id == account_id,
                LoopSession.version == expected_version,
            )
            .values(
                working_draft_node=next_node,
                working_draft_narrative=next_narrative,
                working_draft_narratives=saved_narratives,
                version=LoopSession.version + 1,
                updated_at=func.now(),
            )
            .returning(LoopSession.version, LoopSession.updated_at)
            .execution_options(synchronize_session=False)
        )
        updated_row = updated.one_or_none()
        if updated_row is None:
            await self._db.refresh(session, attribute_names=["version"])
            raise OperationalErrorException(
                status_code=status.HTTP_409_CONFLICT,
                code="version_conflict",
                detail="Loop Session was changed by another request",
                current_version=session.version,
            )
        attributes.set_committed_value(session, "working_draft_node", next_node)
        attributes.set_committed_value(
            session, "working_draft_narrative", next_narrative
        )
        attributes.set_committed_value(
            session, "working_draft_narratives", saved_narratives
        )
        attributes.set_committed_value(session, "version", updated_row.version)
        attributes.set_committed_value(session, "updated_at", updated_row.updated_at)
        response = await self._to_response(session)
        await self._db.commit()
        return response

    async def list_cards(
        self, *, session_id: UUID, account_id: UUID
    ) -> list[CardResponse]:
        session = await self._load_session(session_id, account_id)
        return [CardResponse.model_validate(card) for card in session.cards]

    async def create_card(
        self,
        *,
        session_id: UUID,
        account_id: UUID,
        kind: CardKind,
        body: dict[str, Any],
        expected_version: int,
    ) -> CardMutationResponse:
        session = await self._load_session(session_id, account_id)
        self._assert_card_owner(session, kind)
        next_version = await self._increment_session_version(
            session,
            session_id=session_id,
            account_id=account_id,
            expected_version=expected_version,
        )
        card = Card(session_id=session.id, kind=kind.value, body=body)
        self._db.add(card)
        await self._db.commit()
        await self._db.refresh(card)
        return self._to_mutation_response(card, next_version)

    async def patch_card(
        self,
        *,
        session_id: UUID,
        account_id: UUID,
        card_id: UUID,
        body: dict[str, Any],
        expected_version: int,
    ) -> CardMutationResponse:
        session = await self._load_session(session_id, account_id)
        card = next((item for item in session.cards if item.id == card_id), None)
        if card is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Card not found"
            )
        self._assert_card_owner(session, card.kind_enum())
        next_version = await self._increment_session_version(
            session,
            session_id=session_id,
            account_id=account_id,
            expected_version=expected_version,
        )
        card.body = body
        await self._db.commit()
        await self._db.refresh(card)
        return self._to_mutation_response(card, next_version)

    async def replace_cards(
        self,
        *,
        session_id: UUID,
        account_id: UUID,
        kind: CardKind,
        bodies: list[dict[str, Any]],
        expected_version: int,
    ) -> CardBatchMutationResponse:
        session = await self._load_session(session_id, account_id)
        self._assert_card_owner(session, kind)
        next_version = await self._increment_session_version(
            session,
            session_id=session_id,
            account_id=account_id,
            expected_version=expected_version,
        )
        remaining = sorted(
            (card for card in session.cards if card.kind_enum() == kind),
            key=lambda card: (card.created_at, str(card.id)),
        )
        saved_cards: list[Card] = []
        for body in bodies:
            role = body.get("role")
            direction_id = body.get("direction_id")
            card = next(
                (
                    item
                    for item in remaining
                    if role is not None
                    and item.body.get("role") == role
                    and direction_id is not None
                    and item.body.get("direction_id") == direction_id
                ),
                None,
            )
            if card is None and role is not None:
                card = next(
                    (item for item in remaining if item.body.get("role") == role),
                    None,
                )
            if card is None and remaining:
                card = remaining[0]
            if card is None:
                card = Card(session_id=session.id, kind=kind.value, body=body)
                self._db.add(card)
            else:
                remaining.remove(card)
            card.body = body
            saved_cards.append(card)
        for card in remaining:
            await self._db.delete(card)
        await self._db.commit()
        for card in saved_cards:
            await self._db.refresh(card)
        return CardBatchMutationResponse(
            cards=[CardResponse.model_validate(card) for card in saved_cards],
            version=next_version,
        )

    async def list_decisions(
        self, *, session_id: UUID, account_id: UUID
    ) -> list[DecisionResponse]:
        session = await self._load_session(session_id, account_id)
        ordered = sorted(session.decisions, key=lambda row: row.created_at)
        return [DecisionResponse.model_validate(row) for row in ordered]

    async def pick_handling_option(
        self,
        *,
        session_id: UUID,
        account_id: UUID,
        expected_version: int,
        handling_option_id: UUID | None,
        prose: str | None,
        target_node: WorkflowNode | None,
    ) -> LoopSessionResponse:
        session = await self._load_session(session_id, account_id)
        if session.working_draft_node != WorkflowNode.AGGREGATOR.value:
            raise OperationalErrorException(
                status_code=status.HTTP_409_CONFLICT,
                code="invalid_working_draft_target",
                detail="PICK requires the Working Draft Aggregator",
            )
        if session.version != expected_version:
            raise OperationalErrorException(
                status_code=status.HTTP_409_CONFLICT,
                code="version_conflict",
                detail="Loop Session was changed by another request",
                current_version=session.version,
            )
        heads = {head.node_enum(): head for head in session.node_heads}
        report = await self._current_aggregator_report(session)
        if handling_option_id is not None:
            option = next(
                (
                    item
                    for item in report["options"]
                    if item.get("id") == str(handling_option_id)
                ),
                None,
            )
            if option is None:
                raise OperationalErrorException(
                    status_code=status.HTTP_409_CONFLICT,
                    code="handling_option_not_found",
                    detail="Handling Option is not on the current Aggregator Report",
                )
            target = WorkflowNode(str(option["target_node"]))
            patch_prose = str(option.get("prose") or "")
            card_ids = _card_ids_for_option(report["issues"], option)
        else:
            other_prose = (prose or "").strip()
            if not other_prose or target_node is None:
                raise OperationalErrorException(
                    status_code=status.HTTP_409_CONFLICT,
                    code="handling_option_not_found",
                    detail="Other requires Account prose and a target Workflow Node",
                )
            if target_node.value not in HANDLING_OPTION_TARGETS:
                raise OperationalErrorException(
                    status_code=status.HTTP_409_CONFLICT,
                    code="invalid_working_draft_target",
                    detail="Other target must be a Handling Option Workflow Node",
                )
            if not report["issues"] and not report["options"]:
                aggregator = heads.get(WorkflowNode.AGGREGATOR)
                if (
                    aggregator is None
                    or aggregator.status_enum() is not NodeHeadStatus.CURRENT
                ):
                    raise OperationalErrorException(
                        status_code=status.HTTP_409_CONFLICT,
                        code="handling_option_not_found",
                        detail="PICK requires a current Aggregator Report",
                    )
            target = target_node
            patch_prose = other_prose
            card_ids = []

        for ancestor in ancestors(target):
            if heads[ancestor].status_enum() != NodeHeadStatus.CURRENT:
                raise OperationalErrorException(
                    status_code=status.HTTP_409_CONFLICT,
                    code="upstream_not_current",
                    detail="Upstream Node Heads must be current",
                )
        if heads[target].status_enum() != NodeHeadStatus.CURRENT:
            raise OperationalErrorException(
                status_code=status.HTTP_409_CONFLICT,
                code="invalid_working_draft_target",
                detail="PICK can only reopen a current Workflow Node",
            )

        next_narrative = self._narrative_for_current_node(session, heads, target)
        next_narrative["suggested_patch"] = patch_prose
        next_narrative["target_card_ids"] = card_ids
        saved_narratives = dict(session.working_draft_narratives)
        saved_narratives[session.working_draft_node] = dict(
            session.working_draft_narrative
        )
        saved_narratives[target.value] = next_narrative
        updated = await self._db.execute(
            update(LoopSession)
            .where(
                LoopSession.id == session_id,
                LoopSession.account_id == account_id,
                LoopSession.version == expected_version,
            )
            .values(
                working_draft_node=target.value,
                working_draft_narrative=next_narrative,
                working_draft_narratives=saved_narratives,
                version=LoopSession.version + 1,
                updated_at=func.now(),
            )
            .returning(LoopSession.version, LoopSession.updated_at)
            .execution_options(synchronize_session=False)
        )
        updated_row = updated.one_or_none()
        if updated_row is None:
            await self._db.refresh(session, attribute_names=["version"])
            raise OperationalErrorException(
                status_code=status.HTTP_409_CONFLICT,
                code="version_conflict",
                detail="Loop Session was changed by another request",
                current_version=session.version,
            )
        attributes.set_committed_value(session, "working_draft_node", target.value)
        attributes.set_committed_value(
            session, "working_draft_narrative", next_narrative
        )
        attributes.set_committed_value(
            session, "working_draft_narratives", saved_narratives
        )
        attributes.set_committed_value(session, "version", updated_row.version)
        attributes.set_committed_value(session, "updated_at", updated_row.updated_at)
        self._db.add(
            Decision(
                session_id=session.id,
                kind=DecisionKind.PICK.value,
                node=target.value,
                stage_revision_id=heads[target].stage_revision_id,
            )
        )
        response = await self._to_response(session)
        await self._db.commit()
        return response

    async def _current_aggregator_report(
        self, session: LoopSession
    ) -> dict[str, list[dict[str, Any]]]:
        port = self._ports[WorkflowNode.AGGREGATOR.value]
        projected = await port.project(
            session_id=session.id,
            node=WorkflowNode.AGGREGATOR.value,
            revision_id=None,
        )
        options = projected.get("handling_options")
        issues = projected.get("issues")
        if not isinstance(options, list):
            options = []
        if not isinstance(issues, list):
            issues = []
        if options or issues:
            return {"options": options, "issues": issues}
        heads = {head.node_enum(): head for head in session.node_heads}
        aggregator = heads.get(WorkflowNode.AGGREGATOR)
        if aggregator is None or aggregator.stage_revision_id is None:
            return {"options": [], "issues": []}
        frozen = await port.project(
            session_id=session.id,
            node=WorkflowNode.AGGREGATOR.value,
            revision_id=aggregator.stage_revision_id,
        )
        frozen_options = frozen.get("handling_options")
        frozen_issues = frozen.get("issues")
        return {
            "options": frozen_options if isinstance(frozen_options, list) else [],
            "issues": frozen_issues if isinstance(frozen_issues, list) else [],
        }

    def _narrative_for_current_node(
        self,
        session: LoopSession,
        heads: dict[WorkflowNode, NodeHead],
        node: WorkflowNode,
    ) -> dict[str, Any]:
        saved_narratives = dict(session.working_draft_narratives)
        saved_narrative = saved_narratives.get(node.value)
        if isinstance(saved_narrative, dict):
            return dict(saved_narrative)
        revision_id = heads[node].stage_revision_id
        if revision_id is None:
            return {}
        revision = next(
            (item for item in session.stage_revisions if item.id == revision_id),
            None,
        )
        if revision is None:
            return {}
        return dict(revision.narrative)

    async def confirm(
        self,
        *,
        session_id: UUID,
        account_id: UUID,
        node: WorkflowNode,
        expected_version: int,
        stale_reaccept: bool = False,
    ) -> LoopSessionResponse:
        session = await self._load_session(session_id, account_id)
        if session.working_draft_node != node.value:
            raise OperationalErrorException(
                status_code=status.HTTP_409_CONFLICT,
                code="invalid_working_draft_target",
                detail="confirm must target the Working Draft Workflow Node",
            )
        heads = {head.node_enum(): head for head in session.node_heads}
        for ancestor in ancestors(node):
            if heads[ancestor].status_enum() != NodeHeadStatus.CURRENT:
                raise OperationalErrorException(
                    status_code=status.HTTP_409_CONFLICT,
                    code="upstream_not_current",
                    detail="Upstream Node Heads must be current",
                )

        if session.version != expected_version:
            raise OperationalErrorException(
                status_code=status.HTTP_409_CONFLICT,
                code="version_conflict",
                detail="Loop Session was changed by another request",
                current_version=session.version,
            )
        head = heads[node]
        if (
            head.status_enum() is NodeHeadStatus.STALE
            and not head.generated_since_prepare
            and not stale_reaccept
        ):
            raise OperationalErrorException(
                status_code=status.HTTP_409_CONFLICT,
                code="stale_reaccept_required",
                detail=(
                    "Confirming a Stale Workflow Node without a post-prepare "
                    "generate requires stale_reaccept"
                ),
            )
        if node is WorkflowNode.IDEA_INTERPRETATION and not interpretation_confirmable(
            dict(session.working_draft_narrative)
        ):
            raise OperationalErrorException(
                status_code=status.HTTP_409_CONFLICT,
                code="interpretation_not_confirmable",
                detail="Confirm requires a non-blank Idea Frame (intent, problem, and research_question)",
            )

        await self._increment_session_version(
            session,
            session_id=session_id,
            account_id=account_id,
            expected_version=expected_version,
        )

        minted = await self._freeze_working_node(session, node)
        if minted:
            if node is WorkflowNode.IDEA_INTERPRETATION:
                saved_narratives = dict(session.working_draft_narratives)
                saved_narratives[node.value] = dict(session.working_draft_narrative)
                saved_narratives[WorkflowNode.IDEA_DECOMPOSITION.value] = {}
                session.working_draft_narratives = saved_narratives
                session.working_draft_node = WorkflowNode.IDEA_DECOMPOSITION.value
                session.working_draft_narrative = {}

        if node is WorkflowNode.FEASIBILITY and (
            minted or session.valid_spec_version_id is None
        ):
            document = await self._assemble_spec(session, heads)
            spec = SpecVersion(session_id=session.id, document=document)
            session.spec_versions.append(spec)
            await self._db.flush()
            session.produced_spec_version_id = spec.id
            session.valid_spec_version_id = spec.id

        if node is WorkflowNode.AGGREGATOR:
            await self._seed_export_scratch_if_absent(session)

        await self._db.commit()
        return await self.get_session(session_id=session_id, account_id=account_id)

    async def confirm_generated_judge(
        self,
        *,
        session_id: UUID,
        account_id: UUID,
        node: WorkflowNode,
    ) -> None:
        if node not in FIVE_JUDGE_NODES:
            return
        session = await self._load_session(session_id, account_id)
        await self._freeze_working_node(session, node)

    async def _freeze_working_node(
        self, session: LoopSession, node: WorkflowNode
    ) -> bool:
        heads = {head.node_enum(): head for head in session.node_heads}
        head = heads[node]
        owned = set(owned_kinds(node))
        slice_cards = [card for card in session.cards if card.kind_enum() in owned]
        snapshot = _card_snapshot(slice_cards)
        narrative = dict(session.working_draft_narrative)
        port = self._ports[node.value]
        typed_data = await port.fingerprint(session_id=session.id, node=node.value)
        digest = _freeze_hash(narrative, snapshot, typed_data)

        if head.stage_revision_id is not None:
            current_rev = next(
                (
                    rev
                    for rev in session.stage_revisions
                    if rev.id == head.stage_revision_id
                ),
                None,
            )
            if current_rev is not None and current_rev.freeze_hash == digest:
                if head.status_enum() is NodeHeadStatus.STALE:
                    head.status = NodeHeadStatus.CURRENT.value
                head.generated_since_prepare = False
                return False

        next_n = 1 + max(
            (
                rev.revision_n
                for rev in session.stage_revisions
                if rev.node == node.value
            ),
            default=0,
        )
        revision = StageRevision(
            session_id=session.id,
            node=node.value,
            revision_n=next_n,
            narrative=narrative,
            card_snapshot=snapshot,
            freeze_hash=digest,
        )
        self._db.add(revision)
        await self._db.flush()
        session.stage_revisions.append(revision)

        head.status = NodeHeadStatus.CURRENT.value
        head.stage_revision_id = revision.id
        head.generated_since_prepare = False

        if next_n > 1:
            for child in descendants(node):
                child_head = heads[child]
                if child_head.stage_revision_id is not None:
                    child_head.status = NodeHeadStatus.STALE.value
                    child_head.generated_since_prepare = False
            if node not in LOOP_STAGE_NODES[LoopStage.INDEPENDENT_JUDGES]:
                session.valid_spec_version_id = None

        self._db.add(
            Decision(
                session_id=session.id,
                kind=DecisionKind.CONFIRM.value,
                node=node.value,
                stage_revision_id=revision.id,
            )
        )

        await port.freeze(
            session_id=session.id, node=node.value, revision_id=revision.id
        )
        return True

    async def recompute_prepare(
        self,
        *,
        session_id: UUID,
        account_id: UUID,
        stage: LoopStage,
        expected_version: int,
    ) -> LoopSessionResponse:
        session = await self._load_session(session_id, account_id)
        if session.version != expected_version:
            raise OperationalErrorException(
                status_code=status.HTTP_409_CONFLICT,
                code="version_conflict",
                detail="Loop Session was changed by another request",
                current_version=session.version,
            )
        heads = {head.node_enum(): head for head in session.node_heads}
        for node in upstream_of_stage(stage):
            if heads[node].status_enum() != NodeHeadStatus.CURRENT:
                raise OperationalErrorException(
                    status_code=status.HTTP_409_CONFLICT,
                    code="upstream_not_current",
                    detail="Upstream Node Heads of this Loop Stage must be current",
                )
        status_map = {
            node: heads[node].status_enum() for node in LOOP_STAGE_NODES[stage]
        }
        landing = prepare_landing(stage, status_map)
        if landing is None:
            raise OperationalErrorException(
                status_code=status.HTTP_409_CONFLICT,
                code="stage_already_current",
                detail="Every Workflow Node in this Loop Stage is current",
            )

        await self._increment_session_version(
            session,
            session_id=session_id,
            account_id=account_id,
            expected_version=expected_version,
        )

        revisions = {rev.id: rev for rev in session.stage_revisions}
        saved_narratives = dict(session.working_draft_narratives)
        saved_narratives[session.working_draft_node] = dict(
            session.working_draft_narrative
        )
        for node in LOOP_STAGE_NODES[stage]:
            head = heads[node]
            if head.status_enum() not in (NodeHeadStatus.STALE, NodeHeadStatus.EMPTY):
                continue
            head.generated_since_prepare = False
            from_revision_id = head.stage_revision_id
            if (
                from_revision_id is not None
                and head.status_enum() is NodeHeadStatus.STALE
            ):
                revision = revisions[from_revision_id]
                restored_narrative = dict(revision.narrative)
                saved_narratives[node.value] = restored_narrative
                if landing is node:
                    session.working_draft_narrative = restored_narrative
                snapshot_ids = {item["id"]: item for item in revision.card_snapshot}
                for card in session.cards:
                    item = snapshot_ids.get(str(card.id))
                    if item is not None:
                        card.body = item["body"]
                await self._ports[node.value].reset_working(
                    session_id=session.id,
                    node=node.value,
                    from_revision_id=from_revision_id,
                )
            elif node.value in saved_narratives:
                if landing is node:
                    session.working_draft_narrative = dict(saved_narratives[node.value])
            else:
                saved_narratives[node.value] = {}
                if landing is node:
                    session.working_draft_narrative = {}
                await self._ports[node.value].reset_working(
                    session_id=session.id,
                    node=node.value,
                    from_revision_id=None,
                )

        session.working_draft_node = landing.value
        session.working_draft_narratives = saved_narratives
        await self._db.commit()
        return await self.get_session(session_id=session_id, account_id=account_id)

    async def apply_idea_generate(
        self,
        *,
        session_id: UUID,
        account_id: UUID,
        expected_version: int,
        narrative: dict[str, Any],
        card_texts: list[tuple[CardKind, str]] | None,
    ) -> LoopSessionResponse:
        session = await self._load_session(session_id, account_id)
        await self._increment_session_version(
            session,
            session_id=session_id,
            account_id=account_id,
            expected_version=expected_version,
        )
        session.working_draft_narrative = narrative
        saved_narratives = dict(session.working_draft_narratives)
        saved_narratives[session.working_draft_node] = narrative
        session.working_draft_narratives = saved_narratives
        if (
            card_texts is not None
            and session.working_draft_node == WorkflowNode.IDEA_DECOMPOSITION.value
        ):
            self._upsert_decomposition_cards(session, card_texts)
        self.mark_generated_since_prepare(
            session, WorkflowNode(session.working_draft_node)
        )
        await self._db.commit()
        return await self.get_session(session_id=session_id, account_id=account_id)

    @staticmethod
    def mark_generated_since_prepare(session: LoopSession, node: WorkflowNode) -> None:
        for head in session.node_heads:
            if head.node_enum() is node:
                head.generated_since_prepare = True
                return

    def _upsert_decomposition_cards(
        self,
        session: LoopSession,
        card_texts: list[tuple[CardKind, str]],
    ) -> None:
        existing = sorted(session.cards, key=lambda card: (card.created_at, card.id))
        by_kind: dict[CardKind, list[Card]] = {}
        for card in existing:
            by_kind.setdefault(card.kind_enum(), []).append(card)

        incoming: dict[CardKind, list[str]] = {}
        for kind, text in card_texts:
            incoming.setdefault(kind, []).append(text)

        singular = (CardKind.PROBLEM, CardKind.RESEARCH_QUESTION)
        many = (CardKind.CONSTRAINT, CardKind.OPEN_QUESTION)
        for kind in (*singular, *many):
            texts = incoming.get(kind, [])
            rows = by_kind.get(kind, [])
            limit = 1 if kind in singular else len(texts)
            for index, text in enumerate(texts[:limit]):
                if index < len(rows):
                    rows[index].body = {**dict(rows[index].body), "text": text}
                else:
                    card = Card(
                        session_id=session.id,
                        kind=kind.value,
                        body={"text": text},
                    )
                    self._db.add(card)
                    session.cards.append(card)

    async def project_context(
        self, *, session_id: UUID, account_id: UUID, node: WorkflowNode
    ) -> dict[str, Any]:
        session = await self._load_session(session_id, account_id)
        heads = {head.node_enum(): head for head in session.node_heads}
        revisions = {rev.id: rev for rev in session.stage_revisions}
        upstream: dict[str, Any] = {}
        for ancestor in ancestors(node):
            head = heads[ancestor]
            if (
                head.status_enum() is NodeHeadStatus.CURRENT
                and head.stage_revision_id is not None
            ):
                rev = revisions[head.stage_revision_id]
                upstream[ancestor.value] = {
                    "card_snapshot": rev.card_snapshot,
                    "narrative": rev.narrative,
                    "projected": await self._ports[ancestor.value].project(
                        session_id=session.id,
                        node=ancestor.value,
                        revision_id=head.stage_revision_id,
                    ),
                }
        projected = await self._ports[node.value].project(
            session_id=session.id,
            node=node.value,
            revision_id=None,
        )
        working_cards = [
            card for card in session.cards if card.kind_enum() in set(owned_kinds(node))
        ]
        valid_spec = None
        if session.valid_spec_version_id is not None:
            spec = next(
                (
                    item
                    for item in session.spec_versions
                    if item.id == session.valid_spec_version_id
                ),
                None,
            )
            if spec is not None:
                valid_spec = {"id": str(spec.id), "document": spec.document}
        return {
            "node": node.value,
            "projected": projected,
            "upstream": upstream,
            "working_draft": {
                "card_snapshot": _card_snapshot(working_cards),
                "narrative": session.working_draft_narrative,
                "node": session.working_draft_node,
            },
            "valid_spec_version": valid_spec,
        }

    async def project_prompt_view(
        self, *, session_id: UUID, account_id: UUID, node: WorkflowNode
    ) -> dict[str, Any]:
        projection = await self.project_context(
            session_id=session_id, account_id=account_id, node=node
        )
        return prompt_view(node, projection)

    def _assert_card_owner(self, session: LoopSession, kind: CardKind) -> None:
        owners = CARD_KIND_OWNERS[kind]
        if session.working_draft_node not in [owner.value for owner in owners]:
            raise OperationalErrorException(
                status_code=status.HTTP_409_CONFLICT,
                code="card_owner_mismatch",
                detail="Card writes require the Working Draft to be the owning Workflow Node",
            )

    async def _increment_session_version(
        self,
        session: LoopSession,
        *,
        session_id: UUID,
        account_id: UUID,
        expected_version: int,
    ) -> int:
        updated = await self._db.execute(
            update(LoopSession)
            .where(
                LoopSession.id == session_id,
                LoopSession.account_id == account_id,
                LoopSession.version == expected_version,
            )
            .values(
                version=LoopSession.version + 1,
                updated_at=func.now(),
            )
            .returning(LoopSession.version)
            .execution_options(synchronize_session=False)
        )
        updated_row = updated.one_or_none()
        if updated_row is None:
            await self._db.refresh(session, attribute_names=["version"])
            raise OperationalErrorException(
                status_code=status.HTTP_409_CONFLICT,
                code="version_conflict",
                detail="Loop Session was changed by another request",
                current_version=session.version,
            )
        attributes.set_committed_value(session, "version", updated_row.version)
        return updated_row.version

    def _to_mutation_response(self, card: Card, version: int) -> CardMutationResponse:
        return CardMutationResponse(
            id=card.id,
            kind=card.kind_enum(),
            body=card.body,
            created_at=card.created_at,
            updated_at=card.updated_at,
            version=version,
        )

    async def _load_session(self, session_id: UUID, account_id: UUID) -> LoopSession:
        session = await self._db.scalar(
            select(LoopSession)
            .where(LoopSession.id == session_id, LoopSession.account_id == account_id)
            .options(
                selectinload(LoopSession.cards),
                selectinload(LoopSession.node_heads),
                selectinload(LoopSession.stage_revisions),
                selectinload(LoopSession.decisions),
                selectinload(LoopSession.spec_versions),
                selectinload(LoopSession.export_scratches),
                selectinload(LoopSession.export_scratch_snapshots),
            )
        )
        if session is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Loop Session not found"
            )
        return session

    async def _seed_export_scratch_if_absent(self, session: LoopSession) -> None:
        spec_id = session.valid_spec_version_id
        if spec_id is None:
            return
        existing = next(
            (
                row
                for row in session.export_scratches
                if row.spec_version_id == spec_id
            ),
            None,
        )
        if existing is not None:
            return
        spec = next(
            (item for item in session.spec_versions if item.id == spec_id),
            None,
        )
        if spec is None:
            spec = await self._db.get(SpecVersion, spec_id)
        if spec is None:
            return
        paper = project_paper_document(dict(spec.document))
        scratch = ExportScratch(
            session_id=session.id,
            spec_version_id=spec_id,
            document=paper,
        )
        session.export_scratches.append(scratch)
        self._db.add(scratch)
        await self._db.flush()
        snapshot = ExportScratchSnapshot(
            session_id=session.id,
            export_scratch_id=scratch.id,
            spec_version_id=spec_id,
            snapshot_n=1,
            document=json.loads(json.dumps(paper)),
        )
        session.export_scratch_snapshots.append(snapshot)
        self._db.add(snapshot)
        await self._db.flush()

    async def _to_response(
        self,
        session: LoopSession,
        *,
        spec_version_id: UUID | None = None,
    ) -> LoopSessionResponse:
        produced = None
        if session.produced_spec_version_id is not None:
            produced = next(
                (
                    item
                    for item in session.spec_versions
                    if item.id == session.produced_spec_version_id
                ),
                None,
            )
            if produced is None:
                # Same-request mint: spec_versions may still be the empty
                # selectinload from _load_session (expire_on_commit=False).
                produced = await self._db.get(
                    SpecVersion, session.produced_spec_version_id
                )
        heads = sorted(
            session.node_heads, key=lambda head: WORKFLOW_NODES.index(head.node_enum())
        )
        revisions = {rev.id: rev for rev in session.stage_revisions}
        target_spec_id = spec_version_id or session.valid_spec_version_id
        scratch = next(
            (
                row
                for row in session.export_scratches
                if row.spec_version_id == target_spec_id
            ),
            None,
        )
        snapshots = [
            row
            for row in session.export_scratch_snapshots
            if row.spec_version_id == target_spec_id
        ]
        snapshots.sort(key=lambda row: row.snapshot_n)
        return LoopSessionResponse(
            id=session.id,
            title=session.title,
            version=session.version,
            working_draft_node=WorkflowNode(session.working_draft_node),
            working_draft_narrative=session.working_draft_narrative,
            node_heads=[
                NodeHeadResponse(
                    node=head.node_enum(),
                    status=head.status_enum(),
                    stage_revision_id=head.stage_revision_id,
                    generated_since_prepare=head.generated_since_prepare,
                    head_revision=_head_revision(head, revisions),
                )
                for head in heads
            ],
            cards=[CardResponse.model_validate(card) for card in session.cards],
            stage_revisions=[
                StageRevisionResponse.model_validate(rev)
                for rev in session.stage_revisions
            ],
            produced_spec_version=SpecVersionResponse.model_validate(produced)
            if produced
            else None,
            valid_spec_version_id=session.valid_spec_version_id,
            readiness=await self._readiness(session),
            export_scratch=ExportScratchResponse.model_validate(scratch)
            if scratch
            else None,
            export_scratch_snapshots=[
                ExportScratchSnapshotResponse.model_validate(row) for row in snapshots
            ],
            created_at=session.created_at,
            updated_at=session.updated_at,
        )

    async def _assemble_spec(
        self,
        session: LoopSession,
        heads: dict[WorkflowNode, NodeHead],
    ) -> dict[str, Any]:
        revisions = {rev.id: rev for rev in session.stage_revisions}
        nodes: dict[str, Any] = {}
        for node in WORKFLOW_NODES:
            head = heads[node]
            if (
                head.status_enum() is NodeHeadStatus.CURRENT
                and head.stage_revision_id is not None
            ):
                rev = revisions[head.stage_revision_id]
                narrative = dict(rev.narrative)
                if node is WorkflowNode.GAP and any(
                    card.get("kind") == CardKind.GAP.value for card in rev.card_snapshot
                ):
                    # The generated candidate is copied into the confirmed Gap Card.
                    # Keep it in the Stage Revision for history, but avoid storing the
                    # same logical Gap twice in the assembled Spec Version document.
                    narrative.pop("candidate", None)
                node_document = {
                    "stage_revision_id": str(rev.id),
                    "card_snapshot": rev.card_snapshot,
                    "narrative": narrative,
                }
                projection = await self._ports[node.value].project(
                    session_id=session.id,
                    node=node.value,
                    revision_id=rev.id,
                )
                if projection:
                    node_document["projection"] = projection
                nodes[node.value] = node_document
        return {"nodes": nodes}

    async def export_spec_artifact(
        self,
        *,
        session_id: UUID,
        account_id: UUID,
        critical_export_ack: bool = False,
    ) -> SpecArtifactResponse:
        session = await self._load_session(session_id, account_id)
        readiness = await self._readiness(session)
        if readiness.state == "not_evaluated":
            raise OperationalErrorException(
                status_code=status.HTTP_409_CONFLICT,
                code="readiness_not_evaluated",
                detail="Spec Artifact export requires a current Aggregator Report",
            )
        if readiness.state == "blocked" and not critical_export_ack:
            raise OperationalErrorException(
                status_code=status.HTTP_409_CONFLICT,
                code="critical_export_confirmation_required",
                detail=(
                    "Spec Artifact export while Readiness is blocked requires "
                    "a Critical Export Confirmation"
                ),
            )
        if session.valid_spec_version_id is None:
            raise OperationalErrorException(
                status_code=status.HTTP_409_CONFLICT,
                code="valid_spec_version_required",
                detail="Spec Artifact export requires a Valid Spec Version",
            )
        spec = next(
            (
                item
                for item in session.spec_versions
                if item.id == session.valid_spec_version_id
            ),
            None,
        )
        if spec is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Spec Version not found"
            )
        if readiness.state == "blocked":
            self._db.add(
                Decision(
                    session_id=session.id,
                    kind=DecisionKind.EXPORT_ACK.value,
                    node=None,
                    stage_revision_id=None,
                    detail={
                        "target": "spec_artifact",
                        "format": "json",
                        "spec_version_id": str(spec.id),
                    },
                )
            )
            await self._db.commit()
        return SpecArtifactResponse(spec_version_id=spec.id, document=spec.document)

    async def _readiness(self, session: LoopSession) -> ReadinessSummary:
        notice = "This is not conference acceptance."
        heads = {head.node_enum(): head for head in session.node_heads}
        aggregator = heads.get(WorkflowNode.AGGREGATOR)
        if (
            aggregator is None
            or aggregator.status_enum() is not NodeHeadStatus.CURRENT
            or aggregator.stage_revision_id is None
        ):
            return ReadinessSummary(state="not_evaluated", notice=notice)
        projected = await self._ports[WorkflowNode.AGGREGATOR.value].project(
            session_id=session.id,
            node=WorkflowNode.AGGREGATOR.value,
            revision_id=aggregator.stage_revision_id,
        )
        issues = projected.get("issues")
        if not isinstance(issues, list):
            issues = []
        state = (
            "blocked"
            if any(
                isinstance(item, dict) and item.get("severity") == "CRITICAL"
                for item in issues
            )
            else "ready"
        )
        scores = projected.get("scores")
        return ReadinessSummary(
            state=state,
            notice=notice,
            scores=scores if isinstance(scores, dict) else None,
        )
