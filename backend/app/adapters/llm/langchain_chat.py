"""LangChain LCEL adapter for LlmPort."""

from __future__ import annotations

import json
import logging
import re
from collections.abc import AsyncGenerator
from typing import NoReturn

from langchain_core.messages import AIMessage
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI
from pydantic import SecretStr, TypeAdapter

from app.ports.llm import LlmCompleteError, LlmProviderError

logger = logging.getLogger("app.adapters.llm")

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


def _strip_json_fence(raw: str) -> str:
    return re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip(), flags=re.IGNORECASE)


def _http_status(exc: BaseException) -> int | None:
    current: BaseException | None = exc
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        status_code = getattr(current, "status_code", None)
        if isinstance(status_code, int):
            return status_code
        current = current.__cause__ or current.__context__
    return None


def _vendor_response_text(exc: BaseException) -> str:
    """Best-effort vendor body for server logs (not returned to HTTP clients)."""
    current: BaseException | None = exc
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        body = getattr(current, "body", None)
        if body is not None:
            if isinstance(body, (dict, list)):
                return json.dumps(body, ensure_ascii=False)[:4000]
            return str(body)[:4000]
        response = getattr(current, "response", None)
        if response is not None:
            text = getattr(response, "text", None)
            if isinstance(text, str) and text.strip():
                return text[:4000]
            try:
                payload = response.json()
            except Exception:  # noqa: BLE001 - logging aid only
                payload = None
            if payload is not None:
                return json.dumps(payload, ensure_ascii=False)[:4000]
        current = current.__cause__ or current.__context__
    return str(exc)[:4000]


def _log_vendor_failure(exc: Exception, *, where: str) -> None:
    logger.warning(
        "LLM vendor failure where=%s status=%s type=%s response=%s",
        where,
        _http_status(exc),
        type(exc).__name__,
        _vendor_response_text(exc),
    )


def _reraise_llm_failure(exc: Exception, *, where: str) -> NoReturn:
    """Map vendor failures to safe port errors (no response body / account leakage)."""
    if isinstance(exc, (LlmCompleteError, LlmProviderError)):
        raise exc

    _log_vendor_failure(exc, where=where)

    status_code = _http_status(exc)
    code = getattr(exc, "code", None)
    if code is not None:
        code = str(code)

    if status_code in {401, 403}:
        raise LlmProviderError(
            "LLM provider rejected the configured API key",
            provider="langchain",
            status_code=status_code,
            code=code or "auth_error",
        ) from exc
    if status_code == 429:
        raise LlmProviderError(
            "LLM rate limit or quota was reached; retry later",
            provider="langchain",
            status_code=429,
            code=code or "rate_limit",
        ) from exc
    if status_code is not None and status_code >= 500:
        raise LlmProviderError(
            "LLM provider is temporarily unavailable",
            provider="langchain",
            status_code=status_code,
            code=code or "upstream_error",
        ) from exc
    if status_code is not None:
        raise LlmProviderError(
            f"LLM provider rejected the generation request (HTTP {status_code})",
            provider="langchain",
            status_code=status_code,
            code=code,
        ) from exc
    raise LlmCompleteError("LLM completion failed") from exc


class LangChainChatAdapter:
    def __init__(
        self,
        *,
        api_key: str | None = None,
        api_key_env: str = "LLM_API_KEY",
        base_url: str | None = None,
        default_model: str,
    ) -> None:
        self._api_key = api_key
        self._api_key_env = api_key_env
        self._base_url = base_url
        self.default_model = default_model

    async def stream(
        self, *, system: str, prompt: str, model: str | None = None
    ) -> AsyncGenerator[str, None]:
        if not self._api_key:
            raise LlmCompleteError(f"{self._api_key_env} is not set")
        resolved = model or self.default_model
        if not resolved:
            raise LlmCompleteError("LLM model is not set")
        try:
            chat = ChatOpenAI(
                model=resolved,
                api_key=SecretStr(self._api_key),
                base_url=self._base_url or None,
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
        except (LlmCompleteError, LlmProviderError):
            raise
        except Exception as exc:
            _reraise_llm_failure(exc, where="stream")

    async def complete(
        self, *, system: str, prompt: str, model: str | None = None
    ) -> str:
        parts: list[str] = []
        async for token in self.stream(system=system, prompt=prompt, model=model):
            parts.append(token)
        return "".join(parts)

    async def complete_structured[T](
        self,
        *,
        system: str,
        prompt: str,
        schema: type[T],
        model: str | None = None,
    ) -> T:
        if not self._api_key:
            raise LlmCompleteError(f"{self._api_key_env} is not set")
        resolved = model or self.default_model
        if not resolved:
            raise LlmCompleteError("LLM model is not set")
        # OpenAI-compatible gateways (including campus ai-fit) often reject
        # tool calling and response_format=json_object. Use a plain completion
        # plus local schema validation instead.
        if self._base_url:
            return await self._complete_structured_via_json(
                system=system, prompt=prompt, schema=schema, model=model
            )
        try:
            chat = ChatOpenAI(
                model=resolved,
                api_key=SecretStr(self._api_key),
                base_url=None,
            )
            try:
                structured_chat = chat.with_structured_output(
                    schema, method="json_mode"
                )
                chain = _PROMPT | structured_chat
                raw = await chain.ainvoke(
                    {
                        "system": _escape_template(system),
                        "prompt": _escape_template(prompt),
                    }
                )
                return TypeAdapter(schema).validate_python(raw)
            except Exception as structured_exc:
                if _http_status(structured_exc) not in {400, 404, 422}:
                    raise
                _log_vendor_failure(structured_exc, where="structured_json_mode")
                return await self._complete_structured_via_json(
                    system=system, prompt=prompt, schema=schema, model=model
                )
        except (LlmCompleteError, LlmProviderError):
            raise
        except Exception as exc:
            _reraise_llm_failure(exc, where="complete_structured")
            raise  # pragma: no cover — NoReturn for type checkers

    async def _complete_structured_via_json[T](
        self,
        *,
        system: str,
        prompt: str,
        schema: type[T],
        model: str | None,
    ) -> T:
        schema_hint = json.dumps(
            TypeAdapter(schema).json_schema(), ensure_ascii=False
        )
        raw = await self.complete(
            system=(
                f"{system}\n\nRespond with a single JSON object matching this "
                f"JSON Schema:\n{schema_hint}"
            ),
            prompt=prompt,
            model=model,
        )
        try:
            return TypeAdapter(schema).validate_json(_strip_json_fence(raw))
        except Exception as exc:
            logger.warning(
                "LLM structured JSON validate failed schema=%s raw=%s",
                getattr(schema, "__name__", str(schema)),
                raw[:4000],
            )
            raise LlmCompleteError(
                "LLM returned JSON that did not match the expected schema"
            ) from exc
