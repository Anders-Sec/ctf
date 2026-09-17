"""The party detail panel (spec 059 §5).

Reached from both boards — the party board's rows and the player board's Party
column open the same thing — because what a player wants is a glance at who a
party is, and that does not earn a route of its own.

**No XP, including no member XP.** A per-member XP list would be the
scoreboard's worst habit reintroduced one level down.

Everything except the achievement count and the founding date is read straight
off the board payload, so the panel cannot disagree with the list it was opened
from: the same rank, the same stars, the same levels.
"""

from typing import Any
from uuid import UUID

from redis.asyncio import Redis
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.errors import NotFoundError
from app.models.notification import AchievementAward
from app.models.team import Team, TeamMembership
from app.services import scoreboard_cache


async def detail(db: AsyncSession, redis: Redis, team_id: UUID) -> dict[str, Any]:
    team = await db.get(Team, team_id)
    if team is None or team.disbanded_at is not None:
        # A disbanded party is not on the board it would have been opened from,
        # so there is nothing to show and nothing to explain.
        raise NotFoundError("No such party.")

    payload = await scoreboard_cache.refresh(db, redis)
    entry = next(
        (row for row in payload["teams"] if row["team_id"] == str(team_id)),
        None,
    )
    if entry is None:
        raise NotFoundError("No such party.")

    members = [
        {
            "user_id": row["user_id"],
            "display_name": row["display_name"],
            "has_avatar": row["has_avatar"],
            "level": row["level"],
            "class_name": row["class_name"],
            "class_rarity": row["class_rarity"],
        }
        # Board order, so the roster reads strongest-first without a second sort
        # and without publishing the number that produced it.
        for row in payload["players"]
        if row["team_id"] == str(team_id)
    ]

    return {
        "team_id": str(team_id),
        "name": entry["name"],
        "rank": entry["rank"],
        "level": entry["level"],
        "member_count": entry["member_count"],
        "solve_count": entry["solve_count"],
        "stars": entry["stars"],
        "achievement_count": await _achievement_count(db, team_id),
        "founded_at": team.created_at.isoformat(),
        "members": members,
    }


async def _achievement_count(db: AsyncSession, team_id: UUID) -> int:
    """Distinct achievements held by the party's current members.

    Distinct rather than summed, matching how the party's score and its stars are
    computed (spec 005): two members who both earned *First Blood* have earned the
    party one achievement, not two.
    """
    return int(
        await db.scalar(
            select(func.count(func.distinct(AchievementAward.achievement_id)))
            .join(TeamMembership, TeamMembership.user_id == AchievementAward.user_id)
            .where(
                TeamMembership.team_id == team_id,
                TeamMembership.removed_at.is_(None),
            )
        )
        or 0
    )
