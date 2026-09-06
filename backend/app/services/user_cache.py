"""A short-lived cache of the per-request user lookup.

Role, status and party membership are deliberately absent from the access token
so that an approval, kick or disable takes effect on the very next request. That
trade costs a lookup per request, which this cache absorbs.

Redis is a cache here and nothing more: a miss, or a Redis outage, falls through
to Postgres. Correctness never depends on it.
"""

import json
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.logging import get_logger
from app.models.team import Team, TeamMembership
from app.models.user import User

logger = get_logger(__name__)

_KEY_PREFIX = "user:v1:"


def _key(user_id: UUID) -> str:
    return f"{_KEY_PREFIX}{user_id}"


async def invalidate(redis: Redis, user_id: UUID) -> None:
    """Drop a user's cached record.

    Called on approve, disable, role change, and every party membership change.
    Failing to invalidate would leave a kicked player acting on stale membership
    for up to the TTL, so a Redis error here is logged rather than swallowed.
    """
    try:
        await redis.delete(_key(user_id))
    except Exception as exc:
        logger.warning(
            "user_cache_invalidate_failed",
            extra={"user_id": str(user_id), "error_type": type(exc).__name__},
        )


async def get_cached_membership(
    redis: Redis,
    db: AsyncSession,
    settings: Settings,
    user_id: UUID,
) -> dict[str, Any] | None:
    """Return the user's current party summary, or None if they have none."""
    try:
        raw = await redis.get(_key(user_id))
        if raw is not None:
            payload: dict[str, Any] = json.loads(raw)
            return payload.get("team")
    except Exception as exc:
        logger.warning(
            "user_cache_read_failed",
            extra={"user_id": str(user_id), "error_type": type(exc).__name__},
        )

    team = await load_active_team(db, user_id)
    summary = (
        None
        if team is None
        else {"id": str(team.id), "name": team.name, "is_leader": team.leader_user_id == user_id}
    )

    try:
        await redis.set(
            _key(user_id),
            json.dumps({"team": summary, "cached_at": datetime.now(UTC).isoformat()}),
            ex=settings.user_cache_ttl_seconds,
        )
    except Exception as exc:
        logger.warning(
            "user_cache_write_failed",
            extra={"user_id": str(user_id), "error_type": type(exc).__name__},
        )

    return summary


async def load_active_team(db: AsyncSession, user_id: UUID) -> Team | None:
    return (
        await db.execute(
            select(Team)
            .join(TeamMembership, TeamMembership.team_id == Team.id)
            .where(
                TeamMembership.user_id == user_id,
                TeamMembership.removed_at.is_(None),
                Team.disbanded_at.is_(None),
            )
        )
    ).scalar_one_or_none()


async def load_user(db: AsyncSession, user_id: UUID) -> User | None:
    """Always from Postgres. Status and role are never served from cache."""
    return (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
