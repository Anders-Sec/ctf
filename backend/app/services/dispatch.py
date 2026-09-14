"""The daily state-of-the-dungeon message (spec 032).

One broadcast a day, the same text for everyone, drawn from facts the platform
already has. The prose is a deterministic template in the System AI's voice, as
every other narrated line is.

The interesting part is not the message, it is sending it once. The deployment
runs two replicas, so both run this loop; a restart near the send window would
otherwise send again. The broadcast log's unique constraint arbitrates — keyed
on the date, so the second pod's insert fails and it does nothing.
"""

import asyncio
import contextlib
from datetime import UTC, date, datetime

from redis.asyncio import Redis
from sqlalchemy import distinct, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.logging import get_logger
from app.models.challenge import Category, Challenge
from app.models.event import EVENT_CONFIG_ID, EventConfig
from app.models.notification import NotificationKind
from app.models.play import Solve
from app.services import narrator, notifications

logger = get_logger(__name__)

#: How often the loop wakes. The send itself is guarded by the log, so waking
#: often is cheap — it just finds the day already claimed and goes back to sleep.
POLL_SECONDS = 900


async def send_today(
    db: AsyncSession, redis: Redis | None = None, *, now: datetime | None = None
) -> bool:
    """Send the dispatch for today, unless it has already gone out.

    Returns whether this call was the one that sent it.
    """
    now = now or datetime.now(UTC)
    event = await db.get(EventConfig, EVENT_CONFIG_ID)

    # Before the event opens there is nothing to report, and a dispatch full of
    # zeros is worse than silence.
    if event is None or event.starts_at is None or now < event.starts_at:
        return False
    if event.ends_at is not None and now > event.ends_at:
        return False

    day = (now.date() - event.starts_at.date()).days + 1
    solves = (await db.scalar(select(func.count(Solve.id)))) or 0
    bosses_down = (
        await db.scalar(
            select(func.count(distinct(Solve.challenge_id)))
            .join(Challenge, Challenge.id == Solve.challenge_id)
            .where(Challenge.boss_tier.is_not(None))
        )
    ) or 0
    zones_open = (await db.scalar(select(func.count(Category.id)))) or 0

    result = await notifications.broadcast(
        db,
        kind=NotificationKind.DISPATCH,
        key=_key(now.date()),
        title=f"Day {day}",
        body=narrator.daily_dispatch(day, solves, bosses_down, zones_open),
        link="/challenges",
        redis=redis,
    )
    if result.sent:
        logger.info("daily_dispatch_sent", extra={"day": day, "recipients": result.recipients})
    return result.sent


def _key(on: date) -> str:
    return on.isoformat()


class DispatchLoop:
    """Wakes periodically and lets the database decide whether to send.

    Mirrors the reconciler: one task per process, several replicas staying off
    each other's toes through a shared arbiter rather than shared memory.
    """

    def __init__(self) -> None:
        self._task: asyncio.Task | None = None

    def start(self, sessionmaker: async_sessionmaker[AsyncSession], redis: Redis) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._run(sessionmaker, redis))

    async def stop(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self._task
        self._task = None

    async def _run(self, sessionmaker: async_sessionmaker[AsyncSession], redis: Redis) -> None:
        while True:
            try:
                async with sessionmaker() as session:
                    await send_today(session, redis)
                    await session.commit()
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - a failed dispatch must not kill the app
                logger.exception("daily_dispatch_failed")
            await asyncio.sleep(POLL_SECONDS)


loop = DispatchLoop()
