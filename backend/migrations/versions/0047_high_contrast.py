"""The accessibility switch, separate from the theme choice (spec 048 §10).

A boolean rather than a theme value, so that turning high contrast off returns
the player to whichever side of the light/dark toggle they were on without the
platform having to remember a "previous theme".

Revision ID: 0047
Revises: 0046
"""

import sqlalchemy as sa
from alembic import op

revision = "0047"
down_revision = "0046"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "user",
        sa.Column("high_contrast", sa.Boolean(), nullable=False, server_default="false"),
    )
    # Torchlight is gone (spec 048 §10): beside Dark Dungeon it read as the same
    # theme two values apart. Anyone holding it moves to the dark theme it was
    # a variant of, rather than being silently bounced to the light default by
    # the unknown-theme fallback.
    op.execute("UPDATE \"user\" SET theme = 'dark-dungeon' WHERE theme = 'torchlight'")
    op.execute(
        "UPDATE event_config SET default_theme = 'dark-dungeon' WHERE default_theme = 'torchlight'"
    )


def downgrade() -> None:
    op.drop_column("user", "high_contrast")
