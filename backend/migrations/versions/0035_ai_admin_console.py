"""The AI admin console: acknowledgement, call cost, and the indexes it reads on (spec 034).

Two of these are not optional. A multi-day event accumulates tens of thousands of
message rows, and a dashboard on a ten-second refresh that sequential-scans them
twice per load is a self-inflicted outage — so `created_at` gets an index, and
`trace` gets a GIN index for the per-gate counts.

Revision ID: 0035
Revises: 0034
"""

import sqlalchemy as sa
from alembic import op

revision = "0035"
down_revision = "0034"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Findings have never had a reviewed/unreviewed state, so staff could not
    # work through a backlog: every refresh showed the same rows.
    op.add_column(
        "assistant_finding",
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "assistant_finding",
        sa.Column("acknowledged_by_user_id", sa.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_assistant_finding_acknowledged_by",
        "assistant_finding",
        "user",
        ["acknowledged_by_user_id"],
        ["id"],
        ondelete="SET NULL",
    )
    # Partial: the default view is "unreviewed", which is the many rather than
    # the few, so the index that matters is over the unacknowledged ones.
    op.create_index(
        "ix_assistant_finding_unacknowledged",
        "assistant_finding",
        ["created_at"],
        postgresql_where=sa.text("acknowledged_at IS NULL"),
    )

    op.add_column("assistant_message", sa.Column("upstream_calls", sa.Integer(), nullable=True))

    # Every window on the dashboard filters on time.
    op.create_index("ix_assistant_message_created", "assistant_message", ["created_at"])
    # Containment queries for the per-gate counts: trace @> '["router"]'.
    op.create_index(
        "ix_assistant_message_trace",
        "assistant_message",
        ["trace"],
        postgresql_using="gin",
    )


def downgrade() -> None:
    op.drop_index("ix_assistant_message_trace", table_name="assistant_message")
    op.drop_index("ix_assistant_message_created", table_name="assistant_message")
    op.drop_column("assistant_message", "upstream_calls")

    op.drop_index("ix_assistant_finding_unacknowledged", table_name="assistant_finding")
    op.drop_constraint(
        "fk_assistant_finding_acknowledged_by", "assistant_finding", type_="foreignkey"
    )
    op.drop_column("assistant_finding", "acknowledged_by_user_id")
    op.drop_column("assistant_finding", "acknowledged_at")
