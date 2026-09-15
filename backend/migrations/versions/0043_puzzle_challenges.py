"""The authored puzzle, and one player's play of it (spec 044).

Two tables and no change to `challenge`. A challenge either has a puzzle or does
not, which is a nullable relationship rather than columns every list query would
carry for the sake of fifteen rows.

`challenge_puzzle.config` holds the answers and is never projected to a player
directly; `puzzle_session.state` holds what one player has done and is theirs
alone. Both cascade from the challenge, so deleting a challenge takes its puzzle
and every session with it.

Revision ID: 0043
Revises: 0042
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0043"
down_revision = "0042"
branch_labels = None
depends_on = None

KINDS = ("wordle", "connections", "crossword")
STATUSES = ("in_progress", "solved", "failed")


def upgrade() -> None:
    postgresql.ENUM(*KINDS, name="puzzle_kind").create(op.get_bind(), checkfirst=True)
    postgresql.ENUM(*STATUSES, name="puzzle_status").create(op.get_bind(), checkfirst=True)
    # create_type=False: both types are made above, and create_table would
    # otherwise emit a second CREATE TYPE in the same transaction and fail.
    kind = postgresql.ENUM(*KINDS, name="puzzle_kind", create_type=False)
    status = postgresql.ENUM(*STATUSES, name="puzzle_status", create_type=False)

    op.create_table(
        "challenge_puzzle",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "challenge_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("challenge.id", ondelete="CASCADE"),
            # One puzzle per challenge, as a database guarantee.
            unique=True,
            nullable=False,
        ),
        sa.Column("kind", kind, nullable=False),
        sa.Column("config", postgresql.JSONB, nullable=False, server_default="{}"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )

    op.create_table(
        "puzzle_session",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("user.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "challenge_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("challenge.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("status", status, nullable=False, server_default="in_progress"),
        sa.Column("state", postgresql.JSONB, nullable=False, server_default="{}"),
        sa.Column("moves_used", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        # Two moves racing on a fresh puzzle would both pass a check-then-insert
        # and create two sessions, and the loser's guesses would stop counting.
        sa.UniqueConstraint("user_id", "challenge_id", name="uq_puzzle_session_user_challenge"),
    )
    # The board asks "what is this player's status on each of these challenges",
    # which the unique constraint already serves. This one is for the other
    # direction — an admin looking at one puzzle's sessions, and the reset.
    op.create_index("ix_puzzle_session_challenge", "puzzle_session", ["challenge_id"])


def downgrade() -> None:
    op.drop_index("ix_puzzle_session_challenge", table_name="puzzle_session")
    op.drop_table("puzzle_session")
    op.drop_table("challenge_puzzle")
    postgresql.ENUM(name="puzzle_status").drop(op.get_bind(), checkfirst=True)
    postgresql.ENUM(name="puzzle_kind").drop(op.get_bind(), checkfirst=True)
