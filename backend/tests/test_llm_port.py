"""LlmPort bind map, FakeLlm, LangChain adapter, and LLM call traces (ADR 0006, ADR 0022)."""

import logging

import pytest
from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableLambda

from app.adapters.llm import (
    FakeLlm,
    LangChainChatAdapter,
    TracingLlm,
    bind_llm_ports,
    get_llm_port,
    traced_ports,
)
from app.core.config import get_settings
from app.modules.loop.catalog import WORKFLOW_NODES
from app.ports.llm import LlmCompleteError, LlmProviderError


@pytest.fixture(autouse=True)
def _reset_llm_bind() -> None:
    bind_llm_ports({})
    yield
    bind_llm_ports({})


@pytest.mark.asyncio
async def test_fake_llm_records_calls_and_returns_configured_string() -> None:
    fake = FakeLlm(response="hello")
    text = await fake.complete(system="sys", prompt="go", model="gpt-test")
    assert text == "hello"
    assert fake.calls[0].system == "sys"
    assert fake.calls[0].prompt == "go"
    assert fake.calls[0].model == "gpt-test"


@pytest.mark.asyncio
async def test_fake_llm_stream_yields_configured_chunks() -> None:
    fake = FakeLlm(chunks=["he", "llo"])
    parts: list[str] = []
    async for token in fake.stream(system="sys", prompt="go"):
        parts.append(token)
    assert parts == ["he", "llo"]
    assert await fake.complete(system="sys", prompt="go") == "hello"


def test_bind_maps_every_workflow_node_to_the_same_instance() -> None:
    fake = FakeLlm()
    bind_llm_ports({node.value: fake for node in WORKFLOW_NODES})
    ports = [get_llm_port(node.value) for node in WORKFLOW_NODES]
    assert len(ports) == len(WORKFLOW_NODES)
    assert all(port is fake for port in ports)


def test_get_llm_port_missing_node_fails_loudly() -> None:
    bind_llm_ports({"idea_interpretation": FakeLlm()})
    with pytest.raises(KeyError, match="idea_decomposition"):
        get_llm_port("idea_decomposition")


def test_get_llm_port_unbound_fails_loudly() -> None:
    from app.adapters import llm as llm_mod

    llm_mod._llm_ports = None
    with pytest.raises(RuntimeError, match="not bound"):
        get_llm_port("idea_interpretation")


@pytest.mark.asyncio
async def test_langchain_complete_requires_api_key() -> None:
    adapter = LangChainChatAdapter(api_key=None, default_model="gpt-test")
    with pytest.raises(LlmCompleteError, match="LLM_API_KEY"):
        await adapter.complete(system="sys", prompt="go")


@pytest.mark.asyncio
async def test_langchain_structured_uses_json_path_when_base_url_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from pydantic import BaseModel

    class Out(BaseModel):
        value: str

    def boom(**_kwargs: object) -> object:
        raise AssertionError("ChatOpenAI should not be constructed for structured via JSON")

    async def fake_complete(
        self: LangChainChatAdapter,
        *,
        system: str,
        prompt: str,
        model: str | None = None,
    ) -> str:
        del self, prompt, model
        assert "JSON Schema" in system
        return '{"value":"via-base-url"}'

    monkeypatch.setattr("app.adapters.llm.langchain_chat.ChatOpenAI", boom)
    monkeypatch.setattr(LangChainChatAdapter, "complete", fake_complete)
    adapter = LangChainChatAdapter(
        api_key="sk-test",
        base_url="https://ai-fit.hcmus.edu.vn/openai",
        default_model="Qwen3.6-27B",
    )
    result = await adapter.complete_structured(system="sys", prompt="go", schema=Out)
    assert result == Out(value="via-base-url")


@pytest.mark.asyncio
async def test_langchain_structured_falls_back_when_json_mode_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from pydantic import BaseModel

    class Out(BaseModel):
        value: str

    class BadRequest(Exception):
        status_code = 400

    class FakeChat:
        def with_structured_output(self, _schema: object, **_kwargs: object):
            async def _raise(_messages: object) -> object:
                raise BadRequest()

            return RunnableLambda(_raise)

    async def fake_complete(
        self: LangChainChatAdapter,
        *,
        system: str,
        prompt: str,
        model: str | None = None,
    ) -> str:
        del self, prompt, model
        assert "JSON Schema" in system
        return '{"value":"ok"}'

    monkeypatch.setattr(
        "app.adapters.llm.langchain_chat.ChatOpenAI",
        lambda **_kwargs: FakeChat(),
    )
    monkeypatch.setattr(LangChainChatAdapter, "complete", fake_complete)
    adapter = LangChainChatAdapter(api_key="sk-test", default_model="gpt-test")
    result = await adapter.complete_structured(system="sys", prompt="go", schema=Out)
    assert result == Out(value="ok")


