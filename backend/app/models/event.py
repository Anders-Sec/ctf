"""Event-wide configuration.

A single row. The gate that blocks gameplay before the doors open needs
somewhere to read a start time from, which is why this lands in spec 002 rather
than waiting for the admin tooling in spec 006.
"""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

#: The one and only row. A fixed id plus a CHECK is a cheap way to make "there is
#: exactly one event config" a database guarantee rather than a convention.
EVENT_CONFIG_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")


class EventConfig(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "event_config"
    __table_args__ = (
        CheckConstraint(
            f"id = '{EVENT_CONFIG_ID}'::uuid",
            name="ck_event_config_singleton",
        ),
    )

    name: Mapped[str] = mapped_column(String(120), nullable=False)
    #: Null means "not scheduled yet", which reads as closed rather than open —
    #: failing shut is the right default for a gate.
    starts_at: Mapped[datetime | None] = mapped_column(nullable=True)
    ends_at: Mapped[datetime | None] = mapped_column(nullable=True)
    registration_open: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )

    #: The runtime off switch for the dungeon master. ``AI_ENABLED`` remains the
    #: deployment-level one, but reaching for a redeploy is the wrong tool at
    #: 11pm on day two when the assistant starts saying something unfortunate.
    #: Dim locked zones on the dungeon map (spec 017). Presentation only — the
    #: gating is the zone's unlock requirements, which apply either way. Inert
    #: until an admin gates a zone.
    fog_of_war: Mapped[bool] = mapped_column(nullable=False, default=True, server_default="true")

    assistant_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )

    updated_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("user.id", ondelete="SET NULL"), nullable=True
    )

    def has_started(self, now: datetime) -> bool:
        return self.starts_at is not None and now >= self.starts_at

    def has_ended(self, now: datetime) -> bool:
        return self.ends_at is not None and now >= self.ends_at

    def is_running(self, now: datetime) -> bool:
        return self.has_started(now) and not self.has_ended(now)
