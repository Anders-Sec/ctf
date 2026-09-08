"""Request and response models for skills and the category→skill map (spec 015)."""

from uuid import UUID

from pydantic import BaseModel, Field


class SkillResponse(BaseModel):
    id: UUID
    name: str
    display_order: int
    description: str | None


class CreateSkillRequest(BaseModel):
    name: str = Field(min_length=2, max_length=60)
    display_order: int = 0
    description: str | None = Field(default=None, max_length=500)


class UpdateSkillRequest(BaseModel):
    """Every field optional — a PATCH sends only what changed."""

    name: str | None = Field(default=None, min_length=2, max_length=60)
    display_order: int | None = None
    description: str | None = Field(default=None, max_length=500)


class AdminCategoryResponse(BaseModel):
    """A category with its skill mapping, for the admin skills page."""

    id: UUID
    name: str
    slug: str
    display_order: int
    skill_id: UUID | None


class SetCategorySkillRequest(BaseModel):
    #: The skill to map this category to, or null to un-map it.
    skill_id: UUID | None
