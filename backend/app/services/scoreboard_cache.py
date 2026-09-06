"""Caching and broadcasting the boards.

The shape of the problem: one solve changes the value of that challenge for
everyone who has solved it, so a scoring event can move hundreds of entries.
Deltas would be more code and more bugs for no gain, so the whole board is
recomputed and published.

What stops that being expensive is the debounce. A burst of twenty flags in the
same second produces one recompute, not twenty, and only one pod does the work
because it is held behind a short Redis lock.

Redis holds cache and pub/sub only. Losing it costs a rebuild on the next
request and a pause in pushes — never data.
"""

import asyncio
import contextlib
import json
from dataclasses import asdict
from datetime import UTC, datetime

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.logging import get_logger
from app.services import scoreboard

logger = get_logger(__name__)

CACHE_KEY = "scoreboard:v1:payload"
DIRTY_KEY = "scoreboard:v1:dirty"
LOCK_KEY = "scoreboard:v1:lock"
CHANNEL = "scoreboard:v1:updates"

#: At most one recompute per second, however fast flags land.
DEBOUNCE_SECONDS = 1.0
#: Long enough to cover a recompute, short enough that a crashed pod does not
#: block the board for long.
LOCK_TTL_SECONDS = 10
#: The cache is a convenience, not a source of truth; a stale entry is only ever
#: seconds old because every scoring event invalidates it.
CACHE_TTL_SECONDS = 300


def serialise(boards: scoreboard.Boards) -> dict:
    return {
        "generated_at": boards.generated_at.isoformat(),
        "players": [_entry(asdict(entry)) for entry in boards.players],
        "teams": [_entry(asdict(entry)) for entry in boards.teams],
    }


def _entry(row: dict) -> dict:
    return {
        key: (
            str(value)
            if key.endswith("_id") and value is not None
            else value.isoformat()
            if isinstance(value, datetime)
            else value
        )
        for key, value in row.items()
    }


async def mark_dirty(redis: Redis) -> None:
    """Record that something scoring-relevant happened.

    Never raises: a solve must not fail because the scoreboard cache is
    unreachable. The board simply rebuilds on the next read.
    """
    try:
        await redis.set(DIRTY_KEY, "1")
    except Exception as exc:
        logger.warning("scoreboard_mark_dirty_failed", extra={"error_type": type(exc).__name__})


async def get_cached(redis: Redis) -> dict | None:
    try:
        raw = await redis.get(CACHE_KEY)
        return json.loads(raw) if raw else None
    except Exception as exc:
        logger.warning("scoreboard_cache_read_failed", extra={"error_type": type(exc).__name__})
        return None


async def refresh(db: AsyncSession, redis: Redis, *, force: bool = False) -> dict:
    """Recompute if the board is dirty, and publish the result.

    Returns the current payload either way. Falls back to computing without the
    cache when Redis is unavailable, so the endpoints keep answering.
    """
    try:
        dirty = force or await redis.get(DIRTY_KEY) is not None
        if not dirty:
            cached = await get_cached(redis)
            if cached is not None:
                return cached

        # Only one pod recomputes. The others fall through to whatever is
        # cached, which is at most a second behind.
        got_lock = await redis.set(LOCK_KEY, "1", nx=True, ex=LOCK_TTL_SECONDS)
        if not got_lock:
            cached = await get_cached(redis)
            if cached is not None:
                return cached

        payload = serialise(await scoreboard.compute(db, datetime.now(UTC)))

        await redis.set(CACHE_KEY, json.dumps(payload), ex=CACHE_TTL_SECONDS)
        await redis.delete(DIRTY_KEY)
        await redis.publish(CHANNEL, json.dumps(payload))
        return payload
    except Exception as exc:
        logger.warning("scoreboard_refresh_degraded", extra={"error_type": type(exc).__name__})
        # Degraded, not broken: straight from Postgres, no cache, no push.
        return serialise(await scoreboard.compute(db, datetime.now(UTC)))


class ScoreboardBroadcaster:
    """Debounced recompute loop plus fan-out to this pod's WebSocket clients.

    One instance per process, started with the app. Clients are held in memory
    here; the Redis channel is what keeps several pods in step.
    """

    def __init__(self) -> None:
        self._clients: set[asyncio.Queue[str]] = set()
        self._tasks: list[asyncio.Task] = []
        self._stopping = asyncio.Event()

    def subscribe(self) -> asyncio.Queue[str]:
        # Bounded: a client too slow to keep up is dropped rather than allowed
        # to grow a queue without limit.
        queue: asyncio.Queue[str] = asyncio.Queue(maxsize=8)
        self._clients.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[str]) -> None:
        self._clients.discard(queue)

    @property
    def client_count(self) -> int:
        return len(self._clients)

    def start(self, sessionmaker, redis: Redis) -> None:  # noqa: ANN001
        self._stopping.clear()
        self._tasks = [
            asyncio.create_task(self._recompute_loop(sessionmaker, redis)),
            asyncio.create_task(self._listen(redis)),
        ]

    async def stop(self) -> None:
        self._stopping.set()
        for task in self._tasks:
            task.cancel()
        for task in self._tasks:
            with contextlib.suppress(BaseException):
                await task
        self._tasks = []

    async def _recompute_loop(self, sessionmaker, redis: Redis) -> None:  # noqa: ANN001
        """Wake once a second; do nothing unless something changed."""
        while not self._stopping.is_set():
            try:
                await asyncio.sleep(DEBOUNCE_SECONDS)
                if await redis.get(DIRTY_KEY) is None:
                    continue
                async with sessionmaker() as session:
                    await refresh(session, redis)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("scoreboard_loop_error", extra={"error_type": type(exc).__name__})

    async def _listen(self, redis: Redis) -> None:
        """Relay published boards to this pod's clients."""
        while not self._stopping.is_set():
            try:
                pubsub = redis.pubsub()
                await pubsub.subscribe(CHANNEL)
                async for message in pubsub.listen():
                    if self._stopping.is_set():
                        break
                    if message.get("type") == "message":
                        self._fan_out(message["data"])
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning(
                    "scoreboard_subscribe_failed", extra={"error_type": type(exc).__name__}
                )
                # Reconnect rather than leaving clients silently stale.
                await asyncio.sleep(2)

    def _fan_out(self, payload: str) -> None:
        for queue in list(self._clients):
            try:
                queue.put_nowait(payload)
            except asyncio.QueueFull:
                # A client that cannot keep up gets dropped; every message is a
                # whole board, so reconnecting makes it whole again.
                self._clients.discard(queue)


broadcaster = ScoreboardBroadcaster()
