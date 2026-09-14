"""Recording the platform events three achievements ask about (spec 039).

Two ways in, because the two kinds of caller are genuinely different.

``record`` joins the caller's transaction, and is for the success path — a class
change that rolls back must not leave behind a record that it happened.

``record_detached`` opens its own session, for callers on a **failure** path. It
exists because of a specific trap: ``get_db_session`` rolls the request session
back on any exception, so a row added while raising a 403 — or while handling a
500 — is discarded along with everything else. The event outlives the request
that produced it or it is not recorded at all.
"""

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_sessionmaker
from app.logging import get_logger
from app.models.player_event import PlayerEvent, PlayerEventKind

logger = get_logger(__name__)


async def record(db: AsyncSession, user_id: UUID, kind: PlayerEventKind) -> None:
    """Append an event inside the caller's transaction."""
    db.add(PlayerEvent(user_id=user_id, kind=kind))


async def record_detached(user_id: UUID, kind: PlayerEventKind) -> None:
    """Append an event in a session of its own, and never raise.

    Called from a 403 gate and from the unhandled-exception handler. Neither can
    afford to fail: a 500 that becomes a *different* 500 while recording the
    first one is a strictly worse outcome than losing the row.
    """
    try:
        async with get_sessionmaker()() as session:
            session.add(PlayerEvent(user_id=user_id, kind=kind))
            await session.commit()
    except Exception:  # noqa: BLE001 - the response matters more than the row
        logger.warning("player_event_record_failed", extra={"kind": kind.value})


async def count(db: AsyncSession, user_id: UUID, kind: PlayerEventKind) -> int:
    """How many of this kind the player has. The only question asked of them."""
    total = await db.scalar(
        select(func.count(PlayerEvent.id)).where(
            PlayerEvent.user_id == user_id, PlayerEvent.kind == kind
        )
    )
    return total or 0
