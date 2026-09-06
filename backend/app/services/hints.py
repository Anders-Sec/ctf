"""Reading and unlocking hints."""

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.errors import AppError, NotFoundError
from app.models.hint import Hint, HintUnlock
from app.models.play import Solve


class HintLocked(AppError):
    status_code = 403
    code = "hint_locked"
    message = "That hint is not available yet."


@dataclass(frozen=True)
class HintView:
    hint: Hint
    unlocked: bool
    #: False when a prerequisite is unbought or the reveal time has not come.
    available: bool
    #: What unlocking would cost right now — zero once the challenge is solved.
    effective_cost: int


@dataclass(frozen=True)
class UnlockResult:
    body: str
    cost_charged: int
    already_unlocked: bool


async def list_for_challenge(
    db: AsyncSession, challenge_id: UUID, user_id: UUID, now: datetime | None = None
) -> list[HintView]:
    now = now or datetime.now(UTC)

    hints = (
        (
            await db.execute(
                select(Hint)
                .where(Hint.challenge_id == challenge_id)
                .order_by(Hint.display_order, Hint.created_at)
            )
        )
        .scalars()
        .all()
    )
    if not hints:
        return []

    unlocked_ids = set(
        (
            await db.execute(
                select(HintUnlock.hint_id).where(
                    HintUnlock.user_id == user_id,
                    HintUnlock.hint_id.in_([hint.id for hint in hints]),
                )
            )
        )
        .scalars()
        .all()
    )
    solved = await _has_solved(db, user_id, challenge_id)

    return [
        HintView(
            hint=hint,
            unlocked=hint.id in unlocked_ids,
            available=_is_available(hint, unlocked_ids, now),
            effective_cost=0 if solved else hint.cost,
        )
        for hint in hints
    ]


def _is_available(hint: Hint, unlocked_ids: set[UUID], now: datetime) -> bool:
    """Both gates are optional and independent: a ladder, a schedule, or neither."""
    not_yet = hint.available_after is not None and now < hint.available_after
    prerequisite_unmet = (
        hint.prerequisite_hint_id is not None and hint.prerequisite_hint_id not in unlocked_ids
    )
    return not (not_yet or prerequisite_unmet)


async def _has_solved(db: AsyncSession, user_id: UUID, challenge_id: UUID) -> bool:
    return (
        await db.scalar(
            select(Solve.id).where(Solve.user_id == user_id, Solve.challenge_id == challenge_id)
        )
    ) is not None


async def unlock(
    db: AsyncSession,
    hint_id: UUID,
    challenge_id: UUID,
    user_id: UUID,
    now: datetime | None = None,
) -> UnlockResult:
    """Buy a hint. Idempotent, and free once the challenge is solved."""
    now = now or datetime.now(UTC)

    hint = (
        await db.execute(select(Hint).where(Hint.id == hint_id, Hint.challenge_id == challenge_id))
    ).scalar_one_or_none()
    if hint is None:
        raise NotFoundError("No such hint.")

    existing = (
        await db.execute(
            select(HintUnlock).where(HintUnlock.user_id == user_id, HintUnlock.hint_id == hint_id)
        )
    ).scalar_one_or_none()
    if existing is not None:
        # Players double-click. Hand back the body, charge nothing again.
        return UnlockResult(hint.body, 0, True)

    unlocked_ids = set(
        (await db.execute(select(HintUnlock.hint_id).where(HintUnlock.user_id == user_id)))
        .scalars()
        .all()
    )
    if not _is_available(hint, unlocked_ids, now):
        raise HintLocked

    # Free after solving: reading the hint to see what you missed is the
    # behaviour a learning event should encourage, not charge for.
    cost = 0 if await _has_solved(db, user_id, challenge_id) else hint.cost

    record = HintUnlock(user_id=user_id, hint_id=hint_id, cost_charged=cost, unlocked_at=now)
    try:
        # A savepoint: losing this race is not an error, and rolling back the
        # session would discard whatever else the request had done.
        async with db.begin_nested():
            db.add(record)
    except IntegrityError:
        return UnlockResult(hint.body, 0, True)

    return UnlockResult(hint.body, cost, False)


async def total_hint_cost(db: AsyncSession, user_id: UUID) -> int:
    return (
        await db.scalar(
            select(func.coalesce(func.sum(HintUnlock.cost_charged), 0)).where(
                HintUnlock.user_id == user_id
            )
        )
    ) or 0
