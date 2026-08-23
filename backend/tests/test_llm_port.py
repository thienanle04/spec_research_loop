"""LlmPort bind map, FakeLlm, and LangChain adapter (ADR 0006, ADR 0022)."""

import pytest
from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableLambda

from app.adapters.llm import FakeLlm, LangChainChatAdapter, bind_llm_ports, get_llm_port
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


def test_create_app_binds_one_langchain_adapter_for_every_node() -> None:
    from app.main import create_app

    create_app()
    first = get_llm_port("idea_interpretation")
    assert isinstance(first, LangChainChatAdapter)
    for node in WORKFLOW_NODES:
        assert get_llm_port(node.value) is first
