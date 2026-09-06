"""Request and response models for parties."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.models.team import JoinRequestStatus, TeamVisibility


class TeamMemberResponse(BaseModel):
    user_id: UUID
    display_name: str
    is_leader: bool
    has_avatar: bool
    joined_at: datetime


class TeamListItem(BaseModel):
    """The party browser. Deliberately shows no member identities."""

    id: UUID
    name: str
    visibility: TeamVisibility
    member_count: int
    max_members: int
    has_space: bool
    #: Whether joining needs a password, so the UI can prompt for one. Says
    #: nothing about what the password is.
    requires_password: bool


class TeamDetailResponse(BaseModel):
    id: UUID
    name: str
    visibility: TeamVisibility
    member_count: int
    max_members: int
    has_space: bool
    requires_password: bool
    leader_user_id: UUID
    members: list[TeamMemberResponse]
    created_at: datetime


class CreateTeamRequest(BaseModel):
    name: str = Field(min_length=3, max_length=32)
    visibility: TeamVisibility = TeamVisibility.PUBLIC
    #: Private parties only. Omitted means request-to-join is the only route in.
    join_password: str | None = Field(default=None, min_length=6, max_length=128)


class UpdateTeamRequest(BaseModel):
    name: str | None = Field(default=None, min_length=3, max_length=32)
    visibility: TeamVisibility | None = None
    join_password: str | None = Field(default=None, min_length=6, max_length=128)
    clear_password: bool = False


class JoinTeamRequest(BaseModel):
    password: str | None = Field(default=None, max_length=128)


class TransferLeadershipRequest(BaseModel):
    user_id: UUID


class CreateJoinRequest(BaseModel):
    message: str | None = Field(default=None, max_length=280)


class JoinRequestResponse(BaseModel):
    id: UUID
    team_id: UUID
    user_id: UUID
    display_name: str
    status: JoinRequestStatus
    message: str | None
    created_at: datetime
