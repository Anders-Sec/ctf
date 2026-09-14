"""Broadcast log, and the three broadcast notification kinds (spec 032).

The unique constraint on (kind, key) is what makes a broadcast send exactly
once. Two replicas run the same daily timer and a restart near the send window
would otherwise send again; whichever pod inserts first sends, and the loser's
insert fails.

Revision ID: 0037
Revises: 0036
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0037"
down_revision = "0036"
branch_labels = None
depends_on = None

NEW_KINDS = ("boss_kill", "announcement", "dispatch")


def upgrade() -> None:
    for value in NEW_KINDS:
        # IF NOT EXISTS so a re-run is harmless; enum values cannot be dropped,
        # which is why the downgrade leaves them in place.
        op.execute(f"ALTER TYPE notification_kind ADD VALUE IF NOT EXISTS '{value}'")
    op.execute("COMMIT")

    kind = postgresql.ENUM(name="notification_kind", create_type=False)
    op.create_table(
        "broadcast_log",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("kind", kind, nullable=False),
        sa.Column("key", sa.String(200), nullable=False),
        sa.Column("recipients", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.UniqueConstraint("kind", "key", name="uq_broadcast_once"),
    )


def downgrade() -> None:
    op.drop_table("broadcast_log")
    # Postgres cannot remove a value from an enum. The three new kinds stay;
    # nothing reads them once the table is gone.
