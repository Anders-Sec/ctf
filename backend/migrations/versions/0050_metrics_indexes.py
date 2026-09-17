"""Indexes for the metrics access patterns (spec 050 §7).

Both of these are new shapes. The near-miss computation in particular scans
wrong answers per challenge, and the stalled-player bands scan a player's
submissions by time.

Revision ID: 0050
Revises: 0049
"""

from alembic import op

revision = "0050"
down_revision = "0049"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ix_submission_challenge_correct_created",
        "submission",
        ["challenge_id", "is_correct", "created_at"],
    )
    op.create_index("ix_submission_user_created", "submission", ["user_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_submission_user_created", table_name="submission")
    op.drop_index("ix_submission_challenge_correct_created", table_name="submission")
