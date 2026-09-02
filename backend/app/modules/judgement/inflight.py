"""Per-Loop-Session lock while Aggregator phrasing is in-flight."""

import asyncio
from uuid import UUID


class PhrasingLock:
    def __init__(self) -> None:
        self._guard = asyncio.Lock()
        self._busy: set[UUID] = set()
        self._epoch: dict[UUID, int] = {}

    def held(self, session_id: UUID) -> bool:
        return session_id in self._busy

    def bump_epoch(self, session_id: UUID) -> int:
        nxt = self._epoch.get(session_id, 0) + 1
        self._epoch[session_id] = nxt
        return nxt

    def epoch(self, session_id: UUID) -> int:
        return self._epoch.get(session_id, 0)

    async def acquire(self, session_id: UUID) -> bool:
        async with self._guard:
            if session_id in self._busy:
                return False
            self._busy.add(session_id)
            return True

    async def release(self, session_id: UUID) -> None:
        async with self._guard:
            self._busy.discard(session_id)


aggregator_phrasing_lock = PhrasingLock()
