"""What a party has claimed, zone by zone (spec 067).

Spec 005 scores a challenge **once per party** however many members solve it:
*"size buys speed and coverage, never a higher ceiling."* The consequence is that
two members working the same challenge is wasted effort, and until this nothing
on the platform said so.

Coverage is the union rule made visible. The bar moves when *anybody* clears
something, because that is exactly what the scoring does.

**Members only.** Another party's coverage is not a view, it is reconnaissance:
it would name the zones a rival has not touched and the challenges nobody has
claimed. The route enforces that; this module assumes it has already happened.
"""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.challenge import Challenge, ChallengeState
from app.models.play import Solve
from app.models.team import TeamMembership
from app.models.user import User
from app.services.challenges import PLAYER_VISIBLE


@dataclass(frozen=True)
class ZoneCoverage:
    name: str
    slug: str
    cleared: int
    total: int
    #: Every challenge in it is locked for the whole party.
    sealed: bool


@dataclass(frozen=True)
class PartyProgress:
    zones: list[ZoneCoverage]
    #: challenge id → the member who got there first. Absent when unclaimed.
    solved_by: dict[str, str]


async def for_team(db: AsyncSession, team_id: UUID, now: datetime) -> PartyProgress:
    members = (
        (
            await db.execute(
                select(TeamMembership.user_id).where(
                    TeamMembership.team_id == team_id,
                    TeamMembership.removed_at.is_(None),
                )
            )
        )
        .scalars()
        .all()
    )

    challenges = (
        (
            await db.execute(
                select(Challenge)
                .options(selectinload(Challenge.category))
                .where(Challenge.state != ChallengeState.DRAFT)
            )
        )
        .scalars()
        .all()
    )
    # The same player-visible set the board shows, so the denominators match what
    # members actually see (§4). Counted across the party: a zone open to one
    # member is a zone the party can work on (§7.1).
    visible = [
        challenge for challenge in challenges if challenge.effective_state(now) in PLAYER_VISIBLE
    ]

    solved_by: dict[str, str] = {}
    if members:
        rows = (
            await db.execute(
                select(Solve.challenge_id, Solve.submitted_at, Solve.user_id)
                .where(Solve.user_id.in_(members))
                .order_by(Solve.submitted_at)
            )
        ).all()
        # Ordered by time and written once per challenge, so the earliest solver
        # wins — the one spec 005's union credits.
        names = await _names(db, members)
        for challenge_id, _at, user_id in rows:
            solved_by.setdefault(str(challenge_id), names.get(user_id, "somebody"))

    by_zone: dict[str, dict] = {}
    for challenge in visible:
        zone = by_zone.setdefault(
            challenge.category.slug,
            {
                "name": challenge.category.name,
                "slug": challenge.category.slug,
                "order": challenge.category.display_order,
                "cleared": 0,
                "total": 0,
                "open": 0,
            },
        )
        zone["total"] += 1
        if challenge.effective_state(now) != ChallengeState.LOCKED:
            zone["open"] += 1
        if str(challenge.id) in solved_by:
            zone["cleared"] += 1

    return PartyProgress(
        zones=[
            ZoneCoverage(
                name=zone["name"],
                slug=zone["slug"],
                cleared=zone["cleared"],
                total=zone["total"],
                sealed=zone["open"] == 0,
            )
            for zone in sorted(by_zone.values(), key=lambda z: (z["order"], z["name"]))
        ],
        solved_by=solved_by,
    )


async def _names(db: AsyncSession, user_ids) -> dict[UUID, str]:  # noqa: ANN001
    rows = (await db.execute(select(User.id, User.display_name).where(User.id.in_(user_ids)))).all()
    return dict(rows)


async def is_member(db: AsyncSession, team_id: UUID, user_id: UUID) -> bool:
    return (
        await db.scalar(
            select(TeamMembership.id).where(
                TeamMembership.team_id == team_id,
                TeamMembership.user_id == user_id,
                TeamMembership.removed_at.is_(None),
            )
        )
    ) is not None
