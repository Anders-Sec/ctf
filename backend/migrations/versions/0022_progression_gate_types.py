"""Percentage and player-level unlock gates

Spec 019. The zone progression is expressed in percentages ("clear 25% of
Networking") because categories differ in size, and in player levels ("reach
level 5"). Neither could be said with the existing four types.

Revision ID: 0022
Revises: 0021
Create Date: 2026-09-08
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0022"
down_revision: str | None = "0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    for value in ("percent_in_category", "player_level"):
        op.execute(f"ALTER TYPE requirement_type ADD VALUE IF NOT EXISTS '{value}'")

    # Postgres refuses to *use* an enum value in the transaction that added it,
    # and 0023 seeds rows with these — so end the transaction here.
    op.execute("COMMIT")


def downgrade() -> None:
    # Postgres cannot drop enum values; rows using them go instead, so nothing
    # is left pointing at a member the application no longer knows.
    op.execute(
        "DELETE FROM unlock_requirement "
        "WHERE requirement_type IN ('percent_in_category', 'player_level')"
    )
