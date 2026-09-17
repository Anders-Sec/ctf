"""Announcements, with a history (spec 054).

Every route is `Admin`. Speaking to 200 people is not a read-only action, and
the existing endpoint already required `administer`.
"""

from uuid import UUID

from fastapi import APIRouter, Query, Request

from app.api.deps import Admin, DbSession, RedisClient
from app.models.announcement import AnnouncementAudience
from app.schemas.admin_announcements import (
    AnnouncementResponse,
    CreateAnnouncementRequest,
    UpdateAnnouncementRequest,
)
from app.services import announcements
from app.services.identity import record_audit

router = APIRouter(prefix="/admin/announcements", tags=["admin"])


@router.get("")
async def list_announcements(
    db: DbSession,
    current: Admin,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> list[AnnouncementResponse]:
    rows = await announcements.history(db, limit=limit, offset=offset)
    return [AnnouncementResponse(**row) for row in rows]


@router.post("")
async def create_announcement(
    payload: CreateAnnouncementRequest,
    request: Request,
    db: DbSession,
    redis: RedisClient,
    current: Admin,
) -> AnnouncementResponse:
    """Send now, or schedule.

    Not recallable once sent: deleting something people have already read would
    be a lie about what happened, so a correction is another announcement.
    """
    announcement = await announcements.create(
        db,
        current.user,
        title=payload.title.strip(),
        body=payload.body.strip(),
        audience=AnnouncementAudience(payload.audience),
        scheduled_for=payload.scheduled_for,
        redis=redis,
    )

    await record_audit(
        db,
        action="notification.announce" if announcement.sent_at else "notification.schedule",
        target_type="announcement",
        target_id=announcement.id,
        actor_user_id=current.user.id,
        meta={"title": announcement.title, "recipients": announcement.recipient_count},
        request_id=getattr(request.state, "request_id", None),
    )

    rows = await announcements.history(db, limit=1)
    return AnnouncementResponse(**next(row for row in rows if row["id"] == announcement.id))


@router.patch("/{announcement_id}")
async def update_announcement(
    announcement_id: UUID,
    payload: UpdateAnnouncementRequest,
    db: DbSession,
    current: Admin,
) -> AnnouncementResponse:
    """Pending only — the one state nobody has read yet."""
    await announcements.update_pending(
        db,
        announcement_id,
        title=payload.title,
        body=payload.body,
        scheduled_for=payload.scheduled_for,
    )
    rows = await announcements.history(db, limit=500)
    return AnnouncementResponse(**next(row for row in rows if row["id"] == announcement_id))


@router.post("/{announcement_id}/cancel")
async def cancel_announcement(
    announcement_id: UUID,
    request: Request,
    db: DbSession,
    current: Admin,
) -> AnnouncementResponse:
    await announcements.cancel(db, announcement_id)
    await record_audit(
        db,
        action="notification.announce_cancel",
        target_type="announcement",
        target_id=announcement_id,
        actor_user_id=current.user.id,
        request_id=getattr(request.state, "request_id", None),
    )
    rows = await announcements.history(db, limit=500)
    return AnnouncementResponse(**next(row for row in rows if row["id"] == announcement_id))
