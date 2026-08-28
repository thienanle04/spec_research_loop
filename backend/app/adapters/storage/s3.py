"""S3-compatible object storage adapter (MinIO / R2 / S3)."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import aioboto3
from botocore.client import Config
from botocore.exceptions import ClientError

from app.core.config import get_settings
from app.ports.storage import ObjectStoragePort


class S3ObjectStorage(ObjectStoragePort):
    def __init__(self) -> None:
        self._session = aioboto3.Session()
        self._settings = get_settings()

    @asynccontextmanager
    async def _client(self) -> AsyncIterator[Any]:
        settings = self._settings
        async with self._session.client(
            "s3",
            endpoint_url=settings.s3_endpoint_url,
            aws_access_key_id=settings.s3_access_key,
            aws_secret_access_key=settings.s3_secret_key,
            region_name=settings.s3_region,
            config=Config(signature_version="s3v4"),
        ) as client:
            yield client

    async def ensure_bucket(self) -> None:
        settings = self._settings
        async with self._client() as client:
            try:
                await client.head_bucket(Bucket=settings.s3_bucket)
            except ClientError as exc:
                error_code = str(exc.response.get("Error", {}).get("Code", ""))
                if error_code not in {"404", "NoSuchBucket", "NotFound"}:
                    raise
                await client.create_bucket(Bucket=settings.s3_bucket)

    async def put_bytes(self, *, key: str, data: bytes, content_type: str) -> str:
        settings = self._settings
        async with self._client() as client:
            await client.put_object(
                Bucket=settings.s3_bucket,
                Key=key,
                Body=data,
                ContentType=content_type,
            )
        return key

    async def get_bytes(self, *, key: str) -> bytes:
        settings = self._settings
        async with self._client() as client:
            response = await client.get_object(Bucket=settings.s3_bucket, Key=key)
            body = response["Body"]
            return await body.read()

    async def delete_bytes(self, *, key: str) -> None:
        settings = self._settings
        async with self._client() as client:
            await client.delete_object(Bucket=settings.s3_bucket, Key=key)


def get_object_storage() -> S3ObjectStorage:
    return S3ObjectStorage()
