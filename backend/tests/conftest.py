"""Async HTTP client against a dedicated Postgres database."""

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import get_settings
from app.db import models as _models  # noqa: F401
from app.db.base import Base
from app.db.session import dispose_engine, get_engine
from app.main import create_app

TEST_DB = "specresearch_test"
ADMIN_URL = "postgresql+asyncpg://postgres:postgres@localhost:55432/postgres"
TEST_URL = f"postgresql+asyncpg://postgres:postgres@localhost:55432/{TEST_DB}"


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
    monkeypatch.setenv("RESEARCH_LLM_PROVIDER", "fake")
    get_settings.cache_clear()
    await dispose_engine()
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as instance:
        yield instance

    await dispose_engine()
    get_settings.cache_clear()
