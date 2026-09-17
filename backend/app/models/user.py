"""The player identity, shared by both login paths."""

import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Enum, ForeignKey, Integer, LargeBinary, String
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

    #: Takes the dungeon master away from one person mid-event. Without it the
    #: only lever is the event-wide switch, and one player misbehaving should
    #: not cost the other 199 the feature.
    assistant_blocked: Mapped[bool] = mapped_column(
        nullable=False, default=False, server_default="false"
    )

    #: An explicit ladder selection (spec 033). Null — the default — means "track
    #: my maximum", so a player who never touches the selector always faces the
    #: level their solves have earned. A selection is what lets them go *back*:
    #: without it, solving a level destroys it forever.
    #:
    #: Never trusted above the derived maximum. The level is a security boundary
    #: and the maximum is recomputed from solves on every turn.
    ai_ladder_level: Mapped[int | None] = mapped_column(Integer, nullable=True)

    #: When the System AI first handed this player level 0's flag. One indexed
    #: column rather than a join over message history, because it is read on
    #: every unlock evaluation.
    ai_ladder_leaked_at: Mapped[datetime | None] = mapped_column(nullable=True)

    #: The chosen theme (spec 048). Null means "follow the event default", which
    #: is not the same as having chosen the default — it is what lets an admin
    #: move everyone who has not expressed a preference.
    #:
    #: Held as a plain string rather than an enum: the roster lives in
    #: ``app.theme`` and in the frontend's CSS, and a database enum would add a
    #: migration to every preset added or removed. An unrecognised value falls
    #: back rather than raising (see ``app.theme.resolve_theme``).
    theme: Mapped[str | None] = mapped_column(String(32), nullable=True)

    approved_at: Mapped[datetime | None] = mapped_column(nullable=True)
    approved_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("user.id", ondelete="SET NULL"), nullable=True
    )
    #: Why an admin disabled the account. Admin-facing only.
    disabled_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)

    last_login_at: Mapped[datetime | None] = mapped_column(nullable=True)

    #: The player's chosen archetype (spec 016). SET NULL so deleting a class
    #: returns its players to Classless rather than cascading into user rows.
    character_class_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("character_class.id", ondelete="SET NULL"), nullable=True
    )

    #: The one loot title being worn, shown beside the name on the scoreboard
    #: (spec 038). Cosmetic; it never touches the board's ordering.
    equipped_title_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("loot_item.id", ondelete="SET NULL"), nullable=True
    )

    memberships: Mapped[list["TeamMembership"]] = relationship(
        back_populates="user",
        foreign_keys="TeamMembership.user_id",
    )

    @property
    def is_staff(self) -> bool:
        return self.role in (UserRole.ORGANIZER, UserRole.ADMIN)

    def __repr__(self) -> str:
        return f"<User {self.email} {self.source} {self.status}>"
