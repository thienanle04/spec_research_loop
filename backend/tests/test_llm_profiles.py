"""Tests for Provider / ModelRef / Profile composition (ADR 0034)."""

import json

import pytest

from app.adapters.llm import (
    DEFAULT_NODE_PROFILE_MAP,
    FakeLlm,
    LangChainChatAdapter,
    bind_llm_ports,
    build_llm_ports,
    get_llm_port,
)
from app.core.config import get_settings
from app.modules.loop.catalog import WORKFLOW_NODES


@pytest.fixture(autouse=True)
def _reset_bind() -> None:
    bind_llm_ports({})
    yield
    bind_llm_ports({})


def test_default_node_profile_map_covers_every_workflow_node() -> None:
    assert set(DEFAULT_NODE_PROFILE_MAP) == {node.value for node in WORKFLOW_NODES}


def test_json_profiles_and_api_key_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "LLM_PROVIDERS",
        json.dumps(
            {
                "local": {
                    "kind": "langchain",
                    "api_key_env": "LOCAL_LLM_KEY",
                    "base_url": "http://localhost:11434/v1",
                },
                "fake": {"kind": "fake"},
            }
        ),
    )
    monkeypatch.setenv(
        "LLM_PROFILES",
        json.dumps(
            {
                "creative": {"provider_id": "local", "model": "llama"},
                "research": {"provider_id": "fake", "model": "fake"},
                "structured": {"provider_id": "local", "model": "llama"},
                "judge": {"provider_id": "local", "model": "llama"},
            }
        ),
    )
    monkeypatch.setenv("LOCAL_LLM_KEY", "sk-local")
    monkeypatch.setenv("LLM_NODE_PROFILE_OVERRIDES", "")
    get_settings.cache_clear()
    try:
        ports = build_llm_ports(get_settings())
        bind_llm_ports(ports)
        idea = get_llm_port("idea_interpretation")
        research = get_llm_port("gap")
        assert isinstance(idea, LangChainChatAdapter)
        assert idea.default_model == "llama"
        assert idea._api_key == "sk-local"
        assert idea._base_url == "http://localhost:11434/v1"
        assert isinstance(research, FakeLlm)
        assert get_llm_port("claims") is idea
    finally:
        get_settings.cache_clear()


def test_json_langchain_provider_falls_back_to_llm_base_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "LLM_PROVIDERS",
        json.dumps(
            {
                "openai": {"kind": "langchain", "api_key_env": "LLM_API_KEY"},
                "fake": {"kind": "fake"},
            }
        ),
    )
    monkeypatch.setenv(
        "LLM_PROFILES",
        json.dumps(
            {
                "creative": {"provider_id": "openai", "model": "Qwen"},
                "research": {"provider_id": "fake", "model": "fake"},
                "structured": {"provider_id": "openai", "model": "Qwen"},
                "judge": {"provider_id": "openai", "model": "Qwen"},
            }
        ),
    )
    monkeypatch.setenv("LLM_NODE_PROFILE_OVERRIDES", "")
    monkeypatch.setenv("LLM_API_KEY", "sk-test")
    monkeypatch.setenv("LLM_BASE_URL", "https://ai-fit.hcmus.edu.vn/openai")
    get_settings.cache_clear()
    try:
        ports = build_llm_ports(get_settings())
        bind_llm_ports(ports)
        idea = get_llm_port("idea_interpretation")
        assert isinstance(idea, LangChainChatAdapter)
        assert idea._base_url == "https://ai-fit.hcmus.edu.vn/openai"
    finally:
        get_settings.cache_clear()


