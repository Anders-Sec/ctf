"""Challenge visibility and answer submission over HTTP (spec 003)."""

from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.challenge import (
    ChallengeState,
    MatchType,
    PreReleaseState,
    ScoringMode,
)
from app.models.play import Solve, Submission
from app.models.user import UserStatus
from tests.factories import make_challenge, make_user, record_solve

pytestmark = pytest.mark.usefixtures("running_event")


async def player(db_session, client, sign_in, **kwargs):
    kwargs.setdefault("status", UserStatus.ACTIVE)
    user = await make_user(db_session, **kwargs)
    await sign_in(client, user)
    return user


class TestTheGate:
    async def test_an_anonymous_visitor_sees_nothing(self, client: AsyncClient) -> None:
        assert (await client.get("/api/challenges")).status_code == 401

    async def test_a_pending_guest_cannot_play(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await player(db_session, client, sign_in, status=UserStatus.PENDING_APPROVAL)
        await make_challenge(db_session)

        response = await client.get("/api/challenges")

        assert response.status_code == 403
        assert response.json()["error"]["code"] == "account_pending_approval"

    async def test_nobody_plays_before_the_doors_open(
        self, client: AsyncClient, db_session: AsyncSession, sign_in, running_event
    ) -> None:
        running_event.starts_at = datetime.now(UTC) + timedelta(hours=1)
        await db_session.flush()
        await player(db_session, client, sign_in)

        response = await client.get("/api/challenges")

        assert response.status_code == 403
        assert response.json()["error"]["code"] == "event_not_started"


class TestVisibility:
    async def test_published_challenges_are_listed(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await player(db_session, client, sign_in)
        await make_challenge(db_session, title="Open Door", state=ChallengeState.PUBLISHED)

        titles = [c["title"] for c in (await client.get("/api/challenges")).json()]

        assert "Open Door" in titles

    @pytest.mark.parametrize("state", [ChallengeState.DRAFT, ChallengeState.HIDDEN])
    async def test_drafts_and_hidden_challenges_are_invisible(
        self, client: AsyncClient, db_session: AsyncSession, sign_in, state: ChallengeState
    ) -> None:
        await player(db_session, client, sign_in)
        await make_challenge(db_session, title="Not Yours", state=state)

        titles = [c["title"] for c in (await client.get("/api/challenges")).json()]

        assert "Not Yours" not in titles

    @pytest.mark.parametrize("state", [ChallengeState.DRAFT, ChallengeState.HIDDEN])
    async def test_direct_access_404s_rather_than_403s(
        self, client: AsyncClient, db_session: AsyncSession, sign_in, state: ChallengeState
    ) -> None:
        """A 403 would confirm the id is real — an oracle for guessing what is coming."""
        await player(db_session, client, sign_in)
        challenge = await make_challenge(db_session, state=state)

        assert (await client.get(f"/api/challenges/{challenge.id}")).status_code == 404

    async def test_a_locked_challenge_shows_its_name_and_value(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await player(db_session, client, sign_in)
        await make_challenge(
            db_session, title="Coming Tonight", state=ChallengeState.LOCKED, initial_points=300
        )

        row = next(
            c
            for c in (await client.get("/api/challenges")).json()
            if c["title"] == "Coming Tonight"
        )

        assert row["locked"] is True
        assert row["value"] == 300

    async def test_a_locked_challenge_never_sends_its_body(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        """Withheld server-side. The client is not trusted to hide it."""
        await player(db_session, client, sign_in)
        challenge = await make_challenge(
            db_session,
            state=ChallengeState.LOCKED,
            body="THE SECRET QUESTION",
        )

        response = await client.get(f"/api/challenges/{challenge.id}")

        assert response.status_code == 200
        assert response.json()["body"] is None
        assert "THE SECRET QUESTION" not in response.text

    async def test_a_published_challenge_sends_its_body(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await player(db_session, client, sign_in)
        challenge = await make_challenge(db_session, body="Find the flag in the pcap.")

        body = (await client.get(f"/api/challenges/{challenge.id}")).json()

        assert body["body"] == "Find the flag in the pcap."


class TestScheduledRelease:
    async def test_a_future_release_hides_the_challenge_by_default(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await player(db_session, client, sign_in)
        await make_challenge(
            db_session,
            title="Tomorrow",
            state=ChallengeState.PUBLISHED,
            release_at=datetime.now(UTC) + timedelta(hours=2),
        )

        titles = [c["title"] for c in (await client.get("/api/challenges")).json()]

        assert "Tomorrow" not in titles

    async def test_it_can_instead_appear_locked_before_release(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        """A wave can advertise itself without leaking its questions."""
        await player(db_session, client, sign_in)
        await make_challenge(
            db_session,
            title="Tonight",
            state=ChallengeState.PUBLISHED,
            release_at=datetime.now(UTC) + timedelta(hours=2),
            pre_release_state=PreReleaseState.LOCKED,
        )

        row = next(
            c for c in (await client.get("/api/challenges")).json() if c["title"] == "Tonight"
        )

        assert row["locked"] is True

    async def test_a_past_release_opens_the_challenge(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await player(db_session, client, sign_in)
        challenge = await make_challenge(
            db_session,
            state=ChallengeState.PUBLISHED,
            release_at=datetime.now(UTC) - timedelta(minutes=1),
        )

        assert (await client.get(f"/api/challenges/{challenge.id}")).json()["locked"] is False

    async def test_a_draft_never_releases_on_a_timer(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        """An unfinished challenge going live at 09:00 is exactly the accident to avoid."""
        await player(db_session, client, sign_in)
        challenge = await make_challenge(
            db_session,
            state=ChallengeState.DRAFT,
            release_at=datetime.now(UTC) - timedelta(hours=1),
        )

        assert (await client.get(f"/api/challenges/{challenge.id}")).status_code == 404


class TestSubmission:
    async def test_a_correct_answer_awards_points(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await player(db_session, client, sign_in)
        challenge = await make_challenge(db_session, scoring=ScoringMode.STATIC, initial_points=250)

        response = await client.post(
            f"/api/challenges/{challenge.id}/submit", json={"answer": "flag{correct}"}
        )

        assert response.status_code == 200
        body = response.json()
        assert body["correct"] is True
        assert body["points_awarded"] == 250

    async def test_a_wrong_answer_awards_nothing(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await player(db_session, client, sign_in)
        challenge = await make_challenge(db_session)

        body = (
            await client.post(
                f"/api/challenges/{challenge.id}/submit", json={"answer": "flag{nope}"}
            )
        ).json()

        assert body["correct"] is False
        assert body["points_awarded"] == 0

    async def test_a_regex_answer_works_end_to_end(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        """The capability this platform exists for."""
        await player(db_session, client, sign_in)
        challenge = await make_challenge(
            db_session, answers=[(MatchType.REGEX, r"flag\{[0-9a-f]{8}\}")]
        )

        good = await client.post(
            f"/api/challenges/{challenge.id}/submit", json={"answer": "flag{deadbeef}"}
        )
        bad = await client.post(
            f"/api/challenges/{challenge.id}/submit", json={"answer": "flag{xyz}"}
        )

        assert good.json()["correct"] is True
        assert bad.json()["correct"] is False

    async def test_every_attempt_is_logged(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        user = await player(db_session, client, sign_in)
        challenge = await make_challenge(db_session)

        await client.post(f"/api/challenges/{challenge.id}/submit", json={"answer": "wrong one"})
        await client.post(
            f"/api/challenges/{challenge.id}/submit", json={"answer": "flag{correct}"}
        )

        rows = (
            (
                await db_session.execute(
                    select(Submission)
                    .where(Submission.user_id == user.id)
                    .order_by(Submission.created_at)
                )
            )
            .scalars()
            .all()
        )
        assert [r.is_correct for r in rows] == [False, True]
        # The exact text is what makes duplicate-submission detection possible.
        assert rows[0].submitted_value == "wrong one"
        assert rows[0].request_id is not None

    async def test_solving_twice_does_not_award_twice(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        """Players do re-submit to check."""
        user = await player(db_session, client, sign_in)
        challenge = await make_challenge(db_session)
        payload = {"answer": "flag{correct}"}

        first = await client.post(f"/api/challenges/{challenge.id}/submit", json=payload)
        second = await client.post(f"/api/challenges/{challenge.id}/submit", json=payload)

        assert first.json()["points_awarded"] > 0
        assert second.json()["already_solved"] is True
        assert second.json()["points_awarded"] == 0

        solves = (
            (
                await db_session.execute(
                    select(Solve).where(
                        Solve.user_id == user.id, Solve.challenge_id == challenge.id
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(solves) == 1

    async def test_a_solve_records_the_party_of_the_moment(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        """History for the team-basis curve and for spec 007 — not ownership."""
        from tests.factories import make_team

        user = await player(db_session, client, sign_in)
        team = await make_team(db_session, user)
        challenge = await make_challenge(db_session)

        await client.post(
            f"/api/challenges/{challenge.id}/submit", json={"answer": "flag{correct}"}
        )

        solve = (
            await db_session.execute(select(Solve).where(Solve.user_id == user.id))
        ).scalar_one()
        assert solve.team_id_at_solve == team.id

    async def test_a_locked_challenge_refuses_submissions(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await player(db_session, client, sign_in)
        challenge = await make_challenge(db_session, state=ChallengeState.LOCKED)

        response = await client.post(
            f"/api/challenges/{challenge.id}/submit", json={"answer": "flag{correct}"}
        )

        assert response.status_code == 403
        assert response.json()["error"]["code"] == "challenge_locked"

    async def test_probing_a_locked_challenge_is_still_logged(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        """Worth seeing in spec 007."""
        user = await player(db_session, client, sign_in)
        challenge = await make_challenge(db_session, state=ChallengeState.LOCKED)

        await client.post(
            f"/api/challenges/{challenge.id}/submit", json={"answer": "flag{correct}"}
        )

        count = len(
            (await db_session.execute(select(Submission).where(Submission.user_id == user.id)))
            .scalars()
            .all()
        )
        assert count == 1

    async def test_submitting_to_a_hidden_challenge_404s(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await player(db_session, client, sign_in)
        challenge = await make_challenge(db_session, state=ChallengeState.HIDDEN)

        response = await client.post(
            f"/api/challenges/{challenge.id}/submit", json={"answer": "flag{correct}"}
        )

        assert response.status_code == 404

    async def test_an_empty_answer_is_rejected(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await player(db_session, client, sign_in)
        challenge = await make_challenge(db_session)

        response = await client.post(f"/api/challenges/{challenge.id}/submit", json={"answer": ""})

        assert response.status_code == 422


class TestAttemptCaps:
    async def test_attempts_are_unlimited_by_default(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await player(db_session, client, sign_in)
        challenge = await make_challenge(db_session)

        body = (
            await client.post(f"/api/challenges/{challenge.id}/submit", json={"answer": "x"})
        ).json()

        assert body["attempts_remaining"] is None

    async def test_a_cap_is_counted_down_and_then_enforced(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await player(db_session, client, sign_in)
        challenge = await make_challenge(db_session, max_attempts=2)

        first = await client.post(f"/api/challenges/{challenge.id}/submit", json={"answer": "a"})
        second = await client.post(f"/api/challenges/{challenge.id}/submit", json={"answer": "b"})
        third = await client.post(f"/api/challenges/{challenge.id}/submit", json={"answer": "c"})

        assert first.json()["attempts_remaining"] == 1
        assert second.json()["attempts_remaining"] == 0
        assert third.status_code == 429
        assert third.json()["error"]["code"] == "attempts_exhausted"

    async def test_the_cap_is_visible_before_it_bites(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        """A player should never be surprised by running out."""
        await player(db_session, client, sign_in)
        challenge = await make_challenge(db_session, max_attempts=3)

        row = (await client.get(f"/api/challenges/{challenge.id}")).json()

        assert row["max_attempts"] == 3
        assert row["attempts_remaining"] == 3


class TestScoreView:
    async def test_a_player_sees_their_own_total(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        user = await player(db_session, client, sign_in)
        first = await make_challenge(db_session, scoring=ScoringMode.STATIC, initial_points=200)
        second = await make_challenge(db_session, scoring=ScoringMode.STATIC, initial_points=150)
        await record_solve(db_session, user, first)
        await record_solve(db_session, user, second)

        body = (await client.get("/api/me/score")).json()

        assert body["total"] == 350
        assert len(body["solves"]) == 2

    async def test_an_unsolved_player_scores_zero(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await player(db_session, client, sign_in)

        body = (await client.get("/api/me/score")).json()

        assert body["total"] == 0
        assert body["solves"] == []
