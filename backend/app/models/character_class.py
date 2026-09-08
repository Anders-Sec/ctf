"""Character classes — a player's archetype (specs 016, 024).

A class is the archetype layered on top of the sheet: Rogue, Wizard, Cleric. It
is admin-defined and never touches scoring — identity now, and a hook the
boss/loot specs read later.

Spec 018 removed the single "affinity skill": skills are now per-challenge and
numerous, so one skill no longer characterises a class. 024 replaces it with
**preference targets** — one or more abilities *or* skills that the recommender
matches a player against — and **unlock requirements**, skill-level thresholds a
player must reach before a class exists for them at all.
"""

import enum
from uuid import UUID

from sqlalchemy import CheckConstraint, Enum, ForeignKey, Integer, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import CITEXT
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.challenge import Ability


class Rarity(enum.StrEnum):
    """How hard a class was to reach. Affects **colour and nothing else** — the
    unlock requirements do the gating on their own."""

    COMMON = "common"
    UNCOMMON = "uncommon"
    RARE = "rare"
    LEGENDARY = "legendary"
    MYTHIC = "mythic"


class CharacterClass(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "character_class"

    name: Mapped[str] = mapped_column(CITEXT(), unique=True, nullable=False)
    #: Order in the picker and on the sheet.
    display_order: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    #: Flavour line, shown in the picker. Reserved for the narrative pass.
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: Presentation only. Never read by a gate, a score or an ordering.
    rarity: Mapped[Rarity] = mapped_column(
        Enum(Rarity, name="class_rarity", values_callable=lambda e: [m.value for m in e]),
        nullable=False,
        default=Rarity.COMMON,
        server_default=Rarity.COMMON.value,
    )

    preferences: Mapped[list["ClassPreference"]] = relationship(
        back_populates="character_class", cascade="all, delete-orphan", lazy="selectin"
    )
    requirements: Mapped[list["ClassRequirement"]] = relationship(
        back_populates="character_class", cascade="all, delete-orphan", lazy="selectin"
    )


class ClassPreference(UUIDPrimaryKeyMixin, Base):
    """What the recommender matches a player against (spec 024).

    Exactly one of ``ability`` or ``skill_id`` — the D&D-named classes point at
    abilities, the cyber-named ones at skills. Same XOR shape as
    ``unlock_requirement``, for the same reason: one table beats two nearly
    identical ones.
    """

    __tablename__ = "class_preference"
    __table_args__ = (
        CheckConstraint(
            "(ability IS NULL) <> (skill_id IS NULL)",
            name="ck_class_preference_one_target",
        ),
    )

    class_id: Mapped[UUID] = mapped_column(
        ForeignKey("character_class.id", ondelete="CASCADE"), nullable=False, index=True
    )
    ability: Mapped[Ability | None] = mapped_column(
        Enum(Ability, name="ability", values_callable=lambda e: [m.value for m in e]),
        nullable=True,
    )
    skill_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("skill.id", ondelete="CASCADE"), nullable=True
    )

    character_class: Mapped[CharacterClass] = relationship(back_populates="preferences")


class ClassRequirement(UUIDPrimaryKeyMixin, Base):
    """A skill level a player must reach before this class exists for them.

    Every requirement in the 024 roster is of this one shape, so this stays a
    narrow table rather than an arm of ``unlock_requirement`` — that one carries
    six gate types and a challenge-XOR-category target, none of which apply.
    """

    __tablename__ = "class_requirement"
    __table_args__ = (UniqueConstraint("class_id", "skill_id", name="uq_class_requirement_skill"),)

    class_id: Mapped[UUID] = mapped_column(
        ForeignKey("character_class.id", ondelete="CASCADE"), nullable=False, index=True
    )
    skill_id: Mapped[UUID] = mapped_column(
        ForeignKey("skill.id", ondelete="CASCADE"), nullable=False
    )
    min_level: Mapped[int] = mapped_column(Integer, nullable=False)

    character_class: Mapped[CharacterClass] = relationship(back_populates="requirements")
