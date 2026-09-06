"""Passwordless guest login.

Two rules shape everything here:

* **No account enumeration.** Requesting a link answers identically for a known
  address, an unknown one, and one that is rate limited. Nothing about the
  response tells an attacker who is registered.
* **One use, one window.** A token is consumed atomically, so a double-clicked
  link cannot mint two sessions, and issuing a new token retires the old.
"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from redis.asyncio import Redis
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.logging import get_logger
from app.models.auth import MagicLinkToken
from app.services.security import generate_token, hash_token

logger = get_logger(__name__)

#: Per address, per hour. Generous for a person mistyping their address, tight
#: enough to stop the platform being used to mail-bomb someone.
REQUESTS_PER_EMAIL_PER_HOUR = 5
#: Per source address. Higher, because a whole office can share one egress IP.
REQUESTS_PER_IP_PER_HOUR = 30
#: Verification attempts. This is the brute-force surface, so it is the tightest.
VERIFY_ATTEMPTS_PER_IP_PER_HOUR = 20

_WINDOW_SECONDS = 3600


@dataclass(frozen=True)
class RateLimitResult:
    allowed: bool
    #: Which limit tripped, for logs. Never returned to the caller.
    scope: str | None = None


async def check_rate_limit(redis: Redis, key: str, limit: int) -> bool:
    """Fixed-window counter. Fails open if Redis is down.

    A Redis outage should not lock every guest out of the event; the tokens are
    still single-use and short-lived, so the fallback risk is bounded.
    """
    try:
        count = await redis.incr(key)
        if count == 1:
            await redis.expire(key, _WINDOW_SECONDS)
        return count <= limit
    except Exception as exc:
        logger.warning("rate_limit_unavailable", extra={"error_type": type(exc).__name__})
        return True


async def check_request_limits(redis: Redis, email: str, ip: str | None) -> RateLimitResult:
    if not await check_rate_limit(
        redis, f"magiclink:req:email:{email.lower()}", REQUESTS_PER_EMAIL_PER_HOUR
    ):
        return RateLimitResult(False, "email")
    if ip and not await check_rate_limit(redis, f"magiclink:req:ip:{ip}", REQUESTS_PER_IP_PER_HOUR):
        return RateLimitResult(False, "ip")
    return RateLimitResult(True)


async def check_verify_limits(redis: Redis, ip: str | None) -> bool:
    if ip is None:
        return True
    return await check_rate_limit(
        redis, f"magiclink:verify:ip:{ip}", VERIFY_ATTEMPTS_PER_IP_PER_HOUR
    )


async def issue_magic_link(
    db: AsyncSession,
    settings: Settings,
    email: str,
    *,
    ip: str | None = None,
    user_agent: str | None = None,
) -> str:
    """Create a token and return the link to email. Retires any earlier token."""
    now = datetime.now(UTC)

    # Superseding earlier tokens means a forwarded old email stops working as
    # soon as the person asks for a fresh one.
    await db.execute(
        update(MagicLinkToken)
        .where(
            MagicLinkToken.email == email,
            MagicLinkToken.consumed_at.is_(None),
            MagicLinkToken.superseded_at.is_(None),
        )
        .values(superseded_at=now)
    )

    raw_token = generate_token()
    db.add(
        MagicLinkToken(
            email=email,
            token_hash=hash_token(raw_token),
            expires_at=now + timedelta(seconds=settings.magic_link_ttl_seconds),
            requested_ip=ip,
            requested_user_agent=(user_agent or "")[:500] or None,
        )
    )
    await db.flush()

    return f"{settings.app_public_url.rstrip('/')}/auth/magic-link?token={raw_token}"


async def consume_magic_link(db: AsyncSession, raw_token: str) -> str | None:
    """Atomically consume a token, returning the email it was issued for.

    The UPDATE ... WHERE consumed_at IS NULL RETURNING is the whole point: two
    concurrent requests with the same token produce exactly one winner, so a
    double-clicked link cannot create two sessions.
    """
    now = datetime.now(UTC)
    result = await db.execute(
        update(MagicLinkToken)
        .where(
            MagicLinkToken.token_hash == hash_token(raw_token),
            MagicLinkToken.consumed_at.is_(None),
            MagicLinkToken.superseded_at.is_(None),
            MagicLinkToken.expires_at > now,
        )
        .values(consumed_at=now)
        .returning(MagicLinkToken.email)
    )
    return result.scalar_one_or_none()
