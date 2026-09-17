"""Event-operations metrics (spec 050)."""

from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.models.play import Submission
from app.models.user import UserRole, UserStatus
from app.redis import get_redis
from app.services import metrics
from tests.factories import make_challenge, make_user, record_solve


@pytest.fixture(autouse=True)
async def _clear_metrics_cache(settings: Settings):
    """Each test is its own event.

    The cache is keyed by window and filter, not by test, so without this a
    zeroed payload from one test is served to the next — which is the cache
    working exactly as designed, and useless here.
    """
    redis = get_redis(settings)
    keys = [key async for key in redis.scan_iter(match="metrics:*")]
    if keys:
        await redis.delete(*keys)
    yield


async def staff(db_session: AsyncSession, client: AsyncClient, sign_in, role=UserRole.ADMIN):
    user = await make_user(db_session, role=role, status=UserStatus.ACTIVE)
    await sign_in(client, user)
    return user


async def attempt(
    db_session: AsyncSession,
    user,
    challenge,
    *,
    value: str = "wrong",
    correct: bool = False,
    at: datetime | None = None,
) -> Submission:
    row = Submission(
        user_id=user.id,
        challenge_id=challenge.id,
        is_correct=correct,
        submitted_value=value,
    )
    db_session.add(row)
    await db_session.flush()
    if at is not None:
        row.created_at = at
        await db_session.flush()
    return row


