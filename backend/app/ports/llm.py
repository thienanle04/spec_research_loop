"""LLM port — modules depend on this, not on vendor SDKs."""

from typing import Protocol, TypeVar, runtime_checkable

T = TypeVar("T")


class LlmCompleteError(Exception):
    """A completion could not be produced (missing config or vendor failure)."""


@runtime_checkable
class LlmPort(Protocol):
    async def complete(self, *, system: str, prompt: str, model: str | None = None) -> str:
        """Return a single completion string."""
        ...

    async def complete_structured(self, *, system: str, prompt: str, schema: type[T], model: str | None = None) -> T:
        """Return a structured completion mapped to the given Pydantic schema."""
        ...
