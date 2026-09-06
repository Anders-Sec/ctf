"""Where challenge artifact bytes live.

MinIO runs in the cluster and speaks S3, so any number of API replicas share one
store without needing a ReadWriteMany volume — which is the failure this avoids:
on a ReadWriteOnce volume a file uploaded through one pod is invisible to the
next, and downloads succeed or fail depending on which pod answers.

Everything goes through `ArtifactStorage`, so the Postgres-backed implementation
below stays a drop-in if MinIO is ever not worth running. Application code never
knows which is wired in.

boto3 is synchronous, so calls are pushed to a worker thread. An async S3 client
would be a heavier dependency for a path that handles a few dozen files.
"""

import asyncio
import hashlib
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

from app.config import Settings
from app.errors import AppError
from app.logging import get_logger

logger = get_logger(__name__)

#: Read size for streaming. Large enough to be efficient, small enough that a
#: 200 MB artifact never sits in memory in one piece.
CHUNK_SIZE = 64 * 1024


class StorageUnavailable(AppError):
    status_code = 503
    code = "storage_unavailable"
    message = "Challenge files are temporarily unavailable."


@dataclass(frozen=True)
class StoredObject:
    storage_key: str
    size_bytes: int
    checksum_sha256: str


class ArtifactStorage(ABC):
    @abstractmethod
    async def put(self, key: str, data: bytes, content_type: str) -> StoredObject: ...

    @abstractmethod
    def stream(self, key: str) -> AsyncIterator[bytes]: ...

    @abstractmethod
    async def delete(self, key: str) -> None: ...

    @abstractmethod
    async def healthy(self) -> bool: ...


class S3ArtifactStorage(ArtifactStorage):
    """MinIO, or anything else speaking S3."""

    def __init__(self, settings: Settings) -> None:
        self._bucket = settings.s3_bucket
        self._settings = settings
        self._client: Any | None = None

    def _get_client(self) -> Any:
        if self._client is None:
            import boto3
            from botocore.config import Config

            self._client = boto3.client(
                "s3",
                endpoint_url=self._settings.s3_endpoint_url,
                aws_access_key_id=self._settings.s3_access_key,
                aws_secret_access_key=self._settings.s3_secret_key,
                region_name=self._settings.s3_region,
                config=Config(
                    signature_version="s3v4",
                    # MinIO wants path-style addressing; virtual-host style
                    # requires DNS per bucket, which an in-cluster service
                    # does not have.
                    s3={"addressing_style": "path"},
                    retries={"max_attempts": 3, "mode": "standard"},
                ),
            )
        return self._client

    async def put(self, key: str, data: bytes, content_type: str) -> StoredObject:
        checksum = hashlib.sha256(data).hexdigest()

        def _upload() -> None:
            self._get_client().put_object(
                Bucket=self._bucket,
                Key=key,
                Body=data,
                ContentType=content_type,
                # Stored alongside the object so corruption is detectable even
                # if the database row and the object ever drift apart.
                Metadata={"sha256": checksum},
            )

        try:
            await asyncio.to_thread(_upload)
        except Exception as exc:
            logger.error("artifact_upload_failed", extra={"error_type": type(exc).__name__})
            raise StorageUnavailable("Could not store that file.") from exc

        return StoredObject(key, len(data), checksum)

    async def stream(self, key: str) -> AsyncIterator[bytes]:
        def _open() -> Any:
            return self._get_client().get_object(Bucket=self._bucket, Key=key)["Body"]

        try:
            body = await asyncio.to_thread(_open)
        except Exception as exc:
            logger.error("artifact_fetch_failed", extra={"error_type": type(exc).__name__})
            raise StorageUnavailable from exc

        try:
            while True:
                chunk = await asyncio.to_thread(body.read, CHUNK_SIZE)
                if not chunk:
                    break
                yield chunk
        finally:
            await asyncio.to_thread(body.close)

    async def delete(self, key: str) -> None:
        def _delete() -> None:
            self._get_client().delete_object(Bucket=self._bucket, Key=key)

        try:
            await asyncio.to_thread(_delete)
        except Exception as exc:
            # A failed delete leaves an orphan, which is untidy but harmless —
            # far better than failing the request that removed the row.
            logger.warning("artifact_delete_failed", extra={"error_type": type(exc).__name__})

    async def healthy(self) -> bool:
        def _head() -> None:
            self._get_client().head_bucket(Bucket=self._bucket)

        try:
            await asyncio.to_thread(_head)
            return True
        except Exception:
            return False

    async def ensure_bucket(self) -> None:
        """Create the bucket if it is missing. Convenience for local development."""

        def _create() -> None:
            client = self._get_client()
            try:
                client.head_bucket(Bucket=self._bucket)
            except Exception:
                client.create_bucket(Bucket=self._bucket)

        await asyncio.to_thread(_create)


class UnconfiguredStorage(ArtifactStorage):
    """Stands in when no object store is configured.

    Refuses clearly rather than pretending to work: a silent no-op here means an
    admin uploads a file, sees success, and discovers at 09:00 that no player
    can download it.
    """

    async def put(self, key: str, data: bytes, content_type: str) -> StoredObject:
        raise StorageUnavailable("No artifact storage is configured.")

    async def stream(self, key: str) -> AsyncIterator[bytes]:
        raise StorageUnavailable("No artifact storage is configured.")
        yield b""  # pragma: no cover - unreachable, satisfies the generator type

    async def delete(self, key: str) -> None:
        return None

    async def healthy(self) -> bool:
        return False


#: Cached per endpoint/bucket rather than per Settings object: Settings is not
#: hashable, and rebuilding a boto3 client on every request would be wasteful.
_storages: dict[tuple[str | None, str], ArtifactStorage] = {}


def get_storage(settings: Settings) -> ArtifactStorage:
    key = (settings.s3_endpoint_url, settings.s3_bucket)
    if key not in _storages:
        if settings.s3_configured:
            _storages[key] = S3ArtifactStorage(settings)
        else:
            logger.warning("artifact_storage_not_configured")
            _storages[key] = UnconfiguredStorage()
    return _storages[key]
