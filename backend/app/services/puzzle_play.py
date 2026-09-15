"""Playing a daily puzzle (spec 044 §5, §6).

The engines in :mod:`app.services.puzzles` know the games. This module knows the
platform: visibility, rate limiting, the attempt log, the session row, and the
one route by which finishing a puzzle becomes a solve.

Every move passes the same gate in the same order before its kind matters at all,
which is the reason there is one move endpoint and not three.
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.errors import AppError
from app.logging import get_logger
from app.models.challenge import Challenge, ChallengeState
from app.models.play import Solve
from app.models.puzzle import ChallengePuzzle, PuzzleKind, PuzzleSession, PuzzleStatus
from app.models.user import User
from app.services import achievements
from app.services import challenges as challenge_service
from app.services.puzzles import InvalidMove, PuzzleFinished, engine_for
from app.services.rate_limit import (
    RateLimited,
    check_puzzle_save_limit,
    check_submission_limits,
)
from app.services.user_cache import load_active_team

logger = get_logger(__name__)


class NotAPuzzle(AppError):
    """This challenge is answered, not played."""

    status_code = 404
    code = "not_a_puzzle"
    message = "This challenge is not a puzzle."


class SaveNotSupported(AppError):
    """Only the crossword has typing to keep between checks."""

    status_code = 400
    code = "save_not_supported"
    message = "This puzzle has nothing to save."


@dataclass(frozen=True)
class PuzzleView:
    kind: PuzzleKind
    #: The engine's answer-free projection. Answer-revealing only when the
    #: session is terminal, and the engine decides what that means for its game.
    puzzle: dict[str, Any]
    status: PuzzleStatus | None
    moves_used: int
    solved: bool
    #: Set on the move that finished it; null every other time.
    feedback: dict[str, Any] | None = None
    xp_awarded: int = 0


async def get_puzzle(db: AsyncSession, challenge_id: UUID) -> ChallengePuzzle | None:
    return (
        await db.execute(
            select(ChallengePuzzle).where(ChallengePuzzle.challenge_id == challenge_id)
        )
    ).scalar_one_or_none()


async def is_puzzle(db: AsyncSession, challenge_id: UUID) -> bool:
    return (
        await db.scalar(
            select(ChallengePuzzle.id).where(ChallengePuzzle.challenge_id == challenge_id)
        )
    ) is not None


async def kinds_for(db: AsyncSession, challenge_ids: list[UUID]) -> dict[UUID, PuzzleKind]:
    """Which of these challenges are puzzles, and which game each one is.

    One query for the whole board, so the list endpoint can badge a card without
    a lookup per row.
    """
    if not challenge_ids:
        return {}
    rows = (
        await db.execute(
            select(ChallengePuzzle.challenge_id, ChallengePuzzle.kind).where(
                ChallengePuzzle.challenge_id.in_(challenge_ids)
            )
        )
    ).all()
    return {challenge_id: kind for challenge_id, kind in rows}


async def statuses_for(
    db: AsyncSession, user_id: UUID, challenge_ids: list[UUID]
) -> dict[UUID, PuzzleStatus]:
    """This player's standing on each puzzle — so the board can mark the ones
    they lost, which `solved` alone cannot express."""
    if not challenge_ids:
        return {}
    rows = (
        await db.execute(
            select(PuzzleSession.challenge_id, PuzzleSession.status).where(
                PuzzleSession.user_id == user_id,
                PuzzleSession.challenge_id.in_(challenge_ids),
            )
        )
    ).all()
    return {challenge_id: status for challenge_id, status in rows}


async def session_for(
    db: AsyncSession, user_id: UUID, challenge_id: UUID
) -> PuzzleSession | None:
    return (
        await db.execute(
            select(PuzzleSession).where(
                PuzzleSession.user_id == user_id, PuzzleSession.challenge_id == challenge_id
            )
        )
    ).scalar_one_or_none()


async def _open_challenge(
    db: AsyncSession, challenge_id: UUID, user_id: UUID, now: datetime
) -> Challenge:
    """Resolve a challenge the way a player experiences it, or refuse.

    Hidden, draft and unreleased all arrive here as a 404 from the challenge
    service — the same answer an id that does not exist gets, which is the point.
    """
    row = await challenge_service.get_for_player(db, challenge_id, user_id, now)
    if row["effective_state"] == ChallengeState.LOCKED:
        raise challenge_service.ChallengeLocked
    return row["challenge"]


async def _create_session(
    db: AsyncSession, user_id: UUID, challenge: Challenge, kind: PuzzleKind, now: datetime
) -> PuzzleSession:
    session = PuzzleSession(
        user_id=user_id,
        challenge_id=challenge.id,
        status=PuzzleStatus.IN_PROGRESS,
        state=engine_for(kind).initial_state(),
        moves_used=0,
        started_at=now,
    )
    try:
        # A savepoint, so losing the race does not discard the transaction.
        async with db.begin_nested():
            db.add(session)
    except IntegrityError:
        # Two first moves raced. The constraint decided; re-read the winner.
        existing = await session_for(db, user_id, challenge.id)
        if existing is None:  # pragma: no cover - the constraint says otherwise
            raise
        return existing
    await db.flush()
    return session


def _seeded(session: PuzzleSession) -> dict[str, Any]:
    """The session's state, with its shuffle seed present.

    Derived from the session id rather than stored: stable across reloads without
    a column, and different per player, so two people cannot compare tile
    positions and learn anything.
    """
    return {**session.state, "seed": str(session.id)}


def _view(
    kind: PuzzleKind,
    config: dict[str, Any],
    session: PuzzleSession | None,
    *,
    feedback: dict[str, Any] | None = None,
    xp_awarded: int = 0,
) -> PuzzleView:
    engine = engine_for(kind)
    state = _seeded(session) if session else engine.initial_state()
    # The single gate on answer-revealing content: terminal sessions only.
    reveal = bool(session and session.terminal)
    return PuzzleView(
        kind=kind,
        puzzle=engine.view(config, state, reveal=reveal),
        status=session.status if session else None,
        moves_used=session.moves_used if session else 0,
        solved=bool(session and session.status == PuzzleStatus.SOLVED),
        feedback=feedback,
        xp_awarded=xp_awarded,
    )


async def view_for_player(
    db: AsyncSession, challenge_id: UUID, user_id: UUID, now: datetime | None = None
) -> PuzzleView:
    """The puzzle as it stands for this player.

    Creates nothing: opening a puzzle to look at it does not commit you to
    playing it. The session arrives with the first move.
    """
    now = now or datetime.now(UTC)
    challenge = await _open_challenge(db, challenge_id, user_id, now)

    puzzle = await get_puzzle(db, challenge.id)
    if puzzle is None:
        raise NotAPuzzle

    return _view(puzzle.kind, puzzle.config, await session_for(db, user_id, challenge.id))


async def apply_move(
    db: AsyncSession,
    redis: Redis,
    user: User,
    challenge_id: UUID,
    move: dict[str, Any],
    *,
    now: datetime | None = None,
    ip: str | None = None,
    request_id: str | None = None,
) -> PuzzleView:
    """Play one move.

    The order below is the whole point of a single move endpoint: visibility,
    rate limit, lock, prerequisites and terminality are the same five questions
    for every game, and only then does the kind matter.
    """
    now = now or datetime.now(UTC)

    # Resolved first, so a hidden or unreleased puzzle is a 404 before anything
    # else is spent on it.
    row = await challenge_service.get_for_player(db, challenge_id, user.id, now)
    challenge = row["challenge"]

    # Before the locked check, so probing a locked puzzle is not an unmetered
    # oracle either — the same order `submit_answer` uses.
    decision = await check_submission_limits(redis, user.id, challenge.id)
    if not decision.allowed:
        raise RateLimited(
            "Too many moves. Wait a moment before trying again.",
            details={"retry_after_seconds": decision.retry_after_seconds},
        )

    puzzle = await get_puzzle(db, challenge.id)
    if puzzle is None:
        raise NotAPuzzle

    if row["effective_state"] == ChallengeState.LOCKED:
        # Logged anyway: someone probing locked challenges is worth seeing in 007.
        await challenge_service.record_attempt(
            db, user, challenge, _probe_value(move), False, None, ip, request_id, now
        )
        raise challenge_service.ChallengeLocked

    # Enforced server-side, so the gate is real rather than cosmetic.
    prereqs = await challenge_service.prerequisite_status(db, user.id, [challenge.id], now)
    status_row = prereqs.get(challenge.id)
    if status_row is not None and status_row.locked:
        await challenge_service.record_attempt(
            db, user, challenge, _probe_value(move), False, None, ip, request_id, now
        )
        raise challenge_service.ChallengeLocked

    session = await session_for(db, user.id, challenge.id)
    if session is None:
        session = await _create_session(db, user.id, challenge, puzzle.kind, now)
    if session.terminal:
        raise PuzzleFinished

    engine = engine_for(puzzle.kind)
    # Raises InvalidMove for something malformed, which costs nothing and is not
    # logged: it never reached the puzzle.
    outcome = engine.move(puzzle.config, _seeded(session), move)

    # The seed is derived, so it never goes back into storage.
    session.state = {key: value for key, value in outcome.state.items() if key != "seed"}

    xp_awarded = 0
    if outcome.counted:
        session.moves_used += 1

        submission = None
        if outcome.log_value:
            submission = await challenge_service.record_attempt(
                db,
                user,
                challenge,
                outcome.log_value,
                # True only on the move that finishes it. A correct Connections
                # group is progress, not a solve, and marking it correct would
                # make the attempt log lie.
                outcome.solved,
                None,
                ip,
                request_id,
                now,
            )

        if outcome.solved:
            session.status = PuzzleStatus.SOLVED
            session.finished_at = now
            xp_awarded = await _award(db, redis, user, challenge, submission, now)
        elif outcome.failed:
            session.status = PuzzleStatus.FAILED
            session.finished_at = now
            logger.info(
                "puzzle_failed",
                extra={"challenge_id": str(challenge.id), "kind": puzzle.kind.value},
            )

        # Every attempt, right or wrong — the same triggers `submit_answer` runs.
        await achievements.evaluate(
            db, user.id, achievements.SUBMIT, achievements.PLATFORM, redis=redis
        )

    await db.flush()
    return _view(
        puzzle.kind, puzzle.config, session, feedback=outcome.feedback, xp_awarded=xp_awarded
    )


async def _award(
    db: AsyncSession,
    redis: Redis,
    user: User,
    challenge: Challenge,
    submission: Any,
    now: datetime,
) -> int:
    """Turn a finished puzzle into a solve, through the ordinary award path."""
    already = (
        await db.execute(
            select(Solve).where(Solve.user_id == user.id, Solve.challenge_id == challenge.id)
        )
    ).scalar_one_or_none()
    if already is not None:
        # Nothing to award twice. Reachable if an admin granted the solve, or if
        # a session was reset out from under a solve that stayed.
        return 0

    team = await load_active_team(db, user.id)
    awarded = await challenge_service.award_solve(
        db,
        redis,
        user,
        challenge,
        submission_id=submission.id if submission else None,
        team_id=team.id if team else None,
        now=now,
    )
    return awarded.xp_awarded


def _probe_value(move: dict[str, Any]) -> str:
    """A move rendered for the attempt log when the puzzle refused to run it."""
    for key in ("guess", "members", "grid"):
        if key in move:
            return str(move[key])[:200]
    return "(puzzle move)"


async def save_progress(
    db: AsyncSession,
    redis: Redis,
    user: User,
    challenge_id: UUID,
    payload: dict[str, Any],
    *,
    now: datetime | None = None,
) -> PuzzleView:
    """Store typing. Evaluates nothing, consumes no check, scores nothing.

    Crossword only — it is the one game with work in progress worth keeping
    between moves.
    """
    now = now or datetime.now(UTC)
    challenge = await _open_challenge(db, challenge_id, user.id, now)

    puzzle = await get_puzzle(db, challenge.id)
    if puzzle is None:
        raise NotAPuzzle

    engine = engine_for(puzzle.kind)
    save = getattr(engine, "save", None)
    if save is None:
        raise SaveNotSupported

    decision = await check_puzzle_save_limit(redis, user.id, challenge.id)
    if not decision.allowed:
        raise RateLimited(
            "Saving too often.", details={"retry_after_seconds": decision.retry_after_seconds}
        )

    session = await session_for(db, user.id, challenge.id)
    if session is None:
        session = await _create_session(db, user.id, challenge, puzzle.kind, now)
    if session.terminal:
        # Nothing to keep. Refused rather than silently ignored, so a client that
        # has lost track of the session finds out.
        raise PuzzleFinished

    session.state = {
        key: value
        for key, value in save(puzzle.config, _seeded(session), payload).items()
        if key != "seed"
    }
    await db.flush()
    return _view(puzzle.kind, puzzle.config, session)


__all__ = [
    "InvalidMove",
    "NotAPuzzle",
    "PuzzleFinished",
    "PuzzleView",
    "SaveNotSupported",
    "apply_move",
    "get_puzzle",
    "is_puzzle",
    "kinds_for",
    "save_progress",
    "session_for",
    "statuses_for",
    "view_for_player",
]
