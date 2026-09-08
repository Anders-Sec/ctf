"""Computing both boards.

Everything is derived from Postgres in one pass. Dynamic scoring means a single
solve changes the value of that challenge for everyone who has solved it, so
there is no useful notion of an incremental update — a whole recompute at this
scale is one handful of grouped queries and tens of milliseconds.

**The party rule:** a party scores the sum of the current value of each
*distinct* challenge solved by any current member, minus the cost of each
*distinct* hint any current member unlocked, plus their adjustments. A party of
one and a party of eight therefore have the same attainable maximum: size buys
speed and coverage, never a higher ceiling.
"""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.play import ScoreAdjustment, Solve
from app.models.team import Team, TeamMembership
from app.models.user import User, UserRole, UserStatus
from app.services.scoring import level_for_xp


@dataclass(frozen=True)
class PlayerEntry:
    rank: int
    user_id: UUID
    display_name: str
    has_avatar: bool
    team_id: UUID | None
    team_name: str | None
    score: int
    level: int
    solve_count: int
    #: When this entry last gained points. Ties break on who got there first.
    last_gain_at: datetime | None


@dataclass(frozen=True)
class TeamEntry:
    rank: int
    team_id: UUID
    name: str
    member_count: int
    score: int
    level: int
    #: Distinct challenges solved by any current member.
    solve_count: int
    last_gain_at: datetime | None


@dataclass(frozen=True)
class Boards:
    players: list[PlayerEntry]
    teams: list[TeamEntry]
    generated_at: datetime


async def compute(db: AsyncSession, now: datetime) -> Boards:
    level_base = get_settings().xp_level_base

    solves = (
        await db.execute(
            select(Solve.user_id, Solve.challenge_id, Solve.submitted_at, Solve.xp_awarded)
        )
    ).all()
    adjustments = (
        await db.execute(
            select(
                ScoreAdjustment.user_id,
                ScoreAdjustment.team_id,
                ScoreAdjustment.points,
                ScoreAdjustment.created_at,
            )
        )
    ).all()

    players = (
        (
            await db.execute(
                select(User).where(
                    User.status == UserStatus.ACTIVE,
                    # Staff accounts exist to run the event, not to win it.
                    User.role == UserRole.PLAYER,
                )
            )
        )
        .scalars()
        .all()
    )
    memberships = (
        await db.execute(
            select(TeamMembership.team_id, TeamMembership.user_id)
            .join(Team, Team.id == TeamMembership.team_id)
            .where(TeamMembership.removed_at.is_(None), Team.disbanded_at.is_(None))
        )
    ).all()
    teams = (await db.execute(select(Team).where(Team.disbanded_at.is_(None)))).scalars().all()

    eligible = {player.id for player in players}

    # (submitted_at, xp) per solve; XP is banked, hints already netted out.
    solves_by_user: dict[UUID, dict[UUID, tuple[datetime, int]]] = {}
    for user_id, challenge_id, submitted_at, xp in solves:
        solves_by_user.setdefault(user_id, {})[challenge_id] = (submitted_at, xp)

    adjust_by_user: dict[UUID, int] = {}
    adjust_gain_at: dict[UUID, datetime] = {}
    # Party-scoped adjustments belong to the party, never to a member, so they
    # move the party board without touching anybody's personal score.
    adjust_by_team: dict[UUID, int] = {}
    team_adjust_gain_at: dict[UUID, datetime] = {}

    for user_id, team_id, points, created_at in adjustments:
        target, totals, gains = (
            (user_id, adjust_by_user, adjust_gain_at)
            if user_id is not None
            else (team_id, adjust_by_team, team_adjust_gain_at)
        )
        if target is None:
            continue
        totals[target] = totals.get(target, 0) + points
        if points > 0:
            previous = gains.get(target)
            gains[target] = max(previous, created_at) if previous else created_at

    team_of_user = {user_id: team_id for team_id, user_id in memberships}
    # Every live party gets an entry, even an empty one: it may still hold a
    # party-scoped adjustment, and it can be rejoined.
    members_of_team = {team.id: [] for team in teams}
    for team_id, user_id in memberships:
        if user_id in eligible:
            members_of_team.setdefault(team_id, []).append(user_id)

    team_names = {team.id: team.name for team in teams}

    player_entries = _rank_players(
        players,
        solves_by_user,
        adjust_by_user,
        adjust_gain_at,
        team_of_user,
        team_names,
        level_base,
    )
    team_entries = _rank_teams(
        members_of_team,
        team_names,
        solves_by_user,
        adjust_by_user,
        adjust_gain_at,
        adjust_by_team,
        team_adjust_gain_at,
        level_base,
    )

    return Boards(players=player_entries, teams=team_entries, generated_at=now)


