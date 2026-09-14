"""Things that happened to a player with nowhere else to live (spec 039).

029 makes an achievement trigger a **predicate over stored history**. Three
achievements were inert because their history was not stored anywhere: breaking
the server, rattling an admin door, and changing class. Each of those is an
event the platform sees and then forgets.

This table is the smallest thing that lets a trigger ask about them. Rows exist
to be counted, and that is all — there is deliberately **no payload column**. A
free-form detail field written from an exception handler is an invitation to put
a stack trace into the database, and a stack trace on this platform may contain
a flag or a connection string. What went wrong belongs in the structured log.
"""

import enum
import uuid

from sqlalchemy import Enum, ForeignKey, Index
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class PlayerEventKind(enum.StrEnum):
    #: An unhandled exception, on a request this player made.
    SERVER_ERROR = "server_error"
    #: An authenticated non-admin turned down by `require_admin`.
    FORBIDDEN_ADMIN = "forbidden_admin"
    #: The player's class actually changed — not merely re-selected.
    CLASS_CHANGE = "class_change"


class PlayerEvent(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "player_event"
    __table_args__ = (Index("ix_player_event_user_kind", "user_id", "kind"),)

    user_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("user.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[PlayerEventKind] = mapped_column(
        Enum(
            PlayerEventKind,
            name="player_event_kind",
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=False,
    )
