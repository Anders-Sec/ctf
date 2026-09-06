"""Request and response models for admin hint management."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class CreateHintRequest(BaseModel):
    title: str = Field(min_length=2, max_length=200)
    body: str = Field(min_length=1, max_length=4000)
    #: Zero is allowed — a free hint is a legitimate thing to write.
    cost: int = Field(default=0, ge=0, le=100_000)
    display_order: int = 0
    prerequisite_hint_id: UUID | None = None
    available_after: datetime | None = None


class UpdateHintRequest(BaseModel):
    title: str | None = Field(default=None, min_length=2, max_length=200)
    body: str | None = Field(default=None, min_length=1, max_length=4000)
    cost: int | None = Field(default=None, ge=0, le=100_000)
    display_order: int | None = None
    prerequisite_hint_id: UUID | None = None
    available_after: datetime | None = None


class AdminHintResponse(BaseModel):
    id: UUID
    challenge_id: UUID
    title: str
    body: str
    cost: int
    display_order: int
    prerequisite_hint_id: UUID | None
    available_after: datetime | None
    #: How many players have paid. A hint with unlocks cannot be deleted.
    unlock_count: int
