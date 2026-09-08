"""add character_class and user.character_class_id

Revision ID: 4c810980cb59
Revises: 0012
Create Date: 2026-09-07 21:13:27.165603
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "4c810980cb59"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "character_class",
        sa.Column("name", postgresql.CITEXT(), nullable=False),
        sa.Column("display_order", sa.Integer(), server_default="0", nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("affinity_skill_id", sa.UUID(), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["affinity_skill_id"],
            ["skill.id"],
            name="fk_character_class_affinity_skill",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )
    op.add_column("user", sa.Column("character_class_id", sa.UUID(), nullable=True))
    op.create_foreign_key(
        "fk_user_character_class",
        "user",
        "character_class",
        ["character_class_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_user_character_class", "user", type_="foreignkey")
    op.drop_column("user", "character_class_id")
    op.drop_table("character_class")
