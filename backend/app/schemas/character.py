"""Request and response models for character sheets (spec 015, 016)."""

from uuid import UUID

from pydantic import BaseModel


class ClassResponse(BaseModel):
    id: UUID
    name: str
    description: str | None


class SetClassRequest(BaseModel):
    #: The class to adopt, or null to return to Classless.
    class_id: UUID | None


class AbilityResponse(BaseModel):
    """A D&D ability score. The score shows; progress toward the next point does
    not — abilities tick up quietly (spec 018)."""

    ability: str
    score: int


class SkillRowResponse(BaseModel):
    """Name and level only. There is deliberately **no XP field** — the numbers
    cannot leak through the API if they are never carried. ``name`` is a
    placeholder while ``discovered`` is false."""

    skill_id: UUID
    name: str
    kind: str
    level: int
    discovered: bool


class CharacterSheetResponse(BaseModel):
    """The player's own sheet: full progress detail and board rank."""

    user_id: UUID
    display_name: str
    has_avatar: bool
    total_xp: int
    level: int
    xp_into_level: int
    xp_to_next: int
    rank: int | None
    abilities: list[AbilityResponse]
    skills: list[SkillRowResponse]
    character_class: ClassResponse | None
    class_unlocked: bool
    class_unlock_level: int


class PublicCharacterResponse(BaseModel):
    """Another player's sheet. Everything is fair game (spec 018) except skills
    they have not discovered, which are omitted rather than placeholdered — there
    is nothing to tease a stranger with."""

    user_id: UUID
    display_name: str
    has_avatar: bool
    level: int
    abilities: list[AbilityResponse]
    skills: list[SkillRowResponse]
    character_class: ClassResponse | None
