"""Request and response models for challenges and submissions."""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from app.models.challenge import ChallengeState, Difficulty
from app.models.play import MAX_SUBMISSION_LENGTH
from app.models.puzzle import PuzzleKind, PuzzleStatus


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
    #: Which game this is, when it is one (spec 044). Null for an ordinary
    #: challenge, which is nearly all of them.
    puzzle_kind: PuzzleKind | None = None
    #: This player's standing on it. `solved` cannot express having lost, and a
    #: failed daily should not look untouched on the board.
    puzzle_status: PuzzleStatus | None = None


class ChallengeDetail(ChallengeListItem):
    #: Omitted (None) while locked — not merely hidden by the client.
    body: str | None
    artifacts: list[ArtifactResponse]
    hints: list["HintResponse"]
    #: Whether this challenge has a live container the player can summon.
    has_container: bool = False


class PuzzleStateResponse(BaseModel):
    """A puzzle as it stands for one player (spec 044 §5).

    ``puzzle`` is the engine's projection and is deliberately untyped here: each
    game has its own shape, and the answer-free guarantee is enforced by the
    engine that builds it rather than by this model. Pinning three shapes into
    a discriminated union would move that guarantee somewhere it does not live.
    """

    kind: PuzzleKind
    puzzle: dict[str, Any]
    #: Null before the first move — looking is not playing.
    status: PuzzleStatus | None
    moves_used: int
    solved: bool
    #: What the move just played told the player. Null on a plain read.
    feedback: dict[str, Any] | None = None
    #: Banked by the move that finished it, hints already deducted.
    xp_awarded: int = 0


class PuzzleMoveRequest(BaseModel):
    """One move, in whichever shape its game uses.

    Free-form for the same reason as above — the engine validates it, and a
    malformed move is a 422 that costs the player nothing.
    """

    move: dict[str, Any] = Field(default_factory=dict)


class PuzzleSaveRequest(BaseModel):
    """Crossword typing. Evaluates nothing and consumes no check."""

    grid: list[list[str | None]] = Field(default_factory=list)


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
