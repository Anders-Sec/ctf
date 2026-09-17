"""The staff view of the board (spec 051 §3).

Built *on top of* the public board rather than beside it. Ranks and totals come
from exactly the same computation, so the two surfaces can never disagree about
who is winning — the whole point of this page is settling that question, and a
second ranking that drifted would be worse than no page at all.

What it adds is the three things the public board deliberately withholds:

- the split between solve points and manual adjustments,
- the tie-break timestamp that decided a close placement,
- the accounts that score but are not ranked (disabled, or staff).
"""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from redis.asyncio import Redis
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.play import ScoreAdjustment, Solve
from app.models.team import Team, TeamMembership
from app.models.user import User, UserRole, UserStatus
from app.services import scoreboard_cache


async def _adjustments(db: AsyncSession) -> tuple[dict[UUID, int], dict[UUID, int]]:
    """Manual points, per player and per party.

    A party-scoped adjustment belongs to the party and never to a member, which
    is why these are two maps rather than one — the same rule the public board
    computes under.
    """
    by_user: dict[UUID, int] = {}
    by_team: dict[UUID, int] = {}

    rows = await db.execute(
        select(
            ScoreAdjustment.user_id,
            ScoreAdjustment.team_id,
            func.sum(ScoreAdjustment.points),
        ).group_by(ScoreAdjustment.user_id, ScoreAdjustment.team_id)
    )
    for user_id, team_id, points in rows:
        if user_id is not None:
            by_user[user_id] = by_user.get(user_id, 0) + int(points or 0)
        elif team_id is not None:
            by_team[team_id] = by_team.get(team_id, 0) + int(points or 0)

    return by_user, by_team


async def _unranked(db: AsyncSession, by_user: dict[UUID, int]) -> list[dict[str, Any]]:
    """Accounts with points that the public board leaves out.

    A player disabled mid-event vanishes from the board and everyone below moves
    up; an admin settling a placement needs to see that happened. Listed
    separately rather than woven into the ranking, because giving them ranks
    would make this board disagree with the public one about every position
    below them.
    """
    excluded = (
        (
            await db.execute(
                select(User).where(
                    (User.status != UserStatus.ACTIVE) | (User.role != UserRole.PLAYER)
                )
            )
        )
        .scalars()
        .all()
    )

    solve_totals = dict(
        (
            await db.execute(
                select(Solve.user_id, func.coalesce(func.sum(Solve.xp_awarded), 0)).group_by(
                    Solve.user_id
                )
            )
        ).all()
    )

    rows = []
    for user in excluded:
        solve_points = int(solve_totals.get(user.id, 0))
        adjustment_points = by_user.get(user.id, 0)
        if solve_points == 0 and adjustment_points == 0:
            # Never played. Listing every staff account and every unapproved
            # signup would bury the one disabled player this section exists for.
            continue
        rows.append(
            {
                "user_id": str(user.id),
                "display_name": user.display_name,
                "solve_points": solve_points,
                "adjustment_points": adjustment_points,
                "score": solve_points + adjustment_points,
                "status": user.status.value,
                "role": user.role.value,
                "reason": "disabled" if user.status != UserStatus.ACTIVE else "staff",
            }
        )

    rows.sort(key=lambda row: row["score"], reverse=True)
    return rows


async def _eligible_members(db: AsyncSession) -> dict[UUID, list[UUID]]:
    """Active members per live party, matching the public board's rule exactly.

    A disabled member stops contributing to their party's score, so they have to
    be excluded here too — otherwise the adjustment half of the split would
    include points the total does not.
    """
    rows = await db.execute(
        select(TeamMembership.team_id, TeamMembership.user_id)
        .join(Team, Team.id == TeamMembership.team_id)
        .join(User, User.id == TeamMembership.user_id)
        .where(
            TeamMembership.removed_at.is_(None),
            Team.disbanded_at.is_(None),
            User.status == UserStatus.ACTIVE,
            User.role == UserRole.PLAYER,
        )
    )
    members: dict[UUID, list[UUID]] = {}
    for team_id, user_id in rows:
        members.setdefault(team_id, []).append(user_id)
    return members


async def board(db: AsyncSession, redis: Redis) -> dict[str, Any]:
    by_user, by_team = await _adjustments(db)
    members = await _eligible_members(db)
    payload = await scoreboard_cache.refresh(db, redis)

    def split(row: dict[str, Any], adjustment: int) -> dict[str, Any]:
        # `score` is authoritative and comes from the public computation. The
        # solve half is derived by subtraction rather than recomputed, so the
        # two halves always add back to the number on the public board.
        return {**row, "adjustment_points": adjustment, "solve_points": row["score"] - adjustment}

    def party_adjustment(team_id: UUID) -> int:
        # A party carries its members' personal adjustments as well as its own —
        # their personal scores are part of the party. Same rule the public
        # board totals under.
        return by_team.get(team_id, 0) + sum(
            by_user.get(member_id, 0) for member_id in members.get(team_id, [])
        )

    return {
        "generated_at": payload["generated_at"],
        "server_time": datetime.now(UTC).isoformat(),
        "players": [
            split(row, by_user.get(UUID(str(row["user_id"])), 0)) for row in payload["players"]
        ],
        "teams": [
            split(row, party_adjustment(UUID(str(row["team_id"])))) for row in payload["teams"]
        ],
        "unranked": await _unranked(db, by_user),
    }
