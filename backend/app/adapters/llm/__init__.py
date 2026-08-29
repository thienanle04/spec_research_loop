"""LLM provider adapters. Implement LlmPort here."""

from app.adapters.llm.fake import FakeLlm
from app.adapters.llm.langchain_chat import LangChainChatAdapter
from app.adapters.llm.profiles import (
    DEFAULT_NODE_PROFILE_MAP,
    ModelRef,
    Profile,
    Provider,
    build_llm_ports,
    build_port_for_profile,
)
from app.adapters.llm.tracing import (
    TracingLlm,
    configure_llm_trace_logger,
    traced_ports,
)
from app.ports.llm import LlmPort, LlmProviderError

_llm_ports: dict[str, LlmPort] | None = None


def bind_llm_ports(ports: dict[str, LlmPort]) -> None:
    global _llm_ports
    _llm_ports = ports


def get_llm_port(node: str) -> LlmPort:
    if _llm_ports is None:
        raise RuntimeError("Llm ports are not bound")
    try:
        return _llm_ports[node]
    except KeyError:
        raise KeyError(f"No LlmPort bound for workflow node {node!r}") from None


__all__ = [
    "DEFAULT_NODE_PROFILE_MAP",
    "FakeLlm",
    "LangChainChatAdapter",
    "LlmProviderError",
    "ModelRef",
    "Profile",
    "Provider",
    "TracingLlm",
    "bind_llm_ports",
    "build_llm_ports",
    "build_port_for_profile",
    "configure_llm_trace_logger",
    "get_llm_port",
    "traced_ports",
]
