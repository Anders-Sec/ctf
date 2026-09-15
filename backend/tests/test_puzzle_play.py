"""Playing a puzzle over HTTP (spec 044 §5, §6).

The engines are tested against dicts in ``test_puzzle_engines``. This is about
the platform around them: what reaches the wire, what a solve does to the score,
what failing costs, and the several ways a challenge can refuse to be played.
"""

from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.challenge import ChallengeState, PreReleaseState, ScoringMode
from app.models.play import Solve, Submission
from app.models.puzzle import PuzzleKind, PuzzleSession, PuzzleStatus
from app.models.user import UserStatus
from tests.factories import make_challenge, make_puzzle, make_user

pytestmark = pytest.mark.usefixtures("running_event")

SOLUTION = [["C", "A", "T"], ["A", "R", "E"], ["T", "E", "N"]]


async def player(db_session, client, sign_in, **kwargs):
    kwargs.setdefault("status", UserStatus.ACTIVE)
    user = await make_user(db_session, **kwargs)
    await sign_in(client, user)
    return user


async def puzzle_challenge(db_session, kind=PuzzleKind.WORDLE, config=None, **kwargs):
    kwargs.setdefault("scoring", ScoringMode.STATIC)
    kwargs.setdefault("initial_points", 150)
    challenge = await make_challenge(db_session, **kwargs)
    await make_puzzle(db_session, challenge, kind=kind, config=config)
    return challenge


async def move(client: AsyncClient, challenge_id, **payload):
    return await client.post(f"/api/challenges/{challenge_id}/puzzle/move", json={"move": payload})


