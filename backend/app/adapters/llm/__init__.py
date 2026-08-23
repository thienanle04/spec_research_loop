"""LLM provider adapters. Implement LlmPort here."""

from app.adapters.llm.fake import FakeLlm
from app.adapters.llm.langchain_chat import LangChainChatAdapter
from app.ports.llm import LlmPort

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
    "FakeLlm",
    "LangChainChatAdapter",
    "bind_llm_ports",
    "get_llm_port",
]
