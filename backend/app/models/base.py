"""SQLAlchemy declarative base and shared column mixins."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, func
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Declarative base.

    ``type_annotation_map`` makes every ``datetime`` column ``timestamptz``
    without each model having to say so. Naive timestamps in a multi-day event
    spanning a DST boundary are a data-loss bug waiting to happen.
    """

    type_annotation_map = {datetime: DateTime(timezone=True)}


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
