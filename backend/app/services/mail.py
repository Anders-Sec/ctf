"""Outbound email over Proton Mail SMTP.

Sending is deliberately best-effort from the caller's point of view: a slow or
unreachable relay must never block an HTTP response, and a delivery failure is
logged with the request id so an admin can find it mid-event rather than
guessing why one player never got their link.
"""

import time
from email.message import EmailMessage

import aiosmtplib
from sqlalchemy import select

from app.config import Settings
from app.db import get_sessionmaker
from app.logging import get_logger
from app.models.email import EmailDelivery, EmailKind, EmailStatus
from app.models.user import User

logger = get_logger(__name__)


async def _record(
    settings: Settings,
    *,
    kind: EmailKind,
    to_email: str,
    status: EmailStatus,
    error_type: str | None,
    duration_ms: int | None,
) -> None:
    """Write the attempt down (spec 055 §3).

    Its own session: these senders run as background tasks, after the response,
    by which point the request's session is closed.

    Never raises. A failure to record is logged and swallowed — an
    audit-adjacent row is not worth failing a login over, and the send has
    already happened either way.
    """
    try:
        sessionmaker = get_sessionmaker(settings)
        async with sessionmaker() as session:
            user_id = await session.scalar(select(User.id).where(User.email == to_email))
            session.add(
                EmailDelivery(
                    kind=kind,
                    to_email=to_email,
                    user_id=user_id,
                    status=status,
                    error_type=error_type,
                    duration_ms=duration_ms,
                )
            )
            await session.commit()
    except Exception as exc:
        logger.warning("email_delivery_not_recorded", extra={"error_type": type(exc).__name__})


async def _deliver(
    settings: Settings, message: EmailMessage, *, kind: EmailKind, to_email: str
) -> bool:
    """Send, time it, and record the attempt. Never raises.

    The caller answers the same way whatever happens here — 202 for a magic
    link, whether or not the address exists — so this must not become a way to
    tell those cases apart. Both paths write a row, identically.
    """
    started = time.monotonic()
    status = EmailStatus.SENT
    error_type: str | None = None

    try:
        await send_message(settings, message)
    except MailNotConfigured:
        status = EmailStatus.NOT_CONFIGURED
        logger.error("mail_not_sent_smtp_unconfigured", extra={"kind": kind.value})
    except Exception as exc:
        # The exception text can contain the recipient address; the type only.
        status = EmailStatus.FAILED
        error_type = type(exc).__name__
        logger.error("mail_send_failed", extra={"kind": kind.value, "error_type": error_type})

    duration_ms = int((time.monotonic() - started) * 1000)
    await _record(
        settings,
        kind=kind,
        to_email=to_email,
        status=status,
        error_type=error_type,
        duration_ms=duration_ms,
    )
    return status is EmailStatus.SENT


class MailNotConfigured(Exception):
    """No SMTP host is configured, so guest login cannot work."""


def build_magic_link_email(settings: Settings, to_email: str, link: str) -> EmailMessage:
    message = EmailMessage()
    message["From"] = settings.smtp_from or ""
    message["To"] = to_email
    message["Subject"] = "Your key to the dungeon"
    minutes = settings.magic_link_ttl_seconds // 60
    message.set_content(
        "A sign-in link was requested for this address.\n\n"
        f"{link}\n\n"
        f"The link works once and expires in {minutes} minutes.\n"
        "If this wasn't you, you can ignore this message — nothing has changed.\n"
    )
    return message


async def send_message(settings: Settings, message: EmailMessage) -> None:
    if not settings.smtp_configured:
        raise MailNotConfigured("SMTP_HOST and SMTP_FROM must be set to send mail")

    # Port 465 is implicit TLS; 587 negotiates STARTTLS after connecting.
    use_implicit_tls = settings.smtp_port == 465
    await aiosmtplib.send(
        message,
        hostname=settings.smtp_host,
        port=settings.smtp_port,
        username=settings.smtp_username,
        password=settings.smtp_token,
        use_tls=use_implicit_tls,
        start_tls=settings.smtp_use_tls and not use_implicit_tls,
        timeout=15,
    )


async def send_magic_link(settings: Settings, to_email: str, link: str) -> bool:
    """Send a login link. Returns whether it went out.

    Never raises: the caller answers 202 either way so that a failing relay
    cannot be used to probe which addresses exist.
    """
    return await _deliver(
        settings,
        build_magic_link_email(settings, to_email, link),
        kind=EmailKind.MAGIC_LINK,
        to_email=to_email,
    )


async def send_approval_notice(settings: Settings, to_email: str) -> bool:
    """Tell an approved guest they can come and play.

    Someone who signed up the night before otherwise has no signal to return.
    """
    message = EmailMessage()
    message["From"] = settings.smtp_from or ""
    message["To"] = to_email
    message["Subject"] = "You've been let into the dungeon"
    message.set_content(
        "Your account has been approved. Sign in and the dungeon is open to you.\n\n"
        f"{settings.app_public_url}\n"
    )
    try:
        await send_message(settings, message)
    except Exception as exc:
        logger.warning("approval_notice_failed", extra={"error_type": type(exc).__name__})
        return False
    return True


async def send_test_message(settings: Settings, to_email: str) -> bool:
    """Prove the relay works, to the admin's own address (spec 055 §4).

    The one control that turns "is mail working?" from a guess into a fact, and
    the first thing anyone reaches for when a guest says they got nothing.
    """
    message = EmailMessage()
    message["From"] = settings.smtp_from or ""
    message["To"] = to_email
    message["Subject"] = "Test from the dungeon"
    message.set_content(
        "This is a test message sent from the platform's Email Delivery page.\n"
        "If you are reading it, the relay is working.\n"
    )
    return await _deliver(settings, message, kind=EmailKind.TEST, to_email=to_email)
