"""Per-Loop-Session in-flight generate lock."""

import asyncio
from uuid import UUID


class GenerateLock:
    def __init__(self) -> None:
        self._guard = asyncio.Lock()
        self._busy: set[UUID] = set()

    async def acquire(self, session_id: UUID) -> bool:
        async with self._guard:
            if session_id in self._busy:
                return False
            self._busy.add(session_id)
            return True

    async def release(self, session_id: UUID) -> None:
        async with self._guard:
            self._busy.discard(session_id)


generate_lock = GenerateLock()
