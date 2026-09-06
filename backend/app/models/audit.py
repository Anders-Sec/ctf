"""Append-only record of consequential actions.

Plan.md files audit logging under Admin Tooling, but approvals and kicks happen
in spec 002, so the table is introduced here and spec 006 adds actions and read
views on top of it rather than inventing a second one.
"""

import uuid
from typing import Any

from sqlalchemy import ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class AuditLog(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "audit_log"
    __table_args__ = (
        Index("ix_audit_log_created", "created_at"),
        Index("ix_audit_log_target", "target_type", "target_id"),
        Index("ix_audit_log_actor", "actor_user_id"),
    )

    #: Null for actions the system took on nobody's behalf (scheduled cleanup,
    #: automatic leadership transfer).
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("user.id", ondelete="SET NULL"), nullable=True
    )
    #: Dotted verb, e.g. "user.approve", "team.kick", "event_config.update".
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    target_type: Mapped[str] = mapped_column(String(32), nullable=False)
    target_id: Mapped[uuid.UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)

    #: Free text supplied by the admin. Scoring overrides in spec 006 require it.
    reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # "metadata" is taken by SQLAlchemy's declarative API, so the attribute is
    # `meta` while the column keeps the name that reads correctly in SQL.
    meta: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default="{}"
    )

    #: Ties the entry back to the request that caused it, and so to the logs.
    request_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
