"""Parties: membership, join requests, and the rules around them.

A party is a social layer. It holds no score of its own — solves belong to the
player who earned them, and a party's standing is an aggregate computed over its
current members. That is what makes an open roster safe, and it is why there is
no ``points`` column here.
"""

import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Enum, ForeignKey, Index, SmallInteger, String, Text, text
from sqlalchemy.dialects.postgresql import CITEXT
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.user import User

#: The party size cap. Per-team overridable so an admin can widen one party
#: mid-event without a deploy.
DEFAULT_MAX_MEMBERS = 8


class TeamVisibility(enum.StrEnum):
    PUBLIC = "public"
    PRIVATE = "private"


class MembershipRole(enum.StrEnum):
    LEADER = "leader"
    MEMBER = "member"


class RemovalReason(enum.StrEnum):
    LEFT = "left"
    KICKED = "kicked"
    ADMIN = "admin"
    DISBANDED = "disbanded"


class JoinRequestStatus(enum.StrEnum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    CANCELLED = "cancelled"


def _enum(python_enum: type[enum.StrEnum], name: str) -> Enum:
    return Enum(python_enum, name=name, values_callable=lambda e: [m.value for m in e])


class Team(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "team"

    name: Mapped[str] = mapped_column(CITEXT(), unique=True, nullable=False)
    visibility: Mapped[TeamVisibility] = mapped_column(
        _enum(TeamVisibility, "team_visibility"), nullable=False
    )
    #: Argon2id. Private parties only; null means request-to-join is the only way in.
    join_password_hash: Mapped[str | None] = mapped_column(Text, nullable=True)

    leader_user_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("user.id", ondelete="RESTRICT"), nullable=False
    )
    max_members: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, default=DEFAULT_MAX_MEMBERS, server_default="8"
    )
    #: Soft delete. A party that ever had members must remain resolvable for the
    #: audit trail, so it is stamped rather than removed.
    disbanded_at: Mapped[datetime | None] = mapped_column(nullable=True)

    # lazy="raise": eager-joining the leader would make `SELECT ... FOR UPDATE`
    # illegal in Postgres (no outer joins under a row lock), and the join lock is
    # what keeps party capacity correct. Load it explicitly where it is needed.
    leader: Mapped["User"] = relationship(foreign_keys=[leader_user_id], lazy="raise")
    memberships: Mapped[list["TeamMembership"]] = relationship(
        back_populates="team",
        foreign_keys="TeamMembership.team_id",
    )

    @property
    def is_private(self) -> bool:
        return self.visibility == TeamVisibility.PRIVATE

    def __repr__(self) -> str:
        return f"<Team {self.name} {self.visibility}>"


class TeamMembership(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Who is in which party, including who used to be.

    Rows are never hard-deleted: a kicked player's history is needed for
    anti-cheat review (spec 007) and for explaining a leader's actions later.
    """

    __tablename__ = "team_membership"
    __table_args__ = (
        # A user may hold at most one *active* membership. Enforced in the
        # database rather than in application code, because two concurrent joins
        # would otherwise both pass a "are they already in a party?" check.
        Index(
            "uq_team_membership_active_user",
            "user_id",
            unique=True,
            postgresql_where=text("removed_at IS NULL"),
        ),
        Index(
            "ix_team_membership_team_active", "team_id", postgresql_where=text("removed_at IS NULL")
        ),
    )

    team_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("team.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("user.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[MembershipRole] = mapped_column(
        _enum(MembershipRole, "membership_role"),
        nullable=False,
        default=MembershipRole.MEMBER,
        server_default=MembershipRole.MEMBER.value,
    )

    joined_at: Mapped[datetime] = mapped_column(nullable=False)
    removed_at: Mapped[datetime | None] = mapped_column(nullable=True)
    removed_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("user.id", ondelete="SET NULL"), nullable=True
    )
    removal_reason: Mapped[RemovalReason | None] = mapped_column(
        _enum(RemovalReason, "removal_reason"), nullable=True
    )

    team: Mapped["Team"] = relationship(back_populates="memberships", foreign_keys=[team_id])
    user: Mapped["User"] = relationship(back_populates="memberships", foreign_keys=[user_id])

    @property
    def is_active(self) -> bool:
        return self.removed_at is None


class TeamJoinRequest(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A request to join a private party, awaiting the leader's decision."""

    __tablename__ = "team_join_request"
    __table_args__ = (
        Index(
            "uq_team_join_request_pending",
            "team_id",
            "user_id",
            unique=True,
            postgresql_where=text("status = 'pending'"),
        ),
    )

    team_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("team.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("user.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[JoinRequestStatus] = mapped_column(
        _enum(JoinRequestStatus, "join_request_status"),
        nullable=False,
        default=JoinRequestStatus.PENDING,
        server_default=JoinRequestStatus.PENDING.value,
    )
    message: Mapped[str | None] = mapped_column(String(280), nullable=True)

    decided_at: Mapped[datetime | None] = mapped_column(nullable=True)
    decided_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("user.id", ondelete="SET NULL"), nullable=True
    )

    team: Mapped["Team"] = relationship(foreign_keys=[team_id])
    user: Mapped["User"] = relationship(foreign_keys=[user_id], lazy="joined")
