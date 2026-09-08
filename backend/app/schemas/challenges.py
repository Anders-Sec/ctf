"""Request and response models for challenges and submissions."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.models.challenge import ChallengeState, Difficulty
from app.models.play import MAX_SUBMISSION_LENGTH


class CategoryResponse(BaseModel):
    id: UUID
    name: str
    slug: str
    description: str | None
    display_order: int


class ArtifactResponse(BaseModel):
    id: UUID
    filename: str
    content_type: str
    size_bytes: int
    checksum_sha256: str


class UnlockRequirementResponse(BaseModel):
    """One condition on a locked challenge or zone, so the player knows what opens
    it (spec 017).

    ``description`` is pre-rendered server-side so a client can show any gate type
    without a per-type branch, and ``progress`` is what the player currently has —
    enough for "320 / 500".
    """

    type: str
    met: bool
    description: str
    challenge_id: UUID | None = None
    title: str | None = None
    skill_id: UUID | None = None
    skill_name: str | None = None
    category_id: UUID | None = None
    category_name: str | None = None
    threshold: int | None = None
    progress: int | None = None


class ChallengeListItem(BaseModel):
    """A challenge as it appears on the board.

    A locked challenge carries everything here — title, category, value — and
    nothing more. The body never reaches the client until it is published.
    """

    id: UUID
    title: str
    slug: str
    category: CategoryResponse
    difficulty: Difficulty
    state: ChallengeState
    locked: bool
    value: int
    solve_count: int
    solved: bool
    attempts_remaining: int | None
    max_attempts: int | None
    release_at: datetime | None
    #: Present on a challenge locked by prerequisites, listing what unlocks it.
    unlock_requirements: list[UnlockRequirementResponse] = []


class ChallengeDetail(ChallengeListItem):
    #: Omitted (None) while locked — not merely hidden by the client.
    body: str | None
    artifacts: list[ArtifactResponse]
    hints: list["HintResponse"]
    #: Whether this challenge has a live container the player can summon.
    has_container: bool = False


class SubmitAnswerRequest(BaseModel):
    answer: str = Field(min_length=1, max_length=MAX_SUBMISSION_LENGTH)


class SubmitAnswerResponse(BaseModel):
    correct: bool
    already_solved: bool
    points_awarded: int
    attempts_remaining: int | None
    message: str


class SolveSummary(BaseModel):
    challenge_id: UUID
    title: str
    category: str
    value: int
    solved_at: datetime


class MyScoreResponse(BaseModel):
    total: int
    solves: list[SolveSummary]


class HintResponse(BaseModel):
    id: UUID
    title: str
    #: What unlocking costs right now — zero once the challenge is solved.
    cost: int
    unlocked: bool
    #: False while a prerequisite is unbought or the reveal time has not come.
    available: bool
    #: Null until unlocked. Withheld server-side, like a locked challenge's body.
    body: str | None


class UnlockHintResponse(BaseModel):
    body: str
    cost_charged: int
    already_unlocked: bool
    new_total: int
