"""What players did: solves, every attempt, and manual score adjustments."""

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

#: Submissions are capped before storage and before matching. A regex meeting an
#: unbounded input is a denial-of-service; a log table full of megabyte strings
#: is a different one.
MAX_SUBMISSION_LENGTH = 1024


class Solve(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A player's first correct answer to a challenge.

    Owned by the player, never the party — their score travels with them.
    """

    __tablename__ = "solve"
    __table_args__ = (
        # A database constraint, not an application check: two concurrent correct
        # submissions would both pass a read-then-write test and award two solves.
        UniqueConstraint("user_id", "challenge_id", name="uq_solve_user_challenge"),
        Index("ix_solve_challenge", "challenge_id"),
        Index("ix_solve_user", "user_id"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("user.id", ondelete="CASCADE"), nullable=False
    )
    challenge_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("challenge.id", ondelete="CASCADE"), nullable=False
    )
    #: Which party they were in at the time. History, not ownership: it feeds the
    #: team-basis decay curve and spec 007's view of who was sitting with whom.
    #: Null when they had no party, which still counts as a distinct solver.
    team_id_at_solve: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("team.id", ondelete="SET NULL"), nullable=True
    )
    submitted_at: Mapped[datetime] = mapped_column(nullable=False)
    submission_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("submission.id", ondelete="SET NULL"), nullable=True
    )
    #: XP banked at solve time (spec 015): the challenge's value then, minus the
    #: hints the player had used on it. Snapshot, never recomputed, so levels are
    #: monotonic.
    xp_awarded: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")


class Submission(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Every attempt, right or wrong. The raw material for spec 007."""

    __tablename__ = "submission"
    __table_args__ = (
        Index("ix_submission_user_challenge", "user_id", "challenge_id", "created_at"),
        Index("ix_submission_challenge_created", "challenge_id", "created_at"),
        # Anti-cheat asks "who else submitted this exact string?", so the value
        # itself is indexed rather than only scanned.
        Index("ix_submission_value", "submitted_value"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("user.id", ondelete="CASCADE"), nullable=False
    )
    challenge_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("challenge.id", ondelete="CASCADE"), nullable=False
    )
    team_id_at_submit: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("team.id", ondelete="SET NULL"), nullable=True
    )

    is_correct: Mapped[bool] = mapped_column(Boolean, nullable=False)
    #: Stored as submitted. With answers in plaintext there is nothing to protect
    #: by redacting it, and the exact text is what makes duplicate-submission
    #: detection possible.
    submitted_value: Mapped[str] = mapped_column(String(MAX_SUBMISSION_LENGTH), nullable=False)
    #: Which rule accepted it, for debugging a challenge that behaves oddly.
    matched_answer_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("challenge_answer.id", ondelete="SET NULL"), nullable=True
    )

    ip: Mapped[str | None] = mapped_column(String(45), nullable=True)
    #: Ties the attempt back to the server logs around it.
    request_id: Mapped[str | None] = mapped_column(String(64), nullable=True)


class ScoreAdjustment(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A manual correction, to a player's total or to a party's.

    A party-scoped adjustment belongs to the party, not to any member — not
    fanned out across everyone, and not routed through the leader. Leadership
    transfers and leaders leave, so an adjustment attached to a person would
    walk out of the party with them; and routing it through the leader would
    also move them up the *player* board for points they did not earn.
    """

    __tablename__ = "score_adjustment"
    __table_args__ = (
        Index("ix_score_adjustment_user", "user_id"),
        Index("ix_score_adjustment_team", "team_id"),
        # Exactly one target. Belonging to both, or to neither, is meaningless,
        # and the database is the right place to say so.
        CheckConstraint(
            "(user_id IS NOT NULL) <> (team_id IS NOT NULL)",
            name="ck_score_adjustment_one_target",
        ),
    )

    user_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("user.id", ondelete="CASCADE"), nullable=True
    )
    team_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("team.id", ondelete="CASCADE"), nullable=True
    )
    #: Signed: compensation for a broken challenge, or a penalty.
    points: Mapped[int] = mapped_column(Integer, nullable=False)
    #: Required. An unexplained score change is indefensible after the event.
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("user.id", ondelete="SET NULL"), nullable=True
    )
    #: Adjustments are never deleted. A mistake is corrected by a reversing
    #: entry pointing at the original, so the record of the decision survives.
    reverses_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("score_adjustment.id", ondelete="SET NULL"), nullable=True
    )
