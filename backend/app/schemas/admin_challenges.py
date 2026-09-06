"""Request and response models for admin challenge management."""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from app.models.challenge import (
    ChallengeState,
    DecayBasis,
    Difficulty,
    MatchType,
    PreReleaseState,
    ScoringMode,
)
from app.models.play import MAX_SUBMISSION_LENGTH
from app.schemas.challenges import ArtifactResponse, CategoryResponse


class CreateCategoryRequest(BaseModel):
    name: str = Field(min_length=2, max_length=60)
    slug: str = Field(min_length=2, max_length=60, pattern=r"^[a-z0-9-]+$")
    description: str | None = Field(default=None, max_length=500)
    display_order: int = 0


class CreateChallengeRequest(BaseModel):
    title: str = Field(min_length=3, max_length=200)
    slug: str = Field(min_length=3, max_length=200, pattern=r"^[a-z0-9-]+$")
    category_id: UUID
    body: str = ""
    difficulty: Difficulty = Difficulty.MEDIUM
    state: ChallengeState = ChallengeState.DRAFT
    release_at: datetime | None = None
    pre_release_state: PreReleaseState = PreReleaseState.HIDDEN
    initial_points: int = Field(default=500, ge=1, le=100_000)
    minimum_points: int = Field(default=100, ge=0, le=100_000)
    decay_threshold: int = Field(default=40, ge=2, le=100_000)
    scoring: ScoringMode = ScoringMode.DYNAMIC
    decay_basis: DecayBasis = DecayBasis.PLAYERS
    #: Off by default. Rate limiting is the brute-force defence.
    max_attempts: int | None = Field(default=None, ge=1, le=1000)


class UpdateChallengeRequest(BaseModel):
    title: str | None = Field(default=None, min_length=3, max_length=200)
    slug: str | None = Field(default=None, min_length=3, max_length=200, pattern=r"^[a-z0-9-]+$")
    category_id: UUID | None = None
    body: str | None = None
    difficulty: Difficulty | None = None
    release_at: datetime | None = None
    pre_release_state: PreReleaseState | None = None
    initial_points: int | None = Field(default=None, ge=1, le=100_000)
    minimum_points: int | None = Field(default=None, ge=0, le=100_000)
    decay_threshold: int | None = Field(default=None, ge=2, le=100_000)
    scoring: ScoringMode | None = None
    decay_basis: DecayBasis | None = None
    max_attempts: int | None = Field(default=None, ge=1, le=1000)


class SetStateRequest(BaseModel):
    state: ChallengeState
    #: Recorded in the audit log. Pulling a challenge mid-event is exactly the
    #: decision someone will ask about afterwards.
    reason: str | None = Field(default=None, max_length=500)


class CreateAnswerRequest(BaseModel):
    match_type: MatchType
    value: str = Field(min_length=1, max_length=4000)
    options: dict[str, Any] = Field(default_factory=dict)
    label: str | None = Field(default=None, max_length=200)
    display_order: int = 0


class AdminAnswerResponse(BaseModel):
    id: UUID
    match_type: MatchType
    #: Returned in full. An admin who cannot see the expected answer cannot
    #: debug a challenge nobody is solving.
    value: str
    options: dict[str, Any]
    label: str | None
    display_order: int


class AnswerTestRequest(BaseModel):
    candidate: str = Field(min_length=1, max_length=MAX_SUBMISSION_LENGTH)


class AnswerTestResponse(BaseModel):
    correct: bool
    matched_answer_id: UUID | None
    matched_label: str | None
    #: Rules that could not be evaluated — a timed-out pattern, say.
    errors: list[str]


class AdminChallengeSummary(BaseModel):
    id: UUID
    title: str
    slug: str
    category: CategoryResponse
    difficulty: Difficulty
    state: ChallengeState
    #: What a player would see right now, after the release schedule applies.
    effective_state: ChallengeState
    release_at: datetime | None
    solve_count: int
    current_value: int
    answer_count: int


class AdminChallengeDetail(BaseModel):
    id: UUID
    title: str
    slug: str
    category: CategoryResponse
    difficulty: Difficulty
    state: ChallengeState
    release_at: datetime | None
    pre_release_state: PreReleaseState
    initial_points: int
    minimum_points: int
    decay_threshold: int
    scoring: ScoringMode
    decay_basis: DecayBasis
    max_attempts: int | None
    solve_count: int
    current_value: int
    body: str
    answers: list[AdminAnswerResponse]
    artifacts: list[ArtifactResponse]
    created_at: datetime


class SubmissionLogEntry(BaseModel):
    id: UUID
    user_id: UUID
    challenge_id: UUID
    team_id_at_submit: UUID | None
    is_correct: bool
    submitted_value: str
    ip: str | None
    request_id: str | None
    created_at: datetime