class TestReadingAPuzzle:
    async def test_it_reports_the_kind_and_no_session(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await player(db_session, client, sign_in)
        challenge = await puzzle_challenge(db_session)

        body = (await client.get(f"/api/challenges/{challenge.id}/puzzle")).json()

        assert body["kind"] == "wordle"
        assert body["status"] is None
        assert body["moves_used"] == 0
        assert body["puzzle"]["guesses"] == []

    async def test_reading_does_not_start_a_session(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        # Looking at a puzzle must not start the clock on its guesses.
        await player(db_session, client, sign_in)
        challenge = await puzzle_challenge(db_session)

        await client.get(f"/api/challenges/{challenge.id}/puzzle")

        assert (await db_session.execute(select(PuzzleSession))).scalars().all() == []

    async def test_an_ordinary_challenge_is_not_a_puzzle(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await player(db_session, client, sign_in)
        challenge = await make_challenge(db_session)

        response = await client.get(f"/api/challenges/{challenge.id}/puzzle")

        assert response.status_code == 404
        assert response.json()["error"]["code"] == "not_a_puzzle"

    async def test_the_board_marks_a_puzzle_and_its_status(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await player(db_session, client, sign_in)
        challenge = await puzzle_challenge(db_session)

        rows = (await client.get("/api/challenges")).json()
        assert rows[0]["puzzle_kind"] == "wordle"
        assert rows[0]["puzzle_status"] is None

        await move(client, challenge.id, guess="AUDIT")

        rows = (await client.get("/api/challenges")).json()
        assert rows[0]["puzzle_status"] == "in_progress"

    async def test_an_ordinary_challenge_carries_no_puzzle_fields(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await player(db_session, client, sign_in)
        await make_challenge(db_session)

        rows = (await client.get("/api/challenges")).json()

        assert rows[0]["puzzle_kind"] is None
        assert rows[0]["puzzle_status"] is None


class TestLeakage:
    async def test_the_answer_never_reaches_the_wire_while_playing(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        # Asserted against the raw response body rather than the parsed shape:
        # the guarantee is that the bytes do not contain it, wherever it might
        # have been tucked.
        await player(db_session, client, sign_in)
        challenge = await puzzle_challenge(db_session)

        await move(client, challenge.id, guess="AUDIT")
        response = await client.get(f"/api/challenges/{challenge.id}/puzzle")

        assert "PROXY" not in response.text

    async def test_the_crossword_ships_clues_but_not_answers(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await player(db_session, client, sign_in)
        challenge = await puzzle_challenge(db_session, kind=PuzzleKind.CROSSWORD)

        response = await client.get(f"/api/challenges/{challenge.id}/puzzle")

        assert "Feline" in response.text
        assert "CAT" not in response.text

    async def test_connections_does_not_ship_the_grouping(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await player(db_session, client, sign_in)
        challenge = await puzzle_challenge(db_session, kind=PuzzleKind.CONNECTIONS)

        response = await client.get(f"/api/challenges/{challenge.id}/puzzle")

        assert "3389" in response.text  # the tiles are there
        assert "Ports" not in response.text  # which group they are in is not

    async def test_the_answer_arrives_once_the_session_is_over(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await player(db_session, client, sign_in)
        challenge = await puzzle_challenge(db_session, config={"answer": "PROXY", "max_guesses": 1})

        await move(client, challenge.id, guess="AUDIT")
        body = (await client.get(f"/api/challenges/{challenge.id}/puzzle")).json()

        assert body["status"] == "failed"
        assert body["puzzle"]["answer"] == "PROXY"


class TestSolving:
    async def test_finishing_banks_xp_and_records_a_solve(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        user = await player(db_session, client, sign_in)
        challenge = await puzzle_challenge(db_session)

        body = (await move(client, challenge.id, guess="PROXY")).json()

        assert body["solved"] is True
        assert body["status"] == "solved"
        assert body["xp_awarded"] == 150

        solve = (
            await db_session.execute(
                select(Solve).where(Solve.user_id == user.id, Solve.challenge_id == challenge.id)
            )
        ).scalar_one()
        assert solve.xp_awarded == 150

    async def test_the_solve_shows_up_on_the_score(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await player(db_session, client, sign_in)
        challenge = await puzzle_challenge(db_session)

        await move(client, challenge.id, guess="PROXY")

        assert (await client.get("/api/me/score")).json()["total"] == 150

    async def test_every_move_is_logged_but_only_the_last_is_correct(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        user = await player(db_session, client, sign_in)
        challenge = await puzzle_challenge(db_session)

        await move(client, challenge.id, guess="AUDIT")
        await move(client, challenge.id, guess="PROXY")

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
        assert [(row.submitted_value, row.is_correct) for row in rows] == [
            ("AUDIT", False),
            ("PROXY", True),
        ]

    async def test_a_correct_connections_group_is_not_logged_as_correct(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        # Progress is not a solve. Marking it correct would make the attempt log
        # lie, and spec 007 reads that log.
        user = await player(db_session, client, sign_in)
        challenge = await puzzle_challenge(db_session, kind=PuzzleKind.CONNECTIONS)

        await move(client, challenge.id, members=["22", "80", "443", "3389"])

        row = (
            await db_session.execute(select(Submission).where(Submission.user_id == user.id))
        ).scalar_one()
        assert row.is_correct is False

    async def test_a_solved_puzzle_cannot_be_played_on(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await player(db_session, client, sign_in)
        challenge = await puzzle_challenge(db_session)

        await move(client, challenge.id, guess="PROXY")
        response = await move(client, challenge.id, guess="AUDIT")

        assert response.status_code == 409
        assert response.json()["error"]["code"] == "puzzle_finished"


class TestFailing:
    async def test_running_out_ends_the_day_with_no_xp(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        user = await player(db_session, client, sign_in)
        challenge = await puzzle_challenge(db_session, config={"answer": "PROXY", "max_guesses": 2})

        await move(client, challenge.id, guess="AUDIT")
        body = (await move(client, challenge.id, guess="CLAMP")).json()

        assert body["status"] == "failed"
        assert body["xp_awarded"] == 0
        assert (
            await db_session.execute(select(Solve).where(Solve.user_id == user.id))
        ).scalar_one_or_none() is None

    async def test_a_failed_puzzle_refuses_further_moves(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await player(db_session, client, sign_in)
        challenge = await puzzle_challenge(db_session, config={"answer": "PROXY", "max_guesses": 1})

        await move(client, challenge.id, guess="AUDIT")
        response = await move(client, challenge.id, guess="PROXY")

        assert response.status_code == 409

    async def test_the_board_shows_a_failed_puzzle_as_failed_not_untouched(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await player(db_session, client, sign_in)
        challenge = await puzzle_challenge(db_session, config={"answer": "PROXY", "max_guesses": 1})

        await move(client, challenge.id, guess="AUDIT")

        row = (await client.get("/api/challenges")).json()[0]
        assert row["puzzle_status"] == "failed"
        assert row["solved"] is False


class TestMalformedMoves:
    async def test_a_word_outside_the_list_costs_no_guess(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        user = await player(db_session, client, sign_in)
        challenge = await puzzle_challenge(db_session)

        response = await move(client, challenge.id, guess="ZZZZZ")

        assert response.status_code == 422
        assert response.json()["error"]["code"] == "unknown_word"
        # It never reached the puzzle, so it is in no log and on no counter.
        assert (
            await db_session.execute(select(Submission).where(Submission.user_id == user.id))
        ).scalar_one_or_none() is None
        assert (await client.get(f"/api/challenges/{challenge.id}/puzzle")).json()[
            "moves_used"
        ] == 0

    async def test_a_repeated_connections_selection_costs_nothing(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await player(db_session, client, sign_in)
        challenge = await puzzle_challenge(db_session, kind=PuzzleKind.CONNECTIONS)

        await move(client, challenge.id, members=["22", "80", "443", "MD5"])
        body = (await move(client, challenge.id, members=["MD5", "443", "80", "22"])).json()

        assert body["feedback"]["result"] == "repeat"
        assert body["puzzle"]["mistakes"] == 1
        assert body["moves_used"] == 1


class TestTheSubmitEndpointRefuses:
    async def test_a_puzzle_cannot_be_answered_with_a_flag(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        # Without this the whole design is decorative: the Wordle answer would be
        # an ordinary flag and anyone could type it straight in.
        await player(db_session, client, sign_in)
        challenge = await puzzle_challenge(db_session)

        response = await client.post(
            f"/api/challenges/{challenge.id}/submit", json={"answer": "PROXY"}
        )

        assert response.status_code == 409
        assert response.json()["error"]["code"] == "puzzle_challenge"

    async def test_and_creates_no_solve(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        user = await player(db_session, client, sign_in)
        challenge = await puzzle_challenge(db_session)

        await client.post(
            f"/api/challenges/{challenge.id}/submit", json={"answer": "flag{correct}"}
        )

        assert (
            await db_session.execute(select(Solve).where(Solve.user_id == user.id))
        ).scalar_one_or_none() is None


class TestVisibility:
    async def test_a_hidden_puzzle_is_a_404_on_both_routes(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await player(db_session, client, sign_in)
        challenge = await puzzle_challenge(db_session, state=ChallengeState.HIDDEN)

        assert (await client.get(f"/api/challenges/{challenge.id}/puzzle")).status_code == 404
        assert (await move(client, challenge.id, guess="PROXY")).status_code == 404

    async def test_an_unreleased_puzzle_cannot_be_played(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await player(db_session, client, sign_in)
        challenge = await puzzle_challenge(
            db_session,
            release_at=datetime.now(UTC) + timedelta(days=1),
            pre_release_state=PreReleaseState.LOCKED,
        )

        response = await move(client, challenge.id, guess="PROXY")

        assert response.status_code == 403
        assert response.json()["error"]["code"] == "challenge_locked"

    async def test_probing_a_locked_puzzle_is_logged(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        user = await player(db_session, client, sign_in)
        challenge = await puzzle_challenge(
            db_session,
            release_at=datetime.now(UTC) + timedelta(days=1),
            pre_release_state=PreReleaseState.LOCKED,
        )

        await move(client, challenge.id, guess="PROXY")

        row = (
            await db_session.execute(select(Submission).where(Submission.user_id == user.id))
        ).scalar_one()
        assert row.is_correct is False


class TestSaving:
    async def test_saving_keeps_letters_without_consuming_a_check(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await player(db_session, client, sign_in)
        challenge = await puzzle_challenge(db_session, kind=PuzzleKind.CROSSWORD)

        await client.post(
            f"/api/challenges/{challenge.id}/puzzle/save",
            json={"grid": [["C", "", ""], ["", "", ""], ["", "", ""]]},
        )

        body = (await client.get(f"/api/challenges/{challenge.id}/puzzle")).json()
        assert body["puzzle"]["letters"][0][0] == "C"
        assert body["puzzle"]["checks"] == 0
        assert body["moves_used"] == 0

    async def test_a_wordle_has_nothing_to_save(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await player(db_session, client, sign_in)
        challenge = await puzzle_challenge(db_session)

        response = await client.post(
            f"/api/challenges/{challenge.id}/puzzle/save", json={"grid": []}
        )

        assert response.status_code == 400
        assert response.json()["error"]["code"] == "save_not_supported"

    async def test_a_check_marks_wrong_cells_without_saying_what_is_right(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await player(db_session, client, sign_in)
        challenge = await puzzle_challenge(db_session, kind=PuzzleKind.CROSSWORD)

        grid = [list(row) for row in SOLUTION]
        grid[0][0] = "X"
        response = await move(client, challenge.id, grid=grid)

        assert response.json()["feedback"]["wrong"] == [[0, 0]]
        assert "CAT" not in response.text

    async def test_a_full_correct_grid_solves(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await player(db_session, client, sign_in)
        challenge = await puzzle_challenge(db_session, kind=PuzzleKind.CROSSWORD)

        body = (await move(client, challenge.id, grid=SOLUTION)).json()

        assert body["solved"] is True
        assert body["xp_awarded"] == 150


class TestSessionsAreOwned:
    async def test_one_players_progress_is_not_anothers(
        self, client: AsyncClient, db_session: AsyncSession, sign_in, app
    ) -> None:
        from httpx import ASGITransport
        from httpx import AsyncClient as Client

        await player(db_session, client, sign_in)
        challenge = await puzzle_challenge(db_session)
        await move(client, challenge.id, guess="AUDIT")

        other = await make_user(db_session, status=UserStatus.ACTIVE)
        async with Client(transport=ASGITransport(app=app), base_url="http://test") as other_client:
            await sign_in(other_client, other)
            body = (await other_client.get(f"/api/challenges/{challenge.id}/puzzle")).json()

        assert body["status"] is None
        assert body["puzzle"]["guesses"] == []

    async def test_the_session_survives_a_reload(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await player(db_session, client, sign_in)
        challenge = await puzzle_challenge(db_session)

        await move(client, challenge.id, guess="AUDIT")
        body = (await client.get(f"/api/challenges/{challenge.id}/puzzle")).json()

        assert [entry["guess"] for entry in body["puzzle"]["guesses"]] == ["AUDIT"]
        assert body["puzzle"]["guesses_remaining"] == 5

    async def test_the_tile_order_is_stable_across_reads(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await player(db_session, client, sign_in)
        challenge = await puzzle_challenge(db_session, kind=PuzzleKind.CONNECTIONS)
        await move(client, challenge.id, members=["22", "80", "443", "MD5"])

        first = (await client.get(f"/api/challenges/{challenge.id}/puzzle")).json()
        again = (await client.get(f"/api/challenges/{challenge.id}/puzzle")).json()

        assert first["puzzle"]["tiles"] == again["puzzle"]["tiles"]


class TestStatusIsAuthoritative:
    async def test_a_finished_session_is_terminal_in_the_database(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        user = await player(db_session, client, sign_in)
        challenge = await puzzle_challenge(db_session)

        await move(client, challenge.id, guess="PROXY")

        session = (
            await db_session.execute(
                select(PuzzleSession).where(
                    PuzzleSession.user_id == user.id, PuzzleSession.challenge_id == challenge.id
                )
            )
        ).scalar_one()
        assert session.status == PuzzleStatus.SOLVED
        assert session.finished_at is not None
