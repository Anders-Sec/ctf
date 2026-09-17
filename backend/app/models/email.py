"""Outbound email attempts (spec 055).

``mail.py``'s module docstring has always said a delivery failure is "logged
with the request id so an admin can find it mid-event rather than guessing why
one player never got their link." The log went to the pod's stdout, which is
unreachable from the app at the moment a guest is standing in front of you — and
it records the exception *type* only, never the recipient, so even with cluster
access you could not tell which address failed.

This table is that signal, in a place the admin can read.
"""

import enum
import uuid

from sqlalchemy import Enum, ForeignKey, Index, Integer, String
from sqlalchemy.dialects.postgresql import CITEXT
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class EmailKind(enum.StrEnum):
    MAGIC_LINK = "magic_link"
    APPROVAL_NOTICE = "approval_notice"
    #: An admin checking the relay from the Email Delivery page.
    TEST = "test"


class EmailStatus(enum.StrEnum):
    #: The relay accepted it. NOT "it arrived" — SMTP gives no delivery
    #: confirmation, and a row claiming delivery for something that bounced
    #: later would be a lie the page tells confidently.
    SENT = "sent"
    FAILED = "failed"
    NOT_CONFIGURED = "not_configured"


class EmailDelivery(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "email_delivery"
    __table_args__ = (
        Index("ix_email_delivery_created", "created_at"),
        Index("ix_email_delivery_to_email", "to_email"),
    )

    kind: Mapped[EmailKind] = mapped_column(
        Enum(EmailKind, name="email_kind", values_callable=lambda e: [m.value for m in e]),
        nullable=False,
    )

    #: Stored in plaintext, deliberately, and unlike the application logs.
    #:
    #: The `user` table already holds every one of these addresses as the
    #: identity key, so this introduces no category of data the database does
    #: not have. And the address is the entire diagnostic value — a delivery log
    #: you cannot search by recipient answers none of the questions it exists
    #: for. The distinction being preserved is logs versus database: logs are
    #: shipped and read broadly, so they stay free of addresses.
    to_email: Mapped[str] = mapped_column(CITEXT(), nullable=False)

    #: Null when the address has no account — a link can be requested for one
    #: that does not exist. Rows are matched to a player by address, so this is
    #: a convenience rather than the join.
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("user.id", ondelete="SET NULL"), nullable=True
    )

    status: Mapped[EmailStatus] = mapped_column(
        Enum(EmailStatus, name="email_status", values_callable=lambda e: [m.value for m in e]),
        nullable=False,
    )

    #: The exception class name, as the log already records. Never the message:
    #: `mail.py` notes it can contain the recipient address, and a log line is
    #: not the place for one.
    error_type: Mapped[str | None] = mapped_column(String(100), nullable=True)

    #: How long the relay took. A relay that is slow rather than broken looks
    #: like nothing else on the page.
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)

    request_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    def __repr__(self) -> str:
        return f"<EmailDelivery {self.kind} {self.to_email} {self.status}>"
