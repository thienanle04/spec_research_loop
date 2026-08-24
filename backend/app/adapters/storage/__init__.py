"""Object-storage adapters."""

from app.adapters.storage.memory import MemoryObjectStorage
from app.adapters.storage.s3 import S3ObjectStorage, get_object_storage

__all__ = ["MemoryObjectStorage", "S3ObjectStorage", "get_object_storage"]
