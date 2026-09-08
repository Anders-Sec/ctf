"""Generalise unlock requirements, add map coordinates and the fog setting

Spec 017. Three things:

* ``challenge_unlock_requirement`` becomes ``unlock_requirement`` and can gate a
  **category** (a map zone) as well as a challenge — a nullable ``challenge_id``
  XOR a nullable ``category_id``, the same one-target pattern
  ``challenge_instance`` uses for its owner. New value-based gate types get the
  columns they read: ``threshold``, ``required_skill_id``, ``required_category_id``.
* ``challenge.map_x`` / ``map_y`` — optional pinned map coordinates.
* ``event_config.fog_of_war`` — dim locked zones on the map.

The event has not run, so the rename carries no production data risk.

Revision ID: 0018
Revises: 4c810980cb59
Create Date: 2026-09-07
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0018"
down_revision: str | None = "4c810980cb59"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # --- the requirement table, generalised -------------------------------
    op.rename_table("challenge_unlock_requirement", "unlock_requirement")

    # A row now gates a challenge *or* a category, so the challenge side relaxes.
    op.alter_column("unlock_requirement", "challenge_id", nullable=True)
    op.drop_constraint("uq_unlock_requirement_pair", "unlock_requirement", type_="unique")

    op.add_column("unlock_requirement", sa.Column("category_id", sa.UUID(), nullable=True))
    op.add_column("unlock_requirement", sa.Column("required_skill_id", sa.UUID(), nullable=True))
    op.add_column("unlock_requirement", sa.Column("required_category_id", sa.UUID(), nullable=True))
    op.add_column("unlock_requirement", sa.Column("threshold", sa.Integer(), nullable=True))

    op.create_foreign_key(
        "fk_unlock_requirement_category",
        "unlock_requirement",
        "category",
        ["category_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_unlock_requirement_required_skill",
        "unlock_requirement",
        "skill",
        ["required_skill_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_unlock_requirement_required_category",
        "unlock_requirement",
        "category",
        ["required_category_id"],
        ["id"],
        ondelete="CASCADE",
    )

    # Exactly one target, mirroring ck_challenge_instance_one_owner.
    op.create_check_constraint(
        "ck_unlock_requirement_one_target",
        "unlock_requirement",
        "(challenge_id IS NOT NULL) <> (category_id IS NOT NULL)",
    )
    op.create_index("ix_unlock_requirement_category", "unlock_requirement", ["category_id"])

    # One gate of a given shape per target. NULLS NOT DISTINCT (Postgres 15+) is
    # what makes this bite: without it two `min_xp` rows — both with NULL in every
    # required_* column — would not collide.
    op.execute(
        """
        CREATE UNIQUE INDEX uq_unlock_requirement_shape
        ON unlock_requirement (
            challenge_id, category_id, requirement_type,
            required_challenge_id, required_skill_id, required_category_id
        )
        NULLS NOT DISTINCT
        """
    )

    # --- the new gate types ----------------------------------------------
    # ADD VALUE is not transactional-safe to *use* in the same transaction, but
    # nothing here writes a row with one.
    for value in ("min_xp", "skill_level", "solves_in_category"):
        op.execute(f"ALTER TYPE requirement_type ADD VALUE IF NOT EXISTS '{value}'")

    # --- map coordinates and the fog setting ------------------------------
    op.add_column("challenge", sa.Column("map_x", sa.Integer(), nullable=True))
    op.add_column("challenge", sa.Column("map_y", sa.Integer(), nullable=True))
    op.add_column(
        "event_config",
        sa.Column("fog_of_war", sa.Boolean(), server_default="true", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("event_config", "fog_of_war")
    op.drop_column("challenge", "map_y")
    op.drop_column("challenge", "map_x")

    # Postgres cannot drop enum values; the added requirement_type members stay.
    # Rows using them would violate the restored NOT NULL below, so clear them.
    op.execute("DELETE FROM unlock_requirement WHERE category_id IS NOT NULL")

    op.execute("DROP INDEX IF EXISTS uq_unlock_requirement_shape")
    op.drop_index("ix_unlock_requirement_category", table_name="unlock_requirement")
    op.drop_constraint("ck_unlock_requirement_one_target", "unlock_requirement", type_="check")
    op.drop_constraint("fk_unlock_requirement_required_category", "unlock_requirement")
    op.drop_constraint("fk_unlock_requirement_required_skill", "unlock_requirement")
    op.drop_constraint("fk_unlock_requirement_category", "unlock_requirement")

    op.drop_column("unlock_requirement", "threshold")
    op.drop_column("unlock_requirement", "required_category_id")
    op.drop_column("unlock_requirement", "required_skill_id")
    op.drop_column("unlock_requirement", "category_id")

    op.alter_column("unlock_requirement", "challenge_id", nullable=False)
    op.create_unique_constraint(
        "uq_unlock_requirement_pair",
        "unlock_requirement",
        ["challenge_id", "required_challenge_id"],
    )
    op.rename_table("unlock_requirement", "challenge_unlock_requirement")
