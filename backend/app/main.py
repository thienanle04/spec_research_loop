"""SpecResearch Loop API — modular monolith entrypoint."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.adapters.llm import LangChainChatAdapter, bind_llm_ports
from app.adapters.storage import get_object_storage
from app.core.config import get_settings
from app.core.errors import OperationalErrorException, operational_error_handler
from app.db.session import dispose_engine
from app.modules.idea.api import router as idea_router
from app.modules.identity.api import router as identity_router
from app.modules.judgement.api import router as judgement_router
from app.modules.loop.api import router as loop_router
from app.modules.loop.catalog import WORKFLOW_NODES
from app.modules.loop.deps import bind_stage_ports, default_stage_ports
from app.modules.research.api import router as research_router
from app.modules.spec.api import router as spec_router


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    get_settings.cache_clear()
    storage = get_object_storage()
    try:
        await storage.ensure_bucket()
    except Exception:
        # MinIO may still be starting; API can retry puts later.
        pass
    yield
    await dispose_engine()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="SpecResearch Loop", version="0.1.0", lifespan=lifespan)
    app.add_exception_handler(OperationalErrorException, operational_error_handler)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(identity_router, prefix="/api/identity", tags=["identity"])
    app.include_router(loop_router, prefix="/api/loop", tags=["loop"])
    app.include_router(idea_router, prefix="/api/idea", tags=["idea"])
    app.include_router(research_router, prefix="/api/research", tags=["research"])
    app.include_router(spec_router, prefix="/api/spec", tags=["spec"])
    app.include_router(judgement_router, prefix="/api/judgement", tags=["judgement"])
    bind_stage_ports(default_stage_ports())
    llm = LangChainChatAdapter()
    bind_llm_ports({node.value: llm for node in WORKFLOW_NODES})

    @app.get("/health")
    async def root_health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
