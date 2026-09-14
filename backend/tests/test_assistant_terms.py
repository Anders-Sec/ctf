"""The System AI terms gate (spec 035).

The gate exists because spec 034 opens transcripts to admins, and that decision
rests on players knowing. So the properties that matter are: nobody reaches the
chat without accepting, a revised file re-gates everyone, and nobody can accept
wording they were never shown.
"""

import httpx
import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.models.assistant import TermsAcceptance
from app.models.user import UserRole, UserStatus
from app.redis import get_redis
from app.services import ai_client, assistant_terms
from tests.factories import make_ladder, make_user

pytestmark = [pytest.mark.anyio, pytest.mark.usefixtures("running_event")]

TERMS = "# Terms\n\nThis conversation is not private."


@pytest.fixture(autouse=True)
def _reset_terms_cache():
    assistant_terms.reset_cache()
    yield
    assistant_terms.reset_cache()


@pytest.fixture(autouse=True)
async def _ladder(db_session: AsyncSession):
    return await make_ladder(db_session)


@pytest.fixture(autouse=True)
async def _clear_ai_limits(settings: Settings):
    redis = get_redis(settings)
    keys = [key async for key in redis.scan_iter("ai:*")]
    if keys:
        await redis.delete(*keys)
    yield


@pytest.fixture
def terms_file(tmp_path, app):
    """A terms file this test controls, swapped in on the running app."""

    def write(text: str = TERMS):
        path = tmp_path / "terms.md"
        path.write_text(text, encoding="utf-8")
        app.state.settings = app.state.settings.model_copy(update={"ai_terms_path": str(path)})
        assistant_terms.reset_cache()
        return path

    return write


def _model_says(text: str = "A reply.") -> None:
    payload = {
        "model": "test-model",
        "choices": [{"index": 0, "message": {"role": "assistant", "content": text}}],
    }
    ai_client.use_transport(httpx.MockTransport(lambda request: httpx.Response(200, json=payload)))


async def _sign_in_player(db_session, client, sign_in, **kwargs):
    """Signed in but **not** accepted — this module is what tests the gate."""
    user = await make_user(db_session, status=UserStatus.ACTIVE, **kwargs)
    await sign_in(client, user, accept_terms=False)
    return user


class TestTheGate:
    async def test_an_unaccepted_player_cannot_read_the_conversation(
        self, client: AsyncClient, db_session: AsyncSession, sign_in, terms_file
    ) -> None:
        terms_file()
        await _sign_in_player(db_session, client, sign_in)

        response = await client.get("/api/assistant/conversation")

        assert response.status_code == 403
        assert response.json()["error"]["code"] == "assistant_terms_required"

    async def test_an_unaccepted_player_cannot_send(
        self, client: AsyncClient, db_session: AsyncSession, sign_in, terms_file
    ) -> None:
        """Gated on every chat endpoint, not only the one that spends a model call."""
        terms_file()
        await _sign_in_player(db_session, client, sign_in)
        _model_says()

        response = await client.post("/api/assistant/messages", json={"content": "hello"})

        assert response.status_code == 403
        assert response.json()["error"]["code"] == "assistant_terms_required"

    async def test_accepting_opens_the_chat(
        self, client: AsyncClient, db_session: AsyncSession, sign_in, terms_file
    ) -> None:
        terms_file()
        await _sign_in_player(db_session, client, sign_in)
        version = (await client.get("/api/assistant/terms")).json()["version"]

        accepted = await client.post("/api/assistant/terms/accept", json={"version": version})

        assert accepted.status_code == 200
        assert accepted.json()["accepted"] is True
        assert (await client.get("/api/assistant/conversation")).status_code == 200

    async def test_staff_are_gated_too(
        self, client: AsyncClient, db_session: AsyncSession, sign_in, terms_file
    ) -> None:
        """They are the ones who will be reading transcripts."""
        terms_file()
        await _sign_in_player(db_session, client, sign_in, role=UserRole.ADMIN)

        response = await client.get("/api/assistant/conversation")

        assert response.json()["error"]["code"] == "assistant_terms_required"

    async def test_the_block_takes_precedence_over_the_terms(
        self, client: AsyncClient, db_session: AsyncSession, sign_in, terms_file
    ) -> None:
        """A blocked player should be told they are blocked, not asked to accept
        terms that would not help them."""
        terms_file()
        user = await _sign_in_player(db_session, client, sign_in)
        user.assistant_blocked = True
        await db_session.flush()

        response = await client.get("/api/assistant/conversation")

        assert response.json()["error"]["code"] == "assistant_blocked"


