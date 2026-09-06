"""Player reports that a challenge is broken.

The dashboard needs to show what is broken, and players find out first — an
admin marking a challenge broken is already just hiding it.
"""

import enum
import uuid
from datetime import datetime

from sqlalchemy import Enum, ForeignKey, Index, String, Text, text
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class ReportStatus(enum.StrEnum):
    OPEN = "open"
    #: Seen, being looked at. Distinct from resolved so the queue can be worked.
    ACKNOWLEDGED = "acknowledged"
    #: Nothing wrong with the challenge.
    DISMISSED = "dismissed"
    RESOLVED = "resolved"


class ChallengeReport(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "challenge_report"
    __table_args__ = (
        # One open report per player per challenge: a frustrated player clicking
        # twice is not two problems.
        Index(
            "uq_challenge_report_open",
            "challenge_id",
            "user_id",
            unique=True,
            postgresql_where=text("status = 'open'"),
        ),
        Index("ix_challenge_report_status", "status", "created_at"),
    )

    challenge_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("challenge.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("user.id", ondelete="CASCADE"), nullable=False
    )
    message: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[ReportStatus] = mapped_column(
        Enum(ReportStatus, name="report_status", values_callable=lambda e: [m.value for m in e]),
        nullable=False,
        default=ReportStatus.OPEN,
        server_default=ReportStatus.OPEN.value,
    )
    #: What the admin decided, for the player and for the record.
    resolution_note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    resolved_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("user.id", ondelete="SET NULL"), nullable=True
    )
    resolved_at: Mapped[datetime | None] = mapped_column(nullable=True)
