"""Request and response models for admin challenge management."""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from app.models.challenge import (
    BossTier,
    ChallengeState,
    DecayBasis,
    Difficulty,
    MatchType,
    PreReleaseState,
    ScoringMode,
)
from app.models.play import MAX_SUBMISSION_LENGTH
from app.schemas.challenges import ArtifactResponse, CategoryResponse
from app.services.challenge_bulk import BulkAction


class CreateCategoryRequest(BaseModel):
    name: str = Field(min_length=2, max_length=60)
    slug: str = Field(min_length=2, max_length=60, pattern=r"^[a-z0-9-]+$")
    description: str | None = Field(default=None, max_length=500)
    display_order: int = 0


class CreateChallengeRequest(BaseModel):
    title: str = Field(min_length=3, max_length=200)
    slug: str = Field(min_length=3, max_length=200, pattern=r"^[a-z0-9-]+$")
    #: The category name, typed on the form. Resolved to an existing category
    #: (case-insensitively) or created (spec 013).
    category: str = Field(min_length=2, max_length=60)
    body: str = ""
    #: A label describing how hard this is (spec 040). It no longer derives the
    #: XP — it only suggests a starting number for a blank field.
    difficulty: Difficulty = Difficulty.MEDIUM
    #: The XP a solve awards. Omit to take the difficulty's suggestion; once set
    #: it is never recomputed, so relabelling difficulty cannot move it.
    initial_points: int | None = Field(default=None, ge=1, le=1_000_000)
    #: The floor decay stops at. Omit for 40% of the XP. Ignored while scoring
    #: is static.
    minimum_points: int | None = Field(default=None, ge=1, le=1_000_000)
    state: ChallengeState = ChallengeState.DRAFT
    release_at: datetime | None = None
    pre_release_state: PreReleaseState = PreReleaseState.HIDDEN
    decay_threshold: int = Field(default=40, ge=2, le=100_000)
    #: Omit for static (spec 040 — difficulty no longer implies decay). Set
    #: dynamic for a challenge that should lose value as it is solved.
    scoring: ScoringMode | None = None
    decay_basis: DecayBasis = DecayBasis.PLAYERS
    #: Off by default. Rate limiting is the brute-force defence.
    max_attempts: int | None = Field(default=None, ge=1, le=1000)


class UpdateChallengeRequest(BaseModel):
    title: str | None = Field(default=None, min_length=3, max_length=200)
    slug: str | None = Field(default=None, min_length=3, max_length=200, pattern=r"^[a-z0-9-]+$")
    category: str | None = Field(default=None, min_length=2, max_length=60)
    body: str | None = None
    #: A label only. Changing it no longer moves the XP (spec 040).
    difficulty: Difficulty | None = None
    initial_points: int | None = Field(default=None, ge=1, le=1_000_000)
    #: An explicit null resets the floor to 40% of the XP.
    minimum_points: int | None = Field(default=None, ge=1, le=1_000_000)
    release_at: datetime | None = None
    pre_release_state: PreReleaseState | None = None
    decay_threshold: int | None = Field(default=None, ge=2, le=100_000)
    scoring: ScoringMode | None = None
    decay_basis: DecayBasis | None = None
    max_attempts: int | None = Field(default=None, ge=1, le=1000)
    #: Attach (or, with an explicit null, detach) a container template. spec 014.
    container_template_id: UUID | None = None
    #: Null marks this challenge as not a boss; a tier makes it one (spec 031).
    boss_tier: BossTier | None = None
    #: Which rung of the System AI ladder this is, 0-5 (spec 033). Null — almost
    #: every challenge — means "not a ladder level". Setting it is what makes the
    #: challenge's answer the flag that rung defends, so the engine can resolve
    #: it; only one challenge may hold each rung.
    ai_ladder_level: int | None = Field(default=None, ge=0, le=5)


class PrerequisiteResponse(BaseModel):
    challenge_id: UUID
    title: str


class AddPrerequisiteRequest(BaseModel):
    required_challenge_id: UUID


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
    """One row of the challenge manager (spec 041).

    Wide enough that the table can be scanned without opening anything: the
    counts are what tell an admin which challenges are unfinished.
    """

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
    #: After decay. ``initial_points`` is what an admin set.
    current_value: int
    initial_points: int
    boss_tier: BossTier | None = None
    ai_ladder_level: int | None = None
    has_container: bool = False
    #: A zero here is the signal — a challenge nobody can solve, XP that lands on
    #: no character sheet. Counted in one query each, never per row.
    answer_count: int
    hint_count: int = 0
    skill_count: int = 0
    prerequisite_count: int = 0


class ZoneSummaryResponse(BaseModel):
    """A zone's header row in the manager (spec 041 §3)."""

    category_id: UUID
    name: str
    slug: str
    display_order: int
    challenge_count: int
    #: Against the 1,900 per zone that spec 018's curve was tuned for. Worth
    #: showing since spec 040 let a zone drift off it silently.
    total_xp: int
    boss_challenge_id: UUID | None
    boss_tier: BossTier | None
    draft_count: int
    published_count: int


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
    container_template_id: UUID | None = None
    #: Null when this challenge is not a boss (spec 031).
    boss_tier: BossTier | None = None
    prerequisites: list[PrerequisiteResponse] = []
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


class BulkRequest(BaseModel):
    """One endpoint for every bulk edit (spec 042).

    ``value``'s shape depends on the action — a state name, a difficulty, an XP
    expression like ``"+25"`` or ``"-10%"``, a list of skill names, an ISO
    timestamp, or nothing at all for a delete. Validated per action by the
    service rather than by a union type here, so the error names the action.
    """

    challenge_ids: list[UUID] = Field(min_length=1, max_length=500)
    action: BulkAction
    value: Any = None


class BulkItemResult(BaseModel):
    challenge_id: UUID
    ok: bool
    #: Why not, phrased so an admin knows what to do instead.
    reason: str | None = None


class BulkResultResponse(BaseModel):
    succeeded: int
    failed: int
    results: list[BulkItemResult]
    #: Zones deleted because their last challenge left (spec 013). Reported
    #: because it cannot be seen from the selection.
    categories_deleted: list[str] = []


class EmptiedZoneResponse(BaseModel):
    category_id: UUID
    name: str
    skills_orphaned: int


class DeletePreviewResponse(BaseModel):
    """What the confirm dialog shows before a bulk delete runs."""

    deletable: int
    blocked: list[BulkItemResult]
    zones_emptied: list[EmptiedZoneResponse]
