"""System AI terms of use, accepted once per version (spec 035).

One table. The version is the hash of the terms file rather than a number
anybody maintains, so a revised file re-gates everyone — which is the point: a
prior acceptance was to different words.

Revision ID: 0034
Revises: 0033
"""

import sqlalchemy as sa
from alembic import op

revision = "0034"
down_revision = "0033"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "assistant_terms_acceptance",
        sa.Column(
            "id",
            sa.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "user_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("user.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("version", sa.String(64), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        # Two tabs accepting at once is a no-op rather than an error.
        sa.UniqueConstraint("user_id", "version", name="uq_assistant_terms_user_version"),
    )
    op.create_index("ix_assistant_terms_user", "assistant_terms_acceptance", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_assistant_terms_user", table_name="assistant_terms_acceptance")
    op.drop_table("assistant_terms_acceptance")
