"""Character classes — a player's archetype (spec 016).

A class is the archetype layered on top of the sheet: Rogue, Wizard, Cleric. It
is admin-defined and never touches scoring — identity now, and a hook the
boss/loot specs read later.

Spec 018 removed the single "affinity skill": skills are now per-challenge and
numerous, so one skill no longer characterises a class. The real recommender —
a deterministic ranking over a player's top skills — will define its own mapping.
"""

from sqlalchemy import Integer, Text
from sqlalchemy.dialects.postgresql import CITEXT
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
