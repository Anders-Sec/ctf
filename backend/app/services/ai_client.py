"""The only thing in this platform that talks to the model.

Everything about the model host is a liability we are managing: it lives outside
the cluster, on a box whose uptime we do not control, and it will be unreachable
at some point during a multi-day event. None of that may reach a player as a 500
or a hung request, so failure is a first-class return value here rather than an
exception that escapes.
"""

import time
from dataclasses import dataclass, field, replace

import httpx

from app.config import Settings
from app.logging import get_logger

logger = get_logger(__name__)

#: Failure reasons recorded on the message row and surfaced on the staff
#: dashboard. Deliberately coarse: they say what to do about it, not what the
#: stack trace was.
REASON_DISABLED = "disabled"
REASON_UNCONFIGURED = "unconfigured"
REASON_TIMEOUT = "timeout"
REASON_UNREACHABLE = "unreachable"
REASON_BAD_RESPONSE = "bad_response"
REASON_EMPTY = "empty_reply"
REASON_BREAKER_OPEN = "breaker_open"
REASON_BUSY = "busy"


@dataclass(frozen=True)
class ChatMessage:
    role: str
    content: str


@dataclass(frozen=True)
class ChatReply:
    """A completed exchange, successful or not.

    ``reasoning`` is the model's scratchpad. It is captured for the record and
    must never be handed back to a player — see spec 010.
    """

    ok: bool
    content: str = ""
    reasoning: str | None = None
    model: str | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    latency_ms: int = 0
    error: str | None = None


