"""Record that a staff member looked at a signal and concluded it was fine.

Only dismissals are stored. A computed signal goes stale the moment the data
behind it moves, and a standing table of accusations against named colleagues
is not a thing to keep.
"""

import uuid

from sqlalchemy import ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class SignalDismissal(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "signal_dismissal"
    __table_args__ = (
        UniqueConstraint("signal_type", "subject_key", name="uq_signal_dismissal"),
        Index("ix_signal_dismissal_type", "signal_type"),
    )

    signal_type: Mapped[str] = mapped_column(String(64), nullable=False)
    #: A stable digest of the finding's participants and challenge, so a new
    #: finding between the same people on a different challenge appears fresh
    #: rather than staying dismissed.
    subject_key: Mapped[str] = mapped_column(String(64), nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    dismissed_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("user.id", ondelete="SET NULL"), nullable=True
    )
