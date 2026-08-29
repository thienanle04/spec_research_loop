"""Async HTTP client against a dedicated Postgres database."""

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.adapters.llm import bind_llm_ports, get_llm_port
from app.core.config import get_settings
from app.db import models as _models  # noqa: F401
from app.db.base import Base
from app.db.session import dispose_engine, get_engine
from app.main import create_app
from app.modules.loop.catalog import WORKFLOW_NODES, WorkflowNode
from app.modules.research.adapters.fake_llm import FakeLlmPort
from app.modules.spec.deps import FakeSpecLlmPort

TEST_DB = "specresearch_test"
ADMIN_URL = "postgresql+asyncpg://postgres:postgres@localhost:55432/postgres"
TEST_URL = f"postgresql+asyncpg://postgres:postgres@localhost:55432/{TEST_DB}"

_RESEARCH_NODES = {
    WorkflowNode.RESEARCH_INPUTS,
    WorkflowNode.RELATED_WORK,
    WorkflowNode.GAP,
}
_STRUCTURED_NODES = {
    WorkflowNode.CONTRIBUTION,
    WorkflowNode.CLAIMS,
    WorkflowNode.EVIDENCE,
    WorkflowNode.EXPERIMENT_PLAN,
    WorkflowNode.FEASIBILITY,
}


def _bind_test_domain_llms() -> None:
    """HTTP tests need schema-shaped fakes; runtime fake profiles stay generic (ADR 0034)."""
    research_llm = FakeLlmPort()
    spec_llm = FakeSpecLlmPort()
    ports: dict = {}
    for node in WORKFLOW_NODES:
        if node in _RESEARCH_NODES:
            ports[node.value] = research_llm
        elif node in _STRUCTURED_NODES:
            ports[node.value] = spec_llm
        else:
            ports[node.value] = get_llm_port(node.value)
    bind_llm_ports(ports)


@pytest.fixture
async def client(monkeypatch: pytest.MonkeyPatch) -> AsyncClient:
    admin = create_async_engine(ADMIN_URL, isolation_level="AUTOCOMMIT")
    async with admin.connect() as conn:
        exists = await conn.scalar(
            text("SELECT 1 FROM pg_database WHERE datname = :name"),
            {"name": TEST_DB},
        )
        if not exists:
            await conn.execute(text(f"CREATE DATABASE {TEST_DB}"))
    await admin.dispose()

    monkeypatch.setenv("DATABASE_URL", TEST_URL)
    monkeypatch.setenv("RESEARCH_SOURCE_PROVIDER", "fake")
    monkeypatch.setenv("RESEARCH_TEXT_STORAGE", "memory")
    monkeypatch.setenv("RESEARCH_REQUIRE_DOWNLOADABLE_FULL_TEXT", "false")
    get_settings.cache_clear()
    await dispose_engine()
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

    app = create_app()
    _bind_test_domain_llms()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as instance:
        yield instance

    await dispose_engine()
    get_settings.cache_clear()
