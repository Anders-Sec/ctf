"""Request and response models for character sheets (spec 015)."""

from uuid import UUID

from pydantic import BaseModel


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


class PublicCharacterResponse(BaseModel):
    """Another player's public sheet: identity, overall level and skill levels.

    Rank and the fine-grained XP-to-next progress are left off — the board is
    where ranks live, and the exact distance to a player's next level is their
    own business."""

    user_id: UUID
    display_name: str
    has_avatar: bool
    level: int
    skills: list[PublicSkillResponse]
