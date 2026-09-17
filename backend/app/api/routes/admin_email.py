"""The email delivery log (spec 055).

Reads are `Staff`; the test send is `Admin`. It is the one admin surface holding
a list of personal addresses, and the send is the only thing here that acts.
"""

from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Query
from sqlalchemy import func, select

from app.api.deps import Admin, AppSettings, DbSession, RedisClient, Staff
from app.errors import ConflictError
from app.models.email import EmailDelivery, EmailKind, EmailStatus
from app.schemas.admin_email import (
    DeliveryPageResponse,
    DeliveryResponse,
    MailStatusResponse,
)
from app.schemas.auth import MessageResponse
from app.services import magic_link
from app.services.mail import send_test_message

router = APIRouter(prefix="/admin/email", tags=["admin"])

#: The window the status band reports over. Long enough to be a rate, short
#: enough that a relay fixed twenty minutes ago stops looking broken.
STATUS_WINDOW_MINUTES = 60

#: Below this many attempts a "failure rate" is noise — one failed send out of
#: one is 100%, and says nothing.
MIN_ATTEMPTS_FOR_RATE = 3


@router.get("/status")
async def mail_status(db: DbSession, settings: AppSettings, current: Staff) -> MailStatusResponse:
    """Is mail working at all, and has it been lately?

    The part of the page that earns it: "every guest login is failing" is the
    failure nobody notices until it has been true for an hour.
    """
    since = datetime.now(UTC) - timedelta(minutes=STATUS_WINDOW_MINUTES)

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
    attempts = sent + failed

    return MailStatusResponse(
        configured=settings.smtp_configured,
        window_minutes=STATUS_WINDOW_MINUTES,
        sent=sent,
        failed=failed,
        failure_rate=(failed / attempts) if attempts else 0.0,
        # Below the floor there is no rate worth showing, so the banner stays
        # down rather than crying wolf on a sample of one.
        degraded=attempts >= MIN_ATTEMPTS_FOR_RATE and failed / attempts > 0.5,
    )


@router.get("/deliveries")
async def list_deliveries(
    db: DbSession,
    current: Staff,
    kind: EmailKind | None = None,
    status: EmailStatus | None = None,
    user_id: UUID | None = None,
    search: str | None = Query(default=None, max_length=200),
    since: datetime | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> DeliveryPageResponse:
    conditions = []
    if kind is not None:
        conditions.append(EmailDelivery.kind == kind)
    if status is not None:
        conditions.append(EmailDelivery.status == status)
    if user_id is not None:
        conditions.append(EmailDelivery.user_id == user_id)
    if since is not None:
        conditions.append(EmailDelivery.created_at >= since)
    if search:
        conditions.append(EmailDelivery.to_email.ilike(f"%{search}%"))

    total = await db.scalar(select(func.count()).select_from(EmailDelivery).where(*conditions)) or 0
    rows = (
        (
            await db.execute(
                select(EmailDelivery)
                .where(*conditions)
                .order_by(EmailDelivery.created_at.desc())
                .limit(limit)
                .offset(offset)
            )
        )
        .scalars()
        .all()
    )

    return DeliveryPageResponse(
        total=total,
        entries=[
            DeliveryResponse(
                id=row.id,
                kind=row.kind,
                to_email=row.to_email,
                user_id=row.user_id,
                status=row.status,
                error_type=row.error_type,
                duration_ms=row.duration_ms,
                created_at=row.created_at,
            )
            for row in rows
        ],
    )


@router.post("/test")
async def send_test(
    background: BackgroundTasks,
    redis: RedisClient,
    settings: AppSettings,
    current: Admin,
) -> MessageResponse:
    """Send a test message to the caller's own address.

    Deliberately takes no recipient. An authenticated send-to-anyone endpoint is
    an open relay with extra steps, and the question being answered — "is our
    mail working?" — is answered just as well by a message to yourself.
    """
    if not settings.smtp_configured:
        raise ConflictError("SMTP is not configured.", code="mail_unconfigured")

    limit = await magic_link.check_request_limits(redis, current.user.email, None)
    if not limit.allowed:
        raise ConflictError("Slow down — try again shortly.", code="rate_limited")

    background.add_task(send_test_message, settings, current.user.email)
    return MessageResponse(message=f"A test message is on its way to {current.user.email}.")
