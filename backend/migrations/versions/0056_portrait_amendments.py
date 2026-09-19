"""Grid stability, the presentation axis, and admin-granted portraits.

Spec 074 §11, all from using the thing:

- `avatar_job.chosen_candidate_id` so a grid can show which portrait is live
  instead of deleting the ones you did not pick.
- `presentation` on the trait axis enum.
- `user.portrait_grant`, an admin-set top-up on the generation budget.

Revision ID: 0056
Revises: 0055
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0056"
down_revision = "0055"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "avatar_job",
        sa.Column(
            "chosen_candidate_id",
            postgresql.UUID(as_uuid=True),
            # Deliberately no foreign key. The candidate it names is deleted
            # when the next job replaces the grid, and a FK would either block
            # that or null this out — losing the record of what was picked.
            nullable=True,
        ),
    )

    op.add_column(
        "user",
        sa.Column("portrait_grant", sa.Integer(), nullable=False, server_default="0"),
    )

    # Postgres cannot add an enum value inside a transaction block on older
    # servers; ALTER TYPE ... ADD VALUE IF NOT EXISTS is safe and idempotent on
    # 12+, which is what the compose file and the cluster both run.
    op.execute("ALTER TYPE trait_axis ADD VALUE IF NOT EXISTS 'presentation'")


def downgrade() -> None:
    op.drop_column("user", "portrait_grant")
    op.drop_column("avatar_job", "chosen_candidate_id")
    # The enum value is left in place: Postgres has no ALTER TYPE ... DROP
    # VALUE, and removing it would mean rebuilding the type and every column
    # using it. An unused value costs nothing.
