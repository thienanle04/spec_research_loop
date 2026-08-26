"""Tests for the live LLM adapter response contract without network access."""

import json
from typing import Self

import httpx
import pytest
from pydantic import BaseModel

from app.adapters.llm.fit_webui import (
    FitWebUiLlmPort,
)
from app.adapters.llm.fit_webui import (
    _raise_for_status as raise_fit_webui_for_status,
)
from app.adapters.llm.fit_webui import (
    _response_text as fit_webui_response_text,
)
from app.core.config import get_settings
from app.modules.research.adapters.fake_llm import FakeLlmPort
from app.modules.research.deps import get_research_llm
from app.modules.spec.deps import FakeSpecLlmPort
from app.modules.spec.schemas import (
    FeasibilityReport,
    GenerateClaimsResponse,
    GenerateExperimentResponse,
)
from app.ports.llm import LlmPort, LlmProviderError


class _StructuredResult(BaseModel):
    value: str


def test_fit_webui_response_text_reads_chat_completion() -> None:
    payload = {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": '{"queries":["claim evidence"]}',
                }
            }
        ]
    }

    assert fit_webui_response_text(payload) == '{"queries":["claim evidence"]}'


def test_fit_webui_response_text_rejects_empty_output() -> None:
    with pytest.raises(ValueError, match="output text"):
        fit_webui_response_text({"choices": []})


def test_fit_webui_auth_error_is_safe() -> None:
    response = httpx.Response(
        401,
        request=httpx.Request(
            "POST", "https://ai-fit.hcmus.edu.vn/openai/chat/completions"
        ),
        json={"error": {"code": "invalid_key", "message": "vendor detail"}},
    )

    with pytest.raises(LlmProviderError, match="rejected") as caught:
        raise_fit_webui_for_status(response)

    assert caught.value.provider == "fit_webui"
    assert caught.value.status_code == 401
    assert caught.value.code == "invalid_key"
    assert "vendor detail" not in str(caught.value)


@pytest.mark.asyncio
async def test_fit_webui_calls_chat_completions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    class FakeAsyncClient:
        def __init__(self, *, timeout: float) -> None:
            captured["timeout"] = timeout

        async def __aenter__(self) -> Self:
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

        async def post(
            self,
            url: str,
            *,
            headers: dict[str, str],
            json: dict[str, object],
        ) -> httpx.Response:
            captured.update(url=url, headers=headers, json=json)
            return httpx.Response(
                200,
                request=httpx.Request("POST", url),
                json={"choices": [{"message": {"content": "result"}}]},
            )

    monkeypatch.setattr(
        "app.adapters.llm.fit_webui.httpx.AsyncClient", FakeAsyncClient
    )
    adapter = FitWebUiLlmPort(
        api_key="sk-test",
        default_model="Qwen3.6-27B",
        timeout_seconds=30,
    )

    result = await adapter.complete(system="system", prompt="prompt")

    assert result == "result"
    assert captured["url"] == (
        "https://ai-fit.hcmus.edu.vn/openai/chat/completions"
    )
    assert captured["headers"] == {
        "Authorization": "Bearer sk-test",
        "Content-Type": "application/json",
    }
    assert captured["json"] == {
        "model": "Qwen3.6-27B",
        "messages": [
            {"role": "system", "content": "system"},
            {"role": "user", "content": "prompt"},
        ],
        "max_tokens": 4_000,
        "response_format": {"type": "json_object"},
        "stream": False,
    }


@pytest.mark.asyncio
async def test_fit_webui_timeout_is_converted_to_safe_provider_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class TimeoutAsyncClient:
        def __init__(self, *, timeout: float) -> None:
            assert timeout == 120

        async def __aenter__(self) -> Self:
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

        async def post(self, url: str, **_kwargs: object) -> httpx.Response:
            raise httpx.ReadTimeout(
                "vendor detail",
                request=httpx.Request("POST", url),
            )

    monkeypatch.setattr(
        "app.adapters.llm.fit_webui.httpx.AsyncClient", TimeoutAsyncClient
    )
    adapter = FitWebUiLlmPort(
        api_key="sk-test",
        default_model="Qwen3.6-27B",
        timeout_seconds=120,
    )

    with pytest.raises(LlmProviderError, match="timed out") as caught:
        await adapter.complete(system="system", prompt="prompt")

    assert caught.value.provider == "fit_webui"
    assert caught.value.code == "timeout"
    assert "vendor detail" not in str(caught.value)


def test_research_llm_binding_selects_fit_webui(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RESEARCH_LLM_PROVIDER", "fit_webui")
    monkeypatch.setenv("RESEARCH_LLM_MODEL", "Qwen3.6-27B")
    monkeypatch.setenv("FIT_WEBUI_API_KEY", "sk-test")
    get_settings.cache_clear()

    try:
        assert isinstance(get_research_llm(), FitWebUiLlmPort)
    finally:
        get_settings.cache_clear()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "adapter",
    [
        FakeLlmPort(responses={"structured": '{"value":"fake"}'}),
        FitWebUiLlmPort(api_key="sk-test", default_model="Qwen3.6-27B"),
    ],
)
async def test_research_llm_adapters_implement_port(
    adapter: FakeLlmPort | FitWebUiLlmPort,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert isinstance(adapter, LlmPort)

    if isinstance(adapter, FitWebUiLlmPort):
        async def fake_complete(**_kwargs: object) -> str:
            return '{"value":"live"}'

        monkeypatch.setattr(adapter, "complete", fake_complete)
        expected = "live"
    else:
        expected = "fake"

    result = await adapter.complete_structured(
        system="structured",
        prompt="{}",
        schema=_StructuredResult,
    )
    assert result == _StructuredResult(value=expected)


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
    assert experiment.plan.metrics == ["Unsupported claim rate"]
    assert feasibility.is_feasible is True
