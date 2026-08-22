"""LLM port — modules depend on this, not on vendor SDKs."""

from typing import Protocol, runtime_checkable


class LlmProviderError(RuntimeError):
    """Safe provider failure that can be shown without leaking response details."""

    def __init__(
        self,
        message: str,
        *,
        provider: str,
        status_code: int | None = None,
        code: str | None = None,
    ) -> None:
        super().__init__(message)
        self.provider = provider
        self.status_code = status_code
        self.code = code


@runtime_checkable
class LlmPort(Protocol):
    async def complete(
        self, *, system: str, prompt: str, model: str | None = None
    ) -> str:
        """Return a single completion string."""
        ...
