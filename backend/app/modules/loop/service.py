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
    CARD_KIND_OWNER,
    LOOP_STAGE_NODES,
    WORKFLOW_NODES,
    CardKind,
    DecisionKind,
    LoopStage,
    NodeHeadStatus,
    WorkflowNode,
    ancestors,
    descendants,
    first_needs_work,
    owned_kinds,
    upstream_of_stage,
)
from app.modules.loop.deps import get_stage_ports
from app.modules.loop.interpretation_turns import (
    apply_account_reply_patch,
    interpretation_confirmable,
)
from app.modules.loop.prompt_view import prompt_view
from app.modules.loop.models import (
    Card,
    Decision,
    LoopSession,
    NodeHead,
    SpecVersion,
    StageRevision,
)
from app.modules.loop.schemas import (
    CardBatchMutationResponse,
    CardMutationResponse,
    CardResponse,
    DecisionResponse,
    HeadRevisionResponse,
    LoopSessionResponse,
    LoopSessionSummary,
    NodeHeadResponse,
    SpecVersionResponse,
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
        self, *, session_id: UUID, account_id: UUID
    ) -> LoopSessionResponse:
        session = await self._load_session(session_id, account_id)
        return await self._to_response(session)

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
            if heads[node].status_enum() != NodeHeadStatus.CURRENT:
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
                    (item for item in session.stage_revisions if item.id == revision_id),
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
                await self._db.commit()
                return await self.get_session(
                    session_id=session_id, account_id=account_id
                )

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

        if node is WorkflowNode.IDEA_INTERPRETATION:
            saved_narratives = dict(session.working_draft_narratives)
            saved_narratives[node.value] = dict(session.working_draft_narrative)
            saved_narratives[WorkflowNode.IDEA_DECOMPOSITION.value] = {}
            session.working_draft_narratives = saved_narratives
            session.working_draft_node = WorkflowNode.IDEA_DECOMPOSITION.value
            session.working_draft_narrative = {}

        if node is WorkflowNode.FEASIBILITY:
            document = self._assemble_spec(session, heads)
            spec = SpecVersion(session_id=session.id, document=document)
            self._db.add(spec)
            await self._db.flush()
            session.produced_spec_version_id = spec.id
            session.valid_spec_version_id = spec.id

        await self._db.commit()
        return await self.get_session(session_id=session_id, account_id=account_id)

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
        landing = first_needs_work(stage, status_map)
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
                    session.working_draft_narrative = dict(
                        saved_narratives[node.value]
                    )
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
    def mark_generated_since_prepare(
        session: LoopSession, node: WorkflowNode
    ) -> None:
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
            card
            for card in session.cards
            if card.kind_enum() in set(owned_kinds(node))
        ]
        return {
            "node": node.value,
            "projected": projected,
            "upstream": upstream,
            "working_draft": {
                "card_snapshot": _card_snapshot(working_cards),
                "narrative": session.working_draft_narrative,
                "node": session.working_draft_node,
            },
        }

    async def project_prompt_view(
        self, *, session_id: UUID, account_id: UUID, node: WorkflowNode
    ) -> dict[str, Any]:
        projection = await self.project_context(
            session_id=session_id, account_id=account_id, node=node
        )
        return prompt_view(node, projection)

    def _assert_card_owner(self, session: LoopSession, kind: CardKind) -> None:
        owner = CARD_KIND_OWNER[kind]
        if session.working_draft_node != owner.value:
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
            )
        )
        if session is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Loop Session not found"
            )
        return session

    async def _to_response(self, session: LoopSession) -> LoopSessionResponse:
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
        heads = sorted(
            session.node_heads, key=lambda head: WORKFLOW_NODES.index(head.node_enum())
        )
        revisions = {rev.id: rev for rev in session.stage_revisions}
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
            produced_spec_version=SpecVersionResponse.model_validate(produced)
            if produced
            else None,
            valid_spec_version_id=session.valid_spec_version_id,
            created_at=session.created_at,
            updated_at=session.updated_at,
        )

    def _assemble_spec(
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
                    card.get("kind") == CardKind.GAP.value
                    for card in rev.card_snapshot
                ):
                    # The generated candidate is copied into the confirmed Gap Card.
                    # Keep it in the Stage Revision for history, but avoid storing the
                    # same logical Gap twice in the assembled Spec Version document.
                    narrative.pop("candidate", None)
                nodes[node.value] = {
                    "card_snapshot": rev.card_snapshot,
                    "narrative": narrative,
                }
        return {"nodes": nodes}
