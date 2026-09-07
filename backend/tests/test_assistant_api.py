"""The chat endpoints: the gate, degradation, and what never leaves the server (spec 010)."""

from collections.abc import AsyncIterator

import httpx
import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.models.assistant import AssistantMessage, MessageRole
from app.models.user import UserRole, UserStatus
from app.redis import get_redis
from app.services import ai_client
from app.services.rate_limit import check_assistant_limits
from tests.factories import make_challenge, make_user

pytestmark = pytest.mark.usefixtures("running_event")


@pytest.fixture(autouse=True)
async def clear_assistant_limits(settings: Settings) -> AsyncIterator[None]:
    """Counters live in Redis and outlive a rolled-back transaction."""
    redis = get_redis(settings)

    async def flush() -> None:
        keys = [key async for key in redis.scan_iter("ai:*")]
        if keys:
            await redis.delete(*keys)

    await flush()
    yield
    await flush()


def _reply(content: str = "Look to the packet comments.", **extra: object) -> dict:
    message: dict = {"role": "assistant", "content": content}
    message.update(extra)
    return {
        "model": "test-model",
        "choices": [{"index": 0, "message": message}],
        "usage": {"prompt_tokens": 100, "completion_tokens": 20},
    }


def _install(handler) -> None:  # noqa: ANN001 - test helper
    ai_client.use_transport(httpx.MockTransport(handler))


def _answers_with(payload: dict):  # noqa: ANN202 - test helper
    return lambda request: httpx.Response(200, json=payload)


def _reconfigure(app: FastAPI, **changes: object) -> None:
    """Routes read settings off app state, so this is the whole override."""
    app.state.settings = app.state.settings.model_copy(update=changes)


async def staff(db_session, client, sign_in):  # noqa: ANN001 - test helper
    user = await make_user(
        db_session, status=UserStatus.ACTIVE, role=UserRole.ORGANIZER, display_name="Keeper"
    )
    await sign_in(client, user)
    return user


async def player(db_session, client, sign_in):  # noqa: ANN001 - test helper
    user = await make_user(db_session, status=UserStatus.ACTIVE)
    await sign_in(client, user)
    return user


class TestTheGate:
    """Spec 010 ships staff-only; spec 011 opens it once the guardrails exist."""

    async def test_an_anonymous_visitor_is_refused(self, client: AsyncClient) -> None:
        assert (await client.get("/api/assistant/conversation")).status_code == 401

    @pytest.mark.parametrize(
        ("method", "path"),
        [
            ("GET", "/api/assistant/conversation"),
            ("POST", "/api/assistant/messages"),
            ("DELETE", "/api/assistant/conversation"),
            ("GET", "/api/admin/assistant/health"),
        ],
    )
    async def test_a_player_is_refused_until_the_guardrails_land(
        self, client: AsyncClient, db_session: AsyncSession, sign_in, method: str, path: str
    ) -> None:
        await player(db_session, client, sign_in)

        response = await client.request(method, path, json={"content": "hello"})

        assert response.status_code == 403


