"""The player identity, shared by both login paths."""

import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Enum, ForeignKey, Integer, LargeBinary, String
from sqlalchemy.dialects.postgresql import ARRAY, CITEXT, JSONB
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


class AvatarSource(enum.StrEnum):
    """Which base the avatar renderer starts from (spec 073 §3).

    The renderer does not care which: every one of these ends up as a PNG with
    the unlocked accessory layers composited on top. That is the point — there
    is one rendering path, so ``Avatar`` on the frontend is an ``<img>`` and
    nothing else.
    """

    #: Procedural heraldic crest from the user id. The default, and the fallback
    #: whenever generation is unavailable or declined — everybody has one on day
    #: one with no GPU and no setup.
    SIGIL = "sigil"
    #: The cached Entra photo, for the accounts that have one.
    ENTRA = "entra"
    #: A portrait from the generation service (spec 074).
    GENERATED = "generated"


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

    #: Notification kinds this player has turned down (spec 070 §4).
    #:
    #: A volume control, not a filter: a muted kind still arrives and still sits
    #: in the inbox, it simply does not toast and does not count toward the
    #: badge. A notification the server decided to send is part of the record.
    muted_notification_kinds: Mapped[list[str]] = mapped_column(
        ARRAY(String(40)), nullable=False, default=list, server_default="{}"
    )

    #: The **rendered** avatar, and the only thing ``GET /users/{id}/avatar``
    #: ever serves. Entra photos are not publicly fetchable — Graph requires a
    #: token — so those bytes are cached here too.
    #:
    #: Spec 073 made this the output of a renderer rather than a stored upload:
    #: ``avatar_source`` and ``avatar_config`` below are the recipe, and this is
    #: what they composited to. Re-derivable, so it is cache rather than truth.
    avatar_blob: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    avatar_updated_at: Mapped[datetime | None] = mapped_column(nullable=True)

    #: The **base** the renderer starts from: a cached Entra photo, or a
    #: portrait from spec 074. Separate from ``avatar_blob`` because that is now
    #: the composited output — keeping both in one column would mean either
    #: re-compositing on every request (200 roster rows, 2048px canvases) or
    #: losing the original the moment a hat was added.
    #:
    #: Null for a sigil, which is regenerated from the id rather than stored.
    avatar_base: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)

    #: Extra portrait generations an admin has granted this player on top of
    #: the standard budget (spec 074 §11.3). Lets somebody who lost an
    #: afternoon's worth to bad luck be topped up without a deploy.
    portrait_grant: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )

    #: Which base the renderer starts from (spec 073 §3).
    avatar_source: Mapped[AvatarSource] = mapped_column(
        Enum(AvatarSource, name="avatar_source", values_callable=lambda e: [m.value for m in e]),
        nullable=False,
        default=AvatarSource.SIGIL,
        server_default=AvatarSource.SIGIL.value,
    )
    #: ``{"layers": [{"accessory": slug, "x": .., "y": .., "scale": .., "rotation": ..}]}``
    #:
    #: The transform is stored rather than a flattened image, so unlocking a new
    #: hat next Tuesday does not lose the fit of the glasses, and the avatar can
    #: re-render at 40px and 200px from one recipe.
    avatar_config: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}"
    )

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

    #: The accessibility switch (spec 048 §10). Separate from ``theme`` rather
    #: than a value of it, so turning it off returns the player to whichever
    #: side of the light/dark toggle they were on, with nothing having to
    #: remember a "previous theme".
    high_contrast: Mapped[bool] = mapped_column(
        nullable=False, default=False, server_default="false"
    )

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
