"""Notifications and achievements (spec 028).

A notification is one message from the System AI to one player. It is the
substrate: achievements are the loudest producer, but class unlocks, zone
unlocks and level-ups all speak through the same table.

An achievement is a named thing a player did. Its ``code`` is the link to the
trigger implementation in ``app.services.achievements`` — a predicate over the
player's stored history, evaluated after the events that could change its
answer. There is no backfill: an achievement created after the fact awards
nothing for work already done, which is why the roster is seeded before the
event starts.
"""

import enum
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import CITEXT
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.challenge import _enum


class NotificationKind(enum.StrEnum):
    """What produced this. Drives the icon and grouping, never the delivery."""

    ACHIEVEMENT = "achievement"
    CLASS_UNLOCKED = "class_unlocked"
    ZONE_UNLOCKED = "zone_unlocked"
    LEVEL_UP = "level_up"
    ABILITY_MILESTONE = "ability_milestone"
    #: Somebody was first to put a boss down. Broadcast (spec 032).
    BOSS_KILL = "boss_kill"
    #: An admin speaking to the whole event.
    ANNOUNCEMENT = "announcement"
    #: The daily state-of-the-dungeon message.
    DISPATCH = "dispatch"
    SYSTEM = "system"


class Notification(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "notification"
    __table_args__ = (
        # The backlog is read newest-first, filtered to one player, and the
        # unread count is the same query with read_at IS NULL.
        Index("ix_notification_user_created", "user_id", "created_at"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("user.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[NotificationKind] = mapped_column(
        _enum(NotificationKind, "notification_kind"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    #: The System AI's line. Written server-side from a deterministic template —
    #: never a model call, so there is no latency, no token cost and no path for
    #: a challenge answer to reach a prompt.
    body: Mapped[str] = mapped_column(Text, nullable=False)
    #: Where the message points, if anywhere: a zone, the sheet, a challenge.
    link: Mapped[str | None] = mapped_column(String(500), nullable=True)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Achievement(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "achievement"

    #: Stable key naming the trigger that awards it. An achievement whose code
    #: has no registered trigger simply never fires, which is the safe failure.
    code: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(CITEXT(), unique=True, nullable=False)
    #: The System AI's line about it, shown once earned. Hand-written per
    #: achievement; seeded as an obvious placeholder (spec 029).
    description: Mapped[str] = mapped_column(Text, nullable=False)
    #: The criteria in plain words, for the admin roster. Factual and stable,
    #: where description is voice — they answer different questions.
    earned_by: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    display_order: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    #: Hidden from the roster entirely rather than blurred. Reserved: the roster
    #: is all-blurred today, and this exists so a joke or spoiler achievement
    #: needs no migration later.
    secret: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )


class BroadcastLog(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One row per broadcast that has gone out (spec 032).

    The unique constraint is the whole point. Two replicas run the same daily
    timer, and a restart near the send window would otherwise send again — so
    whichever pod inserts first sends, and the loser's insert fails. The same
    arbiter as ``uq_achievement_award_once``, for the same reason: a constraint
    survives concurrency and restarts without anything having to coordinate.
    """

    __tablename__ = "broadcast_log"
    __table_args__ = (UniqueConstraint("kind", "key", name="uq_broadcast_once"),)

    kind: Mapped[NotificationKind] = mapped_column(
        _enum(NotificationKind, "notification_kind"), nullable=False
    )
    #: What makes this broadcast unique within its kind — a date for the daily
    #: dispatch, a challenge id for a first kill, a fresh value for an
    #: announcement, since sending two different ones is legitimate.
    key: Mapped[str] = mapped_column(String(200), nullable=False)
    #: How many players it reached, for the admin console.
    recipients: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class AchievementAward(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "achievement_award"
    __table_args__ = (
        # Once per player. A constraint rather than a check-then-insert, which
        # two concurrent solves could both pass.
        UniqueConstraint("achievement_id", "user_id", name="uq_achievement_award_once"),
        Index("ix_achievement_award_user", "user_id"),
    )

    achievement_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("achievement.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("user.id", ondelete="CASCADE"), nullable=False
    )
