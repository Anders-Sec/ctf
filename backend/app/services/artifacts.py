"""Uploading and reading challenge artifacts."""

import re
import uuid
from collections.abc import AsyncIterator
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.errors import AppError, NotFoundError
from app.logging import get_logger
from app.models.challenge import ChallengeArtifact
from app.services.storage import get_storage

logger = get_logger(__name__)

#: Anything outside this is replaced. A filename reaches a Content-Disposition
#: header and a player's disk, so path separators and control characters have no
#: business in it.
_SAFE_FILENAME = re.compile(r"[^A-Za-z0-9._-]+")

DEFAULT_CONTENT_TYPE = "application/octet-stream"


class ArtifactTooLarge(AppError):
    status_code = 413
    code = "artifact_too_large"
    message = "That file is too large."


def safe_filename(raw: str) -> str:
    """Reduce an uploaded name to something safe to echo back.

    ``../../etc/passwd`` becomes ``.._.._etc_passwd``; a name that reduces to
    nothing gets a neutral placeholder rather than an empty header.
    """
    cleaned = _SAFE_FILENAME.sub("_", raw.strip()).strip("._")
    return cleaned[:255] or "artifact"


def storage_key(challenge_id: UUID, filename: str) -> str:
    """Namespaced by challenge, with a random component.

    Two challenges can both ship ``handout.zip``, and re-uploading must not
    silently overwrite an object a player is midway through downloading.
    """
    return f"challenges/{challenge_id}/{uuid.uuid4().hex}-{safe_filename(filename)}"


async def store_artifact(
    db: AsyncSession,
    settings: Settings,
    challenge_id: UUID,
    filename: str,
    content_type: str | None,
    data: bytes,
) -> ChallengeArtifact:
    if len(data) > settings.max_artifact_bytes:
        raise ArtifactTooLarge(
            f"Files must be under {settings.max_artifact_bytes // (1024 * 1024)} MB."
        )
    if not data:
        raise AppError("That file is empty.", code="artifact_empty", status_code=422)

    clean_name = safe_filename(filename)
    key = storage_key(challenge_id, clean_name)
    stored = await get_storage(settings).put(key, data, content_type or DEFAULT_CONTENT_TYPE)

    artifact = ChallengeArtifact(
        challenge_id=challenge_id,
        filename=clean_name,
        content_type=content_type or DEFAULT_CONTENT_TYPE,
        size_bytes=stored.size_bytes,
        storage_key=stored.storage_key,
        checksum_sha256=stored.checksum_sha256,
    )
    db.add(artifact)
    await db.flush()
    return artifact


async def get_artifact(
    db: AsyncSession, challenge_id: UUID, artifact_id: UUID
) -> ChallengeArtifact:
    artifact = (
        await db.execute(
            select(ChallengeArtifact).where(
                ChallengeArtifact.id == artifact_id,
                # Scoped to the challenge: an artifact id alone must not reach a
                # file attached to a challenge the caller cannot see.
                ChallengeArtifact.challenge_id == challenge_id,
            )
        )
    ).scalar_one_or_none()
    if artifact is None:
        raise NotFoundError("No such file.")
    return artifact


def stream_artifact(settings: Settings, artifact: ChallengeArtifact) -> AsyncIterator[bytes]:
    return get_storage(settings).stream(artifact.storage_key)


async def delete_artifact(
    db: AsyncSession, settings: Settings, artifact: ChallengeArtifact
) -> None:
    key = artifact.storage_key
    await db.delete(artifact)
    await db.flush()
    # After the row, not before: an orphaned object is untidy, a row pointing at
    # a deleted object is a broken download.
    await get_storage(settings).delete(key)
