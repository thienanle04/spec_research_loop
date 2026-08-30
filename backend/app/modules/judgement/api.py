"""Judgement REST and in-request SSE routes."""

import json
from collections.abc import AsyncIterator
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import OperationalError
from app.db.session import get_db
from app.modules.identity.deps import get_current_account
from app.modules.identity.models import Account
from app.modules.judgement.deps import get_judgement_node_llm
from app.modules.judgement.schemas import (
    ConferenceScores,
    JudgementGenerateRequest,
    JudgementNode,
    JudgeRunResponse,
    ReadinessResponse,
    ReadinessState,
)
from app.modules.judgement.service import JudgementService
from app.modules.loop.service import LoopService
from app.ports.llm import LlmPort

router = APIRouter()


@router.get("/health")
async def health() -> dict[str, str]:
    return {"module": "judgement", "status": "ok"}


@router.get(
    "/sessions/{session_id}/nodes/{node}",
    response_model=JudgeRunResponse,
)
async def get_judge_run(
    session_id: UUID,
    node: JudgementNode,
    account: Annotated[Account, Depends(get_current_account)],
    db: Annotated[AsyncSession, Depends(get_db)],
    llm: Annotated[LlmPort, Depends(get_judgement_node_llm)],
    stage_revision_id: UUID | None = None,
) -> JudgeRunResponse:
    return await JudgementService(db, llm).get_run(
        session_id=session_id,
        account_id=account.id,
        node=node,
        stage_revision_id=stage_revision_id,
    )


@router.get(
    "/sessions/{session_id}/readiness",
    response_model=ReadinessResponse,
)
async def get_readiness(
    session_id: UUID,
    account: Annotated[Account, Depends(get_current_account)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ReadinessResponse:
    summary = await LoopService(db).get_readiness(
        session_id=session_id, account_id=account.id
    )
    return ReadinessResponse(
        state=ReadinessState(summary.state),
        notice=summary.notice,
        scores=(
            ConferenceScores.model_validate(summary.scores)
            if summary.scores is not None
            else None
        ),
    )


@router.post(
    "/sessions/{session_id}/nodes/{node}/generate",
    responses={409: {"model": OperationalError}},
)
async def generate(
    session_id: UUID,
    node: JudgementNode,
    body: JudgementGenerateRequest,
    account: Annotated[Account, Depends(get_current_account)],
    db: Annotated[AsyncSession, Depends(get_db)],
    llm: Annotated[LlmPort, Depends(get_judgement_node_llm)],
) -> StreamingResponse:
    service = JudgementService(db, llm)
    run = await service.begin_generation(
        session_id=session_id,
        account_id=account.id,
        node=node,
        body=body,
    )
    return StreamingResponse(
        _event_stream(service.generate(run)),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post(
    "/sessions/{session_id}/generate-pending",
    responses={409: {"model": OperationalError}},
)
async def generate_pending(
    session_id: UUID,
    body: JudgementGenerateRequest,
    account: Annotated[Account, Depends(get_current_account)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> StreamingResponse:
    service = JudgementService(db)
    runs = await service.begin_pending_generation(
        session_id=session_id,
        account_id=account.id,
        body=body,
    )
    return StreamingResponse(
        _event_stream(service.generate_pending(runs)),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


async def _event_stream(
    events: AsyncIterator[dict],
) -> AsyncIterator[str]:
    async for event in events:
        event_name = event.get("type", "message")
        payload = json.dumps(event, ensure_ascii=False)
        yield f"event: {event_name}\ndata: {payload}\n\n"
