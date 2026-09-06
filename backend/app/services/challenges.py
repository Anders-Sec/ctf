"""Reading challenges, and submitting answers to them."""

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from redis.asyncio import Redis
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.errors import AppError, NotFoundError
from app.logging import get_logger
from app.models.challenge import Category, Challenge, ChallengeState
from app.models.play import MAX_SUBMISSION_LENGTH, Solve, Submission
from app.models.user import User
from app.services import answers as answer_service
from app.services import scoring
from app.services.rate_limit import RateLimited, check_submission_limits
from app.services.user_cache import load_active_team

logger = get_logger(__name__)


class ChallengeLocked(AppError):
    status_code = 403
    code = "challenge_locked"
    message = "This challenge is not open yet."


class AttemptsExhausted(AppError):
    status_code = 429
    code = "attempts_exhausted"
    message = "You have used all your attempts on this challenge."


#: What a player is allowed to see at each effective state.
PLAYER_VISIBLE = (ChallengeState.LOCKED, ChallengeState.PUBLISHED)


@dataclass(frozen=True)
class SubmissionOutcome:
    correct: bool
    already_solved: bool
    points_awarded: int
    attempts_remaining: int | None


async def list_for_player(db: AsyncSession, user_id: UUID, now: datetime) -> list[dict]:
    """Every challenge a player may see, with its current value and their status.

    Solve counts are fetched in one grouped query rather than per challenge —
    the classic N+1 that only shows up under load.
    """
    challenges = (
        (
            await db.execute(
                select(Challenge)
                .options(selectinload(Challenge.category))
                .where(Challenge.state != ChallengeState.DRAFT)
                .order_by(Challenge.title)
            )
        )
        .scalars()
        .all()
    )

    visible = [c for c in challenges if c.effective_state(now) in PLAYER_VISIBLE]
    return await _decorate(db, visible, user_id, now)


async def _decorate(
    db: AsyncSession, challenges: list[Challenge], user_id: UUID, now: datetime
) -> list[dict]:
    ids = [c.id for c in challenges]
    player_counts = await scoring.solve_counts_for(db, ids)
    team_counts = await scoring.team_solve_counts_for(db, ids)

    solved_ids = set(
        (
            await db.execute(
                select(Solve.challenge_id).where(
                    Solve.user_id == user_id, Solve.challenge_id.in_(ids)
                )
            )
        )
        .scalars()
        .all()
    )
    attempt_counts = await _attempt_counts(db, user_id, ids)

    rows = []
    for challenge in challenges:
        state = challenge.effective_state(now)
        counts = team_counts if challenge.decay_basis.value == "teams" else player_counts
        count = counts.get(challenge.id, 0)
        rows.append(
            {
                "challenge": challenge,
                "effective_state": state,
                "value": scoring.challenge_value(challenge, count),
                # Player-basis count either way: "how many people solved this" is
                # what a player wants to know, whatever drives the curve.
                "solve_count": player_counts.get(challenge.id, 0),
                "solved": challenge.id in solved_ids,
                "attempts_remaining": _remaining(challenge, attempt_counts.get(challenge.id, 0)),
            }
        )
    return rows


def _remaining(challenge: Challenge, used: int) -> int | None:
    if challenge.max_attempts is None:
        return None
    return max(0, challenge.max_attempts - used)


async def _attempt_counts(
    db: AsyncSession, user_id: UUID, challenge_ids: list[UUID]
) -> dict[UUID, int]:
    if not challenge_ids:
        return {}
    rows = await db.execute(
        select(Submission.challenge_id, func.count())
        .where(Submission.user_id == user_id, Submission.challenge_id.in_(challenge_ids))
        .group_by(Submission.challenge_id)
    )
    return {challenge_id: count for challenge_id, count in rows}


async def get_for_player(
    db: AsyncSession, challenge_id: UUID, user_id: UUID, now: datetime
) -> dict:
    """One challenge, or 404 if the player is not allowed to know it exists.

    A hidden or draft challenge 404s rather than 403ing: a 403 would confirm the
    id is real, which is a small oracle for anyone guessing at what is coming.
    """
    challenge = (
        await db.execute(
            select(Challenge)
            .options(selectinload(Challenge.category), selectinload(Challenge.artifacts))
            .where(Challenge.id == challenge_id)
        )
    ).scalar_one_or_none()

    if challenge is None or challenge.effective_state(now) not in PLAYER_VISIBLE:
        raise NotFoundError("No such challenge.")

    decorated = (await _decorate(db, [challenge], user_id, now))[0]
    return decorated