class TestVersioning:
    async def test_the_version_is_the_hash_of_the_file(
        self, client: AsyncClient, db_session: AsyncSession, sign_in, terms_file
    ) -> None:
        terms_file()
        await _sign_in_player(db_session, client, sign_in)

        first = (await client.get("/api/assistant/terms")).json()
        terms_file(TERMS + "\n\nAnd one more thing.")
        second = (await client.get("/api/assistant/terms")).json()

        assert first["version"] != second["version"]
        assert "one more thing" in second["text"]

    async def test_a_revised_file_re_gates_an_accepted_player(
        self, client: AsyncClient, db_session: AsyncSession, sign_in, terms_file
    ) -> None:
        """Their acceptance was to different words. That is the point of hashing
        the file rather than maintaining a number."""
        terms_file()
        await _sign_in_player(db_session, client, sign_in)
        version = (await client.get("/api/assistant/terms")).json()["version"]
        await client.post("/api/assistant/terms/accept", json={"version": version})
        assert (await client.get("/api/assistant/conversation")).status_code == 200

        terms_file(TERMS + "\n\nRevised.")

        response = await client.get("/api/assistant/conversation")
        assert response.json()["error"]["code"] == "assistant_terms_required"

    async def test_accepting_a_stale_version_is_refused(
        self, client: AsyncClient, db_session: AsyncSession, sign_in, terms_file
    ) -> None:
        """Otherwise a player accepts wording they were never displayed, which is
        the one failure that would make the record worthless."""
        terms_file()
        await _sign_in_player(db_session, client, sign_in)
        stale = (await client.get("/api/assistant/terms")).json()["version"]
        terms_file(TERMS + "\n\nRevised between load and click.")

        response = await client.post("/api/assistant/terms/accept", json={"version": stale})

        assert response.status_code == 409
        assert response.json()["error"]["code"] == "assistant_terms_stale"

    async def test_accepting_twice_is_not_an_error(
        self, client: AsyncClient, db_session: AsyncSession, sign_in, terms_file
    ) -> None:
        """Two tabs."""
        terms_file()
        user = await _sign_in_player(db_session, client, sign_in)
        version = (await client.get("/api/assistant/terms")).json()["version"]

        await client.post("/api/assistant/terms/accept", json={"version": version})
        second = await client.post("/api/assistant/terms/accept", json={"version": version})

        assert second.status_code == 200
        rows = (
            (
                await db_session.execute(
                    select(TermsAcceptance).where(TermsAcceptance.user_id == user.id)
                )
            )
            .scalars()
            .all()
        )
        assert len(rows) == 1

    async def test_an_old_acceptance_survives_a_revision(
        self, client: AsyncClient, db_session: AsyncSession, sign_in, terms_file
    ) -> None:
        """The record is what they accepted and when, across revisions — which is
        the question a consent record gets asked."""
        terms_file()
        user = await _sign_in_player(db_session, client, sign_in)
        first = (await client.get("/api/assistant/terms")).json()["version"]
        await client.post("/api/assistant/terms/accept", json={"version": first})

        terms_file(TERMS + "\n\nRevised.")
        second = (await client.get("/api/assistant/terms")).json()["version"]
        await client.post("/api/assistant/terms/accept", json={"version": second})

        rows = (
            (
                await db_session.execute(
                    select(TermsAcceptance).where(TermsAcceptance.user_id == user.id)
                )
            )
            .scalars()
            .all()
        )
        assert {row.version for row in rows} == {first, second}