class TestConversing:
    async def test_staff_can_ask_and_receive_an_answer(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await staff(db_session, client, sign_in)
        _install(_answers_with(_reply()))

        response = await client.post(
            "/api/assistant/messages", json={"content": "Where do I start?"}
        )

        assert response.status_code == 200
        message = response.json()["message"]
        assert message["role"] == "assistant"
        assert message["content"] == "Look to the packet comments."
        assert message["error"] is None

    async def test_the_exchange_is_persisted_in_order(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await staff(db_session, client, sign_in)
        _install(_answers_with(_reply()))

        await client.post("/api/assistant/messages", json={"content": "first question"})
        messages = (await client.get("/api/assistant/conversation")).json()["messages"]

        assert [m["role"] for m in messages] == ["user", "assistant"]
        assert messages[0]["content"] == "first question"

    async def test_the_challenge_in_view_is_recorded(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await staff(db_session, client, sign_in)
        challenge = await make_challenge(db_session)
        _install(_answers_with(_reply()))

        response = await client.post(
            "/api/assistant/messages",
            json={"content": "any ideas?", "challenge_id": str(challenge.id)},
        )

        assert response.json()["message"]["challenge_id"] == str(challenge.id)

    async def test_clearing_starts_the_conversation_again(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await staff(db_session, client, sign_in)
        _install(_answers_with(_reply()))
        await client.post("/api/assistant/messages", json={"content": "hello"})

        assert (await client.delete("/api/assistant/conversation")).status_code == 204
        assert (await client.get("/api/assistant/conversation")).json()["messages"] == []

    async def test_an_overlong_message_is_refused_by_validation(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await staff(db_session, client, sign_in)

        response = await client.post("/api/assistant/messages", json={"content": "x" * 5000})

        assert response.status_code == 422


class TestWhatNeverLeavesTheServer:
    async def test_reasoning_is_stored_but_never_returned(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        """The scratchpad may contain the model reasoning aloud about a challenge."""
        await staff(db_session, client, sign_in)
        scratchpad = "Internally I suspect the flag is flag{do_not_say}."
        _install(_answers_with(_reply(reasoning_content=scratchpad)))

        response = await client.post("/api/assistant/messages", json={"content": "hint?"})
        conversation = await client.get("/api/assistant/conversation")

        assert "do_not_say" not in response.text
        assert "do_not_say" not in conversation.text

        stored = (
            (
                await db_session.execute(
                    select(AssistantMessage).where(AssistantMessage.role == MessageRole.ASSISTANT)
                )
            )
            .scalars()
            .all()
        )
        assert any(row.reasoning_content == scratchpad for row in stored)


class TestDegradation:
    async def test_an_unreachable_model_gives_an_answer_not_a_500(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await staff(db_session, client, sign_in)

        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("down", request=request)

        _install(handler)
        response = await client.post("/api/assistant/messages", json={"content": "hello"})

        assert response.status_code == 200
        message = response.json()["message"]
        assert message["error"] == ai_client.REASON_UNREACHABLE
        assert "dungeon master" in message["content"].lower()

    async def test_a_failed_exchange_is_still_recorded(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        """A conversation with a gap is harder to review later than one recording the silence."""
        await staff(db_session, client, sign_in)
        _install(_answers_with(_reply(content="")))

        await client.post("/api/assistant/messages", json={"content": "hello"})
        messages = (await client.get("/api/assistant/conversation")).json()["messages"]

        assert [m["role"] for m in messages] == ["user", "assistant"]
        assert messages[1]["error"] == ai_client.REASON_EMPTY

    async def test_an_unconfigured_assistant_reports_itself_unavailable(
        self, app: FastAPI, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await staff(db_session, client, sign_in)
        _reconfigure(app, ai_base_url=None)

        conversation = await client.get("/api/assistant/conversation")
        send = await client.post("/api/assistant/messages", json={"content": "hello"})

        assert conversation.json()["available"] is False
        assert send.status_code == 503
        assert send.json()["error"]["code"] == "assistant_unavailable"

    async def test_me_reports_whether_to_offer_the_chat(
        self, app: FastAPI, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await staff(db_session, client, sign_in)
        assert (await client.get("/api/auth/me")).json()["assistant_available"] is True

        _reconfigure(app, ai_enabled=False)
        assert (await client.get("/api/auth/me")).json()["assistant_available"] is False

    async def test_a_player_is_not_offered_the_chat_yet(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await player(db_session, client, sign_in)

        assert (await client.get("/api/auth/me")).json()["assistant_available"] is False


class TestLimits:
    async def test_a_burst_is_cut_off(
        self, app: FastAPI, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await staff(db_session, client, sign_in)
        _reconfigure(app, ai_messages_per_minute=2)
        _install(_answers_with(_reply()))

        statuses = [
            (await client.post("/api/assistant/messages", json={"content": "hello"})).status_code
            for _ in range(4)
        ]

        assert statuses[:2] == [200, 200]
        assert 429 in statuses

    async def test_the_hourly_limit_is_separate_from_the_minute_one(
        self, app: FastAPI, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await staff(db_session, client, sign_in)
        _reconfigure(app, ai_messages_per_minute=100, ai_messages_per_hour=2)
        _install(_answers_with(_reply()))

        statuses = [
            (await client.post("/api/assistant/messages", json={"content": "hello"})).status_code
            for _ in range(3)
        ]

        assert statuses == [200, 200, 429]

    async def test_the_limiter_fails_open(self) -> None:
        """Unlike submissions, which fail closed.

        The stakes decide it: here the worst case is somebody talking to a
        chatbot too often; there, it was the integrity of the scoreboard.
        """

        class BrokenRedis:
            async def incr(self, *_args: object) -> int:
                raise ConnectionError("redis is down")

        import uuid

        decision = await check_assistant_limits(BrokenRedis(), uuid.uuid4(), 6, 100)

        assert decision.allowed


class TestHealth:
    async def test_staff_see_reachability_and_breaker_state(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await staff(db_session, client, sign_in)
        _install(_answers_with({"data": [{"id": "test-model"}]}))

        body = (await client.get("/api/admin/assistant/health")).json()

        assert body["reachable"] is True
        assert body["breaker_open"] is False
        assert body["model"] == "test-model"

    async def test_an_unreachable_host_is_reported_not_raised(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await staff(db_session, client, sign_in)

        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("down", request=request)

        _install(handler)
        response = await client.get("/api/admin/assistant/health")

        assert response.status_code == 200
        assert response.json()["reachable"] is False
