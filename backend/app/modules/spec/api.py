from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import OperationalError
from app.db.session import get_db
from app.modules.identity.deps import get_current_account
from app.modules.identity.models import Account
from app.modules.spec.deps import get_spec_llm
from app.modules.spec.schemas import (
    ContributionDirectionsRequest,
    ContributionDirectionsResponse,
    SpecConstructionContext,
    GenerateContributionResponse,
    GenerateClaimsResponse,
    GenerateExperimentResponse,
    FeasibilityReport,
    ConfirmRequest,
    ExperimentPlan
)
from app.modules.spec.dependencies import get_mock_spec_context
from app.modules.spec.service import (
    SpecService,
    generate_contribution_options,
    generate_claims_evidence,
    generate_experiment_plan,
    check_feasibility as service_check_feasibility
)
from app.adapters.llm import get_llm_port
from app.modules.loop.catalog import WorkflowNode
from app.ports.llm import LlmPort

router = APIRouter(prefix="/spec", tags=["Spec Construction"])

@router.get("/health")
async def health() -> dict[str, str]:
    return {"module": "spec", "status": "ok"}

@router.post(
    "/sessions/{session_id}/contribution-directions/generate",
    response_model=ContributionDirectionsResponse,
    responses={409: {"model": OperationalError}},
)
async def generate_contribution_directions(
    session_id: UUID,
    body: ContributionDirectionsRequest,
    account: Annotated[Account, Depends(get_current_account)],
    db: Annotated[AsyncSession, Depends(get_db)],
    llm: Annotated[LlmPort, Depends(get_spec_llm)],
) -> ContributionDirectionsResponse:
    return await SpecService(db, llm=llm).generate_contribution_directions(
        session_id=session_id,
        account_id=account.id,
        expected_version=body.expected_version,
    )

@router.post("/contribution/generate", response_model=GenerateContributionResponse)
async def generate_contribution(
    context: SpecConstructionContext = Depends(get_mock_spec_context)
):
    llm = get_llm_port(WorkflowNode.CONTRIBUTION)
    return await generate_contribution_options(context, llm)

@router.post("/contribution/confirm")
async def confirm_contribution(req: ConfirmRequest):
    return {"status": "ok", "message": "Contribution confirmed"}

@router.post("/claims/generate", response_model=GenerateClaimsResponse)
async def generate_claims(
    contribution_desc: str,
    context: SpecConstructionContext = Depends(get_mock_spec_context)
):
    llm = get_llm_port(WorkflowNode.CLAIMS)
    return await generate_claims_evidence(contribution_desc, context, llm)

@router.post("/claims/confirm")
async def confirm_claims(req: ConfirmRequest):
    return {"status": "ok", "message": "Claims confirmed"}

@router.post("/experiment/generate", response_model=GenerateExperimentResponse)
async def generate_experiment(
    claims: list[dict],
    context: SpecConstructionContext = Depends(get_mock_spec_context)
):
    llm = get_llm_port(WorkflowNode.EXPERIMENT_PLAN)
    return await generate_experiment_plan(claims, context, llm)

@router.post("/experiment/confirm")
async def confirm_experiment(req: ConfirmRequest):
    return {"status": "ok", "message": "Experiment confirmed"}

@router.post("/feasibility/check", response_model=FeasibilityReport)
async def check_feasibility(
    plan_desc: str,
    context: SpecConstructionContext = Depends(get_mock_spec_context)
):
    llm = get_llm_port(WorkflowNode.FEASIBILITY)
    return await service_check_feasibility(plan_desc, context, llm)
