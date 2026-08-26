"""Deterministic in-memory object storage for tests and local fake providers."""


class MemoryObjectStorage:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.content_types: dict[str, str] = {}

    async def put_bytes(self, *, key: str, data: bytes, content_type: str) -> str:
        self.objects[key] = data
        self.content_types[key] = content_type
        return key

    async def get_bytes(self, *, key: str) -> bytes:
        return self.objects[key]
