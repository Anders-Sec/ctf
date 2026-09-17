"""Staff-facing platform health (spec 057).

Explicitly **not** observability. `Plan.md` rules out a Prometheus/Grafana stack
for a five-day single-instance event, and this is what that ruling implies: one
screen, read by one person, when something feels wrong. The bar is that when a
player says "it's broken", an admin can tell within ten seconds whether the
problem is the platform, one challenge, or that one player.

The load figures come from counters in this process. Two honest limits, both of
which the page states rather than hides: they reset when the process restarts,
and they are per-pod. Aggregating across replicas is what a metrics stack is
for, and the decision not to run one is upstream of this file.
"""

import asyncio
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from redis.asyncio import Redis
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.logging import get_logger
from app.models.email import EmailDelivery, EmailStatus
from app.services import ai_client, scoreboard_cache

logger = get_logger(__name__)

#: One dependency must not be able to make the health page itself hang. A health
#: page that times out is worse than no health page.
CHECK_TIMEOUT_SECONDS = 2.0

#: The rolling window the load figures cover.
LOAD_WINDOW_SECONDS = 15 * 60

_STARTED_AT = time.monotonic()


@dataclass
class _Counters:
    """A rolling 15-minute view of what this process has served."""

    requests: deque[float] = field(default_factory=deque)
    errors: deque[float] = field(default_factory=deque)
    latencies: deque[tuple[float, float]] = field(default_factory=deque)

    def record(self, *, duration_ms: float, status_code: int) -> None:
        now = time.monotonic()
        self.requests.append(now)
        self.latencies.append((now, duration_ms))
        if status_code >= 500:
            self.errors.append(now)
        self._trim(now)

    def _trim(self, now: float) -> None:
        cutoff = now - LOAD_WINDOW_SECONDS
        for series in (self.requests, self.errors):
            while series and series[0] < cutoff:
                series.popleft()
        while self.latencies and self.latencies[0][0] < cutoff:
            self.latencies.popleft()

    def snapshot(self) -> dict[str, Any]:
        now = time.monotonic()
        self._trim(now)
        samples = sorted(duration for _, duration in self.latencies)
        p95 = samples[min(int(len(samples) * 0.95), len(samples) - 1)] if samples else 0.0
        minutes = LOAD_WINDOW_SECONDS / 60
        return {
            "window_minutes": int(minutes),
            "requests_per_minute": round(len(self.requests) / minutes, 1),
            "p95_ms": round(p95, 1),
            "errors": len(self.errors),
            "uptime_seconds": int(now - _STARTED_AT),
        }


counters = _Counters()


@dataclass(frozen=True)
class Check:
    name: str
    #: ok | degraded | down | not_configured
    state: str
    duration_ms: int | None = None
    detail: str | None = None


async def _timed(name: str, probe, *, slow_ms: int | None = None) -> Check:
    started = time.perf_counter()
    try:
        async with asyncio.timeout(CHECK_TIMEOUT_SECONDS):
            await probe()
    except TimeoutError:
        return Check(name=name, state="down", detail=f"no answer in {CHECK_TIMEOUT_SECONDS:g}s")
    except Exception as exc:
        return Check(name=name, state="down", detail=type(exc).__name__)

    elapsed = int((time.perf_counter() - started) * 1000)
    # Slow is the interesting state for the model host: it is not down, but
    # every player's chat feels broken.
    state = "degraded" if slow_ms is not None and elapsed > slow_ms else "ok"
    return Check(name=name, state=state, duration_ms=elapsed)


async def _postgres(db: AsyncSession) -> Check:
    async def probe() -> None:
        await db.execute(text("SELECT 1"))

    return await _timed("Postgres", probe)


async def _redis(redis: Redis) -> Check:
    async def probe() -> None:
        await redis.ping()

    return await _timed("Redis", probe)


