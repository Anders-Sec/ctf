"""Credential-adjacent state: magic-link tokens and refresh sessions.

Neither table ever stores a token in a form that could be replayed if the
database leaked — only SHA-256 digests. The raw values exist in an emailed URL
and in a cookie, and nowhere else.
"""

import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import CITEXT
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class MagicLinkToken(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A single-use, time-limited guest login token.

    Keyed by email rather than by user: a token is issued before we know whether
    an account exists, which is what lets the request endpoint answer identically
    for known and unknown addresses and leak nothing.
    """

    __tablename__ = "magic_link_token"
    __table_args__ = (Index("ix_magic_link_token_email_created", "email", "created_at"),)

    email: Mapped[str] = mapped_column(CITEXT(), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(nullable=True)
    #: Invalidated because a newer token was issued for the same address.
    superseded_at: Mapped[datetime | None] = mapped_column(nullable=True)

    requested_ip: Mapped[str | None] = mapped_column(String(45), nullable=True)
    requested_user_agent: Mapped[str | None] = mapped_column(String(500), nullable=True)

    def is_usable(self, now: datetime) -> bool:
        return self.consumed_at is None and self.superseded_at is None and self.expires_at > now


class AuthSession(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One row per issued refresh token.

    Refresh tokens rotate on every use: using one revokes it and writes a
    successor. Presenting an already-rotated token means either a replay or a
    stolen cookie, and the whole chain for that user is revoked in response.
    """

    __tablename__ = "auth_session"
    __table_args__ = (Index("ix_auth_session_user_active", "user_id", "revoked_at"),)

    user_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("user.id", ondelete="CASCADE"), nullable=False
    )
    refresh_token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(nullable=False)

    revoked_at: Mapped[datetime | None] = mapped_column(nullable=True)
    #: rotated | logout | reuse_detected | account_disabled
    revoked_reason: Mapped[str | None] = mapped_column(String(32), nullable=True)
    replaced_by_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("auth_session.id", ondelete="SET NULL"), nullable=True
    )

    ip: Mapped[str | None] = mapped_column(String(45), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(500), nullable=True)

    def is_usable(self, now: datetime) -> bool:
        return self.revoked_at is None and self.expires_at > now
