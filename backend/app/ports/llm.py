"""LLM port — modules depend on this, not on vendor SDKs."""

from collections.abc import AsyncIterator
from typing import Protocol, runtime_checkable


class LlmCompleteError(Exception):
    """A completion could not be produced (missing config or vendor failure)."""


@runtime_checkable
class LlmPort(Protocol):
    def stream(self, *, system: str, prompt: str, model: str | None = None) -> AsyncIterator[str]:
        """Yield completion text chunks."""
        ...

    async def complete(self, *, system: str, prompt: str, model: str | None = None) -> str:
        """Return a single completion string (join of stream)."""
        ...
