"""Admin achievement CRUD contracts (spec 030)."""

from uuid import UUID

from pydantic import BaseModel, Field

from app.models.notification import LootBoxType, LootRarity


class AdminAchievementResponse(BaseModel):
    id: UUID
    code: str
    name: str
    description: str
    earned_by: str
    display_order: int
    secret: bool
    #: False when no trigger is registered for this code: the achievement is
    #: inert and will never fire.
    has_trigger: bool
    #: True while the description is still the seeded placeholder.
    needs_copy: bool
    held_by: int
    #: The reward. On the model since spec 038 and editable from nowhere until
    #: spec 058 — which is why an achievement's payout used to be whatever the
    #: seed said, permanently.
    loot_box_type: str | None = None
    loot_rarity: str | None = None
    no_loot_line: str | None = None
    #: The secret theme this hands over (spec 058 §5).
    unlocks_theme: str | None = None


class CreateAchievementRequest(BaseModel):
    code: str = Field(min_length=2, max_length=80, pattern=r"^[a-z][a-z0-9_]*$")
    name: str = Field(min_length=2, max_length=120)
    description: str | None = None
    earned_by: str = ""
    display_order: int = 0
    secret: bool = False
    loot_box_type: LootBoxType | None = None
    loot_rarity: LootRarity | None = None
    no_loot_line: str | None = None
    unlocks_theme: str | None = None


class UpdateAchievementRequest(BaseModel):
    """No `code`: it joins to a trigger and to every award already granted."""

    name: str | None = Field(default=None, min_length=2, max_length=120)
    description: str | None = None
    earned_by: str | None = None
    display_order: int | None = None
    secret: bool | None = None
    #: The reward, editable at last (spec 058 §4). `None` in a PATCH means "not
    #: sent"; clearing a reward is done with the explicit flags below, because
    #: null is the cleared value and PATCH cannot tell the two apart.
    loot_box_type: LootBoxType | None = None
    loot_rarity: LootRarity | None = None
    no_loot_line: str | None = None
    unlocks_theme: str | None = None
    clear_loot: bool = False
    clear_theme: bool = False


class TriggerCodesResponse(BaseModel):
    registered: list[str]
    #: Registered triggers with no achievement row — the suggestion list.
    unused: list[str]
    #: Trigger families, whose codes depend on data rather than being fixed.
    families: list[str] = []
