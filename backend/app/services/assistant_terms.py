"""The System AI's terms of use: loading them, and who has accepted them (spec 035).

The text lives in a file rather than in code so management can revise the wording
without a rebuild, and so the manifests can mount a ConfigMap over it later.

Two properties are load-bearing:

1. **The version is the hash of the file.** Nobody has to remember to bump
   anything, and a revised file re-gates everyone — which is the point, because a
   prior acceptance was to different words.
2. **A missing file makes the assistant unavailable, not open.** A terms gate
   that fails open is not a terms gate.
"""

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.errors import AppError
from app.logging import get_logger
from app.models.assistant import TermsAcceptance
from app.models.user import User

logger = get_logger(__name__)

#: Long enough that a collision is not a practical concern, short enough to read
#: in a log line or an admin panel.
VERSION_LENGTH = 12


class TermsUnavailable(AppError):
    """The terms file is missing or empty.

    A 503 rather than a 403: this is our misconfiguration, not the player's
    problem, and it should read as "broken" on the health panel rather than as
    "you have not accepted".
    """

    status_code = 503
    code = "assistant_terms_unavailable"
    message = "The System AI's terms of use are not available right now."


@dataclass(frozen=True)
class Terms:
    text: str
    version: str


#: Cached on (path, mtime, size) so a ConfigMap remount or an edit in place is
#: picked up without a restart, while a steady file costs one stat per call.
_cache: tuple[tuple[str, float, int], Terms] | None = None


def load(settings: Settings) -> Terms:
    """The current terms. Raises :class:`TermsUnavailable` if there are none."""
    global _cache

    path = Path(settings.ai_terms_path)
    try:
        stat = path.stat()
    except OSError:
        logger.error("terms_file_missing", extra={"path": str(path)})
        raise TermsUnavailable from None

    key = (str(path), stat.st_mtime, stat.st_size)
    if _cache is not None and _cache[0] == key:
        return _cache[1]

    text = path.read_text(encoding="utf-8").strip()
    if not text:
        logger.error("terms_file_empty", extra={"path": str(path)})
        raise TermsUnavailable

    terms = Terms(text=text, version=_version_of(text))
    _cache = (key, terms)
    logger.info("terms_loaded", extra={"version": terms.version})
    return terms


def _version_of(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:VERSION_LENGTH]


def reset_cache() -> None:
    """Test seam."""
    global _cache
    _cache = None


async def has_accepted(db: AsyncSession, user_id: UUID, version: str) -> bool:
    return bool(
        await db.scalar(
            select(TermsAcceptance.id).where(
                TermsAcceptance.user_id == user_id,
                TermsAcceptance.version == version,
            )
        )
    )


async def accept(
    db: AsyncSession, user_id: UUID, version: str, now: datetime | None = None
) -> None:
    """Record an acceptance. Idempotent — two tabs is not an error.

    The caller is responsible for checking the submitted version against the
    current one; accepting a version the player was never shown would make the
    record worthless, so that check does not belong this far down.
    """
    await db.execute(
        insert(TermsAcceptance)
        .values(user_id=user_id, version=version, accepted_at=now or datetime.now(UTC))
        .on_conflict_do_nothing(constraint="uq_assistant_terms_user_version")
    )
    await db.flush()


@dataclass(frozen=True)
class AcceptanceSummary:
    version: str
    accepted: int
    outstanding: int
    #: Only populated when asked for — useful before an event, mildly
    #: surveillance-shaped during one.
    outstanding_names: list[str] | None = None


async def summary(
    db: AsyncSession, version: str, *, include_names: bool = False
) -> AcceptanceSummary:
    """How many have accepted the current version, for the admin panel."""
    accepted = (
        await db.scalar(
            select(func.count(TermsAcceptance.id)).where(TermsAcceptance.version == version)
        )
    ) or 0

    accepted_ids = select(TermsAcceptance.user_id).where(TermsAcceptance.version == version)
    outstanding_q = select(User).where(User.id.not_in(accepted_ids))

    outstanding = (await db.scalar(select(func.count()).select_from(outstanding_q.subquery()))) or 0

    names = None
    if include_names:
        rows = (await db.execute(outstanding_q.order_by(User.display_name))).scalars().all()
        names = [user.display_name for user in rows]

    return AcceptanceSummary(
        version=version,
        accepted=accepted,
        outstanding=outstanding,
        outstanding_names=names,
    )