async def _model_host(settings: Settings) -> Check:
    if not (settings.ai_enabled and settings.ai_configured):
        return Check(name="Model host", state="not_configured")

    started = time.perf_counter()
    try:
        async with asyncio.timeout(CHECK_TIMEOUT_SECONDS):
            state = await ai_client.health(settings)
    except TimeoutError:
        return Check(name="Model host", state="down", detail="no answer in 2s")
    except Exception as exc:
        return Check(name="Model host", state="down", detail=type(exc).__name__)

    elapsed = int((time.perf_counter() - started) * 1000)
    if not state.reachable:
        return Check(name="Model host", state="down", duration_ms=elapsed)
    if state.breaker_open:
        return Check(
            name="Model host", state="degraded", duration_ms=elapsed, detail="breaker open"
        )
    # Two seconds is fine for a database; a model host at two seconds is a chat
    # nobody wants to use, so slow counts as degraded here and nowhere else.
    if elapsed > 1500:
        return Check(name="Model host", state="degraded", duration_ms=elapsed, detail="slow")
    return Check(name="Model host", state="ok", duration_ms=elapsed)


async def _orchestrator(settings: Settings, orchestrator: Any | None) -> Check:
    if not settings.instances_enabled or orchestrator is None:
        # A deliberate setting, not a fault. A red light for something switched
        # off teaches you to ignore red lights.
        return Check(name="Orchestrator", state="not_configured")

    probe = getattr(orchestrator, "health", None)
    if probe is None:
        # Reaching it at all is what this reports — we are on our side of the
        # line spec 057 draws around the cluster.
        return Check(name="Orchestrator", state="ok", detail="no probe available")

    return await _timed("Orchestrator", probe)


async def _mail(db: AsyncSession, settings: Settings) -> Check:
    """Derived from spec 055's rows, never a live SMTP connection.

    Probing the relay on every page load is a good way to get rate-limited by
    Proton.
    """
    if not settings.smtp_configured:
        return Check(name="Mail relay", state="not_configured")

    since = datetime.now(UTC) - timedelta(hours=1)
    rows = (
        await db.execute(
            select(EmailDelivery.status, func.count())
            .where(EmailDelivery.created_at >= since)
            .group_by(EmailDelivery.status)
        )
    ).all()
    counts = {status: int(count) for status, count in rows}
    sent = counts.get(EmailStatus.SENT, 0)
    failed = counts.get(EmailStatus.FAILED, 0) + counts.get(EmailStatus.NOT_CONFIGURED, 0)
    total = sent + failed

    if total < 3:
        return Check(name="Mail relay", state="ok", detail="too few sends to judge")
    if failed / total > 0.5:
        return Check(name="Mail relay", state="down", detail=f"{failed} of {total} failed")
    if failed:
        return Check(name="Mail relay", state="degraded", detail=f"{failed} of {total} failed")
    return Check(name="Mail relay", state="ok")


async def _scoreboard(redis: Redis) -> Check:
    """A stale projection is the failure that looks like "the site is frozen"."""

    async def probe() -> None:
        await redis.get(scoreboard_cache.CACHE_KEY)

    check = await _timed("Scoreboard cache", probe)
    if check.state != "ok":
        return check

    try:
        raw = await redis.get(scoreboard_cache.CACHE_KEY)
    except Exception:
        return Check(name="Scoreboard cache", state="down", detail="unreadable")

    if raw is None:
        return Check(name="Scoreboard cache", state="ok", detail="not built yet")
    return check


async def report(
    db: AsyncSession, redis: Redis, settings: Settings, orchestrator: Any | None = None
) -> dict[str, Any]:
    """Every check at once, in parallel.

    The total is bounded by the slowest check rather than their sum, which is
    what keeps this page usable when one dependency is the thing that is wrong.
    """
    checks = await asyncio.gather(
        _postgres(db),
        _redis(redis),
        _model_host(settings),
        _orchestrator(settings, orchestrator),
        _mail(db, settings),
        _scoreboard(redis),
    )

    return {
        "checked_at": datetime.now(UTC).isoformat(),
        "checks": [
            {
                "name": check.name,
                "state": check.state,
                "duration_ms": check.duration_ms,
                "detail": check.detail,
            }
            for check in checks
        ],
        "connections": {
            # In-process subscriber counts. Per-pod, like everything else here.
            "scoreboard": scoreboard_cache.broadcaster.client_count,
        },
        "build": {
            "version": settings.app_version,
            "environment": settings.environment,
        },
        "load": counters.snapshot(),
    }
