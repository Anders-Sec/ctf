"""Character classes — admin CRUD and the affinity-skill link (spec 016).

Mirrors the skill service in shape. A class carries an optional affinity skill;
deleting that skill un-links it (the FK is ``ON DELETE SET NULL``), and deleting a
class returns its players to Classless the same way. A class never touches
scoring — this is roster management only.
"""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.errors import ConflictError, NotFoundError
from app.models.character_class import CharacterClass


async def list_classes(db: AsyncSession) -> list[CharacterClass]:
    return list(
        (
            await db.execute(
                select(CharacterClass).order_by(CharacterClass.display_order, CharacterClass.name)
            )
        )
        .scalars()
        .all()
    )


async def get_class(db: AsyncSession, class_id: UUID) -> CharacterClass:
    character_class = await db.get(CharacterClass, class_id)
    if character_class is None:
        raise NotFoundError("No such class.")
    return character_class


async def create_class(
    db: AsyncSession,
    *,
    name: str,
    display_order: int = 0,
    description: str | None = None,
) -> CharacterClass:
    if await db.scalar(select(CharacterClass.id).where(CharacterClass.name == name)):
        raise ConflictError("A class with that name already exists.", code="class_exists")

    character_class = CharacterClass(
        name=name,
        display_order=display_order,
        description=description,
    )
    db.add(character_class)
    await db.flush()
    return character_class


async def update_class(db: AsyncSession, class_id: UUID, *, changes: dict) -> CharacterClass:
    character_class = await get_class(db, class_id)

    new_name = changes.get("name")
    if new_name is not None and new_name != character_class.name:
        clash = await db.scalar(
            select(CharacterClass.id).where(
                CharacterClass.name == new_name, CharacterClass.id != class_id
            )
        )
        if clash:
            raise ConflictError("A class with that name already exists.", code="class_exists")

    for field, value in changes.items():
        setattr(character_class, field, value)
    await db.flush()
    return character_class


async def delete_class(db: AsyncSession, class_id: UUID) -> None:
    character_class = await get_class(db, class_id)
    # ON DELETE SET NULL returns this class's players to Classless.
    await db.delete(character_class)
    await db.flush()
