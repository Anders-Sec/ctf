"""Redis client.

Redis is a cache, rate limiter and pub/sub bus — never the source of truth.
Anything that must survive a restart lives in Postgres (see Plan.md, NFRs).
"""

from redis.asyncio import Redis, from_url

from app.config import Settings, get_settings

_client: Redis | None = None


def get_redis(settings: Settings | None = None) -> Redis:
    global _client
    if _client is None:
        settings = settings or get_settings()
        _client = from_url(
            settings.redis_url,
            encoding="utf-8",
            decode_responses=True,
            health_check_interval=30,
        )
    return _client


async def close_redis() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
    _client = None
