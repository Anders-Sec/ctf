"""Row counts and bulk operations for the Content pages (spec 058 §4).

Two jobs, both in service of the list view:

- The counts each row needs to be *scanned* — how many challenges feed a skill,
  how many people wear a class. Grouped queries for the whole page, never one
  per row: at 110 rows an N+1 is 110 round trips for a table nobody would wait
  for.
- Bulk operations, following ``challenge_bulk``'s shape — a list of ids, one
  action, and **per-item results**, so a partial failure is reported rather than
  hidden behind a success.
"""

from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.errors import ConflictError
from app.models.challenge import SkillKind
from app.models.character_class import CharacterClass, ClassPreference, ClassRequirement, Rarity
from app.models.notification import Achievement, AchievementAward, LootBoxType, LootRarity
from app.models.skill import ChallengeSkill, Skill
from app.models.user import User


@dataclass
class BulkOutcome:
    """What happened, item by item."""

    changed: int = 0
    #: id → why it was refused. A bulk delete that skipped three rows has to say
    #: which three and why, or it reads as a success that did less than asked.
    refused: dict[str, str] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {"changed": self.changed, "refused": self.refused}


# --- Counts ----------------------------------------------------------------


async def skill_usage(db: AsyncSession) -> dict[UUID, int]:
    """Challenges feeding each skill.

    Zero is the signal worth seeing: a skill no challenge feeds is XP that lands
    nowhere on anybody's sheet.
    """
    rows = await db.execute(
        select(ChallengeSkill.skill_id, func.count()).group_by(ChallengeSkill.skill_id)
    )
    return {skill_id: int(count) for skill_id, count in rows}


async def class_counts(db: AsyncSession) -> dict[UUID, dict[str, int]]:
    """Preferences, requirements and wearers, per class."""
    preferences = dict(
        (
            await db.execute(
                select(ClassPreference.class_id, func.count()).group_by(ClassPreference.class_id)
            )
        ).all()
    )
    requirements = dict(
        (
            await db.execute(
                select(ClassRequirement.class_id, func.count()).group_by(ClassRequirement.class_id)
            )
        ).all()
    )
    wearers = dict(
        (
            await db.execute(
                select(User.character_class_id, func.count())
                .where(User.character_class_id.is_not(None))
                .group_by(User.character_class_id)
            )
        ).all()
    )

    ids = set(preferences) | set(requirements) | set(wearers)
    return {
        class_id: {
            "preferences": int(preferences.get(class_id, 0)),
            "requirements": int(requirements.get(class_id, 0)),
            "wearers": int(wearers.get(class_id, 0)),
        }
        for class_id in ids
    }


# --- Bulk ------------------------------------------------------------------

SKILL_ACTIONS = {"set_kind", "set_category", "delete"}
CLASS_ACTIONS = {"set_rarity", "delete"}
ACHIEVEMENT_ACTIONS = {"set_loot_box", "set_rarity", "set_secret", "delete"}


async def bulk_skills(db: AsyncSession, ids: list[UUID], action: str, value: Any) -> BulkOutcome:
    if action not in SKILL_ACTIONS:
        raise ConflictError(f"Unknown action: {action}", code="unknown_action")

    outcome = BulkOutcome()
    rows = (await db.execute(select(Skill).where(Skill.id.in_(ids)))).scalars().all()

    if action == "delete":
        for skill in rows:
            await db.execute(delete(ChallengeSkill).where(ChallengeSkill.skill_id == skill.id))
            await db.delete(skill)
            outcome.changed += 1
        await db.flush()
        return outcome

    for skill in rows:
        if action == "set_kind":
            skill.kind = SkillKind(value)
        elif action == "set_category":
            # Null is legitimate: the model's SET NULL leaves a skill without a
            # zone rather than destroying it.
            skill.category_id = UUID(str(value)) if value else None
        outcome.changed += 1

    await db.flush()
    return outcome


async def bulk_classes(db: AsyncSession, ids: list[UUID], action: str, value: Any) -> BulkOutcome:
    if action not in CLASS_ACTIONS:
        raise ConflictError(f"Unknown action: {action}", code="unknown_action")

    outcome = BulkOutcome()
    rows = (
        (await db.execute(select(CharacterClass).where(CharacterClass.id.in_(ids)))).scalars().all()
    )

    if action == "delete":
        worn = dict(
            (
                await db.execute(
                    select(User.character_class_id, func.count())
                    .where(User.character_class_id.in_(ids))
                    .group_by(User.character_class_id)
                )
            ).all()
        )
        for character_class in rows:
            if worn.get(character_class.id):
                # The FK is SET NULL, so deleting would silently return players
                # to Classless. Refusing says so instead.
                outcome.refused[str(character_class.id)] = (
                    f"{worn[character_class.id]} players are wearing it"
                )
                continue
            await db.delete(character_class)
            outcome.changed += 1
        await db.flush()
        return outcome

    for character_class in rows:
        character_class.rarity = Rarity(value)
        outcome.changed += 1

    await db.flush()
    return outcome


async def bulk_achievements(
    db: AsyncSession, ids: list[UUID], action: str, value: Any
) -> BulkOutcome:
    if action not in ACHIEVEMENT_ACTIONS:
        raise ConflictError(f"Unknown action: {action}", code="unknown_action")

    outcome = BulkOutcome()
    rows = (await db.execute(select(Achievement).where(Achievement.id.in_(ids)))).scalars().all()

    if action == "delete":
        held = dict(
            (
                await db.execute(
                    select(AchievementAward.achievement_id, func.count())
                    .where(AchievementAward.achievement_id.in_(ids))
                    .group_by(AchievementAward.achievement_id)
                )
            ).all()
        )
        for achievement in rows:
            if held.get(achievement.id):
                # Spec 030's rule, applied in bulk: taking an achievement back
                # from somebody who earned it is worse than a badly named one.
                outcome.refused[str(achievement.id)] = f"{held[achievement.id]} players hold it"
                continue
            await db.delete(achievement)
            outcome.changed += 1
        await db.flush()
        return outcome

    for achievement in rows:
        if action == "set_loot_box":
            achievement.loot_box_type = LootBoxType(value) if value else None
            if not value:
                # A box and a rarity travel together; clearing one alone would
                # leave a rarity describing nothing.
                achievement.loot_rarity = None
        elif action == "set_rarity":
            achievement.loot_rarity = LootRarity(value) if value else None
        elif action == "set_secret":
            achievement.secret = bool(value)
        outcome.changed += 1

    await db.flush()
    return outcome
