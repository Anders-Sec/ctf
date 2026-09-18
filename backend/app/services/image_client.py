"""The only thing in this platform that talks to the image host.

A deliberate twin of ``ai_client`` (spec 074 §4), whose docstring already makes
the argument: the host lives outside the cluster, on a box whose uptime we do
not control, and it will be unreachable at some point during a multi-day event.
None of that may reach a player as a 500 or a hung request, so **failure is a
first-class return value here rather than an exception that escapes**.

The difference from the AI host is what happens when this one is dark: nothing.
Spec 073 gives everybody a procedural crest with no GPU at all, so an image host
that is off costs a button, not a feature.
"""

import time
from dataclasses import dataclass, field

import httpx

from app.config import Settings
from app.logging import get_logger

logger = get_logger(__name__)

#: Coarse on purpose, like the AI client's: they say what to do about it, not
#: what the stack trace was.
REASON_DISABLED = "disabled"
REASON_UNCONFIGURED = "unconfigured"
REASON_TIMEOUT = "timeout"
REASON_UNREACHABLE = "unreachable"
REASON_BAD_RESPONSE = "bad_response"
REASON_BREAKER_OPEN = "breaker_open"
REASON_BUSY = "busy"
REASON_REJECTED = "rejected"

#: What the service is allowed to hand back. Anything else is a bad response —
#: an HTML error page rendered as an avatar would be a memorable bug.
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


@dataclass(frozen=True)
class ImageReply:
    """A finished generation, successful or not."""

    ok: bool
    image: bytes | None = None
    seed: int | None = None
    latency_ms: int = 0
    error: str | None = None

    @property
    def unavailable(self) -> bool:
        """Whether this was the host being off rather than the request failing.

        The caller shows a different thing for each: "not available right now"
        against "that did not work", and a budget is only spent on the second.
        """
        return self.error in {
            REASON_DISABLED,
            REASON_UNCONFIGURED,
            REASON_BREAKER_OPEN,
            REASON_UNREACHABLE,
        }


@dataclass
class _Breaker:
    """Stops us waiting on a host we already know is wedged.

    Copied in shape from ``ai_client`` rather than shared: the two have
    different thresholds and different failure meanings, and one abstraction
    over both would be a worse thing to read than two small ones.
    """

    threshold: int
    cooldown_seconds: float
    consecutive_failures: int = 0
    opened_at: float | None = None

    def is_open(self, now: float) -> bool:
        if self.opened_at is None:
            return False
        if now - self.opened_at >= self.cooldown_seconds:
            # Half-open: let the next call through and let it decide.
            self.opened_at = None
            self.consecutive_failures = 0
            return False
        return True

    def record_success(self) -> None:
        self.consecutive_failures = 0
        self.opened_at = None

    def record_failure(self, now: float) -> None:
        self.consecutive_failures += 1
        if self.consecutive_failures >= self.threshold and self.opened_at is None:
            self.opened_at = now
            logger.warning(
                "image_breaker_opened",
                extra={"consecutive_failures": self.consecutive_failures},
            )


@dataclass
class _Endpoint:
    client: httpx.AsyncClient
    breaker: _Breaker
    in_flight: int = 0
    recent_latencies: list[int] = field(default_factory=list)


_endpoints: dict[str, _Endpoint] = {}

#: Test seam. Nothing in CI may depend on a GPU box being switched on.
_transport: httpx.AsyncBaseTransport | None = None


def use_transport(transport: httpx.AsyncBaseTransport | None) -> None:
    global _transport
    _transport = transport
    _endpoints.clear()


def reset_state() -> None:
    """Test seam: forget breakers, pools and any installed transport."""
    use_transport(None)


async def close_clients() -> None:
    for endpoint in _endpoints.values():
        await endpoint.client.aclose()
    _endpoints.clear()


