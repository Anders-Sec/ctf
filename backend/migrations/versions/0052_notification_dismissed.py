"""Clearing a notification from the inbox (spec 065 §4).

A soft dismiss rather than a delete: somebody who clears the announcement with
the lunch time in it has not destroyed it, and an organiser can still see it
existed.

Revision ID: 0052
Revises: 0051
"""

import sqlalchemy as sa
from alembic import op

revision = "0052"
down_revision = "0051"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "notification",
        sa.Column("dismissed_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("notification", "dismissed_at")
