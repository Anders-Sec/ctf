"""Order assistant messages explicitly

A question and the answer it produced are written in one transaction, and
Postgres stamps ``now()`` at transaction start, so both rows carry an identical
``created_at`` and sort arbitrarily against each other. An explicit position
fixes the order of a conversation for both the model and the UI.

Revision ID: 0008
Revises: 0007
Create Date: 2026-09-06 19:17:37.706175
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # The server default only exists to fill rows written between 0007 and here;
    # the column is populated explicitly by the application, so it is dropped
    # again immediately rather than left as a silent fallback.
    op.add_column(
        "assistant_message",
        sa.Column("sequence", sa.Integer(), nullable=False, server_default="0"),
    )
    op.alter_column("assistant_message", "sequence", server_default=None)

    op.drop_index("ix_assistant_message_conversation", table_name="assistant_message")
    op.create_index(
        "ix_assistant_message_conversation",
        "assistant_message",
        ["conversation_id", "sequence"],
        unique=False,
    )
    op.create_unique_constraint(
        "uq_assistant_message_sequence", "assistant_message", ["conversation_id", "sequence"]
    )


def downgrade() -> None:
    op.drop_constraint("uq_assistant_message_sequence", "assistant_message", type_="unique")
    op.drop_index("ix_assistant_message_conversation", table_name="assistant_message")
    op.create_index(
        "ix_assistant_message_conversation",
        "assistant_message",
        ["conversation_id", "created_at"],
        unique=False,
    )
    op.drop_column("assistant_message", "sequence")
