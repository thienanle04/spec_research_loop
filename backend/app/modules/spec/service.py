"""Spec application services."""

import json
import re
from typing import Any
from uuid import UUID

from fastapi import HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import OperationalErrorException
from app.modules.loop.catalog import NodeHeadStatus, WorkflowNode, ancestors
from app.modules.loop.models import LoopSession, NodeHead
from app.modules.loop.service import LoopService
from app.modules.spec.schemas import (
    ContributionDirection,
    ContributionDirectionKind,
    ContributionDirectionsResponse,
)
from app.ports.llm import LlmPort


class _GeneratedDirection(BaseModel):
    title: str = Field(min_length=1)
    description: str = Field(min_length=1)


class SpecService:
    def __init__(self, db: AsyncSession, *, llm: LlmPort) -> None:
        self._db = db
        self._llm = llm

    async def generate_contribution_directions(
        self,
        *,
        session_id: UUID,
        account_id: UUID,
        expected_version: int,
    ) -> ContributionDirectionsResponse:
        session = await self._db.scalar(
            select(LoopSession).where(
                LoopSession.id == session_id,
                LoopSession.account_id == account_id,
            )
        )
        if session is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Loop Session not found"
            )
        if session.working_draft_node != WorkflowNode.CONTRIBUTION.value:
            raise OperationalErrorException(
                status_code=status.HTTP_409_CONFLICT,
                code="invalid_working_draft_target",
                detail="Contribution directions require contribution to be the Working Draft",
            )
        heads = list(
            (
                await self._db.scalars(
                    select(NodeHead).where(NodeHead.session_id == session_id)
                )
            ).all()
        )
        status_by_node = {WorkflowNode(head.node): head.status for head in heads}
        if any(
            status_by_node[node] != NodeHeadStatus.CURRENT.value
            for node in ancestors(WorkflowNode.CONTRIBUTION)
        ):
            raise OperationalErrorException(
                status_code=status.HTTP_409_CONFLICT,
                code="upstream_not_current",
                detail="Upstream Workflow Nodes must be current",
            )

        context = await LoopService(self._db).project_context(
            session_id=session_id,
            account_id=account_id,
            node=WorkflowNode.CONTRIBUTION,
        )
        proposed = await self._propose_directions(context)
        directions = [
            ContributionDirection(
                id=f"direction-{chr(97 + index)}",
                title=item.title,
                description=item.description,
            )
            for index, item in enumerate(proposed[:3])
        ]
        directions.extend(
            [
                ContributionDirection(
                    id="combine",
                    title="Combine directions",
                    description="Choose one primary contribution and one or more supporting contributions.",
                    kind=ContributionDirectionKind.COMBINE,
                ),
                ContributionDirection(
                    id="other",
                    title="Other",
                    description="Write a different contribution direction.",
                    kind=ContributionDirectionKind.OTHER,
                ),
            ]
        )
        narrative = {
            "directions": [item.model_dump(mode="json") for item in directions]
        }
        result = await self._db.execute(
            update(LoopSession)
            .where(
                LoopSession.id == session_id,
                LoopSession.account_id == account_id,
                LoopSession.version == expected_version,
            )
            .values(
                working_draft_narrative=narrative,
                version=LoopSession.version + 1,
            )
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
        await self._db.commit()
        return ContributionDirectionsResponse(
            version=row.version, directions=directions
        )

    async def _propose_directions(
        self, context: dict[str, Any]
    ) -> list[_GeneratedDirection]:
        try:
            raw = await self._llm.complete(
                system=(
                    "spec-contribution-directions: return only a JSON array with 1 to 3 "
                    "objects containing title and description. Propose distinct contribution "
                    "directions grounded in the confirmed research idea, Related Work, and Gap. "
                    "Do not include Combine or Other; the application adds those fixed choices."
                ),
                prompt=json.dumps(context, default=str, ensure_ascii=False),
            )
            cleaned = re.sub(
                r"^```(?:json)?\s*|\s*```$", "", raw.strip(), flags=re.IGNORECASE
            )
            payload = json.loads(cleaned)
            if not isinstance(payload, list):
                raise TypeError("Expected a JSON array")
            proposed = [_GeneratedDirection.model_validate(item) for item in payload]
            if not proposed:
                raise ValueError("No directions returned")
            return proposed
        except Exception:  # noqa: BLE001 - keep contribution selection usable on provider failure
            return [
                _GeneratedDirection(
                    title="Focus on the core method",
                    description="Place the contribution in the algorithm or system design that addresses the confirmed Gap.",
                ),
                _GeneratedDirection(
                    title="Focus on verification",
                    description="Place the contribution in how claims or outcomes are checked against evidence.",
                ),
                _GeneratedDirection(
                    title="Focus on human-in-the-loop control",
                    description="Place the contribution in how people confirm and adjust the process.",
                ),
            ]
