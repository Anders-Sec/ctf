"""Announcement history and scheduling (spec 054).

Revision ID: 0049
Revises: 0048
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0049"
down_revision = "0048"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "announcement",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("title", sa.String(length=120), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column(
            "audience",
            sa.Enum("everyone", "staff", name="announcement_audience"),
            server_default="everyone",
            nullable=False,
        ),
        sa.Column(
            "created_by_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("user.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("scheduled_for", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("recipient_count", sa.Integer(), server_default="0", nullable=False),
    )
    op.create_index("ix_announcement_scheduled", "announcement", ["scheduled_for", "sent_at"])

    # So a read count is a count over the fan-out rather than a second number
    # stored on the announcement and kept in step by hand.
    op.add_column(
        "notification",
        sa.Column(
            "announcement_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("announcement.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index("ix_notification_announcement", "notification", ["announcement_id"])


def downgrade() -> None:
    op.drop_index("ix_notification_announcement", table_name="notification")
    op.drop_column("notification", "announcement_id")
    op.drop_index("ix_announcement_scheduled", table_name="announcement")
    op.drop_table("announcement")
    sa.Enum(name="announcement_audience").drop(op.get_bind(), checkfirst=True)
