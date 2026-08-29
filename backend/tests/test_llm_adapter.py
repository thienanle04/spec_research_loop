"""Tests for LLM adapter binding and port contracts without network access."""

import json

import pytest
from pydantic import BaseModel

from app.adapters.llm import bind_llm_ports, build_llm_ports, get_llm_port
from app.adapters.llm.langchain_chat import LangChainChatAdapter
from app.core.config import get_settings
from app.modules.research.adapters.fake_llm import FakeLlmPort
from app.modules.spec.deps import FakeSpecLlmPort
from app.modules.spec.schemas import (
    FeasibilityReport,
    GenerateClaimsResponse,
    GenerateExperimentResponse,
)
from app.ports.llm import LlmPort


class _StructuredResult(BaseModel):
    value: str


def test_default_profiles_bind_ai_fit_langchain(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LLM_API_KEY", "sk-test")
    monkeypatch.setenv("LLM_BASE_URL", "https://ai-fit.hcmus.edu.vn/openai")
    monkeypatch.setenv("LLM_PROVIDERS", "")
    monkeypatch.setenv("LLM_PROFILES", "")
    monkeypatch.setenv("LLM_NODE_PROFILE_OVERRIDES", "")
    get_settings.cache_clear()

    try:
        ports = build_llm_ports(get_settings())
        bind_llm_ports(ports)
        research = get_llm_port("research_inputs")
        assert isinstance(research, LangChainChatAdapter)
        assert research.default_model == "Qwen3.6-27B"
        assert research._base_url == "https://ai-fit.hcmus.edu.vn/openai"
        assert get_llm_port("related_work") is research
        assert get_llm_port("idea_interpretation") is research
    finally:
        get_settings.cache_clear()


@pytest.mark.asyncio
async def test_research_fake_llm_implements_port() -> None:
    adapter = FakeLlmPort(responses={"structured": '{"value":"fake"}'})
    assert isinstance(adapter, LlmPort)
    result = await adapter.complete_structured(
        system="structured",
        prompt="{}",
        schema=_StructuredResult,
    )
    assert result == _StructuredResult(value="fake")


@pytest.mark.asyncio
async def test_fake_spec_llm_implements_port() -> None:
    adapter = FakeSpecLlmPort()

    assert isinstance(adapter, LlmPort)
    chunks = [
        chunk
        async for chunk in adapter.stream(system="directions", prompt="{}")
    ]
    assert len(chunks) == 1
    assert len(json.loads(chunks[0])) == 3

    claims = await adapter.complete_structured(
        system="claims",
        prompt="{}",
        schema=GenerateClaimsResponse,
    )
    experiment = await adapter.complete_structured(
        system="experiment",
        prompt="{}",
        schema=GenerateExperimentResponse,
    )
    feasibility = await adapter.complete_structured(
        system="feasibility",
        prompt="{}",
        schema=FeasibilityReport,
    )

    assert claims.cards[0].id == "claim-1"
    assert experiment.plan.experiments[0].claim.startswith("Claim-level")
    assert feasibility.is_feasible is True
