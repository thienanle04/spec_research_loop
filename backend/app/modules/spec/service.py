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
    CheckFeasibilityResponse,
    ContributionDirection,
    ContributionDirectionKind,
    ContributionDirectionsResponse,
    FeasibilityReport,
    GenerateClaimsResponse,
    GenerateExperimentResponse,
)
from app.ports.llm import LlmPort


class _GeneratedDirection(BaseModel):
    title: str = Field(min_length=1)
    description: str = Field(min_length=1)


_VIETNAMESE_CHARACTERS = frozenset(
    "ăâđêôơưàáạảãằắặẳẵầấậẩẫèéẹẻẽềếệểễìíịỉĩòóọỏõồốộổỗờớợởỡùúụủũừứựửữỳýỵỷỹ"
)
_VIETNAMESE_ASCII_WORDS = frozenset(
    {
        "cac",
        "cho",
        "cua",
        "duoc",
        "khong",
        "la",
        "mot",
        "nghien",
        "nhung",
        "phuong",
        "trong",
        "va",
        "voi",
    }
)


def _confirmed_gap_statement(context: dict[str, Any]) -> str:
    gap_context = context.get("upstream", {}).get(WorkflowNode.GAP.value, {})
    for item in gap_context.get("card_snapshot", []):
        if item.get("kind") != "gap":
            continue
        body = item.get("body", {})
        statement = body.get("statement") or body.get("text")
        if isinstance(statement, str) and statement.strip():
            return statement.strip()
    return ""


def _is_vietnamese(text: str) -> bool:
    normalized = text.casefold()
    if any(character in _VIETNAMESE_CHARACTERS for character in normalized):
        return True
    words = set(re.findall(r"[a-z]+", normalized))
    return len(words & _VIETNAMESE_ASCII_WORDS) >= 2


