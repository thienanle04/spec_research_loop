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
    GenerateClaimsResponse,
    GenerateExperimentResponse,
    CheckFeasibilityResponse,
    FeasibilityReport,
)
from app.ports.llm import LlmPort

class _GeneratedDirection(BaseModel):
    title: str = Field(min_length=1)
    description: str = Field(min_length=1)


class SpecService:
    def __init__(self, db: AsyncSession, *, llm: LlmPort) -> None:
        self._db = db
        self._llm = llm

    async def _ensure_node_ready(self, session_id: UUID, account_id: UUID, expected_version: int, node: WorkflowNode) -> LoopSession:
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
        if session.working_draft_node != node.value:
            raise OperationalErrorException(
                status_code=status.HTTP_409_CONFLICT,
                code="invalid_working_draft_target",
                detail=f"This operation requires {node.value} to be the Working Draft",
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
            status_by_node[ancestor] != NodeHeadStatus.CURRENT.value
            for ancestor in ancestors(node)
        ):
            raise OperationalErrorException(
                status_code=status.HTTP_409_CONFLICT,
                code="upstream_not_current",
                detail="Upstream Workflow Nodes must be current",
            )
        return session

    async def _update_narrative(self, session_id: UUID, account_id: UUID, expected_version: int, narrative: dict, session: LoopSession) -> int:
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
        return row.version

    async def generate_contribution_directions(
        self,
        *,
        session_id: UUID,
        account_id: UUID,
        expected_version: int,
    ) -> ContributionDirectionsResponse:
        session = await self._ensure_node_ready(session_id, account_id, expected_version, WorkflowNode.CONTRIBUTION)

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
        
        new_version = await self._update_narrative(session_id, account_id, expected_version, narrative, session)
        return ContributionDirectionsResponse(version=new_version, directions=directions)

    async def generate_claims(
        self,
        *,
        session_id: UUID,
        account_id: UUID,
        expected_version: int,
    ) -> GenerateClaimsResponse:
        session = await self._ensure_node_ready(session_id, account_id, expected_version, WorkflowNode.CLAIMS)
        context = await LoopService(self._db).project_context(
            session_id=session_id,
            account_id=account_id,
            node=WorkflowNode.CLAIMS,
        )
        
        system = "Bạn là một AI hỗ trợ thiết kế Đặc tả Nghiên cứu (Research Spec)."
        prompt = f"""
        Dựa vào context của dự án:
        {json.dumps(context, default=str, ensure_ascii=False)}
        
        Hãy sinh ra các luận điểm (Claims) chứng minh cho các đóng góp (Contribution) đã chọn.
        Mỗi Claim đi kèm Baseline, Metric cần đo, Bằng chứng kỳ vọng (evidence), và Điều kiện bác bỏ (rejection_condition).
        """
        response_data = await self._llm.complete_structured(
            system=system,
            prompt=prompt,
            schema=GenerateClaimsResponse
        )
        
        narrative = {
            "cards": [card.model_dump(mode="json") for card in response_data.cards]
        }
        new_version = await self._update_narrative(session_id, account_id, expected_version, narrative, session)
        return GenerateClaimsResponse(version=new_version, cards=response_data.cards)

    async def generate_experiment_plan(
        self,
        *,
        session_id: UUID,
        account_id: UUID,
        expected_version: int,
    ) -> GenerateExperimentResponse:
        session = await self._ensure_node_ready(session_id, account_id, expected_version, WorkflowNode.EXPERIMENT_PLAN)
        context = await LoopService(self._db).project_context(
            session_id=session_id,
            account_id=account_id,
            node=WorkflowNode.EXPERIMENT_PLAN,
        )
        
        system = "Bạn là một AI hỗ trợ thiết kế Đặc tả Nghiên cứu (Research Spec)."
        prompt = f"""
        Dựa vào context sau của dự án (đặc biệt là các Claim đã chọn):
        {json.dumps(context, default=str, ensure_ascii=False)}
        
        Hãy lên kế hoạch thử nghiệm chi tiết gồm: Baselines, Metrics, Giao thức đánh giá (evaluation_protocol), Ablation Study, và Generalization.
        """
        response_data = await self._llm.complete_structured(
            system=system,
            prompt=prompt,
            schema=GenerateExperimentResponse
        )
        
        narrative = {
            "plan": response_data.plan.model_dump(mode="json")
        }
        new_version = await self._update_narrative(session_id, account_id, expected_version, narrative, session)
        return GenerateExperimentResponse(version=new_version, plan=response_data.plan)

    async def check_feasibility(
        self,
        *,
        session_id: UUID,
        account_id: UUID,
        expected_version: int,
        plan: dict | None = None
    ) -> CheckFeasibilityResponse:
        session = await self._ensure_node_ready(session_id, account_id, expected_version, WorkflowNode.FEASIBILITY)
        context = await LoopService(self._db).project_context(
            session_id=session_id,
            account_id=account_id,
            node=WorkflowNode.FEASIBILITY,
        )
        
        system = "Bạn là một AI đánh giá tài nguyên và tính khả thi cho Đặc tả Nghiên cứu."
        prompt = f"""
        Kế hoạch thử nghiệm: 
        {json.dumps(plan) if plan else "Dựa vào context experiment plan trong dữ liệu: " + json.dumps(context.get('experiment_plan', {}))}
        
        Context hiện tại của dự án:
        {json.dumps(context, default=str, ensure_ascii=False)}
        
        Hãy đánh giá tính khả thi (Feasibility) của kế hoạch thử nghiệm này. Trả về các thông tin sau:
        - is_feasible: Kết luận chung có khả thi không
        - conclusion: Lời giải thích tóm tắt cho kết luận
        - required_resources: Danh sách các tài nguyên cần thiết (VD: VRAM, Data, Compute Time)
        - potential_bottlenecks: Danh sách các nút thắt hoặc vấn đề tiềm ẩn có thể xảy ra
        - mitigation_strategies: Danh sách các phương án giải quyết/giảm thiểu rủi ro
        """
        report = await self._llm.complete_structured(
            system=system,
            prompt=prompt,
            schema=FeasibilityReport
        )
        
        narrative = {
            "feasibility_report": report.model_dump(mode="json")
        }
        new_version = await self._update_narrative(session_id, account_id, expected_version, narrative, session)
        return CheckFeasibilityResponse(version=new_version, report=report)

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
