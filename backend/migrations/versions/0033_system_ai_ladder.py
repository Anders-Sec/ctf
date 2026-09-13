"""The System AI ladder (spec 033).

Five columns and one enum member. The ladder itself is code and prompts; what
the database has to hold is only the small amount of state that must not come
from the client:

- which challenge is which rung (``challenge.ai_ladder_level``),
- which rung a player has chosen (``user.ai_ladder_level``),
- whether the System AI has already handed them level 0's flag
  (``user.ai_ladder_leaked_at``) — the secret route into the zone,
- how a turn was produced (``assistant_message.ladder_level`` / ``trace``),
- and any-of grouping on unlock requirements, because the zone opens by *either*
  of two conditions and requirements have until now only ever ANDed.

Revision ID: 0033
Revises: 0032
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0033"
down_revision = "0032"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # The ladder rung a challenge is. Unique among non-nulls: the engine resolves
    # a level's flag through this column, so two challenges claiming level 3
    # would make the prompt it builds ambiguous. Partial, so the ~240 challenges
    # that are not ladder levels do not collide with each other.
    op.add_column("challenge", sa.Column("ai_ladder_level", sa.Integer(), nullable=True))
    op.create_check_constraint(
        "ck_challenge_ai_ladder_level_range",
        "challenge",
        "ai_ladder_level IS NULL OR (ai_ladder_level >= 0 AND ai_ladder_level <= 5)",
    )
    op.create_index(
        "uq_challenge_ai_ladder_level",
        "challenge",
        ["ai_ladder_level"],
        unique=True,
        postgresql_where=sa.text("ai_ladder_level IS NOT NULL"),
    )

    # The player's own state. Null level means "track my maximum", which is what
    # every existing row should mean.
    op.add_column("user", sa.Column("ai_ladder_level", sa.Integer(), nullable=True))
    op.add_column(
        "user", sa.Column("ai_ladder_leaked_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.create_check_constraint(
        "ck_user_ai_ladder_level_range",
        "user",
        "ai_ladder_level IS NULL OR (ai_ladder_level >= 0 AND ai_ladder_level <= 5)",
    )
    op.create_index(
        "ix_user_ai_ladder_leaked",
        "user",
        ["ai_ladder_leaked_at"],
        postgresql_where=sa.text("ai_ladder_leaked_at IS NOT NULL"),
    )

    # How a turn was produced.
    op.add_column("assistant_message", sa.Column("ladder_level", sa.Integer(), nullable=True))
    op.add_column(
        "assistant_message",
        sa.Column("trace", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )

    # Any-of grouping. Null on every existing row, so they keep ANDing exactly as
    # they did — the new semantics apply only where a group is set.
    op.add_column(
        "unlock_requirement", sa.Column("alternative_group", sa.SmallInteger(), nullable=True)
    )

    # A new member on the existing enum. Postgres will not add one inside a
    # transaction block on older servers, hence the COMMIT — the same dance
    # 0032 does for creating its type.
    op.execute("COMMIT")
    op.execute("ALTER TYPE requirement_type ADD VALUE IF NOT EXISTS 'ai_ladder_leak'")


def downgrade() -> None:
    # The enum member stays. Postgres cannot drop one, and a requirement row
    # using it is removed below, so nothing is left referencing it.
    op.execute("DELETE FROM unlock_requirement WHERE requirement_type = 'ai_ladder_leak'")

    op.drop_column("unlock_requirement", "alternative_group")
    op.drop_column("assistant_message", "trace")
    op.drop_column("assistant_message", "ladder_level")

    op.drop_index("ix_user_ai_ladder_leaked", table_name="user")
    op.drop_constraint("ck_user_ai_ladder_level_range", "user", type_="check")
    op.drop_column("user", "ai_ladder_leaked_at")
    op.drop_column("user", "ai_ladder_level")

    op.drop_index("uq_challenge_ai_ladder_level", table_name="challenge")
    op.drop_constraint("ck_challenge_ai_ladder_level_range", "challenge", type_="check")
    op.drop_column("challenge", "ai_ladder_level")
