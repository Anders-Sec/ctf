"""Six-tier difficulty ladder, with XP derived from it

Spec 018. Difficulty stops being a hint and starts deriving a challenge's value:
``modifier * XP_BASE`` for the ceiling, 40% of that for the decay floor, and
dynamic scoring only on the top two tiers (the tie-breakers).

Existing rows are mapped onto the new ladder before their values are recomputed:
``insane`` becomes ``nearly_impossible``, and the other three keep their names.

Revision ID: 0019
Revises: 0018
Create Date: 2026-09-08
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0019"
down_revision: str | None = "0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: modifier * XP_BASE(10) -> ceiling; floor is 40%; dynamic on the top two only.
LADDER = {
    "very_easy": (50, 20, "static"),
    "easy": (100, 40, "static"),
    "medium": (150, 60, "static"),
    "hard": (200, 80, "static"),
    "very_hard": (250, 100, "dynamic"),
    "nearly_impossible": (500, 200, "dynamic"),
}


def upgrade() -> None:
    for value in ("very_easy", "very_hard", "nearly_impossible"):
        op.execute(f"ALTER TYPE challenge_difficulty ADD VALUE IF NOT EXISTS '{value}'")

    # ADD VALUE is not usable in the transaction that created it, so the rows are
    # moved in a second one.
    op.execute("COMMIT")

    op.execute("UPDATE challenge SET difficulty = 'nearly_impossible' WHERE difficulty = 'insane'")

    for name, (initial, minimum, scoring) in LADDER.items():
        op.execute(
            f"""
            UPDATE challenge
               SET initial_points = {initial},
                   minimum_points = {minimum},
                   scoring = '{scoring}'
             WHERE difficulty = '{name}'
            """
        )


def downgrade() -> None:
    # Postgres cannot drop enum values, so the added members stay; move any row
    # using one back onto a member the old four-value ladder had.
    op.execute("UPDATE challenge SET difficulty = 'easy' WHERE difficulty = 'very_easy'")
    op.execute("UPDATE challenge SET difficulty = 'hard' WHERE difficulty = 'very_hard'")
    op.execute("UPDATE challenge SET difficulty = 'insane' WHERE difficulty = 'nearly_impossible'")