async def submit_answer(
    db: AsyncSession,
    redis: Redis,
    user: User,
    challenge_id: UUID,
    raw_answer: str,
    *,
    now: datetime | None = None,
    ip: str | None = None,
    request_id: str | None = None,
) -> SubmissionOutcome:
    """Evaluate an answer, record the attempt, and award a solve if it is right."""
    now = now or datetime.now(UTC)

    challenge = (
        await db.execute(
            select(Challenge)
            .options(selectinload(Challenge.answers))
            .where(Challenge.id == challenge_id)
        )
    ).scalar_one_or_none()

    state = challenge.effective_state(now) if challenge else None
    if challenge is None or state not in PLAYER_VISIBLE:
        raise NotFoundError("No such challenge.")

    # Rate limiting comes before the locked check, so probing a locked challenge
    # cannot be used as an unlimited oracle either.
    decision = await check_submission_limits(redis, user.id, challenge.id)
    if not decision.allowed:
        raise RateLimited(
            "Too many attempts. Wait a moment before trying again.",
            details={"retry_after_seconds": decision.retry_after_seconds},
        )

    if state == ChallengeState.LOCKED:
        # Logged anyway: someone probing locked challenges is worth seeing in 007.
        await _record(db, user, challenge, raw_answer, False, None, ip, request_id, now)
        raise ChallengeLocked

    already = (
        await db.execute(
            select(Solve).where(Solve.user_id == user.id, Solve.challenge_id == challenge.id)
        )
    ).scalar_one_or_none()

    used = (
        await db.scalar(
            select(func.count()).where(
                Submission.user_id == user.id, Submission.challenge_id == challenge.id
            )
        )
    ) or 0

    # Counted in Postgres, not Redis: a hard cap must survive a cache flush.
    if already is None and challenge.max_attempts is not None and used >= challenge.max_attempts:
        raise AttemptsExhausted

    verdict = answer_service.check(raw_answer, challenge.answers)
    if verdict.errors:
        logger.warning(
            "answer_rule_errors",
            extra={"challenge_id": str(challenge.id), "errors": list(verdict.errors)},
        )

    submission = await _record(
        db,
        user,
        challenge,
        raw_answer,
        verdict.correct,
        verdict.matched_answer.id if verdict.matched_answer else None,
        ip,
        request_id,
        now,
    )

    remaining = _remaining(challenge, used + 1)

    if not verdict.correct:
        return SubmissionOutcome(False, already is not None, 0, remaining)

    if already is not None:
        # Players do re-submit to check. Logged, no second solve, no points.
        return SubmissionOutcome(True, True, 0, remaining)

    team = await load_active_team(db, user.id)
    solve = Solve(
        user_id=user.id,
        challenge_id=challenge.id,
        team_id_at_solve=team.id if team else None,
        submitted_at=now,
        submission_id=submission.id,
    )
    try:
        # A savepoint, not the whole transaction: rolling the session back here
        # would also discard the submission we just logged, and the attempt log
        # has to survive whichever side of the race we lost.
        async with db.begin_nested():
            db.add(solve)
    except IntegrityError:
        # Two correct submissions raced. The constraint decided; the loser is
        # told they had already solved it, which is true.
        return SubmissionOutcome(True, True, 0, remaining)

    count = await scoring.solve_count(db, challenge)
    return SubmissionOutcome(True, False, scoring.challenge_value(challenge, count), remaining)


async def _record(
    db: AsyncSession,
    user: User,
    challenge: Challenge,
    raw_answer: str,
    correct: bool,
    matched_answer_id: UUID | None,
    ip: str | None,
    request_id: str | None,
    now: datetime,
) -> Submission:
    team = await load_active_team(db, user.id)
    submission = Submission(
        user_id=user.id,
        challenge_id=challenge.id,
        team_id_at_submit=team.id if team else None,
        is_correct=correct,
        submitted_value=raw_answer[:MAX_SUBMISSION_LENGTH],
        matched_answer_id=matched_answer_id,
        ip=ip,
        request_id=request_id,
    )
    db.add(submission)
    await db.flush()
    return submission


async def list_categories(db: AsyncSession) -> list[Category]:
    return list(
        (await db.execute(select(Category).order_by(Category.display_order, Category.name)))
        .scalars()
        .all()
    )
