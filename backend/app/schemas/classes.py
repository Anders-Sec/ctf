"""Request and response models for character classes (spec 016)."""

from uuid import UUID

from pydantic import BaseModel, Field


class ClassResponse(BaseModel):
    id: UUID
    name: str
    display_order: int
    description: str | None


class CreateClassRequest(BaseModel):
    name: str = Field(min_length=2, max_length=60)
    display_order: int = 0
    description: str | None = Field(default=None, max_length=500)


class UpdateClassRequest(BaseModel):
    """Every field optional — a PATCH sends only what changed."""

    name: str | None = Field(default=None, min_length=2, max_length=60)
    display_order: int | None = None
    description: str | None = Field(default=None, max_length=500)
