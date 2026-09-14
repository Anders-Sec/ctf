"""The dungeon master's conversations.

One rolling conversation per player: `Plan.md` wants the chat available from any
screen, and a per-challenge thread would lose the thread every time they
navigate.
"""

import enum
import uuid
from datetime import datetime

from sqlalchemy import Enum, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
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
    #: Never reset. A reset starts a new session rather than deleting rows
    #: (spec 036), so this keeps counting and ``sequence`` stays unique.
    message_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    #: Which session is current. Incremented by a reset; the player and the model
    #: only ever see turns from this one, while staff can read them all.
    current_session: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    last_message_at: Mapped[datetime | None] = mapped_column(nullable=True)

    messages: Mapped[list["AssistantMessage"]] = relationship(
        back_populates="conversation", cascade="all, delete-orphan", lazy="raise"
    )


class TermsAcceptance(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One player accepting one version of the System AI's terms (spec 035).

    A table rather than a column on ``user``, because this is a consent record
    and the question that gets asked of it is "who accepted what, and when" —
    including across revisions. A column would answer only the last one.

    Deliberately **not** purged by spec 011's retention job: it holds no
    conversation content, and deleting the record of consent along with the
    conversations it covered would be the wrong way round.
    """

    __tablename__ = "assistant_terms_acceptance"
    __table_args__ = (
        UniqueConstraint("user_id", "version", name="uq_assistant_terms_user_version"),
        Index("ix_assistant_terms_user", "user_id"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("user.id", ondelete="CASCADE"), nullable=False
    )
    #: The hash of the terms file as it stood when they accepted. Not a number
    #: anyone maintains: a changed file is a new version, which is the safe
    #: direction for a consent record.
    version: Mapped[str] = mapped_column(String(64), nullable=False)
    accepted_at: Mapped[datetime] = mapped_column(nullable=False)


class AssistantMessage(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "assistant_message"
    __table_args__ = (
        UniqueConstraint("conversation_id", "sequence", name="uq_assistant_message_sequence"),
        Index("ix_assistant_message_conversation", "conversation_id", "sequence"),
        # The player's history now filters on the session as well.
        Index(
            "ix_assistant_message_session",
            "conversation_id",
            "session_number",
            "sequence",
        ),
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
    #: Which session this turn belongs to (spec 036). A reset increments the
    #: conversation's counter rather than deleting anything, so the exchange
    #: behind a flag survives the reset that used to erase it — and players reset
    #: after nearly every attempt.
    session_number: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )

    #: Position in the conversation. ``created_at`` cannot order these: Postgres
    #: stamps ``now()`` at transaction start, so the question and the answer it
    #: produced always carry an identical timestamp and would sort arbitrarily.
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)

    #: What the model actually said, kept only when the reply was withheld.
    #: ``content`` stays "what the player saw"; staff reviewing an incident need
    #: the real text.
    original_content: Mapped[str | None] = mapped_column(Text, nullable=True)

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

    #: Which rung of the ladder produced this turn (spec 033). Recorded on the
    #: row because the level is what selected the prompt and the gates, and a
    #: reply is unreadable afterwards without knowing which defences were up.
    ladder_level: Mapped[int | None] = mapped_column(Integer, nullable=True)

    #: Which gates fired, e.g. ``["router"]`` or ``["vault:APPENDIX-OMEGA"]``.
    #: A live feed of what players are trying, and the thing to read when a level
    #: behaves oddly.
    #:
    #: **Telemetry, never a gate.** ``SOLVED`` appearing here means the flag
    #: reached the player — which in this ladder is the win condition, not an
    #: incident.
    trace: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)

    #: How many upstream calls this turn actually cost (spec 034). A level 5 turn
    #: can reach five — router, generate, vault action, generate again, warden —
    #: and each takes one of the eight in-flight slots. Spec 033 could not fix
    #: that capacity question and left it visible; this is what makes it
    #: measurable rather than theoretical.
    upstream_calls: Mapped[int | None] = mapped_column(Integer, nullable=True)

    #: Every upstream call this turn made, in order (spec 036): the router's
    #: verdict, the vault action, the warden's verdict, and — the field that did
    #: not exist anywhere before — **the candidate reply a gate suppressed**.
    #:
    #: That is what separates "the warden is too strict" from "the prompt held",
    #: which is unanswerable from ``trace`` alone. The system prompt is not
    #: stored (derivable from the level, identical every turn, kilobytes), and
    #: neither is the vault's sealed record body, which is the flag.
    gate_log: Mapped[list[dict] | None] = mapped_column(JSONB, nullable=True)

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
