"""Authored map positions for categories

Spec 021. Null means "use the derived layout", so a category that has not been
placed still appears on the map.

Revision ID: 0025
Revises: 0024
Create Date: 2026-09-08
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0025"
down_revision: str | None = "0024"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("category", sa.Column("map_x", sa.Integer(), nullable=True))
    op.add_column("category", sa.Column("map_y", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("category", "map_y")
    op.drop_column("category", "map_x")
