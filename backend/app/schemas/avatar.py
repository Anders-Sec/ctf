"""Avatar payloads (spec 073 §6)."""

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
