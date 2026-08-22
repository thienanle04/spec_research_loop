from typing import Annotated
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
)
from app.modules.spec.service import SpecService
from app.ports.llm import LlmPort

router = APIRouter()


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
