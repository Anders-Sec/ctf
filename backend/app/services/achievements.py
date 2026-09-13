"""Achievements: what a player did, noticed (spec 028).

A trigger is a **predicate over the player's stored history**, not a hook on an
event payload. That is what keeps one writable at all: "three solves inside five
minutes" or "ten wrong flags on one challenge" is a single query, where
threading enough context through every call site to answer it live would not be.
The history is already there — every submission right or wrong is timestamped,
as is every solve and hint unlock.

**There is no backfill.** An achievement created after the fact awards nothing
for work already done; the roster is seeded before the event starts. Triggers
therefore only ever run forward, after the events that could change their answer.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import timedelta
from uuid import UUID

from redis.asyncio import Redis
from sqlalchemy import distinct, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.challenge import Category, Challenge, ChallengeState
from app.models.hint import HintUnlock
from app.models.notification import (
    Achievement,
    AchievementAward,
    NotificationKind,
)
from app.models.play import Solve, Submission
from app.services import narrator, notifications

#: The events that can change a trigger's answer. A trigger declares which it
#: cares about so a solve does not re-run every unrelated query in the roster.
SOLVE = "solve"
#: Every attempt, right or wrong. The highest-frequency event on the platform,
#: so only the few triggers that genuinely need it may listen (spec 029).
SUBMIT = "submit"
HINT = "hint"
CLASS = "class"
PARTY = "party"
ASSISTANT = "assistant"
INSTANCE = "instance"


@dataclass(frozen=True)
class Trigger:
    events: frozenset[str]
    check: Callable[[AsyncSession, UUID], Awaitable[bool]]


REGISTRY: dict[str, Trigger] = {}


def trigger(code: str, *events: str):
    """Register the predicate that awards ``code``."""

    def register(fn: Callable[[AsyncSession, UUID], Awaitable[bool]]):
        REGISTRY[code] = Trigger(events=frozenset(events), check=fn)
        return fn

    return register


# --- The starter set -------------------------------------------------------
# Enough to prove the machinery end to end. The real roster arrives as seed data
# and only needs a trigger registered against its code.


@trigger("first_blood", SOLVE)
async def _first_solve(db: AsyncSession, user_id: UUID) -> bool:
    """Solved anything at all."""
    return bool(await db.scalar(select(Solve.id).where(Solve.user_id == user_id).limit(1)))


@trigger("getting_comfortable", SOLVE)
async def _ten_solves(db: AsyncSession, user_id: UUID) -> bool:
    count = await db.scalar(select(func.count(Solve.id)).where(Solve.user_id == user_id))
    return (count or 0) >= 10


@trigger("clean_sweep", SOLVE)
async def _cleared_a_zone(db: AsyncSession, user_id: UUID) -> bool:
    """Every published challenge in some category, solved."""
    published = (
        await db.execute(
            select(Challenge.category_id, func.count(Challenge.id))
            .where(Challenge.state == ChallengeState.PUBLISHED)
            .group_by(Challenge.category_id)
        )
    ).all()
    solved = dict(
        (
            await db.execute(
                select(Challenge.category_id, func.count(Solve.id))
                .join(Solve, Solve.challenge_id == Challenge.id)
                .where(Solve.user_id == user_id, Challenge.state == ChallengeState.PUBLISHED)
                .group_by(Challenge.category_id)
            )
        ).all()
    )
    return any(
        total > 0 and solved.get(category_id, 0) >= total for category_id, total in published
    )


@trigger("stubborn", SOLVE)
async def _ten_wrong_on_one(db: AsyncSession, user_id: UUID) -> bool:
    """Ten wrong flags on a single challenge, and solved it anyway."""
    worst = await db.scalar(
        select(func.count(Submission.id))
        .where(Submission.user_id == user_id, Submission.is_correct.is_(False))
        .group_by(Submission.challenge_id)
        .order_by(func.count(Submission.id).desc())
        .limit(1)
    )
    return (worst or 0) >= 10


@trigger("blitz", SOLVE)
async def _three_in_five_minutes(db: AsyncSession, user_id: UUID) -> bool:
    """Three solves inside five minutes."""
    times = (
        (
            await db.execute(
                select(Solve.submitted_at)
                .where(Solve.user_id == user_id)
                .order_by(Solve.submitted_at)
            )
        )
        .scalars()
        .all()
    )
    window = timedelta(minutes=5)
    return any(times[index + 2] - times[index] <= window for index in range(len(times) - 2))


@trigger("no_help_needed", SOLVE)
async def _ten_solves_no_hints(db: AsyncSession, user_id: UUID) -> bool:
    """Ten solves without ever taking a hint."""
    used = await db.scalar(select(HintUnlock.id).where(HintUnlock.user_id == user_id).limit(1))
    if used:
        return False
    count = await db.scalar(select(func.count(Solve.id)).where(Solve.user_id == user_id))
    return (count or 0) >= 10


@trigger("well_rounded", SOLVE)
async def _five_categories(db: AsyncSession, user_id: UUID) -> bool:
    """Solved something in five different zones."""
    count = await db.scalar(
        select(func.count(distinct(Challenge.category_id)))
        .join(Solve, Solve.challenge_id == Challenge.id)
        .where(Solve.user_id == user_id)
    )
    return (count or 0) >= 5


# --- Evaluation ------------------------------------------------------------


async def evaluate(
    db: AsyncSession, user_id: UUID, event: str, *, redis: Redis | None = None
) -> list[Achievement]:
    """Award anything this player has newly earned, and tell them.

    Only triggers that care about ``event`` run, so a solve does not re-ask every
    unrelated question in the roster.
    """
    held = set(
        (
            await db.execute(
                select(AchievementAward.achievement_id).where(AchievementAward.user_id == user_id)
            )
        )
        .scalars()
        .all()
    )
    candidates = [
        achievement
        for achievement in (await db.execute(select(Achievement))).scalars().all()
        if achievement.id not in held
        and (trigger := REGISTRY.get(achievement.code)) is not None
        and event in trigger.events
    ]

    earned: list[Achievement] = []
    for achievement in candidates:
        if not await REGISTRY[achievement.code].check(db, user_id):
            continue
        if await _award(db, achievement, user_id):
            earned.append(achievement)
            await notifications.notify(
                db,
                user_id=user_id,
                kind=NotificationKind.ACHIEVEMENT,
                title=achievement.name,
                body=narrator.achievement_earned(achievement.name, achievement.description),
                link="/character",
                redis=redis,
            )
    return earned


async def _award(db: AsyncSession, achievement: Achievement, user_id: UUID) -> bool:
    """True if this call is the one that awarded it.

    The unique constraint is the arbiter: two concurrent solves can both find the
    achievement unheld, and exactly one insert survives.
    """
    try:
        # A savepoint, not the whole transaction: rolling the session back here
        # would discard the solve that triggered this evaluation.
        async with db.begin_nested():
            db.add(AchievementAward(achievement_id=achievement.id, user_id=user_id))
    except IntegrityError:
        return False
    return True


# --- The sheet -------------------------------------------------------------


@dataclass(frozen=True)
class AchievementRow:
    id: UUID
    name: str | None
    description: str | None
    earned: bool
    #: Share of players who have solved something and hold this, 0..1.
    rarity: float | None


async def roster_for(db: AsyncSession, user_id: UUID) -> list[AchievementRow]:
    """The full list, unearned ones redacted.

    Redacted server-side, not merely blurred in CSS: a name a player has not
    earned never reaches the browser, so the mystery survives devtools.
    """
    achievements = list(
        (
            await db.execute(
                select(Achievement).order_by(Achievement.display_order, Achievement.name)
            )
        )
        .scalars()
        .all()
    )
    held = set(
        (
            await db.execute(
                select(AchievementAward.achievement_id).where(AchievementAward.user_id == user_id)
            )
        )
        .scalars()
        .all()
    )
    rarity = await rarity_by_achievement(db)

    rows: list[AchievementRow] = []
    for achievement in achievements:
        if achievement.secret and achievement.id not in held:
            continue
        earned = achievement.id in held
        rows.append(
            AchievementRow(
                id=achievement.id,
                name=achievement.name if earned else None,
                description=achievement.description if earned else None,
                earned=earned,
                rarity=rarity.get(achievement.id) if earned else None,
            )
        )
    return rows


async def rarity_by_achievement(db: AsyncSession) -> dict[UUID, float]:
    """Share of *playing* players holding each achievement.

    The denominator is players with at least one solve. Counting every
    registered account would make everything look rare in proportion to how many
    people signed up and never played, which is noise rather than signal.
    """
    players = await db.scalar(select(func.count(distinct(Solve.user_id))))
    if not players:
        return {}
    rows = (
        await db.execute(
            select(AchievementAward.achievement_id, func.count(AchievementAward.user_id)).group_by(
                AchievementAward.achievement_id
            )
        )
    ).all()
    return {achievement_id: count / players for achievement_id, count in rows}


async def rarest_held(db: AsyncSession, user_id: UUID, limit: int = 5) -> list[AchievementRow]:
    """The player's rarest earned achievements — their bragging rights."""
    earned = [row for row in await roster_for(db, user_id) if row.earned]
    return sorted(earned, key=lambda r: r.rarity if r.rarity is not None else 1.0)[:limit]


async def zone_name(db: AsyncSession, category_id: UUID) -> str:
    return (await db.scalar(select(Category.name).where(Category.id == category_id))) or "a zone"