def test_json_base_url_env_name_and_extra_api_key_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "LLM_PROVIDERS",
        json.dumps(
            {
                "gemini": {
                    "kind": "langchain",
                    "api_key_env": "GEMINI_API_KEY",
                    "base_url": "GEMINI_BASE_URL",
                },
                "fake": {"kind": "fake"},
            }
        ),
    )
    monkeypatch.setenv(
        "LLM_PROFILES",
        json.dumps(
            {
                "creative": {"provider_id": "gemini", "model": "gemini-flash"},
                "research": {"provider_id": "fake", "model": "fake"},
                "structured": {"provider_id": "gemini", "model": "gemini-flash"},
                "judge": {"provider_id": "gemini", "model": "gemini-flash"},
            }
        ),
    )
    monkeypatch.setenv("LLM_NODE_PROFILE_OVERRIDES", "")
    monkeypatch.setenv("GEMINI_API_KEY", "sk-gemini")
    monkeypatch.setenv(
        "GEMINI_BASE_URL", "https://generativelanguage.googleapis.com/v1beta/openai"
    )
    get_settings.cache_clear()
    try:
        ports = build_llm_ports(get_settings())
        bind_llm_ports(ports)
        idea = get_llm_port("idea_interpretation")
        assert isinstance(idea, LangChainChatAdapter)
        assert idea._api_key == "sk-gemini"
        assert (
            idea._base_url
            == "https://generativelanguage.googleapis.com/v1beta/openai"
        )
    finally:
        get_settings.cache_clear()


def test_node_profile_overrides(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "LLM_PROVIDERS",
        json.dumps(
            {
                "ai-fit": {"kind": "langchain", "api_key_env": "LLM_API_KEY"},
                "fake": {"kind": "fake"},
            }
        ),
    )
    monkeypatch.setenv(
        "LLM_PROFILES",
        json.dumps(
            {
                "creative": {"provider_id": "ai-fit", "model": "Qwen3.6-27B"},
                "research": {"provider_id": "fake", "model": "fake"},
                "structured": {"provider_id": "ai-fit", "model": "Qwen3.6-27B"},
                "judge": {"provider_id": "ai-fit", "model": "Qwen3.6-27B"},
            }
        ),
    )
    monkeypatch.setenv("LLM_API_KEY", "sk-test")
    monkeypatch.setenv(
        "LLM_NODE_PROFILE_OVERRIDES",
        json.dumps({"gap": "creative"}),
    )
    get_settings.cache_clear()
    try:
        ports = build_llm_ports(get_settings())
        bind_llm_ports(ports)
        assert get_llm_port("gap") is get_llm_port("idea_interpretation")
        assert isinstance(get_llm_port("related_work"), FakeLlm)
    finally:
        get_settings.cache_clear()


def test_missing_api_key_env_raises_named_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "LLM_PROVIDERS",
        json.dumps(
            {
                "gemini": {
                    "kind": "langchain",
                    "api_key_env": "GEMINI_API_KEY",
                    "base_url": "https://example.com/v1",
                },
                "fake": {"kind": "fake"},
            }
        ),
    )
    monkeypatch.setenv(
        "LLM_PROFILES",
        json.dumps(
            {
                "creative": {"provider_id": "gemini", "model": "g"},
                "research": {"provider_id": "fake", "model": "fake"},
                "structured": {"provider_id": "fake", "model": "fake"},
                "judge": {"provider_id": "fake", "model": "fake"},
            }
        ),
    )
    monkeypatch.setenv("LLM_NODE_PROFILE_OVERRIDES", "")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    get_settings.cache_clear()
    try:
        ports = build_llm_ports(get_settings())
        bind_llm_ports(ports)
        with pytest.raises(Exception, match="GEMINI_API_KEY"):
            asyncio_run = __import__("asyncio").run
            asyncio_run(
                get_llm_port("idea_interpretation").complete(system="s", prompt="p")
            )
    finally:
        get_settings.cache_clear()


def test_shared_profile_reuses_port_instance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LLM_PROVIDERS", "")
    monkeypatch.setenv("LLM_PROFILES", "")
    monkeypatch.setenv("LLM_NODE_PROFILE_OVERRIDES", "")
    monkeypatch.setenv("LLM_API_KEY", "sk-test")
    get_settings.cache_clear()
    try:
        ports = build_llm_ports(get_settings())
        assert ports["research_inputs"] is ports["gap"]
        assert isinstance(ports["research_inputs"], LangChainChatAdapter)
        assert ports["idea_interpretation"] is ports["claims"]
        assert ports["idea_interpretation"] is ports["gap_judge"]
        assert ports["idea_interpretation"] is ports["research_inputs"]
        assert ports["idea_interpretation"].default_model == "Qwen3.6-27B"
    finally:
        get_settings.cache_clear()
