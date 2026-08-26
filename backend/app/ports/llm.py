"""LLM port — modules depend on this, not on vendor SDKs."""

from collections.abc import AsyncIterator
from typing import Protocol, TypeVar, runtime_checkable

T = TypeVar("T")


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


class LlmCompleteError(Exception):
    """A completion could not be produced (missing config or vendor failure)."""


@runtime_checkable
class LlmPort(Protocol):
    def stream(
        self, *, system: str, prompt: str, model: str | None = None
    ) -> AsyncIterator[str]:
        """Yield completion text chunks."""
        ...

    async def complete(
        self, *, system: str, prompt: str, model: str | None = None
    ) -> str:
        """Return a single completion string (join of stream)."""
        ...

    async def complete_structured(self, *, system: str, prompt: str, schema: type[T], model: str | None = None) -> T:
        """Return a structured completion mapped to the given Pydantic schema."""
        ...
