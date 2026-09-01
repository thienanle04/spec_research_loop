from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import OperationalError
from app.db.session import get_db
from app.modules.identity.deps import get_current_account
from app.modules.identity.models import Account
from app.modules.spec.deps import (
    get_claims_llm,
    get_contribution_llm,
    get_experiment_llm,
    get_feasibility_llm,
)
from app.modules.spec.schemas import (
    CheckFeasibilityRequest,
    CheckFeasibilityResponse,
    ContributionDirectionsRequest,
    ContributionDirectionsResponse,
    GenerateClaimsRequest,
    GenerateClaimsResponse,
    GenerateExperimentRequest,
    GenerateExperimentResponse,
)
from app.modules.spec.service import SpecService
from app.ports.llm import LlmPort

router = APIRouter(tags=["Spec Construction"])

@router.get("/health")
async def health() -> dict[str, str]:
    return {"module": "spec", "status": "ok"}

@router.post(
    "/sessions/{session_id}/contribution-directions/generate",
    response_model=ContributionDirectionsResponse,
    responses={409: {"model": OperationalError}, 429: {"model": OperationalError}, 503: {"model": OperationalError}},
)
async def generate_contribution_directions(
    session_id: UUID,
    body: ContributionDirectionsRequest,
    account: Annotated[Account, Depends(get_current_account)],
    db: Annotated[AsyncSession, Depends(get_db)],
    llm: Annotated[LlmPort, Depends(get_contribution_llm)],
) -> ContributionDirectionsResponse:
    return await SpecService(db, llm=llm).generate_contribution_directions(
        session_id=session_id,
        account_id=account.id,
        expected_version=body.expected_version,
    )

@router.post(
    "/sessions/{session_id}/claims/generate",
    response_model=GenerateClaimsResponse,
    responses={409: {"model": OperationalError}, 429: {"model": OperationalError}, 503: {"model": OperationalError}},
)
async def generate_claims(
    session_id: UUID,
    body: GenerateClaimsRequest,
    account: Annotated[Account, Depends(get_current_account)],
    db: Annotated[AsyncSession, Depends(get_db)],
    llm: Annotated[LlmPort, Depends(get_claims_llm)],
) -> GenerateClaimsResponse:
    return await SpecService(db, llm=llm).generate_claims(
        session_id=session_id,
        account_id=account.id,
        expected_version=body.expected_version,
    )

@router.post(
    "/sessions/{session_id}/experiment-plan/generate",
    response_model=GenerateExperimentResponse,
    responses={409: {"model": OperationalError}, 429: {"model": OperationalError}, 503: {"model": OperationalError}},
)
async def generate_experiment(
    session_id: UUID,
    body: GenerateExperimentRequest,
    account: Annotated[Account, Depends(get_current_account)],
    db: Annotated[AsyncSession, Depends(get_db)],
    llm: Annotated[LlmPort, Depends(get_experiment_llm)],
) -> GenerateExperimentResponse:
    return await SpecService(db, llm=llm).generate_experiment_plan(
        session_id=session_id,
        account_id=account.id,
        expected_version=body.expected_version,
    )

@router.post(
    "/sessions/{session_id}/feasibility/check",
    response_model=CheckFeasibilityResponse,
    responses={409: {"model": OperationalError}, 429: {"model": OperationalError}, 503: {"model": OperationalError}},
)
async def check_feasibility(
    session_id: UUID,
    body: CheckFeasibilityRequest,
    account: Annotated[Account, Depends(get_current_account)],
    db: Annotated[AsyncSession, Depends(get_db)],
    llm: Annotated[LlmPort, Depends(get_feasibility_llm)],
) -> CheckFeasibilityResponse:
    return await SpecService(db, llm=llm).check_feasibility(
        session_id=session_id,
        account_id=account.id,
        expected_version=body.expected_version,
        plan=body.plan.model_dump(mode="json") if body.plan else None
    )
