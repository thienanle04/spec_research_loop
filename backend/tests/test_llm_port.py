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
from app.ports.llm import LlmCompleteError


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
async def test_langchain_complete_requires_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    get_settings.cache_clear()
    monkeypatch.setattr(get_settings(), "llm_api_key", None)
    adapter = LangChainChatAdapter()
    with pytest.raises(LlmCompleteError, match="LLM_API_KEY"):
        await adapter.complete(system="sys", prompt="go")
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_langchain_complete_invokes_lcel_chain(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    monkeypatch.setenv("LLM_DEFAULT_MODEL", "gpt-test")
    get_settings.cache_clear()

    captured: dict[str, object] = {}

    def fake_chat(**kwargs: object) -> RunnableLambda:
        captured["kwargs"] = kwargs

        def _reply(messages: object) -> AIMessage:
            captured["messages"] = messages
            return AIMessage(content="done")

        return RunnableLambda(_reply)

    monkeypatch.setattr("app.adapters.llm.langchain_chat.ChatOpenAI", fake_chat)
    adapter = LangChainChatAdapter()
    text = await adapter.complete(system="sys", prompt="go {braces}")
    assert text == "done"
    assert captured["kwargs"]["model"] == "gpt-test"
    assert captured["kwargs"]["api_key"] == "test-key"
    get_settings.cache_clear()


def test_create_app_binds_one_langchain_adapter_for_every_node(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.main import create_app

    monkeypatch.setenv("LLM_TRACE", "false")
    get_settings.cache_clear()
    create_app()
    first = get_llm_port("idea_interpretation")
    assert isinstance(first, LangChainChatAdapter)
    for node in WORKFLOW_NODES:
        assert get_llm_port(node.value) is first
    get_settings.cache_clear()


def test_create_app_wraps_each_node_when_llm_trace_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.main import create_app

    monkeypatch.setenv("LLM_TRACE", "true")
    get_settings.cache_clear()
    try:
        create_app()
        ports = [get_llm_port(node.value) for node in WORKFLOW_NODES]
        assert all(isinstance(port, TracingLlm) for port in ports)
        wrappers = [port for port in ports if isinstance(port, TracingLlm)]
        inners = [port._inner for port in wrappers]
        assert all(inner is inners[0] for inner in inners)
        assert isinstance(inners[0], LangChainChatAdapter)
        assert {port._node for port in wrappers} == {node.value for node in WORKFLOW_NODES}
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
    wrapped = TracingLlm(FakeLlm(response="x"), node="gap_judge")
    with caplog.at_level(logging.INFO, logger="app.adapters.llm"):
        await wrapped.complete(system="s", prompt="p")
    assert "model=gpt-from-settings" in caplog.records[0].getMessage()
    get_settings.cache_clear()


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