@dataclass
class _Breaker:
    """Stops us waiting on a host we already know is wedged.

    Without this, one unreachable host turns every player's chat into a
    30-second wait, and the in-flight slots fill with requests that are all
    going to time out anyway.
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
                "ai_breaker_opened",
                extra={"consecutive_failures": self.consecutive_failures},
            )

    def retry_after(self, now: float) -> int:
        if self.opened_at is None:
            return 0
        return max(1, int(self.cooldown_seconds - (now - self.opened_at)))


@dataclass
class _Endpoint:
    """Per-host state: one shared connection pool, one breaker, one slot count."""

    client: httpx.AsyncClient
    breaker: _Breaker
    in_flight: int = 0
    recent_latencies: list[int] = field(default_factory=list)


_endpoints: dict[str, _Endpoint] = {}

#: Test seam. When set, new clients are built on this transport instead of the
#: network: nothing in CI should depend on a GPU box being switched on.
_transport: httpx.AsyncBaseTransport | None = None


def use_transport(transport: httpx.AsyncBaseTransport | None) -> None:
    _set_transport(transport)


def _endpoint(settings: Settings) -> _Endpoint:
    key = f"{settings.ai_base_url}|{settings.ai_model}"
    endpoint = _endpoints.get(key)
    if endpoint is None:
        endpoint = _Endpoint(
            client=httpx.AsyncClient(
                base_url=str(settings.ai_base_url).rstrip("/"),
                timeout=httpx.Timeout(settings.ai_timeout_seconds, connect=5.0),
                headers=_auth_headers(settings),
                transport=_transport,
            ),
            breaker=_Breaker(
                threshold=settings.ai_breaker_threshold,
                cooldown_seconds=settings.ai_breaker_cooldown_seconds,
            ),
        )
        _endpoints[key] = endpoint
    return endpoint


def _auth_headers(settings: Settings) -> dict[str, str]:
    """Sent even though the host was measured not to enforce it.

    It costs nothing and starts working the day the host checks it. The control
    actually holding today is the firewall in front of that port.
    """
    if not settings.ai_api_key:
        return {}
    return {"Authorization": f"Bearer {settings.ai_api_key}"}


async def close_clients() -> None:
    """Shutdown hook, so a connection pool does not outlive the app."""
    for endpoint in _endpoints.values():
        await endpoint.client.aclose()
    _endpoints.clear()


def reset_state() -> None:
    """Test seam: forget breakers, pools and any installed transport."""
    _set_transport(None)


def _set_transport(transport: httpx.AsyncBaseTransport | None) -> None:
    global _transport
    _transport = transport
    _endpoints.clear()


async def complete(settings: Settings, messages: list[ChatMessage]) -> ChatReply:
    """Ask the model. Never raises; an unavailable host is a ``ChatReply(ok=False)``."""
    if not settings.ai_enabled:
        return ChatReply(ok=False, error=REASON_DISABLED)
    if not settings.ai_configured:
        return ChatReply(ok=False, error=REASON_UNCONFIGURED)

    endpoint = _endpoint(settings)
    if endpoint.breaker.is_open(time.monotonic()):
        return ChatReply(ok=False, error=REASON_BREAKER_OPEN)

    # A hard ceiling rather than a queue: a player waiting behind seven others
    # for a slot has already had a bad experience, and the measured throughput
    # says this host is happiest at eight concurrent.
    if endpoint.in_flight >= settings.ai_max_concurrency:
        return ChatReply(ok=False, error=REASON_BUSY)

    endpoint.in_flight += 1
    started = time.monotonic()
    try:
        reply = await _post(settings, endpoint, messages, started)
    finally:
        endpoint.in_flight -= 1

    if reply.ok:
        endpoint.breaker.record_success()
        endpoint.recent_latencies.append(reply.latency_ms)
        del endpoint.recent_latencies[:-20]
    elif reply.error != REASON_EMPTY:
        # An empty reply is the model behaving oddly, not the host being down.
        # Counting it toward the breaker would take the feature offline over a
        # problem that reconnecting cannot fix.
        endpoint.breaker.record_failure(time.monotonic())
    return reply


async def _post(
    settings: Settings, endpoint: _Endpoint, messages: list[ChatMessage], started: float
) -> ChatReply:
    payload = {
        "model": settings.ai_model,
        "messages": [{"role": m.role, "content": m.content} for m in messages],
        "max_tokens": settings.ai_max_tokens,
        "temperature": settings.ai_temperature,
        "stream": False,
    }
    try:
        response = await endpoint.client.post("/chat/completions", json=payload)
        response.raise_for_status()
        body = response.json()
    except httpx.TimeoutException:
        logger.warning("ai_request_timeout", extra={"timeout": settings.ai_timeout_seconds})
        return ChatReply(ok=False, error=REASON_TIMEOUT, latency_ms=_elapsed(started))
    except httpx.HTTPStatusError as exc:
        logger.warning("ai_request_failed", extra={"status": exc.response.status_code})
        return ChatReply(ok=False, error=REASON_BAD_RESPONSE, latency_ms=_elapsed(started))
    except Exception as exc:
        logger.warning("ai_request_unreachable", extra={"error_type": type(exc).__name__})
        return ChatReply(ok=False, error=REASON_UNREACHABLE, latency_ms=_elapsed(started))

    return _parse(body, _elapsed(started))


def _parse(body: object, latency_ms: int) -> ChatReply:
    """Read the OpenAI-compatible envelope defensively.

    The host is a desktop application rather than a managed API; a malformed
    body should degrade the chat, not raise inside a request handler.
    """
    if not isinstance(body, dict):
        return ChatReply(ok=False, error=REASON_BAD_RESPONSE, latency_ms=latency_ms)

    choices = body.get("choices") or []
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        return ChatReply(ok=False, error=REASON_BAD_RESPONSE, latency_ms=latency_ms)

    message = choices[0].get("message") or {}
    if not isinstance(message, dict):
        return ChatReply(ok=False, error=REASON_BAD_RESPONSE, latency_ms=latency_ms)

    content = (message.get("content") or "").strip()
    # The measured model returns its thinking in a sibling field rather than in
    # inline tags, which is why it can be separated this cleanly.
    reasoning = message.get("reasoning_content") or message.get("reasoning")
    if not isinstance(reasoning, str):
        reasoning = None
    usage = body.get("usage")
    usage = usage if isinstance(usage, dict) else {}

    if not content:
        return ChatReply(ok=False, error=REASON_EMPTY, reasoning=reasoning, latency_ms=latency_ms)

    model = body.get("model")
    return ChatReply(
        ok=True,
        content=content,
        reasoning=reasoning,
        model=model if isinstance(model, str) else None,
        prompt_tokens=_int_or_none(usage.get("prompt_tokens")),
        completion_tokens=_int_or_none(usage.get("completion_tokens")),
        latency_ms=latency_ms,
    )


def _int_or_none(value: object) -> int | None:
    return value if isinstance(value, int) else None


def _elapsed(started: float) -> int:
    return int((time.monotonic() - started) * 1000)


@dataclass(frozen=True)
class AIHealth:
    enabled: bool
    configured: bool
    reachable: bool
    model: str | None
    breaker_open: bool
    consecutive_failures: int
    retry_after_seconds: int
    in_flight: int
    average_latency_ms: int | None
    error: str | None = None


async def health(settings: Settings) -> AIHealth:
    """For the staff dashboard. Cheap enough to poll: it lists models, generating nothing."""
    state = AIHealth(
        enabled=settings.ai_enabled,
        configured=settings.ai_configured,
        reachable=False,
        model=settings.ai_model or None,
        breaker_open=False,
        consecutive_failures=0,
        retry_after_seconds=0,
        in_flight=0,
        average_latency_ms=None,
    )
    if not settings.ai_configured:
        return replace(state, error=REASON_UNCONFIGURED if settings.ai_enabled else REASON_DISABLED)

    endpoint = _endpoint(settings)
    now = time.monotonic()
    latencies = endpoint.recent_latencies
    state = replace(
        state,
        breaker_open=endpoint.breaker.is_open(now),
        consecutive_failures=endpoint.breaker.consecutive_failures,
        retry_after_seconds=endpoint.breaker.retry_after(now),
        in_flight=endpoint.in_flight,
        average_latency_ms=sum(latencies) // len(latencies) if latencies else None,
    )

    try:
        response = await endpoint.client.get("/models", timeout=5.0)
        response.raise_for_status()
    except Exception as exc:
        return replace(state, error=type(exc).__name__)
    return replace(state, reachable=True)
