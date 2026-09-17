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

Boss stars follow the same union rule, keyed on the boss's slug (spec 059 §3),
for the same reason: summing per-member counts would quietly make an eight-person
party look eight times as decorated.

``score`` is computed here and carried on every entry, because rank is derived
from it and the admin board (spec 051) splits it into its halves. It is stripped
on the way out to the public boards — see ``scoreboard_cache.public_view``.
"""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.character_class import CharacterClass
from app.models.play import ScoreAdjustment, Solve
from app.models.team import Team, TeamMembership
from app.models.user import User, UserRole, UserStatus
from app.services import achievements as achievement_service
from app.services import loot as loot_service
from app.services.achievements import BoardStar
from app.services.scoring import level_for_xp


@dataclass(frozen=True)
class PlayerEntry:
    #: Shared on a tie, so a board can show two third places (spec 059 §4.1).
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
    #: This player's own boss kills — never their party's. A player's decoration
    #: is theirs (spec 059 §2).
    stars: list[BoardStar]
    #: The worn loot title (038) and the class (016/024), both cosmetic and both
    #: computed-then-discarded before spec 059.
    title: str | None
    class_name: str | None
    class_rarity: str | None


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
    #: The union across current members, distinct by slug (spec 059 §3).
    stars: list[BoardStar]


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

    # Boss kills, for the star column. One query for the whole board rather
    # than one per player.
    stars = await achievement_service.board_stars(db)
    # Worn loot titles. Cosmetic — this never touches the ordering below.
    titles = await loot_service.equipped_titles(db)
    classes = {
        class_id: (name, getattr(rarity, "value", rarity))
        for class_id, name, rarity in (
            await db.execute(select(CharacterClass.id, CharacterClass.name, CharacterClass.rarity))
        ).all()
    }

    player_entries = _rank_players(
        players,
        solves_by_user,
        adjust_by_user,
        adjust_gain_at,
        team_of_user,
        team_names,
        level_base,
        stars,
        titles,
        classes,
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
        stars,
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
    stars: dict[UUID, list[BoardStar]],
    titles: dict[UUID, str],
    classes: dict[UUID, tuple[str, str]],
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
                # A player's own kills, already distinct — they cannot solve the
                # same boss twice (`uq_solve_user_challenge`).
                "stars": stars.get(player.id, []),
                "title": titles.get(player.id),
                "class_name": class_of[0]
                if (class_of := classes.get(player.character_class_id))
                else None,
                "class_rarity": class_of[1] if class_of else None,
                "sort_name": player.display_name.casefold(),
            }
        )

    rows.sort(key=_sort_key)
    return [
        PlayerEntry(
            rank=rank,
            user_id=row["user_id"],
            display_name=row["display_name"],
            has_avatar=row["has_avatar"],
            team_id=row["team_id"],
            team_name=row["team_name"],
            score=row["score"],
            level=row["level"],
            solve_count=row["solve_count"],
            last_gain_at=row["last_gain_at"],
            stars=row["stars"],
            title=row["title"],
            class_name=row["class_name"],
            class_rarity=row["class_rarity"],
        )
        for rank, row in _with_shared_ranks(rows)
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
    stars: dict[UUID, list[BoardStar]],
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
                "stars": _union_stars(member_ids, stars),
                "sort_name": team_names.get(team_id, "").casefold(),
            }
        )

    rows.sort(key=_sort_key)
    return [
        TeamEntry(
            rank=rank,
            team_id=row["team_id"],
            name=row["name"],
            member_count=row["member_count"],
            score=row["score"],
            level=row["level"],
            solve_count=row["solve_count"],
            last_gain_at=row["last_gain_at"],
            stars=row["stars"],
        )
        for rank, row in _with_shared_ranks(rows)
    ]


def _union_stars(member_ids: list[UUID], stars: dict[UUID, list[BoardStar]]) -> list[BoardStar]:
    """The distinct boss slugs this party's *current* members have felled.

    Spec 005's union rule, applied to decoration: six members who each beat *XYZ*
    give the party one `xyz` star. A member who leaves takes their unique kills
    with them, because this reads the roster it is handed.
    """
    distinct: dict[str, BoardStar] = {}
    for member_id in member_ids:
        for star in stars.get(member_id, []):
            distinct.setdefault(star.slug, star)
    return sorted(distinct.values(), key=lambda star: (-star.level, star.slug))


def _with_shared_ranks(rows: list[dict]):
    """Standard competition ranking: ``1, 2, 3, 3, 5`` (spec 059 §4.1).

    Two entries on equal points share a place, and the next entry takes the one
    its position implies. The *order* within a shared rank is untouched — it is
    still spec 005's tie-break, earliest to reach the score first — so only the
    number beside them changes.

    Takes the rows already sorted, and is the single place both boards get their
    ranks from, which is what keeps the admin board (spec 051) in step.
    """
    rank = 0
    previous_score = None
    for index, row in enumerate(rows):
        if row["score"] != previous_score:
            rank = index + 1
            previous_score = row["score"]
        yield rank, row


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
