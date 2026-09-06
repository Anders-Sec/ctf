"""Request and response models for the admin endpoints."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.models.user import UserRole, UserSource, UserStatus


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


class EventConfigResponse(BaseModel):
    name: str
    starts_at: datetime | None
    ends_at: datetime | None
    registration_open: bool
    server_time: datetime
