"""Avatar accessories — the cosmetic layer (spec 073).

Accessories are **rewards**, and a reward has to be recognisable. That is the
whole reason these are composited PNGs with authored anchors rather than
anything generated: a wizard hat that looked different on every player would
stop reading as a badge. It also means the reward system needs no GPU, so
spec 074's generation host is optional infrastructure rather than a dependency.

Unlocks are **derived, never granted** — see ``app.services.avatars``. You have
the wizard hat because your class is wizard, computed on read from data that
already exists, the way achievements work. No grant table means no grant table
to fall out of sync.
"""

import enum

from sqlalchemy import Enum, Float, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import CITEXT
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.character_class import Rarity


class AccessorySlot(enum.StrEnum):
    """Where an accessory sits.

    Exists so two hats cannot occupy one head: the renderer takes at most one
    accessory per slot, and a config naming two is rejected rather than drawn.
    """

    HEAD = "head"
    EYES = "eyes"
    SHOULDERS = "shoulders"
    FRAME = "frame"


class UnlockKind(enum.StrEnum):
    """What earns an accessory.

    Each of these resolves against something the player already has, which is
    why nothing needs granting. ``ALWAYS`` is the starter set everybody holds.
    """

    ALWAYS = "always"
    CLASS = "class"
    ACHIEVEMENT = "achievement"
    LOOT_RARITY = "loot_rarity"


class AvatarAccessory(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One piece of art, and the rule that earns it."""

    __tablename__ = "avatar_accessory"
    __table_args__ = (UniqueConstraint("slug", name="uq_avatar_accessory_slug"),)

    slug: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(CITEXT(), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    slot: Mapped[AccessorySlot] = mapped_column(
        Enum(AccessorySlot, name="accessory_slot", values_callable=lambda e: [m.value for m in e]),
        nullable=False,
    )
    #: Key in object storage. The art itself never lives in this table.
    image_key: Mapped[str] = mapped_column(String(255), nullable=False)
    rarity: Mapped[Rarity] = mapped_column(
        Enum(Rarity, name="class_rarity", values_callable=lambda e: [m.value for m in e]),
        nullable=False,
        default=Rarity.COMMON,
        server_default=Rarity.COMMON.value,
    )

    #: Defaults that are right for most people, because every corporate photo is
    #: shot at the same angle and the sigil is drawn to a fixed template. The
    #: editor is correction, not composition.
    #:
    #: Fractions of the canvas, so one anchor works at 40px and at 512px.
    anchor_x: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.5, server_default="0.5"
    )
    anchor_y: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.5, server_default="0.5"
    )
    anchor_scale: Mapped[float] = mapped_column(
        Float, nullable=False, default=1.0, server_default="1.0"
    )
    anchor_rotation: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.0, server_default="0.0"
    )

    unlock_kind: Mapped[UnlockKind] = mapped_column(
        Enum(
            UnlockKind, name="accessory_unlock_kind", values_callable=lambda e: [m.value for m in e]
        ),
        nullable=False,
        default=UnlockKind.ALWAYS,
        server_default=UnlockKind.ALWAYS.value,
    )
    #: The class name, achievement code, or loot rarity it reads. Null for
    #: ``ALWAYS``, which needs nothing to resolve against.
    unlock_ref: Mapped[str | None] = mapped_column(String(64), nullable=True)

    display_order: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    #: Lets an operator pull a piece of art mid-event without deleting it and
    #: orphaning the configs that reference it.
    enabled: Mapped[bool] = mapped_column(nullable=False, default=True, server_default="true")
