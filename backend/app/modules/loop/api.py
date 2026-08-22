"""Loop Session HTTP API."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import OperationalError
from app.db.session import get_db
from app.modules.identity.deps import get_current_account
from app.modules.identity.models import Account
from app.modules.loop.schemas import (
    CardMutationResponse,
    CardResponse,
    ConfirmRequest,
    CreateCardRequest,
    CreateSessionRequest,
    DecisionResponse,
    LoopSessionResponse,
    LoopSessionSummary,
    PatchCardRequest,
    PatchSessionRequest,
    PrepareRequest,
    WorkingDraftPatchRequest,
)
from app.modules.loop.service import LoopService

router = APIRouter()


def _service(db: AsyncSession) -> LoopService:
    return LoopService(db)


@router.get("/health")
async def health() -> dict[str, str]:
    return {"module": "loop", "status": "ok"}


@router.post("/sessions", response_model=LoopSessionResponse, status_code=201)
async def create_session(
    body: CreateSessionRequest,
    account: Annotated[Account, Depends(get_current_account)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> LoopSessionResponse:
    return await _service(db).create_session(account_id=account.id, title=body.title)


@router.get("/sessions", response_model=list[LoopSessionSummary])
async def list_sessions(
    account: Annotated[Account, Depends(get_current_account)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[LoopSessionSummary]:
    return await _service(db).list_sessions(account_id=account.id)


@router.get("/sessions/{session_id}", response_model=LoopSessionResponse)
async def get_session(
    session_id: UUID,
    account: Annotated[Account, Depends(get_current_account)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> LoopSessionResponse:
    return await _service(db).get_session(session_id=session_id, account_id=account.id)


@router.patch(
    "/sessions/{session_id}",
    response_model=LoopSessionResponse,
    responses={409: {"model": OperationalError}},
)
async def patch_session(
    session_id: UUID,
    body: PatchSessionRequest,
    account: Annotated[Account, Depends(get_current_account)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> LoopSessionResponse:
    return await _service(db).patch_title(
        session_id=session_id,
        account_id=account.id,
        title=body.title,
        expected_version=body.expected_version,
    )


@router.patch(
    "/sessions/{session_id}/working-draft",
    response_model=LoopSessionResponse,
    responses={409: {"model": OperationalError}},
)
async def patch_working_draft(
    session_id: UUID,
    body: WorkingDraftPatchRequest,
    account: Annotated[Account, Depends(get_current_account)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> LoopSessionResponse:
    return await _service(db).patch_working_draft(
        session_id=session_id,
        account_id=account.id,
        node=body.node,
        narrative=body.narrative,
        expected_version=body.expected_version,
    )


@router.get("/sessions/{session_id}/cards", response_model=list[CardResponse])
async def list_cards(
    session_id: UUID,
    account: Annotated[Account, Depends(get_current_account)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[CardResponse]:
    return await _service(db).list_cards(session_id=session_id, account_id=account.id)


@router.post(
    "/sessions/{session_id}/cards",
    response_model=CardMutationResponse,
    status_code=201,
    responses={409: {"model": OperationalError}},
)
async def create_card(
    session_id: UUID,
    body: CreateCardRequest,
    account: Annotated[Account, Depends(get_current_account)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> CardMutationResponse:
    return await _service(db).create_card(
        session_id=session_id,
        account_id=account.id,
        kind=body.kind,
        body=body.body,
        expected_version=body.expected_version,
    )


@router.patch(
    "/sessions/{session_id}/cards/{card_id}",
    response_model=CardMutationResponse,
    responses={409: {"model": OperationalError}},
)
async def patch_card(
    session_id: UUID,
    card_id: UUID,
    body: PatchCardRequest,
    account: Annotated[Account, Depends(get_current_account)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> CardMutationResponse:
    return await _service(db).patch_card(
        session_id=session_id,
        account_id=account.id,
        card_id=card_id,
        body=body.body,
        expected_version=body.expected_version,
    )


@router.get("/sessions/{session_id}/decisions", response_model=list[DecisionResponse])
async def list_decisions(
    session_id: UUID,
    account: Annotated[Account, Depends(get_current_account)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[DecisionResponse]:
    return await _service(db).list_decisions(
        session_id=session_id, account_id=account.id
    )


@router.post(
    "/sessions/{session_id}/confirm",
    response_model=LoopSessionResponse,
    responses={409: {"model": OperationalError}},
)
async def confirm(
    session_id: UUID,
    body: ConfirmRequest,
    account: Annotated[Account, Depends(get_current_account)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> LoopSessionResponse:
    return await _service(db).confirm(
        session_id=session_id,
        account_id=account.id,
        node=body.node,
        expected_version=body.expected_version,
    )


@router.post(
    "/sessions/{session_id}/recompute-prepare",
    response_model=LoopSessionResponse,
    responses={409: {"model": OperationalError}},
)
async def recompute_prepare(
    session_id: UUID,
    body: PrepareRequest,
    account: Annotated[Account, Depends(get_current_account)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> LoopSessionResponse:
    return await _service(db).recompute_prepare(
        session_id=session_id,
        account_id=account.id,
        stage=body.stage,
        expected_version=body.expected_version,
    )
