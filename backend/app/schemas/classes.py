"""Request and response models for character classes (spec 016)."""

from uuid import UUID

from pydantic import BaseModel, Field

from app.models.challenge import Ability
from app.models.character_class import Rarity


class ClassResponse(BaseModel):
    id: UUID
    name: str
    display_order: int
    description: str | None


class CreateClassRequest(BaseModel):
    name: str = Field(min_length=2, max_length=60)
    display_order: int = 0
    description: str | None = Field(default=None, max_length=500)
    #: Presentation only — never read by a gate, a score or an ordering. It was
    #: on the model from spec 024 and settable from nowhere until spec 058.
    rarity: Rarity | None = None


class UpdateClassRequest(BaseModel):
    """Every field optional — a PATCH sends only what changed."""

    name: str | None = Field(default=None, min_length=2, max_length=60)
    display_order: int | None = None
    description: str | None = Field(default=None, max_length=500)
    rarity: Rarity | None = None


class PreferenceInput(BaseModel):
    """Exactly one of the two, matching the model's CHECK constraint.

    The D&D-named classes point at abilities and the cyber-named ones at skills
    (spec 024), which is why this is an XOR rather than two optional fields that
    happen to both be set sometimes.
    """

    ability: Ability | None = None
    skill_id: UUID | None = None


class RequirementInput(BaseModel):
    skill_id: UUID
    min_level: int = Field(ge=1, le=20)


class SetPreferencesRequest(BaseModel):
    #: The whole set, replacing what is there — the same shape as
    #: `PUT /admin/challenges/{id}/skills`, so an admin never has to reason about
    #: which of several calls left the class in its current state.
    preferences: list[PreferenceInput]


class SetRequirementsRequest(BaseModel):
    requirements: list[RequirementInput]
