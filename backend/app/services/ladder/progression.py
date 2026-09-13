"""Which rung of the ladder a player is on, and which flag that rung defends.

Two rules from spec 033 live here, and both are security properties rather than
bookkeeping:

1. **The level is derived server-side from solves.** Never from a header, a
   cookie, a query parameter, or anything else a player controls. A selection is
   honoured only when it is at or below the maximum their solves have earned.
2. **Level N resolves only level N's flag.** There is no function here that
   returns all six. If every flag could reach one context, breaking level 0 would
   hand over the whole ladder.

The level is per *player*, not per party. Solves and XP still aggregate to the
party, but one teammate clearing the ladder must not leave the rest of their
party facing level 5's defences with none of the practice.
"""

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.challenge import Challenge, ChallengeAnswer
from app.models.play import Solve
from app.models.user import User
from app.services.ladder.engine import MAX_LEVEL


class LevelUnavailable(Exception):
    """A level has no challenge, or its challenge has no answer.

    Raised rather than silently serving a prompt with an empty ``{{FLAG}}`` in
    it — that would be a level nobody can solve, discovered mid-event by a
    confused player rather than at the first request.
    """


async def max_level(db: AsyncSession, user_id: UUID) -> int:
    """The highest rung this player's own solves have earned, capped at 5."""
    solved = (
        await db.scalar(
            select(func.count(Solve.id))
            .join(Challenge, Challenge.id == Solve.challenge_id)
            .where(Solve.user_id == user_id, Challenge.ai_ladder_level.is_not(None))
        )
    ) or 0
    return min(MAX_LEVEL, solved)


async def effective_level(db: AsyncSession, user: User) -> tuple[int, int]:
    """``(level in force, maximum available)``.

    A null selection means "track my maximum", which is what every player gets
    until they touch the selector. A selection above the maximum is ignored
    rather than rejected: the stored value could have been written when the
    player had more solves than an admin has since left them with, and a chat
    that refuses to load is worse than one that quietly steps down a rung.
    """
    ceiling = await max_level(db, user.id)
    if user.ai_ladder_level is None:
        return ceiling, ceiling
    return min(user.ai_ladder_level, ceiling), ceiling


async def flag_for(db: AsyncSession, level: int) -> str:
    """The flag level N defends.

    One level, one flag. The unique partial index on ``ai_ladder_level`` is what
    makes this unambiguous.
    """
    value = await db.scalar(
        select(ChallengeAnswer.value)
        .join(Challenge, Challenge.id == ChallengeAnswer.challenge_id)
        .where(Challenge.ai_ladder_level == level)
        .order_by(ChallengeAnswer.display_order)
        .limit(1)
    )
    if not value:
        raise LevelUnavailable(f"ladder level {level} has no challenge answer")
    return value


async def ladder_challenge_ids(db: AsyncSession) -> list[UUID]:
    """Every ladder challenge, for the anti-cheat exemptions."""
    rows = await db.execute(select(Challenge.id).where(Challenge.ai_ladder_level.is_not(None)))
    return list(rows.scalars().all())


async def record_leak(
    db: AsyncSession, user: User, level: int, now: datetime | None = None
) -> bool:
    """Stamp the first time the System AI hands this player level 0's flag.

    This is the secret route into the ladder's zone: the flag reaching them *is*
    the discovery, so it is recorded the moment it happens rather than waiting
    for a submission they cannot yet make — the zone is shut, so there is nowhere
    to submit it until this fires.

    Only level 0 counts. A leak at a higher rung means they are already in.
    """
    if level != 0 or user.ai_ladder_leaked_at is not None:
        return False
    user.ai_ladder_leaked_at = now or datetime.now(UTC)
    await db.flush()
    return True


async def select_level(db: AsyncSession, user: User, level: int) -> int:
    """Pin the player to a rung. Returns the level now in force.

    Refuses anything above their maximum — the one place a client-supplied level
    could otherwise become the level in force.
    """
    ceiling = await max_level(db, user.id)
    if level < 0 or level > ceiling:
        raise ValueError(f"level {level} is not available")
    user.ai_ladder_level = level
    await db.flush()
    return level
