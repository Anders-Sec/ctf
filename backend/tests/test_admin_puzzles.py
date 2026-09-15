"""Authoring a puzzle (spec 044 §7), and the two rules that keep it honest:
a challenge is answered or played but never both, and only admins may see or
set what the answer is.
"""

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import AuditLog
from app.models.challenge import MatchType
from app.models.puzzle import ChallengePuzzle, PuzzleKind, PuzzleSession
from app.models.user import UserRole, UserStatus
from tests.factories import DEFAULT_PUZZLE_CONFIG, make_challenge, make_puzzle, make_user

pytestmark = pytest.mark.usefixtures("running_event")


async def admin(db_session, client, sign_in):
    user = await make_user(db_session, role=UserRole.ADMIN, status=UserStatus.ACTIVE)
    await sign_in(client, user)
    return user


async def player(db_session, client, sign_in):
    user = await make_user(db_session, status=UserStatus.ACTIVE)
    await sign_in(client, user)
    return user


class TestSettingAPuzzle:
    async def test_a_wordle_is_stored_normalised(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await admin(db_session, client, sign_in)
        challenge = await make_challenge(db_session, answers=[])

        response = await client.put(
            f"/api/admin/challenges/{challenge.id}/puzzle",
            json={"kind": "wordle", "config": {"answer": " proxy "}},
        )

        assert response.status_code == 200
        # What comes back is what will be played, not what was typed.
        assert response.json()["config"]["answer"] == "PROXY"
        assert response.json()["config"]["max_guesses"] == 6

    async def test_it_reports_how_playable_the_word_list_makes_it(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await admin(db_session, client, sign_in)
        challenge = await make_challenge(db_session, answers=[])

        response = await client.put(
            f"/api/admin/challenges/{challenge.id}/puzzle",
            json={"kind": "wordle", "config": {"answer": "PROXY"}},
        )

        assert any("guess list" in note for note in response.json()["notes"])

    async def test_a_crossword_comes_back_with_derived_numbering(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await admin(db_session, client, sign_in)
        challenge = await make_challenge(db_session, answers=[])

        response = await client.put(
            f"/api/admin/challenges/{challenge.id}/puzzle",
            json={"kind": "crossword", "config": DEFAULT_PUZZLE_CONFIG[PuzzleKind.CROSSWORD]},
        )

        numbers = [entry["number"] for entry in response.json()["config"]["entries"]]
        assert numbers == [1, 1, 2, 3, 4, 5]

    async def test_a_bad_config_is_refused_with_the_field_that_is_wrong(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await admin(db_session, client, sign_in)
        challenge = await make_challenge(db_session, answers=[])

        response = await client.put(
            f"/api/admin/challenges/{challenge.id}/puzzle",
            json={"kind": "wordle", "config": {"answer": "TOOLONG"}},
        )

        assert response.status_code == 422
        error = response.json()["error"]
        assert error["code"] == "invalid_puzzle_config"
        assert error["details"]["field"] == "answer"

    async def test_setting_it_twice_replaces_rather_than_duplicates(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await admin(db_session, client, sign_in)
        challenge = await make_challenge(db_session, answers=[])

        for answer in ("PROXY", "AUDIT"):
            await client.put(
                f"/api/admin/challenges/{challenge.id}/puzzle",
                json={"kind": "wordle", "config": {"answer": answer}},
            )

        rows = (
            (
                await db_session.execute(
                    select(ChallengePuzzle).where(ChallengePuzzle.challenge_id == challenge.id)
                )
            )
            .scalars()
            .all()
        )
        assert len(rows) == 1
        assert rows[0].config["answer"] == "AUDIT"

    async def test_the_audit_log_records_the_kind_and_not_the_answer(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        # The audit log is read by organizers. It is not the place to publish
        # today's answers.
        await admin(db_session, client, sign_in)
        challenge = await make_challenge(db_session, answers=[])

        await client.put(
            f"/api/admin/challenges/{challenge.id}/puzzle",
            json={"kind": "wordle", "config": {"answer": "PROXY"}},
        )

        entry = (
            await db_session.execute(
                select(AuditLog).where(AuditLog.action == "challenge.puzzle_set")
            )
        ).scalar_one()
        assert entry.meta == {"kind": "wordle"}
        assert "PROXY" not in str(entry.meta)


class TestAnsweredOrPlayedNeverBoth:
    async def test_a_challenge_with_flags_refuses_a_puzzle(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await admin(db_session, client, sign_in)
        challenge = await make_challenge(db_session)  # comes with the usual flag

        response = await client.put(
            f"/api/admin/challenges/{challenge.id}/puzzle",
            json={"kind": "wordle", "config": {"answer": "PROXY"}},
        )

        assert response.status_code == 409

    async def test_a_puzzle_challenge_refuses_a_flag(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await admin(db_session, client, sign_in)
        challenge = await make_challenge(db_session, answers=[])
        await make_puzzle(db_session, challenge)

        response = await client.post(
            f"/api/admin/challenges/{challenge.id}/answers",
            json={"match_type": MatchType.EXACT.value, "value": "flag{x}"},
        )

        assert response.status_code == 409


class TestClearingAPuzzle:
    async def test_it_takes_the_sessions_with_it(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        # Progress against a puzzle that no longer exists would leave players
        # marked as having failed something unplayable.
        await admin(db_session, client, sign_in)
        challenge = await make_challenge(db_session, answers=[])
        await make_puzzle(db_session, challenge)
        other = await make_user(db_session, status=UserStatus.ACTIVE)
        db_session.add(
            PuzzleSession(
                user_id=other.id,
                challenge_id=challenge.id,
                state={},
                started_at=challenge.created_at,
            )
        )
        await db_session.flush()

        response = await client.delete(f"/api/admin/challenges/{challenge.id}/puzzle")

        assert response.status_code == 200
        assert (
            await db_session.execute(
                select(PuzzleSession).where(PuzzleSession.challenge_id == challenge.id)
            )
        ).scalars().all() == []

    async def test_clearing_a_challenge_with_no_puzzle_is_a_404(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await admin(db_session, client, sign_in)
        challenge = await make_challenge(db_session)

        assert (
            await client.delete(f"/api/admin/challenges/{challenge.id}/puzzle")
        ).status_code == 404


class TestWhoMaySee:
    async def test_the_admin_detail_carries_the_answer_and_the_session_counts(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        # An admin who cannot see the answer cannot debug a puzzle nobody is
        # solving.
        await admin(db_session, client, sign_in)
        challenge = await make_challenge(db_session, answers=[])
        await make_puzzle(db_session, challenge)

        body = (await client.get(f"/api/admin/challenges/{challenge.id}")).json()

        assert body["puzzle"]["kind"] == "wordle"
        assert body["puzzle"]["config"]["answer"] == "PROXY"
        assert body["puzzle"]["sessions"] == 0

    async def test_an_ordinary_challenge_reports_no_puzzle(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await admin(db_session, client, sign_in)
        challenge = await make_challenge(db_session)

        assert (await client.get(f"/api/admin/challenges/{challenge.id}")).json()["puzzle"] is None

    async def test_a_player_cannot_set_a_puzzle(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await player(db_session, client, sign_in)
        challenge = await make_challenge(db_session, answers=[])

        response = await client.put(
            f"/api/admin/challenges/{challenge.id}/puzzle",
            json={"kind": "wordle", "config": {"answer": "PROXY"}},
        )

        assert response.status_code == 403

    async def test_a_player_cannot_read_the_admin_detail(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await player(db_session, client, sign_in)
        challenge = await make_challenge(db_session, answers=[])
        await make_puzzle(db_session, challenge)

        assert (await client.get(f"/api/admin/challenges/{challenge.id}")).status_code == 403
