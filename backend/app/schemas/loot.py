"""Loot box contracts (spec 038)."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class LootBoxResponse(BaseModel):
    """An unopened box waiting in the inventory."""

    id: UUID
    box_type: str
    rarity: str
    achievement_name: str
    created_at: datetime


class HeldTitleResponse(BaseModel):
    item_id: UUID
    title: str
    rarity: str
    box_type: str
    #: Written by the model rather than by hand.
    generated: bool
    equipped: bool


class OpenedResponse(BaseModel):
    box_id: UUID
    title: str
    rarity: str
    box_type: str
    generated: bool


class EquipRequest(BaseModel):
    #: Null takes the title off.
    item_id: UUID | None = None