@pytest.mark.asyncio
async def test_langchain_maps_rate_limit_to_safe_provider_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class RateLimited(Exception):
        status_code = 429
        code = "429"

        def __str__(self) -> str:
            return "Error code: 429 - secret email leak"

    class FakeChat:
        def with_structured_output(
            self, _schema: object, **_kwargs: object
        ) -> RunnableLambda:
            async def _raise(_messages: object) -> object:
                raise RateLimited()

            return RunnableLambda(_raise)

    monkeypatch.setattr(
        "app.adapters.llm.langchain_chat.ChatOpenAI",
        lambda **_kwargs: FakeChat(),
    )
    adapter = LangChainChatAdapter(api_key="sk-test", default_model="gpt-test")
    with pytest.raises(LlmProviderError, match="rate limit") as caught:
        await adapter.complete_structured(system="s", prompt="p", schema=dict)
    assert caught.value.status_code == 429
    assert "secret email" not in str(caught.value)


@pytest.mark.asyncio
async def test_langchain_complete_invokes_lcel_chain(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def fake_chat(**kwargs: object) -> RunnableLambda:
        captured["kwargs"] = kwargs

        def _reply(messages: object) -> AIMessage:
            captured["messages"] = messages
            return AIMessage(content="done")

        return RunnableLambda(_reply)

    monkeypatch.setattr("app.adapters.llm.langchain_chat.ChatOpenAI", fake_chat)
    adapter = LangChainChatAdapter(
        api_key="test-key",
        default_model="gpt-test",
    )
    text = await adapter.complete(system="sys", prompt="go {braces}")
    assert text == "done"
    assert captured["kwargs"]["model"] == "gpt-test"
    assert captured["kwargs"]["api_key"] == "test-key"


def test_create_app_binds_ports_by_profile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.main import create_app

    monkeypatch.setenv("LLM_TRACE", "false")
    monkeypatch.setenv("LLM_PROVIDERS", "")
    monkeypatch.setenv("LLM_PROFILES", "")
    monkeypatch.setenv("LLM_NODE_PROFILE_OVERRIDES", "")
    monkeypatch.setenv("LLM_API_KEY", "sk-test")
    get_settings.cache_clear()
    create_app()
    creative = get_llm_port("idea_interpretation")
    research = get_llm_port("research_inputs")
    structured = get_llm_port("claims")
    judge = get_llm_port("gap_judge")
    assert isinstance(creative, LangChainChatAdapter)
    assert research is creative
    assert structured is creative
    assert judge is creative
    assert get_llm_port("idea_decomposition") is creative
    assert get_llm_port("related_work") is research
    assert get_llm_port("gap") is research
    assert creative.default_model == "Qwen3.6-27B"
    get_settings.cache_clear()


def test_create_app_wraps_each_node_when_llm_trace_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.main import create_app

    monkeypatch.setenv("LLM_TRACE", "true")
    monkeypatch.setenv("LLM_PROVIDERS", "")
    monkeypatch.setenv("LLM_PROFILES", "")
    monkeypatch.setenv("LLM_NODE_PROFILE_OVERRIDES", "")
    monkeypatch.setenv("LLM_API_KEY", "sk-test")
    get_settings.cache_clear()
    try:
        create_app()
        ports = [get_llm_port(node.value) for node in WORKFLOW_NODES]
        assert all(isinstance(port, TracingLlm) for port in ports)
        wrappers = [port for port in ports if isinstance(port, TracingLlm)]
        assert {port._node for port in wrappers} == {node.value for node in WORKFLOW_NODES}
        assert isinstance(get_llm_port("idea_interpretation")._inner, LangChainChatAdapter)
        assert isinstance(get_llm_port("research_inputs")._inner, LangChainChatAdapter)
        assert get_llm_port("idea_interpretation")._inner is get_llm_port(
            "research_inputs"
        )._inner
    finally:
        log = logging.getLogger("app.adapters.llm")
        log.handlers.clear()
        log.propagate = True
        get_settings.cache_clear()


def test_traced_ports_leaves_bind_map_as_plain_dict() -> None:
    fake = FakeLlm()
    wrapped = traced_ports({"idea_interpretation": fake, "idea_decomposition": fake})
    bind_llm_ports(wrapped)
    interpretation = get_llm_port("idea_interpretation")
    decomposition = get_llm_port("idea_decomposition")
    assert isinstance(interpretation, TracingLlm)
    assert isinstance(decomposition, TracingLlm)
    assert interpretation is not decomposition
    assert interpretation._inner is fake
    assert decomposition._inner is fake


@pytest.mark.asyncio
async def test_tracing_llm_logs_one_record_per_complete(caplog: pytest.LogCaptureFixture) -> None:
    fake = FakeLlm(chunks=["he", "llo"])
    wrapped = TracingLlm(fake, node="idea_interpretation")
    with caplog.at_level(logging.INFO, logger="app.adapters.llm"):
        text = await wrapped.complete(system="sys", prompt="go", model="gpt-test")
    assert text == "hello"
    assert fake.calls[0].model == "gpt-test"
    records = [r for r in caplog.records if r.name == "app.adapters.llm"]
    assert len(records) == 1
    msg = records[0].getMessage()
    assert "node=idea_interpretation" in msg
    assert "model=gpt-test" in msg
    assert "outcome=ok" in msg
    assert "system_chars=3" in msg
    assert "prompt_chars=2" in msg
    assert "completion_chars=5" in msg
    assert "--- system ---\nsys\n" in msg
    assert "--- prompt ---\ngo\n" in msg
    assert "--- completion ---\nhello" in msg


@pytest.mark.asyncio
async def test_tracing_llm_uses_default_model_when_omitted(
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LLM_DEFAULT_MODEL", "gpt-from-settings")
    get_settings.cache_clear()
    wrapped = TracingLlm(FakeLlm(response="x", default_model=""), node="gap_judge")
    with caplog.at_level(logging.INFO, logger="app.adapters.llm"):
        await wrapped.complete(system="s", prompt="p")
    assert "model=gpt-from-settings" in caplog.records[0].getMessage()
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_tracing_llm_prefers_inner_default_model(
    caplog: pytest.LogCaptureFixture,
) -> None:
    wrapped = TracingLlm(FakeLlm(response="x", default_model="profile-model"), node="gap")
    with caplog.at_level(logging.INFO, logger="app.adapters.llm"):
        await wrapped.complete(system="s", prompt="p")
    assert "model=profile-model" in caplog.records[0].getMessage()


@pytest.mark.asyncio
async def test_tracing_llm_logs_cancelled_with_partial_completion(
    caplog: pytest.LogCaptureFixture,
) -> None:
    wrapped = TracingLlm(FakeLlm(chunks=["a", "b", "c"]), node="idea_interpretation")
    with caplog.at_level(logging.INFO, logger="app.adapters.llm"):
        agen = wrapped.stream(system="s", prompt="p", model="m")
        assert await anext(agen) == "a"
        await agen.aclose()
    records = [r for r in caplog.records if r.name == "app.adapters.llm"]
    assert len(records) == 1
    msg = records[0].getMessage()
    assert "outcome=cancelled" in msg
    assert "--- completion ---\na" in msg


@pytest.mark.asyncio
async def test_tracing_llm_logs_error_on_llm_complete_error(
    caplog: pytest.LogCaptureFixture,
) -> None:
    class BoomLlm:
        async def stream(self, *, system: str, prompt: str, model: str | None = None):
            raise LlmCompleteError("vendor down")
            yield ""  # pragma: no cover

        async def complete(self, *, system: str, prompt: str, model: str | None = None) -> str:
            raise LlmCompleteError("vendor down")

    wrapped = TracingLlm(BoomLlm(), node="idea_interpretation")
    with caplog.at_level(logging.INFO, logger="app.adapters.llm"):
        with pytest.raises(LlmCompleteError, match="vendor down"):
            await wrapped.complete(system="s", prompt="p", model="m")
    records = [r for r in caplog.records if r.name == "app.adapters.llm"]
    assert len(records) == 1
    assert "outcome=error" in records[0].getMessage()
    assert "completion_chars=0" in records[0].getMessage()
