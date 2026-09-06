"""SQLAlchemy declarative base and shared column mixins.

No domain models yet — spec 002 adds the first ones. This module exists so that
migrations and later specs have a single `Base` to register against.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, func
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class UUIDPrimaryKeyMixin:
    """UUID primary keys.

    Ids appear in player-facing URLs and instance names. Sequential integers would
    leak how many challenges exist and invite enumeration of other teams' rows.
    """

    id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )


class TimestampMixin:
    """Creation and update times, in UTC, set by the database.

    ``server_default``/``onupdate`` rather than Python defaults so rows written by
    a migration or a maintenance script are stamped the same way as rows written
    by the app.
    """

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


__all__ = ["Base", "TimestampMixin", "UUIDPrimaryKeyMixin"]
