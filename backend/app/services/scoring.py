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

from app.models.challenge import Challenge, DecayBasis, ScoringMode
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
    """A player's total.

    ``sum(current value of solved challenges) + sum(adjustments) - sum(hint costs)``

    Can go negative: someone who buys hints and solves nothing has spent more
    than they earned. That is the correct arithmetic, and the scoreboard shows
    it rather than clamping at zero.
    """
    solved = (
        (
            await db.execute(
                select(Challenge)
                .join(Solve, Solve.challenge_id == Challenge.id)
                .where(Solve.user_id == user_id)
            )
        )
        .scalars()
        .all()
    )

    player_counts = await solve_counts_for(db, [c.id for c in solved])
    team_counts = await team_solve_counts_for(
        db, [c.id for c in solved if c.decay_basis == DecayBasis.TEAMS]
    )

    total = 0
    for challenge in solved:
        counts = team_counts if challenge.decay_basis == DecayBasis.TEAMS else player_counts
        total += challenge_value(challenge, counts.get(challenge.id, 0))

    adjustments = (
        await db.scalar(
            select(func.coalesce(func.sum(ScoreAdjustment.points), 0)).where(
                ScoreAdjustment.user_id == user_id
            )
        )
    ) or 0

    # Imported here rather than at module scope: hints depend on Solve, and a
    # top-level import would close the cycle.
    from app.services.hints import total_hint_cost

    return total + adjustments - await total_hint_cost(db, user_id)
