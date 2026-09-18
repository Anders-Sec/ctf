"""Notification kinds a player has turned down (spec 070 §4).

A volume control, not a filter: a muted kind still arrives and still sits in the
inbox, it simply does not toast and does not count toward the badge.

Revision ID: 0053
Revises: 0052
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0053"
down_revision = "0052"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "user",
        sa.Column(
            "muted_notification_kinds",
            postgresql.ARRAY(sa.String(length=40)),
            nullable=False,
            server_default="{}",
        ),
    )


def downgrade() -> None:
    op.drop_column("user", "muted_notification_kinds")