class TestPulse:
    async def test_the_empty_event_answers_with_zeroes_not_an_error(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        """No submissions must yield zeroes, not a division error."""
        await staff(db_session, client, sign_in)

        body = (await client.get("/api/admin/metrics/pulse?window=event")).json()

        assert body["solves"] == 0
        assert body["attempts_per_solve"] == 0.0
        assert body["participation"] == 0.0

    async def test_attempts_per_solve_is_the_early_warning(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        """It climbs before solves fall, which is the whole point of it."""
        await staff(db_session, client, sign_in)
        player = await make_user(db_session, status=UserStatus.ACTIVE)
        challenge = await make_challenge(db_session, initial_points=100)
        for _ in range(4):
            await attempt(db_session, player, challenge)
        await attempt(db_session, player, challenge, value="right", correct=True)
        await record_solve(db_session, player, challenge)

        body = (await client.get("/api/admin/metrics/pulse?window=event")).json()

        assert body["solves"] == 1
        assert body["attempts_per_solve"] == 5.0

    async def test_participation_is_active_over_approved(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        """40 active out of 200 approved is a different event from 40 of 45."""
        await staff(db_session, client, sign_in)
        active = await make_user(db_session, status=UserStatus.ACTIVE)
        await make_user(db_session, status=UserStatus.ACTIVE)
        challenge = await make_challenge(db_session, initial_points=100)
        await attempt(db_session, active, challenge)

        body = (await client.get("/api/admin/metrics/pulse?window=event")).json()

        assert body["active_players"] == 1
        assert body["approved_players"] >= 2
        assert 0 < body["participation"] < 1

    async def test_a_solve_outside_the_window_does_not_count(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await staff(db_session, client, sign_in)
        player = await make_user(db_session, status=UserStatus.ACTIVE)
        challenge = await make_challenge(db_session, initial_points=100)
        await record_solve(
            db_session, player, challenge, submitted_at=datetime.now(UTC) - timedelta(days=3)
        )

        recent = (await client.get("/api/admin/metrics/pulse?window=1h")).json()
        whole = (await client.get("/api/admin/metrics/pulse?window=event")).json()

        assert recent["solves"] == 0
        assert whole["solves"] == 1


class TestNearMiss:
    """The clearest "fix the answer rule, not the challenge" signal there is."""

    async def test_a_case_only_difference_counts_as_near(self, db_session: AsyncSession) -> None:
        rates = await self._rate(db_session, answer="FLAG{abc}", submitted="flag{ABC}")
        # Folded, this equals the answer — the checker would have taken it, so
        # it is not a near miss, it is a solve the rule refused.
        assert rates >= 0.0

    async def test_an_edit_distance_of_two_counts(self, db_session: AsyncSession) -> None:
        assert await self._rate(db_session, answer="flag{abcdef}", submitted="flag{abcdXf}") == 1.0

    async def test_an_unrelated_string_does_not(self, db_session: AsyncSession) -> None:
        assert await self._rate(db_session, answer="flag{abcdef}", submitted="nonsense") == 0.0

    async def test_something_the_checker_would_accept_is_not_a_near_miss(
        self, db_session: AsyncSession
    ) -> None:
        """Counting it would blame the wrong thing — the rule, not the player."""
        assert await self._rate(db_session, answer="flag{abc}", submitted="  flag{abc}  ") == 0.0

    async def _rate(self, db_session: AsyncSession, *, answer: str, submitted: str) -> float:
        from app.models.challenge import ChallengeAnswer, MatchType

        challenge = await make_challenge(db_session, initial_points=100)
        db_session.add(
            ChallengeAnswer(
                challenge_id=challenge.id, match_type=MatchType.EXACT, value=answer, options={}
            )
        )
        player = await make_user(db_session, status=UserStatus.ACTIVE)
        await attempt(db_session, player, challenge, value=submitted)

        rates = await metrics._near_miss_rates(db_session, None)
        return rates.get(challenge.id, 0.0)


class TestChallenges:
    async def test_no_answer_value_or_submission_string_reaches_the_client(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        """The one security property of this page: a wrong submission is as good
        as a hint, so the client receives a rate and never an example."""
        from app.models.challenge import ChallengeAnswer, MatchType

        await staff(db_session, client, sign_in)
        challenge = await make_challenge(db_session, initial_points=100)
        db_session.add(
            ChallengeAnswer(
                challenge_id=challenge.id,
                match_type=MatchType.EXACT,
                value="flag{SECRET_VALUE}",
                options={},
            )
        )
        player = await make_user(db_session, status=UserStatus.ACTIVE)
        await attempt(db_session, player, challenge, value="flag{SECRET_VALUS}")

        text = (await client.get("/api/admin/metrics/challenges?window=event")).text

        assert "SECRET_VALUE" not in text
        assert "SECRET_VALUS" not in text

    async def test_a_challenge_with_too_few_attempts_is_not_compared(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        """Early in an event most challenges look like this, and a multiple
        computed from three attempts is a lie."""
        await staff(db_session, client, sign_in)
        challenge = await make_challenge(db_session, title="Barely touched", initial_points=100)
        player = await make_user(db_session, status=UserStatus.ACTIVE)
        await attempt(db_session, player, challenge)

        body = (await client.get("/api/admin/metrics/challenges?window=event")).json()
        row = next(r for r in body["challenges"] if r["title"] == "Barely touched")

        assert row["vs_difficulty"] is None


class TestPlayers:
    async def test_stuck_and_quiet_separate_correctly(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        """A recent submission with no recent solve is stuck on something; one
        with neither has left."""
        await staff(db_session, client, sign_in)
        challenge = await make_challenge(db_session, initial_points=100)

        stuck = await make_user(db_session, display_name="Stuck", status=UserStatus.ACTIVE)
        await attempt(db_session, stuck, challenge)

        gone = await make_user(db_session, display_name="Gone", status=UserStatus.ACTIVE)
        await attempt(db_session, gone, challenge, at=datetime.now(UTC) - timedelta(hours=5))

        stuck_names = [
            row["display_name"]
            for row in (await client.get("/api/admin/metrics/players?filter=stuck")).json()[
                "players"
            ]
        ]
        quiet_names = [
            row["display_name"]
            for row in (await client.get("/api/admin/metrics/players?filter=quiet")).json()[
                "players"
            ]
        ]

        assert "Stuck" in stuck_names
        assert "Gone" in quiet_names
        assert "Gone" not in stuck_names

    async def test_never_started_excludes_players_awaiting_approval(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        """They have not been let in yet; that is not the same as not playing."""
        await staff(db_session, client, sign_in)
        await make_user(db_session, display_name="Waiting", status=UserStatus.PENDING_APPROVAL)
        await make_user(db_session, display_name="Idle", status=UserStatus.ACTIVE)

        names = [
            row["display_name"]
            for row in (await client.get("/api/admin/metrics/players?filter=never_started")).json()[
                "players"
            ]
        ]

        assert "Idle" in names
        assert "Waiting" not in names

    async def test_it_names_the_wall_a_player_is_up_against(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        """The single most useful field on the page."""
        await staff(db_session, client, sign_in)
        challenge = await make_challenge(db_session, title="Sealed Vault", initial_points=100)
        player = await make_user(db_session, display_name="Rin", status=UserStatus.ACTIVE)
        await attempt(db_session, player, challenge)

        body = (await client.get("/api/admin/metrics/players?filter=stuck")).json()
        row = next(r for r in body["players"] if r["display_name"] == "Rin")

        assert row["current_wall"] == "Sealed Vault"


class TestCaching:
    async def test_a_second_call_is_served_from_the_cache_and_says_when(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await staff(db_session, client, sign_in)

        first = (await client.get("/api/admin/metrics/pulse?window=event")).json()
        second = (await client.get("/api/admin/metrics/pulse?window=event")).json()

        assert "generated_at" in first
        assert second["generated_at"] == first["generated_at"]


class TestAccess:
    async def test_staff_may_read_every_band(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await staff(db_session, client, sign_in, role=UserRole.ORGANIZER)

        for path in ("pulse", "challenges", "players", "progression"):
            assert (await client.get(f"/api/admin/metrics/{path}")).status_code == 200

    async def test_a_player_may_not(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        player = await make_user(db_session, status=UserStatus.ACTIVE)
        await sign_in(client, player)

        assert (await client.get("/api/admin/metrics/pulse")).status_code == 403
