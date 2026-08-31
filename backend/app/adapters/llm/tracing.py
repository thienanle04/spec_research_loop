"""Bind-time LlmPort wrapper: one stdout trace per stream when LLM_TRACE is on."""

from __future__ import annotations

import logging
import time
from collections.abc import AsyncGenerator, Mapping

from app.core.config import get_settings
from app.ports.llm import LlmCompleteError, LlmPort, LlmProviderError

logger = logging.getLogger("app.adapters.llm")


def configure_llm_trace_logger() -> None:
    """Attach a stderr handler so traces/vendor failures show under uvicorn."""
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(levelname)s %(name)s %(message)s"))
        logger.addHandler(handler)
    logger.propagate = False


def traced_ports(ports: Mapping[str, LlmPort]) -> dict[str, LlmPort]:
    return {node: TracingLlm(inner, node=node) for node, inner in ports.items()}


def _resolved_model(model: str | None, inner: LlmPort | None = None) -> str:
    if model:
        return model
    if inner is not None:
        default = getattr(inner, "default_model", None)
        if isinstance(default, str) and default:
            return default
        nested = getattr(inner, "_default_model", None)
        if isinstance(nested, str) and nested:
            return nested
    return get_settings().llm_default_model


def _format_trace(
    *,
    node: str,
    model: str,
    latency_ms: int,
    outcome: str,
    system: str,
    prompt: str,
    completion: str,
) -> str:
    header = (
        f"LLM trace node={node} model={model} latency_ms={latency_ms} "
        f"outcome={outcome} system_chars={len(system)} prompt_chars={len(prompt)} "
        f"completion_chars={len(completion)}"
    )
    return (
        f"{header}\n"
        f"--- system ---\n{system}\n"
        f"--- prompt ---\n{prompt}\n"
        f"--- completion ---\n{completion}"
    )


class TracingLlm:
    """Delegates to an inner LlmPort; logs one record when the stream ends."""

    def __init__(self, inner: LlmPort, *, node: str) -> None:
        self._inner = inner
        self._node = node

    async def stream(
        self, *, system: str, prompt: str, model: str | None = None
    ) -> AsyncGenerator[str, None]:
        started = time.perf_counter()
        parts: list[str] = []
        outcome = "cancelled"
        try:
            async for token in self._inner.stream(system=system, prompt=prompt, model=model):
                parts.append(token)
                yield token
        except (LlmCompleteError, LlmProviderError):
            outcome = "error"
            raise
        else:
            outcome = "ok"
        finally:
            latency_ms = int((time.perf_counter() - started) * 1000)
            logger.info(
                _format_trace(
                    node=self._node,
                    model=_resolved_model(model, self._inner),
                    latency_ms=latency_ms,
                    outcome=outcome,
                    system=system,
                    prompt=prompt,
                    completion="".join(parts),
                )
            )

    async def complete(self, *, system: str, prompt: str, model: str | None = None) -> str:
        parts: list[str] = []
        async for token in self.stream(system=system, prompt=prompt, model=model):
            parts.append(token)
        return "".join(parts)

    async def complete_structured(self, *, system: str, prompt: str, schema: type, model: str | None = None):
        started = time.perf_counter()
        outcome = "cancelled"
        try:
            result = await self._inner.complete_structured(system=system, prompt=prompt, schema=schema, model=model)
        except Exception:
            outcome = "error"
            raise
        else:
            outcome = "ok"
            return result
        finally:
            latency_ms = int((time.perf_counter() - started) * 1000)
            logger.info(
                _format_trace(
                    node=self._node,
                    model=_resolved_model(model, self._inner),
                    latency_ms=latency_ms,
                    outcome=outcome,
                    system=system,
                    prompt=prompt,
                    completion="<STRUCTURED_JSON>",
                )
            )
