"""Loop Session HTTP API."""

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Body, Depends, Query
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import OperationalError
from app.db.session import get_db
from app.modules.identity.deps import get_current_account
from app.modules.identity.models import Account
from app.modules.loop.schemas import (
    CardBatchMutationResponse,
    CardMutationResponse,
    CardResponse,
    ConfirmRequest,
    CreateCardRequest,
    CreateSessionRequest,
    DecisionResponse,
    ExportScratchDiffResponse,
    HandlingOptionPickRequest,
    LoopSessionResponse,
    LoopSessionSummary,
    PatchCardRequest,
    PatchExportScratchRequest,
    PatchSessionRequest,
    PrepareRequest,
    ReplaceCardsRequest,
    RestoreExportScratchSnapshotRequest,
    SaveExportScratchSnapshotRequest,
    SpecArtifactExportRequest,
    SpecArtifactResponse,
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
    spec_version_id: Annotated[UUID | None, Query()] = None,
) -> LoopSessionResponse:
    return await _service(db).get_session(
        session_id=session_id,
        account_id=account.id,
        spec_version_id=spec_version_id,
    )


@router.patch(
    "/sessions/{session_id}",
    response_model=LoopSessionResponse,
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
    )


@router.patch(
    "/sessions/{session_id}/export-scratch",
    response_model=LoopSessionResponse,
    responses={409: {"model": OperationalError}},
)
async def patch_export_scratch(
    session_id: UUID,
    body: PatchExportScratchRequest,
    account: Annotated[Account, Depends(get_current_account)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> LoopSessionResponse:
    return await _service(db).patch_export_scratch(
        session_id=session_id,
        account_id=account.id,
        expected_version=body.expected_version,
        document=body.document.model_dump(),
        spec_version_id=body.spec_version_id,
    )


@router.post(
    "/sessions/{session_id}/export-scratch/snapshots",
    response_model=LoopSessionResponse,
    responses={409: {"model": OperationalError}},
)
async def save_export_scratch_snapshot(
    session_id: UUID,
    body: SaveExportScratchSnapshotRequest,
    account: Annotated[Account, Depends(get_current_account)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> LoopSessionResponse:
    return await _service(db).save_export_scratch_snapshot(
        session_id=session_id,
        account_id=account.id,
        expected_version=body.expected_version,
        spec_version_id=body.spec_version_id,
    )


@router.post(
    "/sessions/{session_id}/export-scratch/snapshots/{snapshot_id}/restore",
    response_model=LoopSessionResponse,
    responses={409: {"model": OperationalError}},
)
async def restore_export_scratch_snapshot(
    session_id: UUID,
    snapshot_id: UUID,
    body: RestoreExportScratchSnapshotRequest,
    account: Annotated[Account, Depends(get_current_account)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> LoopSessionResponse:
    return await _service(db).restore_export_scratch_snapshot(
        session_id=session_id,
        account_id=account.id,
        snapshot_id=snapshot_id,
        expected_version=body.expected_version,
    )


@router.get(
    "/sessions/{session_id}/export-scratch/diff",
    response_model=ExportScratchDiffResponse,
)
async def export_scratch_diff(
    session_id: UUID,
    account: Annotated[Account, Depends(get_current_account)],
    db: Annotated[AsyncSession, Depends(get_db)],
    against: Annotated[Literal["previous", "original"], Query()],
    spec_version_id: Annotated[UUID | None, Query()] = None,
) -> ExportScratchDiffResponse:
    return await _service(db).export_scratch_diff(
        session_id=session_id,
        account_id=account.id,
        against=against,
        spec_version_id=spec_version_id,
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


@router.put(
    "/sessions/{session_id}/cards",
    response_model=CardBatchMutationResponse,
    responses={409: {"model": OperationalError}},
)
async def replace_cards(
    session_id: UUID,
    body: ReplaceCardsRequest,
    account: Annotated[Account, Depends(get_current_account)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> CardBatchMutationResponse:
    return await _service(db).replace_cards(
        session_id=session_id,
        account_id=account.id,
        kind=body.kind,
        bodies=body.bodies,
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
    "/sessions/{session_id}/pick",
    response_model=LoopSessionResponse,
    responses={409: {"model": OperationalError}},
)
async def pick_handling_option(
    session_id: UUID,
    body: HandlingOptionPickRequest,
    account: Annotated[Account, Depends(get_current_account)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> LoopSessionResponse:
    return await _service(db).pick_handling_option(
        session_id=session_id,
        account_id=account.id,
        expected_version=body.expected_version,
        handling_option_id=body.handling_option_id,
        prose=body.prose,
        target_node=body.target_node,
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
        stale_reaccept=body.stale_reaccept,
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


@router.post(
    "/sessions/{session_id}/export-scratch/markdown",
    summary="Download Export Scratch markdown",
    responses={409: {"model": OperationalError}},
)
async def download_export_scratch_markdown(
    session_id: UUID,
    account: Annotated[Account, Depends(get_current_account)],
    db: Annotated[AsyncSession, Depends(get_db)],
    body: Annotated[SpecArtifactExportRequest | None, Body()] = None,
    spec_version_id: Annotated[UUID | None, Query()] = None,
) -> Response:
    ack = False if body is None else body.critical_export_ack
    filename, markdown = await _service(db).download_export_scratch_markdown(
        session_id=session_id,
        account_id=account.id,
        critical_export_ack=ack,
        spec_version_id=spec_version_id,
    )
    return Response(
        content=markdown.encode("utf-8"),
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post(
    "/sessions/{session_id}/export-scratch/pdf",
    summary="Download Export Scratch PDF",
    responses={409: {"model": OperationalError}},
)
async def download_export_scratch_pdf(
    session_id: UUID,
    account: Annotated[Account, Depends(get_current_account)],
    db: Annotated[AsyncSession, Depends(get_db)],
    body: Annotated[SpecArtifactExportRequest | None, Body()] = None,
    spec_version_id: Annotated[UUID | None, Query()] = None,
) -> Response:
    ack = False if body is None else body.critical_export_ack
    filename, pdf_bytes = await _service(db).download_export_scratch_pdf(
        session_id=session_id,
        account_id=account.id,
        critical_export_ack=ack,
        spec_version_id=spec_version_id,
    )
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post(
    "/sessions/{session_id}/spec-artifact",
    response_model=SpecArtifactResponse,
    responses={409: {"model": OperationalError}},
)
async def export_spec_artifact(
    session_id: UUID,
    account: Annotated[Account, Depends(get_current_account)],
    db: Annotated[AsyncSession, Depends(get_db)],
    body: Annotated[SpecArtifactExportRequest | None, Body()] = None,
) -> SpecArtifactResponse:
    ack = False if body is None else body.critical_export_ack
    return await _service(db).export_spec_artifact(
        session_id=session_id,
        account_id=account.id,
        critical_export_ack=ack,
    )
