"""Skills — what a player is good at (spec 015).

A skill is a distinct competency (Hacking, Forensics, Crypto). Categories map
into skills many-to-one, so several categories can feed the same skill. A
player's skill XP is the sum of their banked solve XP for solves whose category
maps to it; the skill's level is derived from that.
"""

from sqlalchemy import Integer, Text
from sqlalchemy.dialects.postgresql import CITEXT
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class Skill(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "skill"

    name: Mapped[str] = mapped_column(CITEXT(), unique=True, nullable=False)
    #: Order on the character sheet.
    display_order: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    #: Reserved for the Phase 3 flavour pass.
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
