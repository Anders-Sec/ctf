"""Admin achievement CRUD contracts (spec 030)."""

from uuid import UUID

from pydantic import BaseModel, Field


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


class CreateAchievementRequest(BaseModel):
    code: str = Field(min_length=2, max_length=80, pattern=r"^[a-z][a-z0-9_]*$")
    name: str = Field(min_length=2, max_length=120)
    description: str | None = None
    earned_by: str = ""
    display_order: int = 0
    secret: bool = False


class UpdateAchievementRequest(BaseModel):
    """No `code`: it joins to a trigger and to every award already granted."""

    name: str | None = Field(default=None, min_length=2, max_length=120)
    description: str | None = None
    earned_by: str | None = None
    display_order: int | None = None
    secret: bool | None = None


class TriggerCodesResponse(BaseModel):
    registered: list[str]
    #: Registered triggers with no achievement row — the suggestion list.
    unused: list[str]
