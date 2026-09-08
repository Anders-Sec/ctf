"""Skills — the many small things a player turns out to be good at (spec 018).

A skill is attached to *challenges*, not categories: an admin picks several per
challenge, and solving it feeds every one of them. Skills therefore **overlap** —
a challenge's XP goes to each attached skill in full rather than being split,
because splitting would punish a challenge for carrying more jokes. That is safe
only because skill XP is never shown to a player; there is no number to reconcile.

``category_id`` is admin convenience: it sorts the picker, nothing more. A skill
may be attached to any challenge in any category.
"""

import uuid

from sqlalchemy import ForeignKey, Index, Integer, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import CITEXT
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.challenge import SkillKind, _enum


class Skill(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "skill"

    name: Mapped[str] = mapped_column(CITEXT(), unique=True, nullable=False)
    #: Order within its category in the admin picker.
    display_order: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    kind: Mapped[SkillKind] = mapped_column(
        _enum(SkillKind, "skill_kind"),
        nullable=False,
        default=SkillKind.USEFUL,
        server_default=SkillKind.USEFUL.value,
    )
    #: Which category's challenges this skill most likely belongs to — used only
    #: to sort the picker. SET NULL so deleting a category leaves its skills as
    #: "other" rather than destroying them.
    category_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("category.id", ondelete="SET NULL"), nullable=True
    )


class ChallengeSkill(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A skill attached to a challenge. Solving the challenge feeds the skill."""

    __tablename__ = "challenge_skill"
    __table_args__ = (
        UniqueConstraint("challenge_id", "skill_id", name="uq_challenge_skill"),
        Index("ix_challenge_skill_challenge", "challenge_id"),
        Index("ix_challenge_skill_skill", "skill_id"),
    )

    challenge_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("challenge.id", ondelete="CASCADE"), nullable=False
    )
    skill_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("skill.id", ondelete="CASCADE"), nullable=False
    )
