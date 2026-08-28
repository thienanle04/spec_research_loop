"""Object storage port for Spec Artifacts."""

from typing import Protocol, runtime_checkable


@runtime_checkable
class ObjectStoragePort(Protocol):
    async def put_bytes(self, *, key: str, data: bytes, content_type: str) -> str:
        """Store bytes; return the object key (or URI)."""
        ...

    async def get_bytes(self, *, key: str) -> bytes:
        ...

    async def delete_bytes(self, *, key: str) -> None:
        """Delete bytes by key. Missing objects are treated as already deleted."""
        ...
