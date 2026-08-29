"""Research REST and in-request SSE routes."""

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
from app.modules.research.deps import (
    get_citation_verifier,
    get_document_text_source,
    get_research_bound_llm,
    get_research_node_llm,
    get_research_object_storage,
    get_scholarly_source,
)
from app.modules.research.ports import (
    CitationVerifier,
    DocumentTextPort,
    ScholarlySourcePort,
)
from app.modules.research.schemas import (
    CitationResponse,
    CitationSelectionUpdate,
    RelatedWorkFindingResponse,
    ResearchGenerateRequest,
    ResearchNode,
)
from app.modules.research.service import GenerationRun, ResearchService
from app.ports.llm import LlmPort
from app.ports.storage import ObjectStoragePort

router = APIRouter()


@router.get("/health")
async def health() -> dict[str, str]:
    return {"module": "research", "status": "ok"}


def _service(
    db: AsyncSession,
    source: ScholarlySourcePort,
    verifier: CitationVerifier,
    llm: LlmPort,
    document_text_source: DocumentTextPort,
    object_storage: ObjectStoragePort | None,
) -> ResearchService:
    return ResearchService(
        db,
        source=source,
        verifier=verifier,
        llm=llm,
        document_text_source=document_text_source,
        object_storage=object_storage,
    )


@router.get(
    "/sessions/{session_id}/citations",
    response_model=list[CitationResponse],
)
async def list_citations(
    session_id: UUID,
    account: Annotated[Account, Depends(get_current_account)],
    db: Annotated[AsyncSession, Depends(get_db)],
    source: Annotated[ScholarlySourcePort, Depends(get_scholarly_source)],
    verifier: Annotated[CitationVerifier, Depends(get_citation_verifier)],
    llm: Annotated[LlmPort, Depends(get_research_bound_llm)],
    document_text_source: Annotated[
        DocumentTextPort, Depends(get_document_text_source)
    ],
    object_storage: Annotated[
        ObjectStoragePort | None, Depends(get_research_object_storage)
    ],
) -> list[CitationResponse]:
    return await _service(
        db, source, verifier, llm, document_text_source, object_storage
    ).list_citations(
        session_id=session_id,
        account_id=account.id,
    )


@router.patch(
    "/sessions/{session_id}/citations/{citation_id}/selection",
    response_model=CitationResponse,
)
async def update_citation_selection(
    session_id: UUID,
    citation_id: UUID,
    body: CitationSelectionUpdate,
    account: Annotated[Account, Depends(get_current_account)],
    db: Annotated[AsyncSession, Depends(get_db)],
    source: Annotated[ScholarlySourcePort, Depends(get_scholarly_source)],
    verifier: Annotated[CitationVerifier, Depends(get_citation_verifier)],
    llm: Annotated[LlmPort, Depends(get_research_bound_llm)],
    document_text_source: Annotated[
        DocumentTextPort, Depends(get_document_text_source)
    ],
    object_storage: Annotated[
        ObjectStoragePort | None, Depends(get_research_object_storage)
    ],
) -> CitationResponse:
    return await _service(
        db, source, verifier, llm, document_text_source, object_storage
    ).set_citation_pinned(
        session_id=session_id,
        citation_id=citation_id,
        account_id=account.id,
        pinned=body.pinned,
    )


@router.get(
    "/sessions/{session_id}/findings",
    response_model=list[RelatedWorkFindingResponse],
)
async def list_findings(
    session_id: UUID,
    account: Annotated[Account, Depends(get_current_account)],
    db: Annotated[AsyncSession, Depends(get_db)],
    source: Annotated[ScholarlySourcePort, Depends(get_scholarly_source)],
    verifier: Annotated[CitationVerifier, Depends(get_citation_verifier)],
    llm: Annotated[LlmPort, Depends(get_research_bound_llm)],
    document_text_source: Annotated[
        DocumentTextPort, Depends(get_document_text_source)
    ],
    object_storage: Annotated[
        ObjectStoragePort | None, Depends(get_research_object_storage)
    ],
) -> list[RelatedWorkFindingResponse]:
    return await _service(
        db, source, verifier, llm, document_text_source, object_storage
    ).list_findings(
        session_id=session_id,
        account_id=account.id,
    )


@router.post(
    "/sessions/{session_id}/nodes/{node}/generate",
    responses={409: {"model": OperationalError}},
)
async def generate(
    session_id: UUID,
    node: ResearchNode,
    body: ResearchGenerateRequest,
    account: Annotated[Account, Depends(get_current_account)],
    db: Annotated[AsyncSession, Depends(get_db)],
    source: Annotated[ScholarlySourcePort, Depends(get_scholarly_source)],
    verifier: Annotated[CitationVerifier, Depends(get_citation_verifier)],
    llm: Annotated[LlmPort, Depends(get_research_node_llm)],
    document_text_source: Annotated[
        DocumentTextPort, Depends(get_document_text_source)
    ],
    object_storage: Annotated[
        ObjectStoragePort | None, Depends(get_research_object_storage)
    ],
) -> StreamingResponse:
    service = _service(
        db, source, verifier, llm, document_text_source, object_storage
    )
    # Preflight and version claim happen before response headers, so auth,
    # topology, and optimistic-concurrency failures keep their HTTP status.
    run = await service.begin_generation(
        session_id=session_id,
        account_id=account.id,
        node=node,
        body=body,
    )
    return StreamingResponse(
        _event_stream(service, run),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


async def _event_stream(
    service: ResearchService,
    run: GenerationRun,
) -> AsyncIterator[str]:
    async for event in service.generate(run):
        event_name = event.get("type", "message")
        payload = json.dumps(event, ensure_ascii=False)
        yield f"event: {event_name}\ndata: {payload}\n\n"