def _endpoint(settings: Settings) -> _Endpoint:
    key = f"{settings.image_base_url}|{settings.image_model}"
    endpoint = _endpoints.get(key)
    if endpoint is None:
        endpoint = _Endpoint(
            client=httpx.AsyncClient(
                base_url=str(settings.image_base_url).rstrip("/"),
                # Generous: four candidates on a busy card is not fast, and a
                # timeout that fires mid-generation wastes the GPU time anyway.
                timeout=httpx.Timeout(settings.image_timeout_seconds, connect=5.0),
                headers=_auth_headers(settings),
                transport=_transport,
            ),
            breaker=_Breaker(
                threshold=settings.image_breaker_threshold,
                cooldown_seconds=settings.image_breaker_cooldown_seconds,
            ),
        )
        _endpoints[key] = endpoint
    return endpoint


def _auth_headers(settings: Settings) -> dict[str, str]:
    if not settings.image_api_key:
        return {}
    return {"Authorization": f"Bearer {settings.image_api_key}"}


def available(settings: Settings) -> bool:
    """Whether the generation entry point should be offered at all.

    Read by the API so a dark host means the button is simply absent rather
    than present and failing (spec 074 §7).
    """
    if not settings.image_enabled or not settings.image_configured:
        return False
    return not _endpoint(settings).breaker.is_open(time.monotonic())


async def generate(
    settings: Settings, prompt: str, *, seed: int, steps: int | None = None
) -> ImageReply:
    """One portrait. Never raises — the failure is in the return value.

    ``prompt`` is assembled server-side from trait keys (spec 074 §1); this
    function does not know or care what the player chose, which is deliberate:
    the only place a prompt can be built is the one place that validates it.
    """
    if not settings.image_enabled:
        return ImageReply(ok=False, error=REASON_DISABLED)
    if not settings.image_configured:
        return ImageReply(ok=False, error=REASON_UNCONFIGURED)

    endpoint = _endpoint(settings)
    now = time.monotonic()
    if endpoint.breaker.is_open(now):
        return ImageReply(ok=False, error=REASON_BREAKER_OPEN)
    if endpoint.in_flight >= settings.image_max_concurrency:
        # One GPU. Queueing is the caller's job; this just refuses to pile on.
        return ImageReply(ok=False, error=REASON_BUSY)

    started = time.monotonic()
    endpoint.in_flight += 1
    try:
        response = await endpoint.client.post(
            "/generate",
            json={
                "prompt": prompt,
                "seed": seed,
                "steps": steps or settings.image_steps,
                "model": settings.image_model,
            },
        )
    except httpx.TimeoutException:
        endpoint.breaker.record_failure(time.monotonic())
        return ImageReply(ok=False, error=REASON_TIMEOUT, latency_ms=_ms(started))
    except httpx.HTTPError:
        endpoint.breaker.record_failure(time.monotonic())
        return ImageReply(ok=False, error=REASON_UNREACHABLE, latency_ms=_ms(started))
    finally:
        endpoint.in_flight -= 1

    latency = _ms(started)

    if response.status_code == 422:
        # The service's own NSFW classifier turned it down. A *successful*
        # conversation with a working host, so the breaker stays shut.
        endpoint.breaker.record_success()
        return ImageReply(ok=False, error=REASON_REJECTED, latency_ms=latency)

    if response.status_code >= 400:
        endpoint.breaker.record_failure(time.monotonic())
        return ImageReply(ok=False, error=REASON_BAD_RESPONSE, latency_ms=latency)

    body = response.content
    if not body.startswith(PNG_MAGIC):
        # An HTML error page rendered as somebody's face would be a memorable
        # bug. Checked rather than trusted.
        endpoint.breaker.record_failure(time.monotonic())
        return ImageReply(ok=False, error=REASON_BAD_RESPONSE, latency_ms=latency)

    endpoint.breaker.record_success()
    endpoint.recent_latencies.append(latency)
    del endpoint.recent_latencies[:-50]
    return ImageReply(ok=True, image=body, seed=seed, latency_ms=latency)


def _ms(started: float) -> int:
    return int((time.monotonic() - started) * 1000)
