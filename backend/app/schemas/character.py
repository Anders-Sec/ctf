"""Request and response models for character sheets (spec 015, 016)."""

from uuid import UUID

from pydantic import BaseModel


class ClassResponse(BaseModel):
    """A class as a player sees it. Only ever an unlocked one — 024 makes the
    roster a mystery, so a locked class is absent rather than described."""

    id: UUID
    name: str
    description: str | None
    #: Presentation only — drives colour, never a gate or a score (spec 024).
    rarity: str


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


class PartyBriefResponse(BaseModel):
    id: UUID
    name: str


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
    #: The party they are in (spec 060 §6). On the sheet rather than left to the
    #: session, so the sheet describes the character on its own.
    party: PartyBriefResponse | None = None
    #: The worn loot title — the name plate everybody else sees on the board.
    equipped_title: str | None = None
    #: The System AI's read on which class fits, or null. Never names a class
    #: the player has not unlocked.
    suggested_class: ClassResponse | None = None
    #: The nudge in the System AI's voice, ready to render (specs 013, 016).
    suggested_class_line: str | None = None


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
