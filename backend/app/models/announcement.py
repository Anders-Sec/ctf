"""What an admin has said to the whole event (spec 054).

A table of its own rather than reverse-engineering the history out of
``notification`` rows: those are one per recipient, and reconstructing "what was
said" from a fan-out would mean grouping ten thousand rows by a title.
"""

import enum
import uuid
from datetime import datetime

from sqlalchemy import Enum, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class AnnouncementAudience(enum.StrEnum):
    EVERYONE = "everyone"
    #: A note to helpers that should not reach players.
    STAFF = "staff"


class Announcement(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "announcement"
    __table_args__ = (Index("ix_announcement_scheduled", "scheduled_for", "sent_at"),)

    title: Mapped[str] = mapped_column(String(120), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)

    audience: Mapped[AnnouncementAudience] = mapped_column(
        Enum(
            AnnouncementAudience,
            name="announcement_audience",
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=False,
        default=AnnouncementAudience.EVERYONE,
        server_default=AnnouncementAudience.EVERYONE.value,
    )

    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("user.id", ondelete="SET NULL"), nullable=True
    )

    #: Null for send-now. While set and unsent the announcement is *pending*,
    #: which is the one state that can still be edited or cancelled — nobody has
    #: read it yet.
    scheduled_for: Mapped[datetime | None] = mapped_column(nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(nullable=True)

    #: Stamped at fan-out. The read count is *not* stored here: it lives on the
    #: notification rows, which is where read state already is, so there is no
    #: second number to keep in step.
    recipient_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )

    @property
    def is_pending(self) -> bool:
        return self.sent_at is None and self.cancelled_at is None

    def __repr__(self) -> str:
        return f"<Announcement {self.title!r} sent={self.sent_at}>"
