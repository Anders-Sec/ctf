"""Assembling a character sheet (spec 015, extended by 016).

One player's XP, level, ability scores and skills, read from the banked solve XP,
plus their class and whether the picker is unlocked.

Abilities **partition** the pool — every category feeds exactly one — while skills
**overlap**, since a challenge feeds each of its skills in full. Skill XP is never
returned; an undiscovered skill is redacted here rather than hidden by the client.

Board rank is layered on by the route from the cached scoreboard.
"""

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.errors import AppError, NotFoundError
from app.models.challenge import Ability
from app.models.character_class import CharacterClass
from app.models.skill import Skill
from app.models.user import User
from app.services import scoring


class ClassLocked(AppError):
    status_code = 403
    code = "class_locked"
    message = "You have not reached the level to choose a class yet."


#: What an undiscovered skill is called. The real name never leaves the server —
#: some skills are meant to be rare surprises, and a CSS blur over the true string
#: would leak every one of them to anyone who opened devtools.
UNDISCOVERED_NAME = "Undiscovered skill"


@dataclass(frozen=True)
class AbilityScore:
    ability: str
    score: int


@dataclass(frozen=True)
class SkillRow:
    """A skill as the player may see it: a name and a level, and nothing else.

    No XP, in the dataclass or the response — the numbers cannot leak if they are
    never carried.
    """

    skill_id: UUID
    name: str
    kind: str
    level: int
    discovered: bool


@dataclass(frozen=True)
class ClassInfo:
    id: UUID
    name: str
    description: str | None


@dataclass(frozen=True)
class Sheet:
    user_id: UUID
    display_name: str
    has_avatar: bool
    total_xp: int
    level: int
    xp_into_level: int
    xp_to_next: int
    abilities: list[AbilityScore]
    skills: list[SkillRow]
    character_class: ClassInfo | None
    class_unlocked: bool
    class_unlock_level: int


async def build_sheet(db: AsyncSession, user: User) -> Sheet:
    settings = get_settings()

    total = await scoring.total_xp(db, user.id)
    level, into, to_next = scoring.level_progress(total, settings.xp_level_base)

    # Abilities partition the pool: every category feeds exactly one, so a solve's
    # XP lands in one score and no other. Unearned abilities still show, at 8.
    ability_xp = await scoring.ability_xp_for_user(db, user.id)
    abilities = [
        AbilityScore(ability=ability.value, score=scoring.ability_score(ability_xp.get(ability, 0)))
        for ability in Ability
    ]

    by_skill = await scoring.skill_xp_for_user(db, user.id)
    skills = (
        (await db.execute(select(Skill).order_by(Skill.display_order, Skill.name))).scalars().all()
    )
    rows = []
    for skill in skills:
        skill_level = scoring.skill_level(by_skill.get(skill.id, 0))
        discovered = skill_level > 0
        rows.append(
            SkillRow(
                skill_id=skill.id,
                # Redacted server-side, not merely hidden by the client.
                name=skill.name if discovered else UNDISCOVERED_NAME,
                kind=skill.kind.value,
                level=skill_level,
                discovered=discovered,
            )
        )

    return Sheet(
        user_id=user.id,
        display_name=user.display_name,
        has_avatar=user.avatar_blob is not None,
        total_xp=total,
        level=level,
        xp_into_level=into,
        xp_to_next=to_next,
        abilities=abilities,
        skills=rows,
        character_class=await _class_info(db, user.character_class_id),
        class_unlocked=level >= settings.class_unlock_level,
        class_unlock_level=settings.class_unlock_level,
    )


async def set_class(db: AsyncSession, user: User, class_id: UUID | None) -> ClassInfo | None:
    """Set or clear the player's own class (spec 016).

    Gated on the unlock level, but only for a *first* choice: a player who has
    already earned a class may change or clear it freely, even if a later score
    adjustment dropped them back below the threshold. Setting ``None`` clears the
    class back to Classless.
    """
    settings = get_settings()
    already_has = user.character_class_id is not None
    if not already_has:
        level = scoring.level_for_xp(await scoring.total_xp(db, user.id), settings.xp_level_base)
        if level < settings.class_unlock_level:
            raise ClassLocked(f"Reach level {settings.class_unlock_level} to choose a class.")

    if class_id is not None and await db.get(CharacterClass, class_id) is None:
        raise NotFoundError("No such class.")

    user.character_class_id = class_id
    await db.flush()
    return await _class_info(db, class_id)


async def _class_info(db: AsyncSession, class_id: UUID | None) -> ClassInfo | None:
    if class_id is None:
        return None
    character_class = await db.get(CharacterClass, class_id)
    if character_class is None:
        return None
    return ClassInfo(
        id=character_class.id,
        name=character_class.name,
        description=character_class.description,
    )
