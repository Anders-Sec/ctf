"""Avatar payloads (spec 073 §6)."""

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models.avatar import AccessorySlot, UnlockKind
from app.models.character_class import Rarity
from app.models.user import AvatarSource


class AccessoryOut(BaseModel):
    """One accessory, and whether this viewer has it.

    ``unlocked`` is computed per request rather than stored. A locked accessory
    is still listed — seeing what there is to earn is the point (spec 060 §9:
    "day-one emptiness is the point") — but §6 refuses it on `PUT`, so knowing
    it exists buys nothing but motivation.
    """

    model_config = ConfigDict(from_attributes=True)

    slug: str
    name: str
    description: str | None
    slot: AccessorySlot
    rarity: Rarity
    unlocked: bool
    #: Plain words for what earns it, so a locked row can say why.
    unlock_kind: UnlockKind
    unlock_ref: str | None
    #: Defaults the editor starts from, so a first placement is already close.
    anchor_x: float
    anchor_y: float
    anchor_scale: float
    anchor_rotation: float


class LayerIn(BaseModel):
    accessory: str = Field(max_length=64)
    x: float = 0.5
    y: float = 0.5
    scale: float = 1.0
    rotation: float = 0.0


class LayerOut(LayerIn):
    pass


class AvatarOut(BaseModel):
    source: AvatarSource
    layers: list[LayerOut]
    #: Plain words for the crest, for an ``alt`` attribute.
    description: str
    #: Whether this account has a photo to switch to at all.
    has_photo: bool


class AvatarIn(BaseModel):
    source: AvatarSource
    layers: list[LayerIn] = Field(default_factory=list, max_length=4)


class AccessoryAdminOut(BaseModel):
    """The whole row, for the admin roster (spec 073 §8)."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    slug: str
    name: str
    description: str | None
    slot: AccessorySlot
    rarity: Rarity
    image_key: str
    unlock_kind: UnlockKind
    unlock_ref: str | None
    anchor_x: float
    anchor_y: float
    anchor_scale: float
    anchor_rotation: float
    display_order: int
    enabled: bool


class CreateAccessoryRequest(BaseModel):
    #: Kebab-case and stable: a config that already names it must keep working,
    #: so this is the one field the admin surface does not offer to change.
    slug: str = Field(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$", max_length=64)
    name: str = Field(min_length=1, max_length=80)
    description: str | None = None
    slot: AccessorySlot
    rarity: Rarity = Rarity.COMMON
    unlock_kind: UnlockKind = UnlockKind.ALWAYS
    unlock_ref: str | None = Field(default=None, max_length=64)
    anchor_x: float = 0.5
    anchor_y: float = 0.3
    anchor_scale: float = 1.0
    anchor_rotation: float = 0.0
    display_order: int = 0


class UpdateAccessoryRequest(BaseModel):
    """Every field optional: this is a patch, and unsent means unchanged."""

    name: str | None = Field(default=None, min_length=1, max_length=80)
    description: str | None = None
    slot: AccessorySlot | None = None
    rarity: Rarity | None = None
    unlock_kind: UnlockKind | None = None
    unlock_ref: str | None = Field(default=None, max_length=64)
    anchor_x: float | None = None
    anchor_y: float | None = None
    anchor_scale: float | None = None
    anchor_rotation: float | None = None
    display_order: int | None = None
    enabled: bool | None = None
