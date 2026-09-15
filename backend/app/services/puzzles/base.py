"""The shape every puzzle game fits into (spec 044 §4).

Three games, one contract. A kind supplies a config validator, a projection that
is safe to hand a player, and a move handler — and the endpoint layer knows
nothing about any of them beyond this protocol. Deliberately the same shape as
the answer-matching registry in :mod:`app.services.answers`: adding a fourth game
is one module and one enum member, not a new endpoint and not a new table.
"""

from dataclasses import dataclass, field
from typing import Any, Protocol

from app.errors import AppError
from app.models.puzzle import PuzzleKind


class InvalidPuzzleConfig(AppError):
    """The authored puzzle is malformed — raised when saving, never when playing.

    Carries the field it objects to so the editor can mark it, rather than
    rejecting a whole grid over one cell.
    """

    status_code = 422
    code = "invalid_puzzle_config"
    message = "That puzzle is not valid."


class InvalidMove(AppError):
    """The player sent something this game cannot interpret.

    Distinct from a *wrong* move, which is ordinary play and costs a guess. This
    is a malformed one — five letters where four were asked for — and it costs
    nothing, because it never reached the puzzle.
    """

    status_code = 422
    code = "invalid_move"
    message = "That move is not valid."


class PuzzleFinished(AppError):
    """Solved or failed. Either way there is no more play in it (spec 044 §6)."""

    status_code = 409
    code = "puzzle_finished"
    message = "This one is over."


@dataclass(frozen=True)
class MoveOutcome:
    """What a move did.

    ``state`` replaces the session's state wholesale rather than merging into it:
    the engine owns the shape, and a partial update is how two versions of it
    start to disagree.
    """

    state: dict[str, Any]
    #: What this move told the player — the letter verdicts, the group found,
    #: the wrong cells. Merged into the response, never stored.
    feedback: dict[str, Any] = field(default_factory=dict)
    solved: bool = False
    failed: bool = False
    #: False for a move that turned out not to count: a repeated Connections
    #: selection, say. Keeps `moves_used` honest and keeps the attempt log clean.
    counted: bool = True
    #: A compact rendering of the move for the attempt log's ``submitted_value``.
    #: Empty means "do not log this one".
    log_value: str = ""


class PuzzleEngine(Protocol):
    """One game."""

    kind: PuzzleKind

    def validate(self, config: dict[str, Any]) -> dict[str, Any]:
        """Check an authored puzzle and return it normalised.

        Raises :class:`InvalidPuzzleConfig`. Returning the normalised config —
        rather than mutating or merely approving it — is what lets the editor
        store uppercase answers and derived clue numbers without every caller
        remembering to do it.
        """
        ...

    def initial_state(self) -> dict[str, Any]:
        """The state a fresh session starts from."""
        ...

    def view(
        self, config: dict[str, Any], state: dict[str, Any], *, reveal: bool
    ) -> dict[str, Any]:
        """The player-safe projection.

        **Never returns anything answer-revealing unless ``reveal``**, which the
        caller sets only for a terminal session. This is the single place the
        answer-leak rule is enforced for each game, which is why the test suite
        asserts against this function's output rather than against a schema.
        """
        ...

    def move(
        self, config: dict[str, Any], state: dict[str, Any], move: dict[str, Any]
    ) -> MoveOutcome:
        """Play one move against the current state."""
        ...


_ENGINES: dict[PuzzleKind, PuzzleEngine] = {}


def register(engine: PuzzleEngine) -> PuzzleEngine:
    _ENGINES[engine.kind] = engine
    return engine


def engine_for(kind: PuzzleKind) -> PuzzleEngine:
    try:
        return _ENGINES[kind]
    except KeyError:  # pragma: no cover - unreachable while the enum is closed
        raise InvalidPuzzleConfig(f"No engine for puzzle kind {kind}.") from None


def require(condition: bool, message: str, field_name: str | None = None) -> None:
    """Assert something about an authored puzzle, or explain why not."""
    if not condition:
        raise InvalidPuzzleConfig(message, details={"field": field_name} if field_name else None)


def require_int(config: dict[str, Any], key: str, *, default: int, low: int, high: int) -> int:
    value = config.get(key, default)
    require(isinstance(value, int) and not isinstance(value, bool), f"{key} must be a number", key)
    require(low <= value <= high, f"{key} must be between {low} and {high}.", key)
    return int(value)
