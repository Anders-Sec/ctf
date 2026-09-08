"""Character classes — a player's archetype (spec 016).

A class is the archetype layered on top of the sheet 015 built: Rogue, Wizard,
Cleric. It is admin-defined and carries an optional *affinity skill* — the skill
the class is "about", which drives the suggested-class nudge. A class never
touches scoring; it is identity now and a hook the boss/loot specs read later.
"""

import uuid

from sqlalchemy import ForeignKey, Integer, Text
from sqlalchemy.dialects.postgresql import CITEXT
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class CharacterClass(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "character_class"

    name: Mapped[str] = mapped_column(CITEXT(), unique=True, nullable=False)
    #: Order in the picker and on the sheet.
    display_order: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    #: Flavour line, shown in the picker. Reserved for the narrative pass.
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: The skill this class is "about". SET NULL so deleting a skill un-links the
    #: affinity rather than deleting the class.
    affinity_skill_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("skill.id", ondelete="SET NULL"), nullable=True
    )
