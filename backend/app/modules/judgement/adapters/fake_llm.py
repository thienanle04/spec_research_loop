"""Deterministic LLM port for judgement tests. Does not call a vendor."""

import json
from collections.abc import AsyncIterator
from typing import Any

from pydantic import TypeAdapter


class FakeJudgeLlmPort:
    """Return empty Judge Issues unless a scripted response is supplied."""

    def __init__(self, response: str | None = None) -> None:
        self.response = response or json.dumps({"issues": []})
        self.calls: list[dict[str, Any]] = []

    async def stream(
        self,
        *,
        system: str,
        prompt: str,
        model: str | None = None,
    ) -> AsyncIterator[str]:
        yield await self.complete(system=system, prompt=prompt, model=model)

    async def complete(
        self,
        *,
        system: str,
        prompt: str,
        model: str | None = None,
    ) -> str:
        self.calls.append({"system": system, "prompt": prompt, "model": model})
        return self.response

    async def complete_structured[T](
        self,
        *,
        system: str,
        prompt: str,
        schema: type[T],
        model: str | None = None,
    ) -> T:
        response = await self.complete(system=system, prompt=prompt, model=model)
        return TypeAdapter(schema).validate_json(response)
