"""Noticing that something changed, and saying so (spec 028).

A solve can move several things at once: XP, a level, an ability score, the lock
on a whole wing. None of them announced themselves before this — a zone opening
is the most narratively satisfying moment the map has, and it happened in
silence.

The shape is snapshot-diff rather than an event bus. Take a small reading of the
player before the action, take it again after, and say what moved. That keeps
the knowledge of "what counts as a change" in one place instead of scattering
it through every call site that might cause one.
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import UUID

from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.challenge import Ability, Category, UnlockRequirement
from app.models.notification import NotificationKind
from app.services import achievements, narrator, notifications, scoring, unlocks

#: Scores worth remarking on. Below 12 is noise; 20 is the cap.
ABILITY_MILESTONES = (12, 16, 20)

ABILITY_NAMES = {
    Ability.STR: "Strength",
    Ability.DEX: "Dexterity",
    Ability.CON: "Constitution",
    Ability.INT: "Intelligence",
    Ability.WIS: "Wisdom",
    Ability.CHA: "Charisma",
}


@dataclass
class Snapshot:
    level: int = 0
    abilities: dict[Ability, int] = field(default_factory=dict)
    open_zones: set[UUID] = field(default_factory=set)


async def snapshot(db: AsyncSession, user_id: UUID) -> Snapshot:
    """A small reading of the player: level, ability scores, which wings are open."""
    total = await scoring.total_xp(db, user_id)
    ability_xp = await scoring.ability_xp_for_user(db, user_id)
    return Snapshot(
        level=scoring.level_for_xp(total),
        abilities={
            ability: scoring.ability_score(ability_xp.get(ability, 0)) for ability in Ability
        },
        open_zones=await _open_zones(db, user_id),
    )


async def _open_zones(db: AsyncSession, user_id: UUID) -> set[UUID]:
    """Zone ids this player can currently enter.

    Evaluates only the category gates rather than building the whole map, which
    would be a lot of work to do twice on every solve.
    """
    requirements = list(
        (
            await db.execute(
                select(UnlockRequirement).where(UnlockRequirement.category_id.is_not(None))
            )
        )
        .scalars()
        .all()
    )
    gated = {req.category_id for req in requirements}
    all_zones = set((await db.execute(select(Category.id))).scalars().all())
    # A zone with no gate is open to everyone.
    open_zones = all_zones - gated

    statuses = await unlocks.evaluate_groups(
        db, user_id, requirements, datetime.now(UTC), key="category_id"
    )
    for category_id, status in statuses.items():
        if not status.locked:
            open_zones.add(category_id)
    return open_zones


async def announce_changes(
    db: AsyncSession,
    user_id: UUID,
    before: Snapshot,
    *,
    redis: Redis | None = None,
    event: str = achievements.SOLVE,
) -> None:
    """Diff the player against ``before`` and tell them what moved.

    Achievements first, because they are the thing the player did; the level and
    the wing are consequences of it.
    """
    await achievements.evaluate(db, user_id, event, achievements.PLATFORM, redis=redis)
    # A first boss kill is the one thing everybody hears about (spec 032).
    if event == achievements.SOLVE:
        await achievements.announce_boss_kill(db, user_id, redis=redis)

    after = await snapshot(db, user_id)

    if after.level > before.level:
        await notifications.notify(
            db,
            user_id=user_id,
            kind=NotificationKind.LEVEL_UP,
            title=f"Level {after.level}",
            body=narrator.level_up(after.level),
            link="/character",
            redis=redis,
        )

    for ability, score in after.abilities.items():
        was = before.abilities.get(ability, 0)
        # Only the highest milestone newly crossed, so a single huge solve does
        # not fire three near-identical lines about the same ability.
        crossed = [m for m in ABILITY_MILESTONES if was < m <= score]
        if crossed:
            await notifications.notify(
                db,
                user_id=user_id,
                kind=NotificationKind.ABILITY_MILESTONE,
                title=f"{ABILITY_NAMES[ability]} {max(crossed)}",
                body=narrator.ability_milestone(ABILITY_NAMES[ability], max(crossed)),
                link="/character",
                redis=redis,
            )

    for zone_id in after.open_zones - before.open_zones:
        name = await achievements.zone_name(db, zone_id)
        await notifications.notify(
            db,
            user_id=user_id,
            kind=NotificationKind.ZONE_UNLOCKED,
            title=f"{name} is open",
            body=narrator.zone_unlocked(name),
            link="/challenges",
            redis=redis,
        )
