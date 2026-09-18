"""The System AI's channel to one player (spec 028).

Every message the game wants to say to a player goes through here: achievements,
class unlocks, zone unlocks, level-ups. One place, so the coming narrative pass
can restyle every line without touching a caller — the same rule 016 set for the
class nudge.

Delivery mirrors the scoreboard socket (spec 007), with one difference that
matters. The scoreboard is a broadcast: every listener wants the same payload,
so one channel serves everyone. Notifications are *addressed*, so the channel is
per recipient. Fanning them all to every connection and filtering in the client
would put one player's messages on another player's wire.
"""

import contextlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from redis.asyncio import Redis
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.notification import BroadcastLog, Notification, NotificationKind
from app.models.user import User, UserRole, UserStatus


#: One channel per recipient. The id is the whole addressing scheme.
def channel_for(user_id: UUID) -> str:
    return f"notifications:v1:user:{user_id}"


@dataclass(frozen=True)
class NotificationView:
    id: UUID
    kind: str
    title: str
    body: str
    link: str | None
    read: bool
    created_at: datetime


def _view(row: Notification) -> NotificationView:
    return NotificationView(
        id=row.id,
        kind=row.kind.value,
        title=row.title,
        body=row.body,
        link=row.link,
        read=row.read_at is not None,
        created_at=row.created_at,
    )


def payload_of(view: NotificationView) -> dict:
    """The wire shape, shared by the socket and the publisher so they cannot drift."""
    return {
        "id": str(view.id),
        "kind": view.kind,
        "title": view.title,
        "body": view.body,
        "link": view.link,
        "read": view.read,
        "created_at": view.created_at.isoformat(),
    }


async def notify(
    db: AsyncSession,
    *,
    user_id: UUID,
    kind: NotificationKind,
    title: str,
    body: str,
    link: str | None = None,
    redis: Redis | None = None,
) -> NotificationView:
    """Say something to one player, and push it if they are listening.

    The row is the record; the push is a nicety. A player who was offline, or
    whose socket dropped, finds it in the backlog — so a failed publish is never
    allowed to fail the action that caused it.
    """
    row = Notification(user_id=user_id, kind=kind, title=title, body=body, link=link)
    db.add(row)
    await db.flush()

    view = _view(row)
    if redis is not None:
        # Delivery is best-effort by design: the row is the record, so a Redis
        # hiccup must never fail the solve that caused the notification.
        with contextlib.suppress(Exception):
            await redis.publish(channel_for(user_id), json.dumps(payload_of(view)))
    return view


async def backlog(
    db: AsyncSession, user_id: UUID, *, limit: int = 50, unread_only: bool = False
) -> list[NotificationView]:
    """Newest first — the feed is read from the top.

    Cleared rows are skipped (spec 065 §4), which is what makes the 50-row cap
    mean something: it is a cap on what the player has not already dealt with.
    """
    stmt = select(Notification).where(
        Notification.user_id == user_id, Notification.dismissed_at.is_(None)
    )
    if unread_only:
        stmt = stmt.where(Notification.read_at.is_(None))
    stmt = stmt.order_by(Notification.created_at.desc()).limit(limit)
    return [_view(row) for row in (await db.execute(stmt)).scalars().all()]


async def unread_count(db: AsyncSession, user_id: UUID) -> int:
    """Unread *and* not cleared.

    A badge that counts rows the player can no longer reach is worse than no
    badge, which is why clearing also marks read — see :func:`dismiss`.
    """
    return (
        await db.scalar(
            select(func.count(Notification.id)).where(
                Notification.user_id == user_id,
                Notification.read_at.is_(None),
                Notification.dismissed_at.is_(None),
            )
        )
    ) or 0


