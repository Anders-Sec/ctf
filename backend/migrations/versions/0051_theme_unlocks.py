"""Secret themes unlocked by achievement, or granted by an admin (spec 058 §5).

Revision ID: 0051
Revises: 0050
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0051"
down_revision = "0050"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("achievement", sa.Column("unlocks_theme", sa.String(length=32), nullable=True))

    op.create_table(
        "user_theme_unlock",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("user.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("theme", sa.String(length=32), nullable=False),
        sa.Column(
            "source", sa.Enum("achievement", "admin", name="unlock_source"), nullable=False
        ),
        sa.Column(
            "source_achievement_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("achievement.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.UniqueConstraint("user_id", "theme", name="uq_user_theme_unlock"),
    )


def downgrade() -> None:
    op.drop_table("user_theme_unlock")
    sa.Enum(name="unlock_source").drop(op.get_bind(), checkfirst=True)
    op.drop_column("achievement", "unlocks_theme")
