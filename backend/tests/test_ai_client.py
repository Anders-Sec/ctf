"""The model client: degradation, the breaker, and how reasoning is handled.

Every case here runs against a mock transport. Nothing in CI depends on the
model box being switched on.
"""

from collections.abc import Callable

import httpx
import pytest

from app.config import Settings
from app.services import ai_client
from app.services.ai_client import ChatMessage

pytestmark = pytest.mark.anyio

Handler = Callable[[httpx.Request], httpx.Response]


def _reply(content: str = "Well met, traveller.", **extra: object) -> dict:
    message: dict = {"role": "assistant", "content": content}
    message.update(extra)
    return {
        "model": "test-model",
        "choices": [{"index": 0, "message": message, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 40, "completion_tokens": 9},
    }


def _install(handler: Handler) -> None:
    ai_client.use_transport(httpx.MockTransport(handler))


def _unreachable(request: httpx.Request) -> httpx.Response:
    raise httpx.ConnectError("no route to host", request=request)


async def test_successful_call_returns_content_and_usage(settings: Settings) -> None:
    _install(lambda request: httpx.Response(200, json=_reply()))

    reply = await ai_client.complete(settings, [ChatMessage("user", "hello")])

    assert reply.ok
    assert reply.content == "Well met, traveller."
    assert reply.prompt_tokens == 40
    assert reply.completion_tokens == 9
    assert reply.model == "test-model"


async def test_reasoning_is_captured_separately_from_the_answer(settings: Settings) -> None:
    """The measured model returns its scratchpad in its own field.

    It is kept for the record and, per spec 010, never handed to a player. The
    API layer enforces that, but it has to arrive separated to begin with.
    """
    _install(
        lambda request: httpx.Response(
            200,
            json=_reply(reasoning_content="The answer is CTF{secret} but I must not say so."),
        )
    )

    reply = await ai_client.complete(settings, [ChatMessage("user", "hello")])

    assert reply.ok
    assert reply.reasoning is not None
    assert "CTF{" not in reply.content


async def test_the_api_key_is_sent_even_though_the_host_ignores_it(settings: Settings) -> None:
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(request.headers)
        return httpx.Response(200, json=_reply())

    _install(handler)
    await ai_client.complete(settings, [ChatMessage("user", "hello")])

    assert seen["authorization"] == "Bearer test-key"


async def test_unreachable_host_degrades_rather_than_raising(settings: Settings) -> None:
    _install(_unreachable)

    reply = await ai_client.complete(settings, [ChatMessage("user", "hello")])

    assert not reply.ok
    assert reply.error == ai_client.REASON_UNREACHABLE


async def test_timeout_degrades_rather_than_raising(settings: Settings) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("too slow", request=request)

    _install(handler)
    reply = await ai_client.complete(settings, [ChatMessage("user", "hello")])

    assert not reply.ok
    assert reply.error == ai_client.REASON_TIMEOUT


async def test_http_error_degrades(settings: Settings) -> None:
    _install(lambda request: httpx.Response(500, text="model exploded"))

    reply = await ai_client.complete(settings, [ChatMessage("user", "hello")])

    assert not reply.ok
    assert reply.error == ai_client.REASON_BAD_RESPONSE


async def test_malformed_body_degrades(settings: Settings) -> None:
    """The host is a desktop app rather than a managed API. Assume nothing about the shape."""
    _install(lambda request: httpx.Response(200, json={"choices": "not a list"}))

    reply = await ai_client.complete(settings, [ChatMessage("user", "hello")])

    assert not reply.ok
    assert reply.error == ai_client.REASON_BAD_RESPONSE


async def test_empty_reply_is_a_failure_not_an_empty_bubble(settings: Settings) -> None:
    _install(lambda request: httpx.Response(200, json=_reply(content="   ")))

    reply = await ai_client.complete(settings, [ChatMessage("user", "hello")])

    assert not reply.ok
    assert reply.error == ai_client.REASON_EMPTY


async def test_breaker_opens_after_consecutive_failures(settings: Settings) -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise httpx.ConnectError("down", request=request)

    _install(handler)
    for _ in range(settings.ai_breaker_threshold):
        await ai_client.complete(settings, [ChatMessage("user", "hello")])

    reply = await ai_client.complete(settings, [ChatMessage("user", "hello")])

    assert reply.error == ai_client.REASON_BREAKER_OPEN
    # The whole point: the host is not called again while the breaker is open.
    assert calls == settings.ai_breaker_threshold


async def test_breaker_closes_after_the_cooldown(settings: Settings) -> None:
    """A wedged host that recovers must not stay locked out."""
    state = {"fail": True}

    def handler(request: httpx.Request) -> httpx.Response:
        if state["fail"]:
            raise httpx.ConnectError("down", request=request)
        return httpx.Response(200, json=_reply())

    _install(handler)
    hot = settings.model_copy(update={"ai_breaker_cooldown_seconds": 0})
    for _ in range(hot.ai_breaker_threshold):
        await ai_client.complete(hot, [ChatMessage("user", "hello")])

    state["fail"] = False
    reply = await ai_client.complete(hot, [ChatMessage("user", "hello")])

    assert reply.ok


async def test_empty_replies_do_not_trip_the_breaker(settings: Settings) -> None:
    """A model answering oddly is not a model that is down.

    Tripping here would take the feature offline for a minute over something
    that reconnecting cannot fix.
    """
    _install(lambda request: httpx.Response(200, json=_reply(content="")))

    for _ in range(settings.ai_breaker_threshold + 2):
        reply = await ai_client.complete(settings, [ChatMessage("user", "hello")])

    assert reply.error == ai_client.REASON_EMPTY


async def test_disabled_and_unconfigured_are_reported_distinctly(settings: Settings) -> None:
    off = settings.model_copy(update={"ai_enabled": False})
    assert (await ai_client.complete(off, [ChatMessage("user", "hi")])).error == "disabled"

    blank = settings.model_copy(update={"ai_base_url": None})
    assert (await ai_client.complete(blank, [ChatMessage("user", "hi")])).error == "unconfigured"


async def test_concurrency_ceiling_refuses_rather_than_queueing(settings: Settings) -> None:
    """Waiting behind a queue is a worse experience than being told to try again."""
    _install(lambda request: httpx.Response(200, json=_reply()))
    capped = settings.model_copy(update={"ai_max_concurrency": 0})

    reply = await ai_client.complete(capped, [ChatMessage("user", "hello")])

    assert reply.error == ai_client.REASON_BUSY


async def test_health_reports_reachability_and_breaker_state(settings: Settings) -> None:
    _install(lambda request: httpx.Response(200, json={"data": [{"id": "test-model"}]}))

    state = await ai_client.health(settings)

    assert state.reachable
    assert state.configured
    assert not state.breaker_open
    assert state.model == "test-model"


async def test_health_reports_an_unreachable_host_without_raising(settings: Settings) -> None:
    _install(_unreachable)

    state = await ai_client.health(settings)

    assert not state.reachable
    assert state.error
