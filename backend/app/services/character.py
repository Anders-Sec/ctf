"""Assembling a character sheet (spec 015).

One player's XP, overall level and per-skill breakdown, read from the banked
solve XP. Board rank is layered on by the route from the cached scoreboard; this
service is just the XP → levels/skills view of one player.
"""

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.skill import Skill
from app.models.user import User
from app.services import scoring


@dataclass(frozen=True)
class SkillSlice:
    skill_id: UUID
    name: str
    xp: int
    level: int
    xp_into_level: int
    xp_to_next: int


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


async def build_sheet(db: AsyncSession, user: User) -> Sheet:
    base = get_settings().xp_level_base

    total = await scoring.total_xp(db, user.id)
    level, into, to_next = scoring.level_progress(total, base)

    by_skill = await scoring.skill_xp_for_user(db, user.id)
    skills = (
        (await db.execute(select(Skill).order_by(Skill.display_order, Skill.name)))
        .scalars()
        .all()
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

    return Sheet(
        user_id=user.id,
        display_name=user.display_name,
        has_avatar=user.avatar_blob is not None,
        total_xp=total,
        level=level,
        xp_into_level=into,
        xp_to_next=to_next,
        skills=slices,
    )
