"""Request and response models for operational admin actions."""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

from app.models.challenge import ChallengeState, PreReleaseState
from app.models.report import ReportStatus


class CreateAdjustmentRequest(BaseModel):
    #: Exactly one target. A party adjustment belongs to the party itself, not
    #: to its members and not to its leader.
    user_id: UUID | None = None
    team_id: UUID | None = None
    points: int = Field(ge=-100_000, le=100_000)
    #: Required. An unexplained score change is indefensible after the event.
    reason: str = Field(min_length=3, max_length=500)

    @model_validator(mode="after")
    def _exactly_one_target(self) -> "CreateAdjustmentRequest":
        if (self.user_id is None) == (self.team_id is None):
            raise ValueError("Provide exactly one of user_id or team_id.")
        return self


class ReverseAdjustmentRequest(BaseModel):
    reason: str = Field(min_length=3, max_length=500)


class AdjustmentResponse(BaseModel):
    id: UUID
    user_id: UUID | None
    team_id: UUID | None
    subject_name: str | None
    points: int
    reason: str
    created_by_user_id: UUID | None
    created_by_name: str | None
    reverses_id: UUID | None
    #: Set when a later entry cancelled this one. Shown struck through, never hidden.
    reversed_by_id: UUID | None
    created_at: datetime


class ReportRequest(BaseModel):
    message: str = Field(min_length=5, max_length=1000)


class ReportResponse(BaseModel):
    id: UUID
    challenge_id: UUID
    challenge_title: str | None
    user_id: UUID
    reporter_name: str | None
    message: str
    status: ReportStatus
    resolution_note: str | None
    created_at: datetime


class TriageReportRequest(BaseModel):
    status: ReportStatus
    note: str | None = Field(default=None, max_length=500)


class ChallengeHealthResponse(BaseModel):
    challenge_id: UUID
    title: str
    state: ChallengeState
    solve_count: int
    attempt_count: int
    open_reports: int
    suspected_broken: bool
    suspiciously_easy: bool


class BulkReleaseRequest(BaseModel):
    challenge_ids: list[UUID] = Field(min_length=1, max_length=200)
    #: Null clears the schedule, making the challenge follow its own state.
    release_at: datetime | None = None
    pre_release_state: PreReleaseState | None = None


class AuditEntryResponse(BaseModel):
    id: UUID
    action: str
    actor_user_id: UUID | None
    actor_name: str | None
    target_type: str
    target_id: UUID | None
    reason: str | None
    metadata: dict[str, Any]
    request_id: str | None
    created_at: datetime


class AuditPageResponse(BaseModel):
    """One page of the log, with the size of the whole result set.

    Paginated where spec 041 deliberately refused to paginate the challenge
    list: that is 242 rows with a known ceiling, while the log grows unbounded
    across five days of approvals, kicks and edits, and has no natural grouping
    to collapse under.
    """

    total: int
    entries: list[AuditEntryResponse]


class PlayDataGroup(BaseModel):
    """What one clearable group currently holds (spec 043)."""

    group: str
    #: Written for an admin, not for a schema — this is the confirm dialog's text.
    label: str
    rows: int


class ResetPlayDataRequest(BaseModel):
    """Groups are named explicitly, never defaulted. The difference between
    clearing one thing and clearing all fourteen must not come down to a
    missing field."""

    groups: list[str] = Field(min_length=1)


class ResetPlayDataResponse(BaseModel):
    #: Table name -> rows removed.
    deleted: dict[str, int]
    total: int
