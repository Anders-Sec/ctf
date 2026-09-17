"""Announcements with a history, and scheduling (spec 054).

The composer in spec 032 was right about everything except what happens after
the send: it reported a recipient count and then forgot. Over five days there
was no way to answer "what have I already told people?" without asking a player
to read their feed back to you.
"""

from datetime import UTC, datetime
from uuid import UUID, uuid4

from redis.asyncio import Redis
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.errors import ConflictError, NotFoundError
from app.logging import get_logger
from app.models.announcement import Announcement, AnnouncementAudience
from app.models.notification import Notification, NotificationKind
from app.models.user import User, UserRole, UserStatus
from app.services import notifications as notification_service

logger = get_logger(__name__)


async def _recipients(db: AsyncSession, audience: AnnouncementAudience) -> list[UUID]:
    conditions = [User.status == UserStatus.ACTIVE]
    if audience is AnnouncementAudience.STAFF:
        conditions.append(User.role.in_([UserRole.ORGANIZER, UserRole.ADMIN]))
    else:
        conditions.append(User.role == UserRole.PLAYER)

    rows = await db.execute(select(User.id).where(*conditions))
    return list(rows.scalars())


async def deliver(
    db: AsyncSession, announcement: Announcement, *, redis: Redis | None = None
) -> int:
    """Fan out, stamp, and tag the rows so the read count can be counted.

    Idempotent through ``sent_at``: a scheduled announcement picked up twice by
    overlapping passes sends once.
    """
    if announcement.sent_at is not None:
        return announcement.recipient_count

    recipient_ids = await _recipients(db, announcement.audience)

    result = await notification_service.broadcast(
        db,
        kind=NotificationKind.ANNOUNCEMENT,
        # Fresh every time: sending two different announcements is entirely
        # legitimate, so the claim key must not collapse them.
        key=f"announcement:{announcement.id}",
        title=announcement.title,
        body=announcement.body,
        redis=redis,
        # The audience, and the tag that makes the read count countable.
        to_user_ids=recipient_ids,
        announcement_id=announcement.id,
    )

    announcement.sent_at = datetime.now(UTC)
    announcement.recipient_count = result.recipients
    await db.flush()

    logger.info(
        "announcement_sent",
        extra={"announcement_id": str(announcement.id), "recipients": result.recipients},
    )
    return result.recipients


async def create(
    db: AsyncSession,
    actor: User,
    *,
    title: str,
    body: str,
    audience: AnnouncementAudience = AnnouncementAudience.EVERYONE,
    scheduled_for: datetime | None = None,
    redis: Redis | None = None,
) -> Announcement:
    announcement = Announcement(
        id=uuid4(),
        title=title,
        body=body,
        audience=audience,
        created_by_user_id=actor.id,
        scheduled_for=scheduled_for,
    )
    db.add(announcement)
    await db.flush()

    # A "schedule" for a time already past is a send; treating it as pending
    # would leave it sitting until the next sweep for no reason.
    if scheduled_for is None or scheduled_for <= datetime.now(UTC):
        await deliver(db, announcement, redis=redis)

    return announcement


async def update_pending(
    db: AsyncSession,
    announcement_id: UUID,
    *,
    title: str | None = None,
    body: str | None = None,
    scheduled_for: datetime | None = None,
) -> Announcement:
    """Edit one nobody has read yet.

    Sent announcements are refused: the composer's own copy has always said a
    message cannot be taken back, and a history that could be rewritten after
    the fact would be worth less than no history.
    """
    announcement = await db.get(Announcement, announcement_id)
    if announcement is None:
        raise NotFoundError("No such announcement.")
    if not announcement.is_pending:
        raise ConflictError(
            "That announcement has already gone out. Send a correction instead.",
            code="already_sent",
        )

    if title is not None:
        announcement.title = title
    if body is not None:
        announcement.body = body
    if scheduled_for is not None:
        announcement.scheduled_for = scheduled_for

    await db.flush()
    return announcement


async def cancel(db: AsyncSession, announcement_id: UUID) -> Announcement:
    announcement = await db.get(Announcement, announcement_id)
    if announcement is None:
        raise NotFoundError("No such announcement.")
    if not announcement.is_pending:
        raise ConflictError("That announcement has already gone out.", code="already_sent")

    announcement.cancelled_at = datetime.now(UTC)
    await db.flush()
    return announcement


async def send_due(db: AsyncSession, redis: Redis | None = None) -> int:
    """Deliver anything whose time has come.

    Late rather than skipped: if the process was down at the due moment the
    announcement still goes, and the history shows both the intended and the
    actual time. "Doors are open" arriving at 09:03 is fine; never arriving is
    not.
    """
    due = (
        (
            await db.execute(
                select(Announcement).where(
                    Announcement.sent_at.is_(None),
                    Announcement.cancelled_at.is_(None),
                    Announcement.scheduled_for.is_not(None),
                    Announcement.scheduled_for <= datetime.now(UTC),
                )
            )
        )
        .scalars()
        .all()
    )

    for announcement in due:
        await deliver(db, announcement, redis=redis)
    return len(due)


async def history(db: AsyncSession, *, limit: int = 100, offset: int = 0) -> list[dict]:
    rows = (
        (
            await db.execute(
                select(Announcement)
                .order_by(
                    # Pending first, then most recently sent.
                    Announcement.sent_at.is_(None).desc(),
                    Announcement.sent_at.desc().nullslast(),
                    Announcement.created_at.desc(),
                )
                .limit(limit)
                .offset(offset)
            )
        )
        .scalars()
        .all()
    )
    if not rows:
        return []

    read_counts = dict(
        (
            await db.execute(
                select(Notification.announcement_id, func.count())
                .where(
                    Notification.announcement_id.in_([row.id for row in rows]),
                    Notification.read_at.is_not(None),
                )
                .group_by(Notification.announcement_id)
            )
        ).all()
    )
    authors = dict(
        (
            await db.execute(
                select(User.id, User.display_name).where(
                    User.id.in_([row.created_by_user_id for row in rows if row.created_by_user_id])
                    if any(row.created_by_user_id for row in rows)
                    else [None]
                )
            )
        ).all()
    )

    return [
        {
            "id": row.id,
            "title": row.title,
            "body": row.body,
            "audience": row.audience.value,
            "created_by_name": authors.get(row.created_by_user_id),
            "scheduled_for": row.scheduled_for,
            "sent_at": row.sent_at,
            "cancelled_at": row.cancelled_at,
            "recipient_count": row.recipient_count,
            "read_count": int(read_counts.get(row.id, 0)),
            "created_at": row.created_at,
        }
        for row in rows
    ]
