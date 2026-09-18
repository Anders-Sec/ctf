"""Request and response models for character sheets (spec 015, 016)."""

from uuid import UUID

from pydantic import BaseModel

from app.schemas.notifications import StarResponse


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


class ZoneSolvesResponse(BaseModel):
    """Counts only. A per-zone XP total would be XP wearing a different hat."""

    zone_name: str
    solves: int


class PublicAchievementResponse(BaseModel):
    """One row of somebody else's trophy case (spec 061 §4).

    `name` and `rarity` are both null when the row is a secret the viewer has not
    earned. Redacted server-side, so there is nothing to un-blur in devtools.
    """

    id: UUID
    name: str | None
    rarity: float | None


class PublicAchievementsResponse(BaseModel):
    earned: int
    #: Hidden from this viewer. Omitted from the display when zero (§9.2).
    secret_count: int
    items: list[PublicAchievementResponse]
    #: The five rarest the viewer can see *named* (§4.2).
    rarest: list[PublicAchievementResponse]


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
    #: Null for anybody the board does not hold — staff accounts are excluded
    #: from it by design, and "no rank" is the honest answer for them.
    rank: int | None = None
    party: PartyBriefResponse | None = None
    equipped_title: str | None = None
    #: Every row the list carries is discovered, so the total has to be sent
    #: separately for "14 of 45 discovered" to be true.
    skills_total: int = 0
    #: Bosses felled. The only place these appear on a player's own page, since
    #: you cannot look at somebody else's challenge list (spec 061 §5).
    stars: list[StarResponse] = []
    solve_count: int = 0
    zones: list[ZoneSolvesResponse] = []
