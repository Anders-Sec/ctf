"""Assembling a character sheet (spec 015, extended by 016).

One player's XP, overall level and per-skill breakdown, read from the banked
solve XP. 016 adds the player's class, the suggested-class nudge (voiced by the
System AI through the narrator seam), and whether the class picker is unlocked.
Board rank is layered on by the route from the cached scoreboard; this service is
the XP → levels/skills/class view of one player.
"""

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.errors import AppError, NotFoundError
from app.models.character_class import CharacterClass
from app.models.skill import Skill
from app.models.user import User
from app.services import narrator, scoring


class ClassLocked(AppError):
    status_code = 403
    code = "class_locked"
    message = "You have not reached the level to choose a class yet."


@dataclass(frozen=True)
class SkillSlice:
    skill_id: UUID
    name: str
    xp: int
    level: int
    xp_into_level: int
    xp_to_next: int


@dataclass(frozen=True)
class ClassInfo:
    id: UUID
    name: str
    description: str | None


@dataclass(frozen=True)
class Suggestion:
    class_id: UUID
    name: str
    from_skill: str
    narration: str


@dataclass(frozen=True)
class Sheet:
    user_id: UUID
    display_name: str
    has_avatar: bool
    total_xp: int
    level: int
    xp_into_level: int
    xp_to_next: int
    skills: list[SkillSlice]
    character_class: ClassInfo | None
    suggested_class: Suggestion | None
    class_unlocked: bool
    class_unlock_level: int


async def build_sheet(db: AsyncSession, user: User) -> Sheet:
    settings = get_settings()
    base = settings.xp_level_base

    total = await scoring.total_xp(db, user.id)
    level, into, to_next = scoring.level_progress(total, base)

    by_skill = await scoring.skill_xp_for_user(db, user.id)
    skills = (
        (await db.execute(select(Skill).order_by(Skill.display_order, Skill.name))).scalars().all()
    )

    slices: list[SkillSlice] = []
    for skill in skills:
        xp = by_skill.get(skill.id, 0)
        s_level, s_into, s_to_next = scoring.level_progress(xp, base)
        slices.append(
            SkillSlice(
                skill_id=skill.id,
                name=skill.name,
                xp=xp,
                level=s_level,
                xp_into_level=s_into,
                xp_to_next=s_to_next,
            )
        )

    character_class = await _class_info(db, user.character_class_id)
    suggested = await _suggested_class(db, skills, by_skill)

    return Sheet(
        user_id=user.id,
        display_name=user.display_name,
        has_avatar=user.avatar_blob is not None,
        total_xp=total,
        level=level,
        xp_into_level=into,
        xp_to_next=to_next,
        skills=slices,
        character_class=character_class,
        suggested_class=suggested,
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


async def _suggested_class(
    db: AsyncSession, skills: list[Skill], by_skill: dict[UUID, int]
) -> Suggestion | None:
    """The class whose affinity skill is the player's highest-XP skill.

    ``skills`` arrives ordered by (display_order, name), so iterating and keeping
    the first skill at the running-max XP breaks ties exactly as the spec says.
    A player with no skill XP, or whose top skill maps to no class, gets nothing.
    """
    top_skill: Skill | None = None
    top_xp = 0
    for skill in skills:
        xp = by_skill.get(skill.id, 0)
        if xp > top_xp:
            top_xp = xp
            top_skill = skill
    if top_skill is None:
        return None

    character_class = (
        await db.execute(
            select(CharacterClass)
            .where(CharacterClass.affinity_skill_id == top_skill.id)
            .order_by(CharacterClass.display_order, CharacterClass.name)
        )
    ).scalar_one_or_none()
    if character_class is None:
        return None

    return Suggestion(
        class_id=character_class.id,
        name=character_class.name,
        from_skill=top_skill.name,
        narration=narrator.class_suggestion(top_skill.name, character_class.name),
    )
