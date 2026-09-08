"""The value of a challenge, and a player's total.

Everything here is derived at read time. Nothing stores a running total — not on
a solve, not on a user, not on a team — because a decay curve plus a stored value
is a contradiction the moment the next player solves.

The curve lives behind one function so the richer modifier model can replace it
without touching submission handling or the scoreboard.
"""

import math
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.challenge import Category, Challenge, DecayBasis, ScoringMode
from app.models.play import ScoreAdjustment, Solve


def challenge_value(challenge: Challenge, solve_count: int) -> int:
    """What a challenge is worth right now, given how many have solved it.

    Quadratic decay: the value holds up for early solvers and falls away as a
    challenge turns out to be easy, reaching the floor at ``decay_threshold``
    solves and staying there.

    The same for everyone at any instant, earlier solvers included. A player's
    total therefore moves when someone else solves — which is the point, and is
    what stops a challenge everybody cracked from dominating the board.
    """
    if challenge.scoring == ScoringMode.STATIC:
        return challenge.initial_points

    initial = challenge.initial_points
    minimum = challenge.minimum_points
    threshold = challenge.decay_threshold

    if solve_count <= 0:
        return initial
    if solve_count >= threshold:
        return minimum

    fraction = solve_count / threshold
    decayed = initial - (initial - minimum) * (fraction**2)
    return max(minimum, math.ceil(decayed))


async def solve_count(db: AsyncSession, challenge: Challenge) -> int:
    """Distinct solvers, on the challenge's configured basis.

    On the team basis, a partyless solver counts as their own distinct solver
    rather than being dropped — otherwise their solve would be invisible to the
    curve, which is not what "count distinct teams" is meant to mean.
    """
    if challenge.decay_basis == DecayBasis.TEAMS:
        grouped = (
            select(func.coalesce(Solve.team_id_at_solve, Solve.user_id).label("solver"))
            .where(Solve.challenge_id == challenge.id)
            .distinct()
            .subquery()
        )
        return await db.scalar(select(func.count()).select_from(grouped)) or 0

    return (
        await db.scalar(
            select(func.count(func.distinct(Solve.user_id))).where(
                Solve.challenge_id == challenge.id
            )
        )
    ) or 0


async def solve_counts_for(db: AsyncSession, challenge_ids: list[UUID]) -> dict[UUID, int]:
    """Player-basis solve counts for many challenges in one query.

    The listing endpoint needs a count per challenge; doing that one query at a
    time is the classic N+1 that shows up under load and nowhere else.
    """
    if not challenge_ids:
        return {}

    rows = await db.execute(
        select(Solve.challenge_id, func.count(func.distinct(Solve.user_id)))
        .where(Solve.challenge_id.in_(challenge_ids))
        .group_by(Solve.challenge_id)
    )
    return {challenge_id: count for challenge_id, count in rows}


async def team_solve_counts_for(db: AsyncSession, challenge_ids: list[UUID]) -> dict[UUID, int]:
    """The same, on the team basis."""
    if not challenge_ids:
        return {}

    distinct_solvers = (
        select(
            Solve.challenge_id.label("challenge_id"),
            func.coalesce(Solve.team_id_at_solve, Solve.user_id).label("solver"),
        )
        .where(Solve.challenge_id.in_(challenge_ids))
        .distinct()
        .subquery()
    )
    rows = await db.execute(
        select(distinct_solvers.c.challenge_id, func.count())
        .select_from(distinct_solvers)
        .group_by(distinct_solvers.c.challenge_id)
    )
    return {challenge_id: count for challenge_id, count in rows}


async def user_score(db: AsyncSession, user_id: UUID) -> int:
    """A player's total XP (spec 015).

    ``sum(banked solve XP) + sum(adjustments)``. Hints are already netted out of
    each solve's banked XP, so there is no separate subtraction. Banked XP never
    changes, so this only moves down if an admin applies a negative adjustment.
    """
    return await total_xp(db, user_id)


async def total_xp(db: AsyncSession, user_id: UUID) -> int:
    banked = (
        await db.scalar(
            select(func.coalesce(func.sum(Solve.xp_awarded), 0)).where(Solve.user_id == user_id)
        )
    ) or 0
    adjustments = (
        await db.scalar(
            select(func.coalesce(func.sum(ScoreAdjustment.points), 0)).where(
                ScoreAdjustment.user_id == user_id
            )
        )
    ) or 0
    return banked + adjustments


async def skill_xp_for_user(db: AsyncSession, user_id: UUID) -> dict[UUID, int]:
    """Banked XP grouped by the skill each solve's category maps to.

    A category with no skill is left out here but still counts in ``total_xp``,
    so the skill slices partition only the mapped part of the pool.
    """
    rows = await db.execute(
        select(Category.skill_id, func.coalesce(func.sum(Solve.xp_awarded), 0))
        .select_from(Solve)
        .join(Challenge, Challenge.id == Solve.challenge_id)
        .join(Category, Category.id == Challenge.category_id)
        .where(Solve.user_id == user_id, Category.skill_id.is_not(None))
        .group_by(Category.skill_id)
    )
    return {skill_id: xp for skill_id, xp in rows}


def xp_for_level(level: int, base: int | None = None) -> int:
    """Cumulative XP needed to reach ``level``. Level 1 is 0 (spec 015)."""
    base = base if base is not None else get_settings().xp_level_base
    return base * level * (level - 1)


def level_for_xp(xp: int, base: int | None = None) -> int:
    """The level a total of ``xp`` reaches, on the standard curve.

    Level L needs cumulative ``base*L*(L-1)`` XP, so higher levels cost more.
    """
    base = base if base is not None else get_settings().xp_level_base
    if xp <= 0 or base <= 0:
        return 1
    level = int((1 + math.sqrt(1 + 4 * xp / base)) / 2)
    while xp_for_level(level + 1, base) <= xp:
        level += 1
    while level > 1 and xp_for_level(level, base) > xp:
        level -= 1
    return level
