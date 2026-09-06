"""Outbound email over Proton Mail SMTP.

Sending is deliberately best-effort from the caller's point of view: a slow or
unreachable relay must never block an HTTP response, and a delivery failure is
logged with the request id so an admin can find it mid-event rather than
guessing why one player never got their link.
"""

from email.message import EmailMessage

import aiosmtplib

from app.config import Settings
from app.logging import get_logger

logger = get_logger(__name__)


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
    try:
        await send_message(settings, build_magic_link_email(settings, to_email, link))
    except MailNotConfigured:
        logger.error("magic_link_not_sent_smtp_unconfigured")
        return False
    except Exception as exc:
        # The exception text can contain the recipient address; log the type only.
        logger.error("magic_link_send_failed", extra={"error_type": type(exc).__name__})
        return False

    logger.info("magic_link_sent")
    return True


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
