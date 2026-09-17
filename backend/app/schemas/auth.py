"""Request and response models for authentication and the current user."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field

from app.models.user import UserRole, UserSource, UserStatus
from app.theme import FALLBACK_THEME


class MagicLinkRequest(BaseModel):
    email: EmailStr


class MagicLinkVerify(BaseModel):
    token: str = Field(min_length=16, max_length=256)


class UpdateProfileRequest(BaseModel):
    display_name: str = Field(min_length=2, max_length=64)


class UpdateThemeRequest(BaseModel):
    #: Null clears the choice, returning the user to the event default. That is
    #: distinct from picking the default explicitly, which pins them to it.
    theme: str | None = None


class UpdateHighContrastRequest(BaseModel):
    high_contrast: bool


class TeamSummary(BaseModel):
    id: UUID
    name: str
    is_leader: bool


class CapabilitiesResponse(BaseModel):
    manage_party: bool
    play: bool
    view_scoreboard: bool
    view_admin: bool
    administer: bool
    blocked_reason: str | None


class UserResponse(BaseModel):
    id: UUID
    email: str
    display_name: str
    source: UserSource
    role: UserRole
    status: UserStatus
    has_avatar: bool
    created_at: datetime


class MeResponse(BaseModel):
    """Everything the SPA needs to decide what to render.

    ``capabilities`` is resolved server-side so the frontend never re-implements
    the authorization matrix and cannot drift from it.
    """

    user: UserResponse
    team: TeamSummary | None
    capabilities: CapabilitiesResponse
    event: "EventSummary | None"
    #: Whether to offer the System AI chat at all: the feature has to be
    #: configured *and* this user has to be allowed to use it.
    assistant_available: bool = False
    #: Whether they have accepted the current terms of use (spec 035). False
    #: means the panel opens on the terms rather than the transcript — known on
    #: load, so the first thing a player sees is not a failed send.
    assistant_terms_accepted: bool = False
    #: The theme to render (spec 048) — already resolved, so the client never
    #: re-implements the precedence rule.
    theme: str = FALLBACK_THEME
    #: Where that theme came from, so the picker can say "following the event
    #: default" instead of pretending the user chose it.
    theme_source: Literal["user", "event"] = "event"
    #: Whether the accessibility switch is on. Reported alongside the resolved
    #: theme so the settings page can show the switch's real state rather than
    #: inferring it from the theme being served.
    high_contrast: bool = False
    #: What the toggle would return them to. Without this the settings page
    #: cannot show which side of light/dark is selected while high contrast is
    #: overriding it.
    base_theme: str = FALLBACK_THEME


class EventSummary(BaseModel):
    name: str
    starts_at: datetime | None
    ends_at: datetime | None
    registration_open: bool
    server_time: datetime


class MessageResponse(BaseModel):
    message: str
