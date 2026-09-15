"""Daily puzzle games (spec 044).

Importing this package registers all three engines. Nothing outside it should
reach for a specific game: callers ask :func:`engine_for` and get the contract in
:mod:`app.services.puzzles.base`.
"""

from app.services.puzzles import connections, crossword, wordle  # noqa: F401  (registration)
from app.services.puzzles.base import (
    InvalidMove,
    InvalidPuzzleConfig,
    MoveOutcome,
    PuzzleEngine,
    PuzzleFinished,
    engine_for,
)

__all__ = [
    "InvalidMove",
    "InvalidPuzzleConfig",
    "MoveOutcome",
    "PuzzleEngine",
    "PuzzleFinished",
    "engine_for",
]
