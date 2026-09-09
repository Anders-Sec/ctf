"""Notifications and achievements (spec 028).

Revision ID: 0028
Revises: 0027
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0028"
down_revision = "0027"
branch_labels = None
depends_on = None

KINDS = (
    "achievement",
    "class_unlocked",
    "zone_unlocked",
    "level_up",
    "ability_milestone",
    "system",
)


def upgrade() -> None:
    kind = postgresql.ENUM(*KINDS, name="notification_kind", create_type=False)
    kind.create(op.get_bind(), checkfirst=True)
    # Postgres will not let a new enum's values be used in the transaction that
    # created the type, and the seed below does exactly that.
    op.execute("COMMIT")

    op.create_table(
        "notification",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("user.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("kind", kind, nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("link", sa.String(500), nullable=True),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )
    op.create_index("ix_notification_user_created", "notification", ["user_id", "created_at"])

    op.create_table(
        "achievement",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("code", sa.String(80), nullable=False, unique=True),
        sa.Column("name", postgresql.CITEXT(), nullable=False, unique=True),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("display_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("secret", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )

    op.create_table(
        "achievement_award",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "achievement_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("achievement.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("user.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        # Once per player: a constraint, not a check-then-insert that two
        # concurrent solves could both pass.
        sa.UniqueConstraint("achievement_id", "user_id", name="uq_achievement_award_once"),
    )
    op.create_index("ix_achievement_award_user", "achievement_award", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_achievement_award_user", table_name="achievement_award")
    op.drop_table("achievement_award")
    op.drop_table("achievement")
    op.drop_index("ix_notification_user_created", table_name="notification")
    op.drop_table("notification")
    op.execute("DROP TYPE IF EXISTS notification_kind")
