"""Cleaning up instances, two ways, because there are two ways to leak.

Expiry reaps instances past their TTL. Orphan reconciliation catches the
dangerous case: a pod still running on the node that no live database row owns —
an unowned, attacker-controlled container. Both run under a Postgres advisory
lock so that several backend replicas do not fight over the same instance; the
lock is the same mechanism the migrations use.

The two `reconcile_*` functions are pure and tested directly against the fake;
the loop is just a clock and the lock around them.
"""

import asyncio
import contextlib
from datetime import UTC, datetime

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.logging import get_logger
from app.models.event import EVENT_CONFIG_ID, EventConfig
from app.models.instance import LIVE_STATUSES, ChallengeInstance, InstanceStatus
from app.models.team import Team
from app.services.instances import launcher
from app.services.instances.orchestrator import InstanceOrchestrator

logger = get_logger(__name__)

#: Advisory-lock id for the reconciler. Distinct from the migration lock, so the
#: two never collide.
RECONCILE_LOCK_ID = 4_919_170_002

TICK_SECONDS = 30
#: Orphan sweep runs less often — listing pods is heavier than a timestamp query,
#: and a leaked pod is not an emergency measured in seconds.
ORPHAN_EVERY_TICKS = 10


async def reconcile_expiry(
    db: AsyncSession,
    settings: Settings,
    orchestrator: InstanceOrchestrator,
    now: datetime | None = None,
) -> int:
    """Destroy every live instance past its TTL. Returns how many."""
    now = now or datetime.now(UTC)
    event = await db.get(EventConfig, EVENT_CONFIG_ID)
    event_over = event is not None and event.has_ended(now)

    # Disbanded parties' instances are torn down here rather than threading the
    # orchestrator through the teams service: a 30-second lag on cleanup is fine,
    # and it keeps instance lifecycle in one place.
    disbanded = select(Team.id).where(Team.disbanded_at.is_not(None))

    condition = ChallengeInstance.status.in_(LIVE_STATUSES)
    if event_over:
        # The crawl is over; nothing should still be running.
        filters = condition
    else:
        filters = condition & (
            (ChallengeInstance.expires_at < now) | (ChallengeInstance.owner_team_id.in_(disbanded))
        )

    expired = (await db.execute(select(ChallengeInstance).where(filters))).scalars().all()
    for instance in expired:
        await launcher.destroy(
            db, settings, orchestrator, instance, status=InstanceStatus.EXPIRED, now=now
        )
    if expired:
        logger.info("instances_expired", extra={"count": len(expired)})
    return len(expired)


async def reconcile_orphans(
    db: AsyncSession, settings: Settings, orchestrator: InstanceOrchestrator
) -> tuple[int, int]:
    """Reconcile pods against rows both ways. Returns (pods deleted, rows failed).

    A pod with no live row is deleted — the dangerous leak. A live row with no pod
    is marked failed — the pod died under it and the player should be told rather
    than left polling a corpse.
    """
    live = (
        (
            await db.execute(
                select(ChallengeInstance).where(ChallengeInstance.status.in_(LIVE_STATUSES))
            )
        )
        .scalars()
        .all()
    )
    live_by_name = {instance.k8s_name: instance for instance in live}
    pod_names = set(await orchestrator.list_managed_pods(settings.kube_namespace))

    deleted = 0
    for pod_name in pod_names - live_by_name.keys():
        await orchestrator.destroy(settings.kube_namespace, pod_name)
        deleted += 1

    failed = 0
    for name, instance in live_by_name.items():
        # A pending instance legitimately has no pod for a moment at launch; only
        # fail a row that claimed to be running.
        if name not in pod_names and instance.status == InstanceStatus.RUNNING:
            instance.status = InstanceStatus.FAILED
            instance.last_error = "pod vanished"
            failed += 1
    await db.flush()

    if deleted or failed:
        logger.warning("instance_orphans_reconciled", extra={"pods": deleted, "rows": failed})
    return deleted, failed


class InstanceReconciler:
    def __init__(self) -> None:
        self._task: asyncio.Task | None = None
        self._stopping = asyncio.Event()

    def start(self, sessionmaker, settings: Settings, orchestrator: InstanceOrchestrator) -> None:  # noqa: ANN001
        self._stopping.clear()
        self._task = asyncio.create_task(self._loop(sessionmaker, settings, orchestrator))

    async def stop(self) -> None:
        self._stopping.set()
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(BaseException):
                await self._task
            self._task = None

    async def _loop(self, sessionmaker, settings: Settings, orchestrator) -> None:  # noqa: ANN001
        tick = 0
        while not self._stopping.is_set():
            try:
                await asyncio.sleep(TICK_SECONDS)
                async with sessionmaker() as session:
                    if not await _acquire(session):
                        continue  # another replica holds the lock this tick
                    try:
                        await reconcile_expiry(session, settings, orchestrator)
                        if tick % ORPHAN_EVERY_TICKS == 0:
                            await reconcile_orphans(session, settings, orchestrator)
                        await session.commit()
                    finally:
                        await _release(session)
                tick += 1
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - a bad tick must not kill the loop
                logger.warning("reconciler_tick_error", extra={"error_type": type(exc).__name__})


async def _acquire(session: AsyncSession) -> bool:
    result = await session.execute(
        text("SELECT pg_try_advisory_lock(:id)"), {"id": RECONCILE_LOCK_ID}
    )
    return bool(result.scalar())


async def _release(session: AsyncSession) -> None:
    await session.execute(text("SELECT pg_advisory_unlock(:id)"), {"id": RECONCILE_LOCK_ID})


reconciler = InstanceReconciler()
