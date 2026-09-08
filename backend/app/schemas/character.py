"""Request and response models for character sheets (spec 015, 016)."""

from uuid import UUID

from pydantic import BaseModel


class ClassResponse(BaseModel):
    id: UUID
    name: str
    description: str | None


class SuggestedClassResponse(BaseModel):
    """The System AI's suggested class, with its voiced narration (spec 016)."""

    class_id: UUID
    name: str
    from_skill: str
    narration: str


class SetClassRequest(BaseModel):
    #: The class to adopt, or null to return to Classless.
    class_id: UUID | None


class SkillSliceResponse(BaseModel):
    skill_id: UUID
    name: str
    xp: int
    level: int
    xp_into_level: int
    xp_to_next: int


class PublicSkillResponse(BaseModel):
    """A skill on someone else's sheet — level without the fine-grained progress."""

    skill_id: UUID
    name: str
    level: int


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
    skills: list[SkillSliceResponse]
    character_class: ClassResponse | None
    suggested_class: SuggestedClassResponse | None
    class_unlocked: bool
    class_unlock_level: int


class PublicCharacterResponse(BaseModel):
    """Another player's public sheet: identity, overall level, skill levels, class.

    Rank, the fine-grained XP-to-next progress, and the suggested-class nudge are
    left off — the board is where ranks live, and the suggestion is the player's
    own business."""

    user_id: UUID
    display_name: str
    has_avatar: bool
    level: int
    skills: list[PublicSkillResponse]
    character_class: ClassResponse | None
