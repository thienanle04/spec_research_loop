"""In-memory LlmPort for tests. Does not call a vendor."""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class LlmCall:
    system: str
    prompt: str
    model: str | None


@dataclass
class FakeLlm:
    response: str = "fake-completion"
    calls: list[LlmCall] = field(default_factory=list)

    async def complete(self, *, system: str, prompt: str, model: str | None = None) -> str:
        self.calls.append(LlmCall(system=system, prompt=prompt, model=model))
        return self.response
