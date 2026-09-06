"""Hints, and who has paid for them."""

import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class Hint(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "hint"
    __table_args__ = (Index("ix_hint_challenge", "challenge_id", "display_order"),)

    challenge_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("challenge.id", ondelete="CASCADE"), nullable=False
    )
    #: Shown before unlocking, so a player knows what they are buying.
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    #: Withheld until unlocked, server-side.
    body: Mapped[str] = mapped_column(Text, nullable=False)
    #: Points. Zero is allowed — a free hint is a legitimate thing to write.
    cost: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    display_order: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )

    #: Optional ladder: this hint only becomes available once that one is bought.
    prerequisite_hint_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("hint.id", ondelete="SET NULL"), nullable=True
    )
    #: Optional schedule, independent of the prerequisite. A day-two reveal.
    available_after: Mapped[datetime | None] = mapped_column(nullable=True)

    unlocks: Mapped[list["HintUnlock"]] = relationship(
        back_populates="hint", cascade="all, delete-orphan", lazy="raise"
    )


class HintUnlock(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A player has paid for a hint. This table is the log.

    Costs are kept here rather than in ``score_adjustment``: that table is the
    record of admin intervention, and spec 006 renders it as such. Mixing
    automatic game mechanics into it would make a scoring dispute harder to
    read, not easier.
    """

    __tablename__ = "hint_unlock"
    __table_args__ = (
        # A database constraint, so a double-clicked unlock cannot charge twice.
        UniqueConstraint("user_id", "hint_id", name="uq_hint_unlock_user_hint"),
        Index("ix_hint_unlock_user", "user_id"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("user.id", ondelete="CASCADE"), nullable=False
    )
    hint_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("hint.id", ondelete="CASCADE"), nullable=False
    )
    #: A snapshot, unlike challenge values which stay live. A challenge's value
    #: moving is the decay mechanic working; a hint's cost is a number one admin
    #: typed, and editing it must not rewrite what someone already paid.
    cost_charged: Mapped[int] = mapped_column(Integer, nullable=False)
    unlocked_at: Mapped[datetime] = mapped_column(nullable=False)

    hint: Mapped["Hint"] = relationship(back_populates="unlocks", lazy="raise")