class TestMissingFile:
    async def test_a_missing_file_makes_the_assistant_unavailable_not_open(
        self, client: AsyncClient, db_session: AsyncSession, sign_in, app, tmp_path
    ) -> None:
        """A terms gate that fails open is not a terms gate."""
        app.state.settings = app.state.settings.model_copy(
            update={"ai_terms_path": str(tmp_path / "does-not-exist.md")}
        )
        assistant_terms.reset_cache()
        await _sign_in_player(db_session, client, sign_in)

        response = await client.get("/api/assistant/conversation")

        assert response.status_code == 503
        assert response.json()["error"]["code"] == "assistant_terms_unavailable"

    async def test_an_empty_file_is_treated_as_missing(
        self, client: AsyncClient, db_session: AsyncSession, sign_in, terms_file
    ) -> None:
        terms_file("   \n  ")
        await _sign_in_player(db_session, client, sign_in)

        assert (await client.get("/api/assistant/conversation")).status_code == 503

    async def test_auth_me_still_answers(
        self, client: AsyncClient, db_session: AsyncSession, sign_in, app, tmp_path
    ) -> None:
        """/auth/me is what the whole SPA boots on; one misconfigured feature
        must not take it down."""
        app.state.settings = app.state.settings.model_copy(
            update={"ai_terms_path": str(tmp_path / "gone.md")}
        )
        assistant_terms.reset_cache()
        await _sign_in_player(db_session, client, sign_in)

        response = await client.get("/api/auth/me")

        assert response.status_code == 200
        assert response.json()["assistant_terms_accepted"] is False


class TestAuthMe:
    async def test_it_reports_acceptance(
        self, client: AsyncClient, db_session: AsyncSession, sign_in, terms_file
    ) -> None:
        """Known on load, so the first thing a player sees is not a failed send."""
        terms_file()
        await _sign_in_player(db_session, client, sign_in)

        assert (await client.get("/api/auth/me")).json()["assistant_terms_accepted"] is False

        version = (await client.get("/api/assistant/terms")).json()["version"]
        await client.post("/api/assistant/terms/accept", json={"version": version})

        assert (await client.get("/api/auth/me")).json()["assistant_terms_accepted"] is True


class TestAdminSummary:
    async def test_it_counts_acceptances_of_the_live_version(
        self, client: AsyncClient, db_session: AsyncSession, sign_in, terms_file
    ) -> None:
        terms_file()
        await _sign_in_player(db_session, client, sign_in, role=UserRole.ADMIN)
        version = (await client.get("/api/assistant/terms")).json()["version"]
        await client.post("/api/assistant/terms/accept", json={"version": version})

        body = (await client.get("/api/admin/assistant/terms")).json()

        assert body["version"] == version
        assert body["accepted"] == 1
        assert body["outstanding_names"] is None  # not unless asked

    async def test_names_are_available_on_request(
        self, client: AsyncClient, db_session: AsyncSession, sign_in, terms_file
    ) -> None:
        terms_file()
        await make_user(db_session, status=UserStatus.ACTIVE, display_name="Unaccepting")
        await _sign_in_player(db_session, client, sign_in, role=UserRole.ADMIN)

        body = (await client.get("/api/admin/assistant/terms?include_names=true")).json()

        assert "Unaccepting" in body["outstanding_names"]

    async def test_a_player_cannot_read_it(
        self, client: AsyncClient, db_session: AsyncSession, sign_in, terms_file
    ) -> None:
        terms_file()
        await _sign_in_player(db_session, client, sign_in)

        assert (await client.get("/api/admin/assistant/terms")).status_code == 403


class TestRetention:
    async def test_acceptance_survives_a_conversation_purge(
        self, client: AsyncClient, db_session: AsyncSession, sign_in, terms_file, settings
    ) -> None:
        """Deleting the record of consent along with the conversations it covered
        would be the wrong way round."""
        from app.services import assistant_review as review

        terms_file()
        user = await _sign_in_player(db_session, client, sign_in)
        version = (await client.get("/api/assistant/terms")).json()["version"]
        await client.post("/api/assistant/terms/accept", json={"version": version})

        await review.purge_expired(db_session, retention_days=0)

        assert await assistant_terms.has_accepted(db_session, user.id, version)
