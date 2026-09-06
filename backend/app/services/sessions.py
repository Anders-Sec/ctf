"""Issuing, rotating and revoking sessions."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.logging import get_logger
from app.models.auth import AuthSession
from app.services.security import (
    create_access_token,
    generate_csrf_token,
    generate_token,
    hash_token,
)

logger = get_logger(__name__)

REVOKED_ROTATED = "rotated"
REVOKED_LOGOUT = "logout"
REVOKED_REUSE = "reuse_detected"
REVOKED_DISABLED = "account_disabled"


class RefreshTokenReuse(Exception):
    """An already-rotated refresh token was presented again.

    Either a replay or a stolen cookie. Either way the whole chain for that user
    is revoked — a legitimate client never presents a rotated token twice.
    """


@dataclass(frozen=True)
class IssuedSession:
    access_token: str
    refresh_token: str
    csrf_token: str
    session_id: UUID


async def issue_session(
    db: AsyncSession,
    settings: Settings,
    user_id: UUID,
    *,
    ip: str | None = None,
    user_agent: str | None = None,
) -> IssuedSession:
    refresh_token = generate_token()
    now = datetime.now(UTC)

    session_row = AuthSession(
        user_id=user_id,
        refresh_token_hash=hash_token(refresh_token),
        expires_at=now + timedelta(seconds=settings.refresh_token_ttl_seconds),
        ip=ip,
        user_agent=(user_agent or "")[:500] or None,
    )
    db.add(session_row)
    await db.flush()

    return IssuedSession(
        access_token=create_access_token(settings, user_id, now=now),
        refresh_token=refresh_token,
        csrf_token=generate_csrf_token(),
        session_id=session_row.id,
    )


async def rotate_session(
    db: AsyncSession,
    settings: Settings,
    refresh_token: str,
    *,
    ip: str | None = None,
    user_agent: str | None = None,
) -> IssuedSession | None:
    """Exchange a refresh token for a new pair, invalidating the old one.

    Returns None when the token is unknown or expired. Raises RefreshTokenReuse
    when the token was already rotated, which is a security event rather than an
    ordinary failure.
    """
    now = datetime.now(UTC)
    existing = (
        await db.execute(
            select(AuthSession).where(AuthSession.refresh_token_hash == hash_token(refresh_token))
        )
    ).scalar_one_or_none()

    if existing is None:
        return None

    if existing.revoked_at is not None:
        if existing.revoked_reason == REVOKED_ROTATED:
            await revoke_all_for_user(db, existing.user_id, reason=REVOKED_REUSE)
            logger.warning(
                "refresh_token_reuse_detected",
                extra={"user_id": str(existing.user_id), "session_id": str(existing.id)},
            )
            raise RefreshTokenReuse
        return None

    if existing.expires_at <= now:
        return None

    issued = await issue_session(db, settings, existing.user_id, ip=ip, user_agent=user_agent)

    existing.revoked_at = now
    existing.revoked_reason = REVOKED_ROTATED
    existing.replaced_by_id = issued.session_id
    await db.flush()

    return issued


async def revoke_session(
    db: AsyncSession, refresh_token: str, *, reason: str = REVOKED_LOGOUT
) -> None:
    await db.execute(
        update(AuthSession)
        .where(
            AuthSession.refresh_token_hash == hash_token(refresh_token),
            AuthSession.revoked_at.is_(None),
        )
        .values(revoked_at=datetime.now(UTC), revoked_reason=reason)
    )


async def revoke_all_for_user(db: AsyncSession, user_id: UUID, *, reason: str) -> None:
    """Kill every live session for a user.

    Used when an admin disables an account and when refresh-token reuse is
    detected. Combined with the per-request user lookup, this means access is
    gone on the next request rather than at the next token expiry.
    """
    await db.execute(
        update(AuthSession)
        .where(AuthSession.user_id == user_id, AuthSession.revoked_at.is_(None))
        .values(revoked_at=datetime.now(UTC), revoked_reason=reason)
    )
