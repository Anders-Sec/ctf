"""The player identity, shared by both login paths."""

import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Enum, ForeignKey, LargeBinary, String
from sqlalchemy.dialects.postgresql import CITEXT
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.team import TeamMembership


class UserSource(enum.StrEnum):
    ENTRA = "entra"
    GUEST = "guest"


class UserRole(enum.StrEnum):
    PLAYER = "player"
    #: Read-only staff visibility. Event staff watching for broken challenges
    #: should not need an account that can silently rewrite scores.
    ORGANIZER = "organizer"
    ADMIN = "admin"


class UserStatus(enum.StrEnum):
    PENDING_APPROVAL = "pending_approval"
    ACTIVE = "active"
    DISABLED = "disabled"


class User(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A player, organizer or admin.

    ``email`` is the identity key across both login paths, which is what lets a
    guest account be upgraded in place when the same person later signs in
    through Entra.

    Phase 2 adds character and stat columns here additively — nothing below is a
    natural key a stat block would have to break.
    """

    __tablename__ = "user"

    email: Mapped[str] = mapped_column(CITEXT(), unique=True, nullable=False, index=True)
    display_name: Mapped[str] = mapped_column(String(64), nullable=False)

    source: Mapped[UserSource] = mapped_column(
        Enum(UserSource, name="user_source", values_callable=lambda e: [m.value for m in e]),
        nullable=False,
    )
    entra_object_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), unique=True, nullable=True
    )

    role: Mapped[UserRole] = mapped_column(
        Enum(UserRole, name="user_role", values_callable=lambda e: [m.value for m in e]),
        nullable=False,
        default=UserRole.PLAYER,
        server_default=UserRole.PLAYER.value,
    )
    status: Mapped[UserStatus] = mapped_column(
        Enum(UserStatus, name="user_status", values_callable=lambda e: [m.value for m in e]),
        nullable=False,
    )

    #: Entra profile photos are not publicly fetchable — Graph requires a token —
    #: so the bytes are cached here and served through our own endpoint.
    avatar_blob: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    avatar_updated_at: Mapped[datetime | None] = mapped_column(nullable=True)

    approved_at: Mapped[datetime | None] = mapped_column(nullable=True)
    approved_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("user.id", ondelete="SET NULL"), nullable=True
    )
    #: Why an admin disabled the account. Admin-facing only.
    disabled_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)

    last_login_at: Mapped[datetime | None] = mapped_column(nullable=True)

    memberships: Mapped[list["TeamMembership"]] = relationship(
        back_populates="user",
        foreign_keys="TeamMembership.user_id",
    )

    @property
    def is_staff(self) -> bool:
        return self.role in (UserRole.ORGANIZER, UserRole.ADMIN)

    def __repr__(self) -> str:
        return f"<User {self.email} {self.source} {self.status}>"
