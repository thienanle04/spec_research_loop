"""Idea workflow HTTP API — Grilling generate/SSE (ADR 0004, 0012, 0024)."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import OperationalError
from app.db.session import get_db
from app.modules.idea.schemas import GenerateRequest
from app.modules.idea.service import IdeaService
from app.modules.identity.deps import get_current_account
from app.modules.identity.models import Account

router = APIRouter()


@router.get("/health")
async def health() -> dict[str, str]:
    return {"module": "idea", "status": "ok"}


@router.post(
    "/sessions/{session_id}/generate",
    responses={409: {"model": OperationalError}},
)
async def generate(
    session_id: UUID,
    body: GenerateRequest,
    request: Request,
    account: Annotated[Account, Depends(get_current_account)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> StreamingResponse:
    service = IdeaService(db)
    run = await service.prepare_generate(
        session_id=session_id,
        account_id=account.id,
        expected_version=body.expected_version,
        message=body.message,
        answers=(
            [item.model_dump() for item in body.answers] if body.answers is not None else None
        ),
        note=body.note,
    )
    return StreamingResponse(
        service.stream_generate(
            session_id=session_id,
            account_id=account.id,
            expected_version=body.expected_version,
            run=run,
            request=request,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
