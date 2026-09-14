"""Sessions that survive a reset, and the gate log (spec 036).

A reset used to be a hard DELETE, and players reset after nearly every attempt —
so the exchange behind every flag was gone, the conversation dropped off the
admin sessions list, and nothing ever reached the retention window. A reset now
increments a session counter instead and deletes nothing.

Existing rows all belong to whatever session is current, so they default to 0,
which is exactly right.

Revision ID: 0036
Revises: 0035
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0036"
down_revision = "0035"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "assistant_conversation",
        sa.Column("current_session", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "assistant_message",
        sa.Column("session_number", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "assistant_message",
        sa.Column("gate_log", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    # The player's history now filters on the session as well as the conversation.
    op.create_index(
        "ix_assistant_message_session",
        "assistant_message",
        ["conversation_id", "session_number", "sequence"],
    )


def downgrade() -> None:
    op.drop_index("ix_assistant_message_session", table_name="assistant_message")
    op.drop_column("assistant_message", "gate_log")
    op.drop_column("assistant_message", "session_number")
    op.drop_column("assistant_conversation", "current_session")
