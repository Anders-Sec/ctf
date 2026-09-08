"""Skills and the category→skill map (spec 015).

A skill is a distinct competency; categories map into it many-to-one. This is
the admin-side plumbing: CRUD on skills and setting a category's ``skill_id``.
Deleting a skill relies on the ``ON DELETE SET NULL`` on ``category.skill_id`` —
the categories survive un-mapped, and their banked XP still counts toward the
overall total, just under no named skill until re-mapped.
"""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.errors import ConflictError, NotFoundError
from app.models.challenge import Category
from app.models.skill import Skill


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
) -> Skill:
    # name is CITEXT-unique; check first so the caller gets a clean 409 rather
    # than an IntegrityError.
    if await db.scalar(select(Skill.id).where(Skill.name == name)):
        raise ConflictError("A skill with that name already exists.", code="skill_exists")

    skill = Skill(name=name, display_order=display_order, description=description)
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


async def set_category_skill(
    db: AsyncSession, category_id: UUID, skill_id: UUID | None
) -> Category:
    """Map a category to a skill (or clear the mapping with ``None``)."""
    category = await db.get(Category, category_id)
    if category is None:
        raise NotFoundError("No such category.")

    if skill_id is not None and await db.get(Skill, skill_id) is None:
        raise NotFoundError("No such skill.")

    category.skill_id = skill_id
    await db.flush()
    return category
