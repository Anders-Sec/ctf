"""Store the three things three achievements were asking about (spec 039).

`you_broke_it`, `above_your_pay_grade` and `identity_crisis` have been inert
since 029 because the platform saw each of their events and forgot it. This is
the smallest table that lets a trigger count them.

No payload column, deliberately: rows here exist to be counted, and a detail
field written from an exception handler would collect stack traces — which on
this platform can carry a flag or a connection string.

Revision ID: 0041
Revises: 0040
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0041"
down_revision = "0040"
branch_labels = None
depends_on = None

KINDS = ("server_error", "forbidden_admin", "class_change")


def upgrade() -> None:
    postgresql.ENUM(*KINDS, name="player_event_kind").create(op.get_bind(), checkfirst=True)
    # create_type=False: the type is made above, and create_table would otherwise
    # emit a second CREATE TYPE inside the same transaction and fail.
    kind = postgresql.ENUM(*KINDS, name="player_event_kind", create_type=False)

    op.create_table(
        "player_event",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            # The player is the only thing a row means. Nothing to keep without
            # one, so it goes with them.
            sa.ForeignKey("user.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("kind", kind, nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    # Every read is "how many of this kind has this player got", so the index is
    # the query.
    op.create_index("ix_player_event_user_kind", "player_event", ["user_id", "kind"])


def downgrade() -> None:
    op.drop_index("ix_player_event_user_kind", table_name="player_event")
    op.drop_table("player_event")
    postgresql.ENUM(name="player_event_kind").drop(op.get_bind(), checkfirst=True)