def _rank_players(
    players,  # noqa: ANN001 - list[User]
    solves_by_user: dict[UUID, dict[UUID, tuple[datetime, int]]],
    adjust_by_user: dict[UUID, int],
    adjust_gain_at: dict[UUID, datetime],
    team_of_user: dict[UUID, UUID],
    team_names: dict[UUID, str],
    level_base: int,
) -> list[PlayerEntry]:
    rows = []
    for player in players:
        solved = solves_by_user.get(player.id, {})
        score = sum(xp for _, xp in solved.values())
        score += adjust_by_user.get(player.id, 0)

        gains = [at for at, _ in solved.values()]
        if player.id in adjust_gain_at:
            gains.append(adjust_gain_at[player.id])
        team_id = team_of_user.get(player.id)

        rows.append(
            {
                "user_id": player.id,
                "display_name": player.display_name,
                "has_avatar": player.avatar_blob is not None,
                "team_id": team_id,
                "team_name": team_names.get(team_id) if team_id else None,
                "score": score,
                "level": level_for_xp(score, level_base),
                "solve_count": len(solved),
                "last_gain_at": max(gains) if gains else None,
                "sort_name": player.display_name.casefold(),
            }
        )

    rows.sort(key=_sort_key)
    return [
        PlayerEntry(
            rank=index + 1,
            user_id=row["user_id"],
            display_name=row["display_name"],
            has_avatar=row["has_avatar"],
            team_id=row["team_id"],
            team_name=row["team_name"],
            score=row["score"],
            level=row["level"],
            solve_count=row["solve_count"],
            last_gain_at=row["last_gain_at"],
        )
        for index, row in enumerate(rows)
    ]


def _rank_teams(
    members_of_team: dict[UUID, list[UUID]],
    team_names: dict[UUID, str],
    solves_by_user: dict[UUID, dict[UUID, tuple[datetime, int]]],
    adjust_by_user: dict[UUID, int],
    adjust_gain_at: dict[UUID, datetime],
    adjust_by_team: dict[UUID, int],
    team_adjust_gain_at: dict[UUID, datetime],
    level_base: int,
) -> list[TeamEntry]:
    rows = []
    for team_id, member_ids in members_of_team.items():
        # The union: each challenge counts once however many members solved it,
        # which is what gives a party of one and of eight the same ceiling. Keep
        # the earliest solve and the XP that solve banked — the party had it then.
        solved: dict[UUID, tuple[datetime, int]] = {}
        for member_id in member_ids:
            for challenge_id, (at, xp) in solves_by_user.get(member_id, {}).items():
                existing = solved.get(challenge_id)
                if existing is None or at < existing[0]:
                    solved[challenge_id] = (at, xp)

        score = sum(xp for _, xp in solved.values())
        # Members' own adjustments count because their personal scores are part
        # of the party; the party's own count once.
        score += sum(adjust_by_user.get(member_id, 0) for member_id in member_ids)
        score += adjust_by_team.get(team_id, 0)

        gains = [at for at, _ in solved.values()]
        gains += [adjust_gain_at[m] for m in member_ids if m in adjust_gain_at]
        if team_id in team_adjust_gain_at:
            gains.append(team_adjust_gain_at[team_id])

        rows.append(
            {
                "team_id": team_id,
                "name": team_names.get(team_id, ""),
                "member_count": len(member_ids),
                "score": score,
                "level": level_for_xp(score, level_base),
                "solve_count": len(solved),
                "last_gain_at": max(gains) if gains else None,
                "sort_name": team_names.get(team_id, "").casefold(),
            }
        )

    rows.sort(key=_sort_key)
    return [
        TeamEntry(
            rank=index + 1,
            team_id=row["team_id"],
            name=row["name"],
            member_count=row["member_count"],
            score=row["score"],
            level=row["level"],
            solve_count=row["solve_count"],
            last_gain_at=row["last_gain_at"],
        )
        for index, row in enumerate(rows)
    ]


#: Sorts after every real timestamp, so entries that have never scored fall to
#: the bottom of their score group rather than to the top.
_NEVER = datetime.max.replace(tzinfo=None)


def _sort_key(row: dict) -> tuple[int, datetime, str]:
    """Score descending, then first-to-reach-it, then name.

    Name last so the order is total: two parties on zero points before the first
    flag lands must not shuffle between refreshes.
    """
    at = row["last_gain_at"]
    return (
        -row["score"],
        at.replace(tzinfo=None) if at is not None else _NEVER,
        row["sort_name"],
    )
