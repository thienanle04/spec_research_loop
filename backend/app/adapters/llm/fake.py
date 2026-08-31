"""In-memory LlmPort for tests and fake profiles. Does not call a vendor."""

from collections.abc import AsyncGenerator
from dataclasses import dataclass, field

from pydantic import TypeAdapter


@dataclass(frozen=True)
class LlmCall:
    system: str
    prompt: str
    model: str | None


@dataclass
class FakeLlm:
    response: str = "fake-completion"
    chunks: list[str] | None = None
    calls: list[LlmCall] = field(default_factory=list)
    default_model: str = "fake"

    async def stream(
        self, *, system: str, prompt: str, model: str | None = None
    ) -> AsyncGenerator[str, None]:
        self.calls.append(LlmCall(system=system, prompt=prompt, model=model))
        if self.chunks is not None:
            for chunk in self.chunks:
                yield chunk
            return
        yield self.response

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
        response = await self.complete(system=system, prompt=prompt, model=model)
        return TypeAdapter(schema).validate_json(response)
