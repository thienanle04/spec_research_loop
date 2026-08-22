"""LangChain LCEL adapter for LlmPort (ADR 0023)."""

from collections.abc import AsyncIterator

from langchain_core.messages import AIMessage
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI

from app.core.config import get_settings
from app.ports.llm import LlmCompleteError

_PROMPT = ChatPromptTemplate.from_messages(
    [
        ("system", "{system}"),
        ("human", "{prompt}"),
    ]
)


def _escape_template(value: str) -> str:
    return value.replace("{", "{{").replace("}", "}}")


def _message_text(content: object) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and block.get("type") == "text":
                parts.append(str(block.get("text", "")))
        return "".join(parts)
    return str(content)


class LangChainChatAdapter:
    async def stream(self, *, system: str, prompt: str, model: str | None = None) -> AsyncIterator[str]:
        settings = get_settings()
        if not settings.llm_api_key:
            raise LlmCompleteError("LLM_API_KEY is not set")
        resolved = model or settings.llm_default_model
        if not resolved:
            raise LlmCompleteError("LLM model is not set")
        try:
            chat = ChatOpenAI(
                model=resolved,
                api_key=settings.llm_api_key,
                base_url=settings.llm_base_url or None,
                streaming=True,
            )
            chain = _PROMPT | chat
            async for message in chain.astream(
                {
                    "system": _escape_template(system),
                    "prompt": _escape_template(prompt),
                }
            ):
                content = message.content if isinstance(message, AIMessage) else getattr(
                    message, "content", message
                )
                text = _message_text(content)
                if text:
                    yield text
        except LlmCompleteError:
            raise
        except Exception as exc:
            raise LlmCompleteError(str(exc)) from exc

    async def complete(self, *, system: str, prompt: str, model: str | None = None) -> str:
        parts: list[str] = []
        async for token in self.stream(system=system, prompt=prompt, model=model):
            parts.append(token)
        return "".join(parts)
