"""Reading challenges, and submitting answers to them."""

import re
import uuid
from collections import defaultdict
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
from app.models.challenge import (
    Category,
    Challenge,
    ChallengeState,
    RequirementType,
    UnlockRequirement,
)
from app.models.play import MAX_SUBMISSION_LENGTH, Solve, Submission
from app.models.user import User
from app.services import answers as answer_service
from app.services import scoring
from app.services.instances import launcher as instance_launcher
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
class RequirementView:
    """One prerequisite of a challenge, for the player-facing 'why locked' hint."""

    challenge_id: UUID
    title: str
    solved: bool


@dataclass(frozen=True)
class PrereqStatus:
    #: True when the player has NOT met every requirement of the gated challenge.
    locked: bool
    #: Only the requirements the player is allowed to see, for the unlock hint.
    visible_requirements: list[RequirementView]


async def prerequisite_status(
    db: AsyncSession, user_id: UUID, challenge_ids: list[UUID], now: datetime
) -> dict[UUID, PrereqStatus]:
    """For each gated challenge, whether this player has unmet prerequisites.

    Locking considers *all* requirements (a hidden prerequisite can never be
    solved, so the gate holds); the returned hint lists only the prerequisites the
    player may see, so a locked challenge does not reveal a hidden one.
    """
    if not challenge_ids:
        return {}

    rows = (
        await db.execute(
            select(UnlockRequirement.challenge_id, Challenge)
            .join(Challenge, Challenge.id == UnlockRequirement.required_challenge_id)
            .where(
                UnlockRequirement.challenge_id.in_(challenge_ids),
                UnlockRequirement.requirement_type == RequirementType.CHALLENGE_SOLVED,
            )
        )
    ).all()
    if not rows:
        return {}

    required_ids = {required.id for _, required in rows}
    solved = set(
        (
            await db.execute(
                select(Solve.challenge_id).where(
                    Solve.user_id == user_id, Solve.challenge_id.in_(required_ids)
                )
            )
        )
        .scalars()
        .all()
    )

    grouped: dict[UUID, list[tuple[Challenge, bool]]] = defaultdict(list)
    for gated_id, required in rows:
        grouped[gated_id].append((required, required.id in solved))

    result: dict[UUID, PrereqStatus] = {}
    for gated_id, reqs in grouped.items():
        locked = not all(is_solved for _, is_solved in reqs)
        visible = [
            RequirementView(challenge_id=req.id, title=req.title, solved=is_solved)
            for req, is_solved in reqs
            if req.effective_state(now) in PLAYER_VISIBLE
        ]
        result[gated_id] = PrereqStatus(locked=locked, visible_requirements=visible)
    return result


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
    prereqs = await prerequisite_status(db, user_id, ids, now)

    rows = []
    for challenge in challenges:
        state = challenge.effective_state(now)
        status = prereqs.get(challenge.id)
        # Prerequisites make "locked" per-player: a published challenge whose
        # requirements this player has not met is experienced as locked.
        requirements: list[RequirementView] = []
        if state == ChallengeState.PUBLISHED and status is not None and status.locked:
            state = ChallengeState.LOCKED
            requirements = status.visible_requirements

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
                "unlock_requirements": requirements,
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

    # Prerequisite gate, enforced server-side so the lock is real, not cosmetic.
    prereqs = await prerequisite_status(db, user.id, [challenge.id], now)
    status_row = prereqs.get(challenge.id)
    if status_row is not None and status_row.locked:
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

    is_correct = verdict.correct
    matched_answer_id = verdict.matched_answer.id if verdict.matched_answer else None
    team = await load_active_team(db, user.id)

    # A container challenge is solved by its own instance's generated answer, in
    # addition to any static rules. Checked only when the static rules missed, so
    # a challenge can carry both a fixed and a per-instance answer.
    if (
        not is_correct
        and challenge.container_template_id is not None
        and await instance_launcher.answer_matches(db, challenge.id, team, user, raw_answer)
    ):
        is_correct = True

    submission = await _record(
        db,
        user,
        challenge,
        raw_answer,
        is_correct,
        matched_answer_id,
        ip,
        request_id,
        now,
    )

    remaining = _remaining(challenge, used + 1)

    if not is_correct:
        return SubmissionOutcome(False, already is not None, 0, remaining)

    if already is not None:
        # Players do re-submit to check. Logged, no second solve, no points.
        return SubmissionOutcome(True, True, 0, remaining)

    # Bank the XP now (spec 015): the challenge's value at this moment, minus the
    # hints this player used on it. A snapshot — it never changes again, so levels
    # stay monotonic. Hints are only "paid for" here, out of the reward.
    count = await scoring.solve_count(db, challenge)
    value = scoring.challenge_value(challenge, count + 1)
    hint_cost = await _hint_cost_for(db, user.id, challenge.id)
    xp_awarded = max(0, value - hint_cost)

    solve = Solve(
        user_id=user.id,
        challenge_id=challenge.id,
        team_id_at_solve=team.id if team else None,
        submitted_at=now,
        submission_id=submission.id,
        xp_awarded=xp_awarded,
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

    return SubmissionOutcome(True, False, xp_awarded, remaining)


async def _hint_cost_for(db: AsyncSession, user_id: UUID, challenge_id: UUID) -> int:
    """Total a player has spent on hints for one challenge — the reward penalty."""
    from app.models.hint import Hint, HintUnlock

    return (
        await db.scalar(
            select(func.coalesce(func.sum(HintUnlock.cost_charged), 0))
            .select_from(HintUnlock)
            .join(Hint, Hint.id == HintUnlock.hint_id)
            .where(HintUnlock.user_id == user_id, Hint.challenge_id == challenge_id)
        )
    ) or 0


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


def _slugify(name: str) -> str:
    """A DNS-ish slug from a display name: lowercase, non-alphanumerics to hyphens."""
    slug = re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-")
    return slug or "category"


async def resolve_or_create_category(db: AsyncSession, name: str) -> Category:
    """Find a category by name (case-insensitively) or create it (spec 013).

    ``Category.name`` is CITEXT, so "web", "Web" and "WEB" resolve to one row and
    the caller gets its canonical spelling back. A genuinely new name is created
    with a derived slug; a concurrent create of the same name is caught and the
    winner's row returned, so two admins cannot make duplicates.
    """
    name = name.strip()
    existing = (
        await db.execute(select(Category).where(Category.name == name))
    ).scalar_one_or_none()
    if existing is not None:
        return existing

    slug = _slugify(name)
    if await db.scalar(select(Category.id).where(Category.slug == slug)):
        # Two different names can derive the same slug; keep it unique.
        slug = f"{slug}-{uuid.uuid4().hex[:6]}"

    category = Category(name=name, slug=slug)
    db.add(category)
    try:
        async with db.begin_nested():
            await db.flush()
    except IntegrityError:
        return (await db.execute(select(Category).where(Category.name == name))).scalar_one()
    return category


async def prune_category_if_empty(db: AsyncSession, category_id: UUID) -> bool:
    """Delete a category once its last challenge is gone (spec 013).

    Categories exist exactly as long as something is in them. The challenge FK is
    ON DELETE RESTRICT, so this can only ever remove a genuinely empty one.
    """
    remaining = await db.scalar(
        select(func.count()).select_from(Challenge).where(Challenge.category_id == category_id)
    )
    if remaining:
        return False
    category = await db.get(Category, category_id)
    if category is None:
        return False
    await db.delete(category)
    await db.flush()
    return True


# --------------------------------------------------------------------------
# Prerequisite management (admin, spec 014)
# --------------------------------------------------------------------------


class InvalidPrerequisite(AppError):
    status_code = 409
    code = "invalid_prerequisite"
    message = "That prerequisite is not allowed."


async def list_prerequisites(db: AsyncSession, challenge_id: UUID) -> list[Challenge]:
    return list(
        (
            await db.execute(
                select(Challenge)
                .join(
                    UnlockRequirement,
                    UnlockRequirement.required_challenge_id == Challenge.id,
                )
                .where(UnlockRequirement.challenge_id == challenge_id)
                .order_by(Challenge.title)
            )
        )
        .scalars()
        .all()
    )


async def add_prerequisite(
    db: AsyncSession, challenge_id: UUID, required_challenge_id: UUID
) -> None:
    """Require ``required_challenge_id`` be solved before ``challenge_id`` unlocks.

    Rejects self-reference and any cycle: if the required challenge already depends
    (transitively) on this one, adding the edge would make both permanently
    unsolvable. Idempotent — a duplicate pair is a no-op.
    """
    if challenge_id == required_challenge_id:
        raise InvalidPrerequisite("A challenge cannot require itself.", code="self_prerequisite")

    if await db.scalar(select(Challenge.id).where(Challenge.id == required_challenge_id)) is None:
        raise NotFoundError("No such challenge.")

    if await _would_cycle(db, challenge_id, required_challenge_id):
        raise InvalidPrerequisite(
            "That would create a prerequisite cycle.", code="prerequisite_cycle"
        )

    existing = await db.scalar(
        select(UnlockRequirement.id).where(
            UnlockRequirement.challenge_id == challenge_id,
            UnlockRequirement.required_challenge_id == required_challenge_id,
        )
    )
    if existing is not None:
        return

    db.add(
        UnlockRequirement(
            challenge_id=challenge_id,
            requirement_type=RequirementType.CHALLENGE_SOLVED,
            required_challenge_id=required_challenge_id,
        )
    )
    await db.flush()


async def remove_prerequisite(
    db: AsyncSession, challenge_id: UUID, required_challenge_id: UUID
) -> None:
    from sqlalchemy import delete as sql_delete

    await db.execute(
        sql_delete(UnlockRequirement).where(
            UnlockRequirement.challenge_id == challenge_id,
            UnlockRequirement.required_challenge_id == required_challenge_id,
        )
    )
    await db.flush()


async def _would_cycle(db: AsyncSession, challenge_id: UUID, required_challenge_id: UUID) -> bool:
    """True if requiring ``required_challenge_id`` reaches back to ``challenge_id``.

    Walks the prerequisite graph from the proposed requirement; if the gated
    challenge is reachable, the edge closes a loop.
    """
    seen: set[UUID] = set()
    frontier = [required_challenge_id]
    while frontier:
        current = frontier.pop()
        if current == challenge_id:
            return True
        if current in seen:
            continue
        seen.add(current)
        parents = (
            (
                await db.execute(
                    select(UnlockRequirement.required_challenge_id).where(
                        UnlockRequirement.challenge_id == current
                    )
                )
            )
            .scalars()
            .all()
        )
        frontier.extend(p for p in parents if p is not None)
    return False