async def dismiss(
    db: AsyncSession,
    user_id: UUID,
    *,
    notification_id: UUID | None = None,
    kinds: list[NotificationKind] | None = None,
) -> int:
    """Clear one row, or every row of the given kinds. Returns how many changed.

    **Clearing marks read as well.** Otherwise the badge keeps counting things
    the player can no longer open, and a badge that lies is worse than no badge.

    A stamp rather than a delete: recoverable, and an organiser can still see
    that an announcement existed after somebody cleared it.
    """
    now = datetime.now(UTC)
    stmt = (
        update(Notification)
        .where(Notification.user_id == user_id, Notification.dismissed_at.is_(None))
        .values(dismissed_at=now, read_at=func.coalesce(Notification.read_at, now))
    )
    if notification_id is not None:
        stmt = stmt.where(Notification.id == notification_id)
    if kinds:
        stmt = stmt.where(Notification.kind.in_(kinds))
    result = await db.execute(stmt)
    await db.flush()
    return result.rowcount or 0


async def mark_read(db: AsyncSession, user_id: UUID, notification_id: UUID | None = None) -> int:
    """Mark one, or all of them. Returns how many changed."""
    stmt = (
        update(Notification)
        .where(Notification.user_id == user_id, Notification.read_at.is_(None))
        .values(read_at=datetime.now(UTC))
    )
    if notification_id is not None:
        stmt = stmt.where(Notification.id == notification_id)
    result = await db.execute(stmt)
    await db.flush()
    return result.rowcount or 0


# --- Broadcast (spec 032) ---------------------------------------------------


@dataclass(frozen=True)
class BroadcastResult:
    sent: bool
    recipients: int


async def claim(db: AsyncSession, kind: NotificationKind, key: str) -> bool:
    """Take the right to send this broadcast, or find somebody already has.

    Two replicas run the same daily timer and a restart near the send window
    would otherwise send again. The unique constraint arbitrates: whichever pod
    inserts first sends, the loser's insert fails and it does nothing.
    """
    try:
        # A savepoint, not the whole transaction: losing the race must not
        # discard whatever the caller was doing.
        async with db.begin_nested():
            db.add(BroadcastLog(kind=kind, key=key))
    except IntegrityError:
        return False
    return True


async def recipients(db: AsyncSession) -> list[UUID]:
    """Who a broadcast goes to.

    Active players only. A pending or disabled account cannot act on the news,
    and staff are watching the console rather than the feed.
    """
    return list(
        (
            await db.execute(
                select(User.id).where(
                    User.status == UserStatus.ACTIVE, User.role == UserRole.PLAYER
                )
            )
        )
        .scalars()
        .all()
    )


async def broadcast(
    db: AsyncSession,
    *,
    kind: NotificationKind,
    key: str,
    title: str,
    body: str,
    link: str | None = None,
    redis: Redis | None = None,
    to_user_ids: list[UUID] | None = None,
    announcement_id: UUID | None = None,
) -> BroadcastResult:
    """Say something to everybody, exactly once.

    Fan-out: one row per recipient rather than a shared row everyone reads. That
    keeps 028's guarantee that a notification names exactly one recipient, and
    reuses the backlog, unread count, read state, socket and toast untouched.
    Ten thousand rows across an event is nothing; a second read path would not
    have been.
    """
    if not await claim(db, kind, key):
        return BroadcastResult(sent=False, recipients=0)

    # A narrowed audience (spec 054) passes its own list; everything else gets
    # every active player, which is what every caller before it wanted.
    targets = to_user_ids if to_user_ids is not None else await recipients(db)
    if not targets:
        return BroadcastResult(sent=True, recipients=0)

    rows = [
        Notification(
            user_id=user_id,
            kind=kind,
            title=title,
            body=body,
            link=link,
            announcement_id=announcement_id,
        )
        for user_id in targets
    ]
    db.add_all(rows)
    await db.flush()

    await db.execute(
        update(BroadcastLog)
        .where(BroadcastLog.kind == kind, BroadcastLog.key == key)
        .values(recipients=len(rows))
    )

    if redis is not None:
        for row in rows:
            # Best-effort per recipient, exactly as notify() is: the rows are
            # the record, so a Redis hiccup costs a toast and nothing else.
            with contextlib.suppress(Exception):
                await redis.publish(channel_for(row.user_id), json.dumps(payload_of(_view(row))))

    return BroadcastResult(sent=True, recipients=len(rows))
