"""Request and response models for the admin endpoints."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.models.user import UserRole, UserSource, UserStatus
from app.theme import THEME_IDS


class UserSummary(BaseModel):
    id: UUID
    email: str
    display_name: str
    source: UserSource
    role: UserRole
    status: UserStatus
    created_at: datetime
    approved_at: datetime | None
    last_login_at: datetime | None
    #: Enough to tell a real player from a dormant account at a glance (spec
    #: 052). Aggregate subqueries on the list query, never an N+1 across 200.
    party_name: str | None = None
    solve_count: int = 0
    xp: int = 0


class EnableUserRequest(BaseModel):
    #: Required for the same reason disabling is: an account whose access
    #: changed without a recorded why is impossible to explain later.
    reason: str = Field(min_length=3, max_length=500)


class AssistantBlockRequest(BaseModel):
    blocked: bool
    reason: str | None = Field(default=None, max_length=500)


class ThemeGrantRequest(BaseModel):
    """Hand a secret theme over, or take it back (spec 058 §5.1)."""

    theme: str
    granted: bool
    reason: str | None = Field(default=None, max_length=500)


class PartySpell(BaseModel):
    """A membership, current or ended."""

    team_id: UUID
    team_name: str
    role: str
    joined_at: datetime
    removed_at: datetime | None
    removal_reason: str | None


class ActivityEntry(BaseModel):
    challenge_id: UUID
    challenge_title: str | None
    is_correct: bool
    created_at: datetime


class UserDetailResponse(BaseModel):
    """Everything the detail drawer needs, in one call.

    One endpoint rather than the panel fanning out to six, so opening a row
    while working a queue costs one request.
    """

    user: UserSummary
    entra_object_id: UUID | None
    approved_by_name: str | None
    disabled_reason: str | None
    assistant_blocked: bool
    level: int
    hints_used: int
    achievement_count: int
    class_name: str | None
    #: Secret themes this player holds, and which ones an admin may hand over.
    unlocked_themes: list[str]
    grantable_themes: list[str]
    parties: list[PartySpell]
    recent_activity: list[ActivityEntry]
    #: The challenge they have most recently attempted without solving — the
    #: single most useful field when someone is stuck (spec 050 §5).
    current_wall: str | None


class UserListResponse(BaseModel):
    total: int
    users: list[UserSummary]


class ApproveUsersRequest(BaseModel):
    #: A list, because approving 200 guests one at a time is not a plan.
    user_ids: list[UUID] = Field(min_length=1, max_length=200)
    reason: str | None = Field(default=None, max_length=500)
    notify: bool = True


class DisableUserRequest(BaseModel):
    #: Required: an account disabled without a recorded reason is impossible to
    #: explain later, and this is the most contested action an admin can take.
    reason: str = Field(min_length=3, max_length=500)


class SetRoleRequest(BaseModel):
    role: UserRole
    reason: str | None = Field(default=None, max_length=500)


class UpdateEventConfigRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    registration_open: bool | None = None
    #: The runtime kill switch for the dungeon master (spec 011). A redeploy is
    #: the wrong tool at 11pm on day two.
    assistant_enabled: bool | None = None
    fog_of_war: bool | None = None
    #: The theme served to everyone who has not chosen one (spec 048). Null
    #: clears it back to the platform default.
    default_theme: str | None = None


class EventConfigResponse(BaseModel):
    name: str
    starts_at: datetime | None
    ends_at: datetime | None
    registration_open: bool
    assistant_enabled: bool
    fog_of_war: bool
    default_theme: str | None
    #: Every selectable theme, so the settings page renders the picker from the
    #: server's roster rather than its own copy of the list.
    themes: list[str] = list(THEME_IDS)
    server_time: datetime
