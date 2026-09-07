"""The dungeon master's conversations.

One rolling conversation per player: `Plan.md` wants the chat available from any
screen, and a per-challenge thread would lose the thread every time they
navigate.
"""

import enum
import uuid
from datetime import datetime

from sqlalchemy import Enum, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class MessageRole(enum.StrEnum):
    USER = "user"
    ASSISTANT = "assistant"


class AssistantConversation(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "assistant_conversation"

    user_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("user.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    message_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    last_message_at: Mapped[datetime | None] = mapped_column(nullable=True)

    messages: Mapped[list["AssistantMessage"]] = relationship(
        back_populates="conversation", cascade="all, delete-orphan", lazy="raise"
    )


class AssistantMessage(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "assistant_message"
    __table_args__ = (
        UniqueConstraint("conversation_id", "sequence", name="uq_assistant_message_sequence"),
        Index("ix_assistant_message_conversation", "conversation_id", "sequence"),
    )

    conversation_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("assistant_conversation.id", ondelete="CASCADE"),
        nullable=False,
    )
    role: Mapped[MessageRole] = mapped_column(
        Enum(MessageRole, name="assistant_role", values_callable=lambda e: [m.value for m in e]),
        nullable=False,
    )
    #: Position in the conversation. ``created_at`` cannot order these: Postgres
    #: stamps ``now()`` at transaction start, so the question and the answer it
    #: produced always carry an identical timestamp and would sort arbitrarily.
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)

    #: What the player was looking at when they asked, so the assistant gets
    #: context without them restating it — and so spec 011 can review what was
    #: asked about what.
    challenge_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("challenge.id", ondelete="SET NULL"), nullable=True
    )
    #: Whether the asker was staff. Staff are the only ones testing this before
    #: the guardrails land, and their transcripts should not muddy the abuse
    #: review afterwards.
    from_staff: Mapped[bool] = mapped_column(nullable=False, default=False, server_default="false")

    model: Mapped[str | None] = mapped_column(String(200), nullable=True)
    prompt_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    completion_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)

    #: The model's scratchpad, kept and **never returned**. It may contain the
    #: model reasoning aloud about a challenge, which is not for players; it is
    #: what makes an odd answer explainable after the fact.
    reasoning_content: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: Why a reply failed, when one did.
    error: Mapped[str | None] = mapped_column(String(200), nullable=True)

    conversation: Mapped["AssistantConversation"] = relationship(
        back_populates="messages", lazy="raise"
    )