class SpecService:
    def __init__(self, db: AsyncSession, *, llm: LlmPort) -> None:
        self._db = db
        self._llm = llm

    async def _ensure_node_ready(
        self,
        session_id: UUID,
        account_id: UUID,
        expected_version: int,
        node: WorkflowNode,
    ) -> LoopSession:
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

    async def _update_narrative(
        self,
        session_id: UUID,
        account_id: UUID,
        expected_version: int,
        narrative: dict,
        session: LoopSession,
    ) -> int:
        saved_narratives = dict(session.working_draft_narratives)
        saved_narratives[session.working_draft_node] = narrative
        result = await self._db.execute(
            update(LoopSession)
            .where(
                LoopSession.id == session_id,
                LoopSession.account_id == account_id,
                LoopSession.version == expected_version,
            )
            .values(
                working_draft_narrative=narrative,
                working_draft_narratives=saved_narratives,
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
        session = await self._ensure_node_ready(
            session_id, account_id, expected_version, WorkflowNode.CONTRIBUTION
        )

        context = await LoopService(self._db).project_context(
            session_id=session_id,
            account_id=account_id,
            node=WorkflowNode.CONTRIBUTION,
        )
        output_language = (
            "Vietnamese"
            if _is_vietnamese(_confirmed_gap_statement(context))
            else "English"
        )
        proposed = await self._propose_directions(context, output_language)
        directions = [
            ContributionDirection(
                id=f"direction-{chr(97 + index)}",
                title=item.title,
                description=item.description,
            )
            for index, item in enumerate(proposed[:3])
        ]
        fixed_directions = (
            [
                ContributionDirection(
                    id="combine",
                    title="Kết hợp các hướng",
                    description=(
                        "Chọn một đóng góp chính và một hoặc nhiều đóng góp hỗ trợ."
                    ),
                    kind=ContributionDirectionKind.COMBINE,
                ),
                ContributionDirection(
                    id="other",
                    title="Khác",
                    description="Viết một hướng đóng góp khác.",
                    kind=ContributionDirectionKind.OTHER,
                ),
            ]
            if output_language == "Vietnamese"
            else [
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
        directions.extend(fixed_directions)
        narrative = {
            "directions": [item.model_dump(mode="json") for item in directions]
        }

        new_version = await self._update_narrative(
            session_id, account_id, expected_version, narrative, session
        )
        return ContributionDirectionsResponse(
            version=new_version, directions=directions
        )

    async def generate_claims(
        self,
        *,
        session_id: UUID,
        account_id: UUID,
        expected_version: int,
    ) -> GenerateClaimsResponse:
        session = await self._ensure_node_ready(
            session_id, account_id, expected_version, WorkflowNode.CLAIMS
        )
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
            system=system, prompt=prompt, schema=GenerateClaimsResponse
        )

        narrative = {
            "cards": [card.model_dump(mode="json") for card in response_data.cards]
        }
        new_version = await self._update_narrative(
            session_id, account_id, expected_version, narrative, session
        )
        return GenerateClaimsResponse(version=new_version, cards=response_data.cards)

    async def generate_experiment_plan(
        self,
        *,
        session_id: UUID,
        account_id: UUID,
        expected_version: int,
    ) -> GenerateExperimentResponse:
        session = await self._ensure_node_ready(
            session_id, account_id, expected_version, WorkflowNode.EXPERIMENT_PLAN
        )
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
            system=system, prompt=prompt, schema=GenerateExperimentResponse
        )

        narrative = {"plan": response_data.plan.model_dump(mode="json")}
        new_version = await self._update_narrative(
            session_id, account_id, expected_version, narrative, session
        )
        return GenerateExperimentResponse(version=new_version, plan=response_data.plan)

    async def check_feasibility(
        self,
        *,
        session_id: UUID,
        account_id: UUID,
        expected_version: int,
        plan: dict | None = None,
    ) -> CheckFeasibilityResponse:
        session = await self._ensure_node_ready(
            session_id, account_id, expected_version, WorkflowNode.FEASIBILITY
        )
        context = await LoopService(self._db).project_context(
            session_id=session_id,
            account_id=account_id,
            node=WorkflowNode.FEASIBILITY,
        )

        system = (
            "Bạn là một AI đánh giá tài nguyên và tính khả thi cho Đặc tả Nghiên cứu."
        )
        prompt = f"""
        Kế hoạch thử nghiệm: 
        {json.dumps(plan) if plan else "Dựa vào context experiment plan trong dữ liệu: " + json.dumps(context.get("experiment_plan", {}))}
        
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
            system=system, prompt=prompt, schema=FeasibilityReport
        )

        narrative = {"feasibility_report": report.model_dump(mode="json")}
        new_version = await self._update_narrative(
            session_id, account_id, expected_version, narrative, session
        )
        return CheckFeasibilityResponse(version=new_version, report=report)

    async def _propose_directions(
        self, context: dict[str, Any], output_language: str
    ) -> list[_GeneratedDirection]:
        gap_statement = _confirmed_gap_statement(context)
        try:
            raw = await self._llm.complete(
                system=(
                    "spec-contribution-directions: return only a JSON array with 1 to 3 "
                    "objects containing title and description. Propose distinct contribution "
                    "directions grounded in the confirmed research idea, Related Work, and Gap. "
                    "Use the language of the confirmed Gap statement for every title and "
                    "description, regardless of the language used by citations or Related Work. "
                    f"The required output language is {output_language}. "
                    "Do not include Combine or Other; the application adds those fixed choices."
                ),
                prompt=json.dumps(
                    {
                        "required_output_language": output_language,
                        "confirmed_gap_statement": gap_statement,
                        "context": context,
                    },
                    default=str,
                    ensure_ascii=False,
                ),
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
            generated_text = " ".join(
                f"{item.title} {item.description}" for item in proposed
            )
            if _is_vietnamese(generated_text) != (output_language == "Vietnamese"):
                raise ValueError("Directions did not match the confirmed Gap language")
            return proposed
        except Exception:  # noqa: BLE001 - keep contribution selection usable on provider failure
            if output_language == "Vietnamese":
                return [
                    _GeneratedDirection(
                        title="Tập trung vào phương pháp cốt lõi",
                        description=(
                            "Đặt đóng góp vào thuật toán hoặc thiết kế hệ thống nhằm giải quyết "
                            "Gap đã được xác nhận."
                        ),
                    ),
                    _GeneratedDirection(
                        title="Tập trung vào khâu kiểm chứng",
                        description=(
                            "Đặt đóng góp vào cách các luận điểm hoặc kết quả được đối chiếu với "
                            "bằng chứng."
                        ),
                    ),
                    _GeneratedDirection(
                        title="Tập trung vào kiểm soát có con người tham gia",
                        description=(
                            "Đặt đóng góp vào cách con người xác nhận và điều chỉnh quy trình."
                        ),
                    ),
                ]
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
