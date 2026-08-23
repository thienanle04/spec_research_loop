"""LangChain LCEL adapter for LlmPort (ADR 0022)."""

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
    async def complete(self, *, system: str, prompt: str, model: str | None = None) -> str:
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
            )
            chain = _PROMPT | chat
            message = await chain.ainvoke(
                {
                    "system": _escape_template(system),
                    "prompt": _escape_template(prompt),
                }
            )
        except LlmCompleteError:
            raise
        except Exception as exc:
            raise LlmCompleteError(str(exc)) from exc
        if isinstance(message, AIMessage):
            return _message_text(message.content)
        content = getattr(message, "content", message)
        return _message_text(content)

    async def complete_structured(self, *, system: str, prompt: str, schema: type, model: str | None = None):
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
            )
            structured_chat = chat.with_structured_output(schema)
            chain = _PROMPT | structured_chat
            result = await chain.ainvoke(
                {
                    "system": _escape_template(system),
                    "prompt": _escape_template(prompt),
                }
            )
            return result
        except LlmCompleteError:
            raise
        except Exception as exc:
            raise LlmCompleteError(str(exc)) from exc
