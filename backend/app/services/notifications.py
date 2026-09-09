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
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.notification import Notification, NotificationKind


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
    """Newest first — the feed is read from the top."""
    stmt = select(Notification).where(Notification.user_id == user_id)
    if unread_only:
        stmt = stmt.where(Notification.read_at.is_(None))
    stmt = stmt.order_by(Notification.created_at.desc()).limit(limit)
    return [_view(row) for row in (await db.execute(stmt)).scalars().all()]


async def unread_count(db: AsyncSession, user_id: UUID) -> int:
    return (
        await db.scalar(
            select(func.count(Notification.id)).where(
                Notification.user_id == user_id, Notification.read_at.is_(None)
            )
        )
    ) or 0


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
