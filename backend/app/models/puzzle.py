"""Daily puzzle challenges — the authored puzzle, and one player's play of it.

Spec 044. A puzzle is a challenge: an ordinary ``challenge`` row that happens to
be *played* rather than answered, so scheduled release, locking, the map, hints,
XP banking, achievements and the deletion rules all apply to it unchanged.

Nothing here is added to :class:`~app.models.challenge.Challenge`. A challenge
either has a puzzle or does not, which is a nullable relationship rather than
five nullable columns on a table every list query already reads.
"""

import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Enum, ForeignKey, Index, Integer, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class PuzzleKind(enum.StrEnum):
    """Which game this is.

    Each kind is one engine — a config validator, a player-safe projection and a
    move handler — registered against its member in ``app.services.puzzles``.
    Adding a fourth game is one module and one member here, not a new endpoint
    and not a new table.
    """

    WORDLE = "wordle"
    CONNECTIONS = "connections"
    CROSSWORD = "crossword"


class PuzzleStatus(enum.StrEnum):
    """Where a player's attempt stands.

    ``SOLVED`` and ``FAILED`` are both **terminal**: there is no replay, and
    running out of guesses ends the day (spec 044 §6). The two are kept apart
    rather than collapsed into a boolean because the board draws them
    differently — "you had a go at this and lost" is not "you have not started".
    """

    IN_PROGRESS = "in_progress"
    SOLVED = "solved"
    FAILED = "failed"


def _enum(python_enum: type[enum.StrEnum], name: str) -> Enum:
    return Enum(python_enum, name=name, values_callable=lambda e: [m.value for m in e])


class ChallengePuzzle(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """The authored puzzle behind a challenge.

    **This row contains the answers.** Nothing that reaches a player is built
    from it directly — every player-facing payload comes from the engine's
    projection, which is answer-free until the session is terminal. The same
    discipline as a locked challenge's body being withheld server-side rather
    than hidden by the client.
    """

    __tablename__ = "challenge_puzzle"

    #: Unique, so the one-puzzle-per-challenge rule is a database guarantee
    #: rather than something the service layer remembers to check.
    challenge_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("challenge.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )
    kind: Mapped[PuzzleKind] = mapped_column(_enum(PuzzleKind, "puzzle_kind"), nullable=False)
    #: Kind-specific, validated by that kind's engine on every write. Shapes are
    #: in spec 044 §4; the engines are the authority on them.
    config: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}"
    )

    def __repr__(self) -> str:
        return f"<ChallengePuzzle {self.kind} challenge={self.challenge_id}>"


class PuzzleSession(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One player's play of one puzzle.

    Server-side because it has to be: the client cannot hold the answer, so it
    cannot evaluate a guess, so the server is already in the loop on every move
    and may as well own the record. It also means a player can close the tab and
    come back on their phone.

    Keyed on the challenge rather than the puzzle row, because that is how every
    caller arrives — the endpoint has a challenge id — and because it makes the
    cascade on challenge deletion direct.
    """

    __tablename__ = "puzzle_session"
    __table_args__ = (
        # One attempt per player per puzzle. A constraint rather than a
        # check-then-insert: two moves racing on a fresh puzzle would both pass
        # the check and create two sessions, and the loser's guesses would
        # silently stop counting.
        UniqueConstraint("user_id", "challenge_id", name="uq_puzzle_session_user_challenge"),
        Index("ix_puzzle_session_challenge", "challenge_id"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("user.id", ondelete="CASCADE"), nullable=False
    )
    challenge_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("challenge.id", ondelete="CASCADE"), nullable=False
    )

    status: Mapped[PuzzleStatus] = mapped_column(
        _enum(PuzzleStatus, "puzzle_status"),
        nullable=False,
        default=PuzzleStatus.IN_PROGRESS,
        server_default=PuzzleStatus.IN_PROGRESS.value,
    )
    #: Kind-specific: the guesses so far, the groups found, the letters typed.
    #: Replaced wholesale by each move rather than merged — the engine owns the
    #: shape and a partial update is how two versions of it start to disagree.
    state: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}"
    )
    #: Guesses, group attempts or checks — whichever its kind counts. The number
    #: the hard-fail rule reads.
    moves_used: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")

    started_at: Mapped[datetime] = mapped_column(nullable=False)
    #: Set when the session goes terminal, either way. Null while in progress.
    finished_at: Mapped[datetime | None] = mapped_column(nullable=True)

    @property
    def terminal(self) -> bool:
        return self.status != PuzzleStatus.IN_PROGRESS

    def __repr__(self) -> str:
        return f"<PuzzleSession {self.status} user={self.user_id} challenge={self.challenge_id}>"
