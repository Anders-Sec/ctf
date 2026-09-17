"""Request and response models for party administration (spec 053)."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class PartySummary(BaseModel):
    team_id: UUID
    name: str
    visibility: str
    member_count: int
    max_members: int
    leader_user_id: UUID
    leader_name: str | None
    #: Disabled, or not seen in a day. The "leader went home" signal, visible
    #: without opening anything.
    leader_absent: bool
    has_password: bool
    created_at: datetime
    disbanded_at: datetime | None


class PartyMember(BaseModel):
    user_id: UUID
    display_name: str
    role: str
    joined_at: datetime
    #: Set for a former member. Rows are never hard-deleted (spec 002), and that
    #: history is what an admin needs when adjudicating a complaint.
    removed_at: datetime | None
    removed_by_name: str | None
    removal_reason: str | None
    solve_count: int
    xp: int


class PendingJoinRequest(BaseModel):
    id: UUID
    user_id: UUID
    display_name: str
    message: str | None
    created_at: datetime


class PartyDetailResponse(BaseModel):
    team_id: UUID
    name: str
    visibility: str
    max_members: int
    leader_user_id: UUID
    has_password: bool
    disbanded_at: datetime | None
    members: list[PartyMember]
    join_requests: list[PendingJoinRequest]


class UpdatePartyRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=64)
    visibility: str | None = Field(default=None, pattern="^(public|private)$")
    max_members: int | None = Field(default=None, ge=1, le=64)
    #: Cleared, never shown — it is an Argon2id hash. Clearing turns a private
    #: party into request-to-join, which is the fix when nobody remembers it.
    clear_join_password: bool = False
    reason: str | None = Field(default=None, max_length=500)


class TransferLeaderRequest(BaseModel):
    user_id: UUID


class AddMemberRequest(BaseModel):
    user_id: UUID
    reason: str | None = Field(default=None, max_length=500)


class MoveMemberRequest(BaseModel):
    to_team_id: UUID
    reason: str | None = Field(default=None, max_length=500)


class ReasonRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=500)


class EligibleMember(BaseModel):
    user_id: UUID
    display_name: str
