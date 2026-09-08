"""Skills and the category→skill map (spec 015).

A skill is a distinct competency; categories map into it many-to-one. This is
the admin-side plumbing: CRUD on skills and setting a category's ``skill_id``.
Deleting a skill relies on the ``ON DELETE SET NULL`` on ``category.skill_id`` —
the categories survive un-mapped, and their banked XP still counts toward the
overall total, just under no named skill until re-mapped.
"""

from uuid import UUID

from sqlalchemy import delete as sql_delete
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.errors import ConflictError, NotFoundError
from app.models.challenge import Category, Challenge
from app.models.skill import ChallengeSkill, Skill


async def list_skills(db: AsyncSession) -> list[Skill]:
    return list(
        (await db.execute(select(Skill).order_by(Skill.display_order, Skill.name))).scalars().all()
    )


async def get_skill(db: AsyncSession, skill_id: UUID) -> Skill:
    skill = await db.get(Skill, skill_id)
    if skill is None:
        raise NotFoundError("No such skill.")
    return skill


async def create_skill(
    db: AsyncSession,
    *,
    name: str,
    display_order: int = 0,
    description: str | None = None,
    kind=None,
    category_id: UUID | None = None,
) -> Skill:
    # name is CITEXT-unique; check first so the caller gets a clean 409 rather
    # than an IntegrityError.
    if await db.scalar(select(Skill.id).where(Skill.name == name)):
        raise ConflictError("A skill with that name already exists.", code="skill_exists")

    skill = Skill(
        name=name,
        display_order=display_order,
        description=description,
        **({"kind": kind} if kind is not None else {}),
        category_id=category_id,
    )
    db.add(skill)
    await db.flush()
    return skill


async def update_skill(
    db: AsyncSession,
    skill_id: UUID,
    *,
    changes: dict,
) -> Skill:
    skill = await get_skill(db, skill_id)

    new_name = changes.get("name")
    if new_name is not None and new_name != skill.name:
        clash = await db.scalar(
            select(Skill.id).where(Skill.name == new_name, Skill.id != skill_id)
        )
        if clash:
            raise ConflictError("A skill with that name already exists.", code="skill_exists")

    for field, value in changes.items():
        setattr(skill, field, value)
    await db.flush()
    return skill


async def delete_skill(db: AsyncSession, skill_id: UUID) -> None:
    skill = await get_skill(db, skill_id)
    # ON DELETE SET NULL un-maps the categories; nothing to detach by hand.
    await db.delete(skill)
    await db.flush()


async def set_category_ability(db: AsyncSession, category_id: UUID, ability) -> Category:
    """Point a category at the ability its XP feeds (spec 018)."""
    category = await db.get(Category, category_id)
    if category is None:
        raise NotFoundError("No such category.")

    category.ability = ability
    await db.flush()
    return category


async def set_challenge_skills(
    db: AsyncSession, challenge_id: UUID, skill_ids: list[UUID]
) -> list[UUID]:
    """Replace a challenge's skills wholesale.

    Solving it will feed each of these in full — skills overlap by design, so
    there is no cost to attaching several (spec 018).
    """
    if await db.get(Challenge, challenge_id) is None:
        raise NotFoundError("No such challenge.")

    wanted = list(dict.fromkeys(skill_ids))
    if wanted:
        found = set(
            (await db.execute(select(Skill.id).where(Skill.id.in_(wanted)))).scalars().all()
        )
        missing = [s for s in wanted if s not in found]
        if missing:
            raise NotFoundError("No such skill.")

    await db.execute(sql_delete(ChallengeSkill).where(ChallengeSkill.challenge_id == challenge_id))
    for skill_id in wanted:
        db.add(ChallengeSkill(challenge_id=challenge_id, skill_id=skill_id))
    await db.flush()
    return wanted


async def list_challenge_skills(db: AsyncSession, challenge_id: UUID) -> list[UUID]:
    rows = await db.execute(
        select(ChallengeSkill.skill_id).where(ChallengeSkill.challenge_id == challenge_id)
    )
    return list(rows.scalars().all())
