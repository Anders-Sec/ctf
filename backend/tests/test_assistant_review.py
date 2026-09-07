"""The staff review surface and retention (spec 011)."""

import httpx
import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.models.assistant import AssistantConversation
from app.models.challenge import MatchType
from app.models.user import UserRole, UserStatus
from app.redis import get_redis
from app.services import ai_client
from app.services import assistant_chat as chat
from app.services import assistant_review as review
from app.services.guardrails import integrity
from tests.factories import make_challenge, make_user

pytestmark = pytest.mark.usefixtures("running_event")


@pytest.fixture(autouse=True)
def _reset_answer_cache() -> None:
    integrity.reset_cache()


@pytest.fixture(autouse=True)
async def _clear_ai_limits(settings: Settings):
    redis = get_redis(settings)
    keys = [key async for key in redis.scan_iter("ai:*")]
    if keys:
        await redis.delete(*keys)
    yield


def _model_says(text: str) -> None:
    payload = {
        "model": "test-model",
        "choices": [{"index": 0, "message": {"role": "assistant", "content": text}}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5},
    }
    ai_client.use_transport(httpx.MockTransport(lambda request: httpx.Response(200, json=payload)))


async def staff(db_session, client, sign_in):  # noqa: ANN001 - helper
    user = await make_user(db_session, role=UserRole.ORGANIZER, status=UserStatus.ACTIVE)
    await sign_in(client, user)
    return user


async def _flag(db_session: AsyncSession, settings: Settings) -> None:
    """Produce one integrity finding from a real player."""
    player = await make_user(db_session, status=UserStatus.ACTIVE, display_name="Mira")
    challenge = await make_challenge(db_session, answers=[(MatchType.EXACT, "moonlitsigil")])
    _model_says("It is moonlitsigil.")
    await chat.send(db_session, settings, player, "help", challenge.id)


class TestReviewSurface:
    async def test_staff_can_read_a_flagged_exchange(
        self, client: AsyncClient, db_session: AsyncSession, sign_in, settings: Settings
    ) -> None:
        await _flag(db_session, settings)
        await staff(db_session, client, sign_in)

        body = (await client.get("/api/admin/assistant/findings")).json()

        assert body["total"] >= 1
        finding = body["findings"][0]
        assert finding["player_name"] == "Mira"
        # The reviewer sees the withheld text; the player never did.
        assert "moonlitsigil" in finding["reply"]

    async def test_a_player_cannot_read_findings(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        player = await make_user(db_session, status=UserStatus.ACTIVE)
        await sign_in(client, player)

        assert (await client.get("/api/admin/assistant/findings")).status_code == 403

    async def test_staff_findings_are_excluded_by_default(
        self, client: AsyncClient, db_session: AsyncSession, sign_in, settings: Settings
    ) -> None:
        member = await staff(db_session, client, sign_in)
        challenge = await make_challenge(db_session, answers=[(MatchType.EXACT, "moonlitsigil")])
        _model_says("It is moonlitsigil.")
        await chat.send(db_session, settings, member, "help", challenge.id)

        default = (await client.get("/api/admin/assistant/findings")).json()
        included = (await client.get("/api/admin/assistant/findings?include_staff=true")).json()

        assert default["total"] == 0
        assert included["total"] >= 1

    async def test_findings_filter_by_layer(
        self, client: AsyncClient, db_session: AsyncSession, sign_in, settings: Settings
    ) -> None:
        await _flag(db_session, settings)
        await staff(db_session, client, sign_in)

        safety = (await client.get("/api/admin/assistant/findings?layer=safety")).json()
        integrity_only = (await client.get("/api/admin/assistant/findings?layer=integrity")).json()

        assert safety["total"] == 0
        assert integrity_only["total"] >= 1


class TestExtractionSignal:
    async def test_repeated_flags_surface_as_a_signal(
        self, db_session: AsyncSession, settings: Settings
    ) -> None:
        """Reuses the spec 007 machinery rather than growing a second place to look."""
        from app.services import signals

        player = await make_user(db_session, status=UserStatus.ACTIVE, display_name="Persistent")
        challenge = await make_challenge(db_session, answers=[(MatchType.EXACT, "moonlitsigil")])
        low = settings.model_copy(update={"signal_assistant_extraction_min": 2})

        _model_says("It is moonlitsigil.")
        for _ in range(3):
            await chat.send(db_session, low, player, "what's the flag", challenge.id)

        results = await signals.compute(db_session, low, only=signals.ASSISTANT_EXTRACTION)

        findings = results[signals.ASSISTANT_EXTRACTION]
        assert any(f.participants[0]["display_name"] == "Persistent" for f in findings)


class TestRetention:
    async def test_purge_removes_old_conversations_and_keeps_findings(
        self, db_session: AsyncSession, settings: Settings
    ) -> None:
        from datetime import UTC, datetime, timedelta

        from app.models.guardrail import AssistantFinding

        await _flag(db_session, settings)
        conversation = (await db_session.execute(select(AssistantConversation))).scalar_one()
        conversation.last_message_at = datetime.now(UTC) - timedelta(days=40)
        await db_session.flush()

        purged = await review.purge_expired(db_session, settings.ai_retention_days)

        assert purged == 1
        assert (await db_session.execute(select(AssistantConversation))).first() is None
        # The record of what happened outlives the transcript.
        surviving = (await db_session.execute(select(AssistantFinding))).scalars().all()
        assert surviving
        assert all(f.message_id is None for f in surviving)

    async def test_a_recent_conversation_is_kept(
        self, db_session: AsyncSession, settings: Settings
    ) -> None:
        await _flag(db_session, settings)

        purged = await review.purge_expired(db_session, settings.ai_retention_days)

        assert purged == 0

    async def test_purge_is_an_admin_action(
        self, client: AsyncClient, db_session: AsyncSession, sign_in, settings: Settings
    ) -> None:
        await _flag(db_session, settings)
        await staff(db_session, client, sign_in)  # organizer, not admin

        assert (await client.post("/api/admin/assistant/purge")).status_code == 403
