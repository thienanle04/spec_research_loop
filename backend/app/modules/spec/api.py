from fastapi import APIRouter, Depends
from typing import Any

from app.modules.spec.schemas import (
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
    generate_contribution_options,
    generate_claims_evidence,
    generate_experiment_plan,
    check_feasibility as service_check_feasibility
)
from app.adapters.llm import get_llm_port
from app.modules.loop.catalog import WorkflowNode

router = APIRouter(prefix="/spec", tags=["Spec Construction"])

@router.post("/contribution/generate", response_model=GenerateContributionResponse)
async def generate_contribution(
    context: SpecConstructionContext = Depends(get_mock_spec_context)
):
    llm = get_llm_port(WorkflowNode.CONTRIBUTION)
    return await generate_contribution_options(context, llm)

@router.post("/contribution/confirm")
async def confirm_contribution(req: ConfirmRequest):
    # TODO: Insert/Update bảng StageRevision, NodeHead
    return {"status": "ok", "message": "Contribution confirmed"}

@router.post("/claims/generate", response_model=GenerateClaimsResponse)
async def generate_claims(
    contribution_desc: str, # Thay cho việc fetch từ DB tạm thời
    context: SpecConstructionContext = Depends(get_mock_spec_context)
):
    llm = get_llm_port(WorkflowNode.CLAIMS)
    return await generate_claims_evidence(contribution_desc, context, llm)

@router.post("/claims/confirm")
async def confirm_claims(req: ConfirmRequest):
    return {"status": "ok", "message": "Claims confirmed"}

@router.post("/experiment/generate", response_model=GenerateExperimentResponse)
async def generate_experiment(
    claims: list[dict], # Tạm nhận qua request
    context: SpecConstructionContext = Depends(get_mock_spec_context)
):
    llm = get_llm_port(WorkflowNode.EXPERIMENT_PLAN)
    return await generate_experiment_plan(claims, context, llm)

@router.post("/experiment/confirm")
async def confirm_experiment(req: ConfirmRequest):
    return {"status": "ok", "message": "Experiment confirmed"}

@router.post("/feasibility/check", response_model=FeasibilityReport)
async def check_feasibility(
    plan_desc: str, # Tạm nhận qua request
    context: SpecConstructionContext = Depends(get_mock_spec_context)
):
    llm = get_llm_port(WorkflowNode.FEASIBILITY)
    return await service_check_feasibility(plan_desc, context, llm)
