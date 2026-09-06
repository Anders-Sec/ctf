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

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.challenge import Challenge, DecayBasis
from app.models.hint import HintUnlock
from app.models.play import ScoreAdjustment, Solve
from app.models.team import Team, TeamMembership
from app.models.user import User, UserRole, UserStatus
from app.services.scoring import challenge_value


@dataclass(frozen=True)
class PlayerEntry:
    rank: int
    user_id: UUID
    display_name: str
    has_avatar: bool
    team_id: UUID | None
    team_name: str | None
    score: int
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
    #: Distinct challenges solved by any current member.
    solve_count: int
    last_gain_at: datetime | None


@dataclass(frozen=True)
class Boards:
    players: list[PlayerEntry]
    teams: list[TeamEntry]
    generated_at: datetime


async def compute(db: AsyncSession, now: datetime) -> Boards:
    challenge_values = await _challenge_values(db)

    solves = (await db.execute(select(Solve.user_id, Solve.challenge_id, Solve.submitted_at))).all()
    adjustments = (
        await db.execute(
            select(ScoreAdjustment.user_id, ScoreAdjustment.points, ScoreAdjustment.created_at)
        )
    ).all()
    unlocks = (
        await db.execute(select(HintUnlock.user_id, HintUnlock.hint_id, HintUnlock.cost_charged))
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

    solves_by_user: dict[UUID, dict[UUID, datetime]] = {}
    for user_id, challenge_id, submitted_at in solves:
        solves_by_user.setdefault(user_id, {})[challenge_id] = submitted_at

    unlocks_by_user: dict[UUID, dict[UUID, int]] = {}
    for user_id, hint_id, cost in unlocks:
        unlocks_by_user.setdefault(user_id, {})[hint_id] = cost

    adjust_by_user: dict[UUID, int] = {}
    adjust_gain_at: dict[UUID, datetime] = {}
    for user_id, points, created_at in adjustments:
        adjust_by_user[user_id] = adjust_by_user.get(user_id, 0) + points
        if points > 0:
            previous = adjust_gain_at.get(user_id)
            adjust_gain_at[user_id] = max(previous, created_at) if previous else created_at

    team_of_user = {user_id: team_id for team_id, user_id in memberships}
    members_of_team: dict[UUID, list[UUID]] = {}
    for team_id, user_id in memberships:
        if user_id in eligible:
            members_of_team.setdefault(team_id, []).append(user_id)

    team_names = {team.id: team.name for team in teams}

    player_entries = _rank_players(
        players,
        challenge_values,
        solves_by_user,
        unlocks_by_user,
        adjust_by_user,
        adjust_gain_at,
        team_of_user,
        team_names,
    )
    team_entries = _rank_teams(
        members_of_team,
        team_names,
        challenge_values,
        solves_by_user,
        unlocks_by_user,
        adjust_by_user,
        adjust_gain_at,
    )

    return Boards(players=player_entries, teams=team_entries, generated_at=now)


async def _challenge_values(db: AsyncSession) -> dict[UUID, int]:
    """Every challenge's value right now, on its own configured decay basis."""
    challenges = (await db.execute(select(Challenge))).scalars().all()
    if not challenges:
        return {}

    player_counts = dict(
        (
            await db.execute(
                select(Solve.challenge_id, func.count(func.distinct(Solve.user_id))).group_by(
                    Solve.challenge_id
                )
            )
        ).all()
    )

    distinct_solvers = (
        select(
            Solve.challenge_id.label("challenge_id"),
            func.coalesce(Solve.team_id_at_solve, Solve.user_id).label("solver"),
        )
        .distinct()
        .subquery()
    )
    team_counts = dict(
        (
            await db.execute(
                select(distinct_solvers.c.challenge_id, func.count())
                .select_from(distinct_solvers)
                .group_by(distinct_solvers.c.challenge_id)
            )
        ).all()
    )

    values = {}
    for challenge in challenges:
        counts = team_counts if challenge.decay_basis == DecayBasis.TEAMS else player_counts
        values[challenge.id] = challenge_value(challenge, counts.get(challenge.id, 0))
    return values


def _rank_players(
    players,  # noqa: ANN001 - list[User]
    values: dict[UUID, int],
    solves_by_user: dict[UUID, dict[UUID, datetime]],
    unlocks_by_user: dict[UUID, dict[UUID, int]],
    adjust_by_user: dict[UUID, int],
    adjust_gain_at: dict[UUID, datetime],
    team_of_user: dict[UUID, UUID],
    team_names: dict[UUID, str],
) -> list[PlayerEntry]:
    rows = []
    for player in players:
        solved = solves_by_user.get(player.id, {})
        score = sum(values.get(challenge_id, 0) for challenge_id in solved)
        score += adjust_by_user.get(player.id, 0)
        score -= sum(unlocks_by_user.get(player.id, {}).values())

        gains = list(solved.values())
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
            solve_count=row["solve_count"],
            last_gain_at=row["last_gain_at"],
        )
        for index, row in enumerate(rows)
    ]


def _rank_teams(
    members_of_team: dict[UUID, list[UUID]],
    team_names: dict[UUID, str],
    values: dict[UUID, int],
    solves_by_user: dict[UUID, dict[UUID, datetime]],
    unlocks_by_user: dict[UUID, dict[UUID, int]],
    adjust_by_user: dict[UUID, int],
    adjust_gain_at: dict[UUID, datetime],
) -> list[TeamEntry]:
    rows = []
    for team_id, member_ids in members_of_team.items():
        # The union: each challenge counts once however many members solved it,
        # which is what gives a party of one and a party of eight the same
        # ceiling. Keep the earliest solve time — the party had it from then.
        solved: dict[UUID, datetime] = {}
        for member_id in member_ids:
            for challenge_id, at in solves_by_user.get(member_id, {}).items():
                existing = solved.get(challenge_id)
                solved[challenge_id] = min(existing, at) if existing else at

        # Hints likewise, at the lowest price any member paid: if one of them
        # got it free because they had already solved, the party is not charged.
        hint_costs: dict[UUID, int] = {}
        for member_id in member_ids:
            for hint_id, cost in unlocks_by_user.get(member_id, {}).items():
                existing = hint_costs.get(hint_id)
                hint_costs[hint_id] = min(existing, cost) if existing is not None else cost

        score = sum(values.get(challenge_id, 0) for challenge_id in solved)
        score -= sum(hint_costs.values())
        # Adjustments are summed, not unioned. They are per-person compensation,
        # and the one thing that can carry a party past the nominal ceiling.
        score += sum(adjust_by_user.get(member_id, 0) for member_id in member_ids)

        gains = list(solved.values())
        gains += [adjust_gain_at[m] for m in member_ids if m in adjust_gain_at]

        rows.append(
            {
                "team_id": team_id,
                "name": team_names.get(team_id, ""),
                "member_count": len(member_ids),
                "score": score,
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
