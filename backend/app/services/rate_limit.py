"""Submission rate limiting.

**This limiter fails closed.** The magic-link limiter in spec 002 fails open,
because it guards against nuisance and locking every guest out of the event
would be worse than the nuisance. This one guards the integrity of the
scoreboard: an event running with brute-force protection silently switched off
is worse than one that briefly refuses submissions.
"""

from dataclasses import dataclass
from uuid import UUID

from redis.asyncio import Redis

from app.errors import AppError
from app.logging import get_logger

logger = get_logger(__name__)

#: Per player per challenge. Comfortable for someone typing carefully, hostile
#: to a script.
ATTEMPTS_PER_CHALLENGE_PER_MINUTE = 10
#: Across all challenges, so a script cannot spread itself thinly to dodge the
#: per-challenge limit.
ATTEMPTS_PER_USER_PER_MINUTE = 60

WINDOW_SECONDS = 60


class RateLimited(AppError):
    status_code = 429
    code = "rate_limited"
    message = "Too many attempts. Wait a moment before trying again."


@dataclass(frozen=True)
class LimitDecision:
    allowed: bool
    retry_after_seconds: int = 0
    scope: str | None = None


async def _hit(redis: Redis, key: str, limit: int) -> tuple[bool, int]:
    """Increment a fixed-window counter. Raises on Redis failure — see module docstring."""
    count = await redis.incr(key)
    if count == 1:
        await redis.expire(key, WINDOW_SECONDS)
    if count <= limit:
        return True, 0
    ttl = await redis.ttl(key)
    return False, max(ttl, 1)


async def check_submission_limits(redis: Redis, user_id: UUID, challenge_id: UUID) -> LimitDecision:
    try:
        allowed, retry = await _hit(
            redis,
            f"submit:u:{user_id}:c:{challenge_id}",
            ATTEMPTS_PER_CHALLENGE_PER_MINUTE,
        )
        if not allowed:
            return LimitDecision(False, retry, "challenge")

        allowed, retry = await _hit(redis, f"submit:u:{user_id}", ATTEMPTS_PER_USER_PER_MINUTE)
        if not allowed:
            return LimitDecision(False, retry, "user")

        return LimitDecision(True)
    except Exception as exc:
        # Fail closed. Deliberate, and the opposite of the magic-link limiter.
        logger.error(
            "submission_rate_limiter_unavailable",
            extra={"error_type": type(exc).__name__},
        )
        raise RateLimited(
            "Submissions are briefly unavailable. Try again shortly.",
            code="rate_limiter_unavailable",
            status_code=503,
        ) from exc
