"""Request and response models for skills and the category→ability map (spec 018)."""

from uuid import UUID

from pydantic import BaseModel, Field

from app.models.challenge import Ability, SkillKind


class SkillResponse(BaseModel):
    id: UUID
    name: str
    display_order: int
    description: str | None
    kind: SkillKind
    #: Sorts the challenge editor's picker; it does not constrain which
    #: challenges may carry the skill.
    category_id: UUID | None


class CreateSkillRequest(BaseModel):
    name: str = Field(min_length=2, max_length=60)
    display_order: int = 0
    description: str | None = Field(default=None, max_length=500)
    kind: SkillKind = SkillKind.USEFUL
    category_id: UUID | None = None


class UpdateSkillRequest(BaseModel):
    """Every field optional — a PATCH sends only what changed."""

    name: str | None = Field(default=None, min_length=2, max_length=60)
    display_order: int | None = None
    description: str | None = Field(default=None, max_length=500)
    kind: SkillKind | None = None
    category_id: UUID | None = None


class AdminCategoryResponse(BaseModel):
    """A category with the ability it feeds (spec 018)."""

    id: UUID
    name: str
    slug: str
    display_order: int
    ability: Ability


class SetCategoryAbilityRequest(BaseModel):
    #: Required — an unmapped category would drop its XP out of the stat block.
    ability: Ability


class SetChallengeSkillsRequest(BaseModel):
    """The complete set of skills for a challenge; replaces whatever was there."""

    skill_ids: list[UUID]
