"""Event-operations metrics (spec 050).

One endpoint per band, so a slow band cannot block the page. All `Staff`, all
read-only, all cached for a minute — the payload carries the cache timestamp so
the page can say how fresh it is.
"""

from uuid import UUID

from fastapi import APIRouter, Query

from app.api.deps import DbSession, RedisClient, Staff
from app.services import metrics

router = APIRouter(prefix="/admin/metrics", tags=["admin"])

Window = Query(default="today", pattern="^(1h|4h|today|event)$")


@router.get("/pulse")
async def pulse(db: DbSession, redis: RedisClient, current: Staff, window: str = Window) -> dict:
    return await metrics.cached_pulse(db, redis, window)


@router.get("/challenges")
async def challenges(
    db: DbSession,
    redis: RedisClient,
    current: Staff,
    window: str = Window,
    category_id: UUID | None = None,
    difficulty: str | None = None,
) -> dict:
    return await metrics.cached_challenges(
        db, redis, window, category_id=category_id, difficulty=difficulty
    )


@router.get("/players")
async def players(
    db: DbSession,
    redis: RedisClient,
    current: Staff,
    filter: str = Query(default="stuck", pattern="^(stuck|quiet|never_started)$"),
) -> dict:
    """Ignores the window control deliberately.

    "Stalled" is about the recent past; a whole-event window would make every
    filter here meaningless, so these use their own fixed thresholds and the
    page says the control does not apply.
    """
    return await metrics.cached_players(db, redis, filter)


@router.get("/progression")
async def progression(db: DbSession, redis: RedisClient, current: Staff) -> dict:
    return await metrics.cached_progression(db, redis)
