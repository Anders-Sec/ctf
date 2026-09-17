"""Persist outbound email attempts (spec 055).

Revision ID: 0048
Revises: 0047
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0048"
down_revision = "0047"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "email_delivery",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "kind",
            sa.Enum("magic_link", "approval_notice", "test", name="email_kind"),
            nullable=False,
        ),
        sa.Column("to_email", postgresql.CITEXT(), nullable=False),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("user.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "status",
            sa.Enum("sent", "failed", "not_configured", name="email_status"),
            nullable=False,
        ),
        sa.Column("error_type", sa.String(length=100), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("request_id", sa.String(length=64), nullable=True),
    )
    op.create_index("ix_email_delivery_created", "email_delivery", ["created_at"])
    op.create_index("ix_email_delivery_to_email", "email_delivery", ["to_email"])


def downgrade() -> None:
    op.drop_index("ix_email_delivery_to_email", table_name="email_delivery")
    op.drop_index("ix_email_delivery_created", table_name="email_delivery")
    op.drop_table("email_delivery")
    sa.Enum(name="email_status").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="email_kind").drop(op.get_bind(), checkfirst=True)
