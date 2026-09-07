"""What the guardrails saw.

Deliberately not built on spec 007's signal machinery. Those signals are
computed on demand from data that already exists and can be recomputed at any
time; these are events that happened at a moment, to a message, and cannot be
reconstructed afterwards. The same review instinct, a different shape.
"""

import enum
import uuid
from typing import Any

from sqlalchemy import Enum, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class GuardrailLayer(enum.StrEnum):
    """`Plan.md` treats these as equally important and independent.

    Separate rules, separate rows, and neither able to suppress the other: a
    jailbreak could target either one.
    """

    INTEGRITY = "integrity"
    SAFETY = "safety"


class Severity(enum.StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class FindingAction(enum.StrEnum):
    #: Recorded, and the player saw the reply anyway. `Plan.md` asks for checks
    #: logged "without necessarily blocking gameplay flow".
    LOGGED = "logged"
    #: The reply was withheld and replaced with an in-character refusal.
    DEFLECTED = "deflected"


def _enum(python_enum: type[enum.StrEnum], name: str) -> Enum:
    return Enum(python_enum, name=name, values_callable=lambda e: [m.value for m in e])


class AssistantFinding(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "assistant_finding"
    __table_args__ = (
        Index("ix_assistant_finding_created", "created_at"),
        Index("ix_assistant_finding_user", "user_id", "layer"),
    )

    #: Nullable so a finding outlives the conversation it came from: retention
    #: purges transcripts, and the record of what happened should survive it.
    message_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("assistant_message.id", ondelete="SET NULL"),
        nullable=True,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("user.id", ondelete="CASCADE"), nullable=False
    )

    layer: Mapped[GuardrailLayer] = mapped_column(_enum(GuardrailLayer, "guardrail_layer"))
    #: Stable identifier for the rule that fired, e.g. ``answer_verbatim``.
    rule: Mapped[str] = mapped_column(String(64), nullable=False)
    severity: Mapped[Severity] = mapped_column(_enum(Severity, "guardrail_severity"))
    action: Mapped[FindingAction] = mapped_column(_enum(FindingAction, "guardrail_action"))

    #: **What matched, never the value.** The challenge id rather than its
    #: answer: a review screen that pastes flags onto an organiser's monitor
    #: would be a new leak wearing an audit badge.
    detail: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}"
    )

    #: Kept out of the review screen by default so our own testing does not bury
    #: the real findings.
    from_staff: Mapped[bool] = mapped_column(nullable=False, default=False, server_default="false")
