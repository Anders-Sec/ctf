"""Theme preference, per user and per event (spec 048).

Both columns are nullable strings rather than a database enum. The theme roster
lives in ``app.theme`` and in the frontend's CSS; an enum would mean a migration
every time a preset is added or removed, and an unrecognised value already falls
back safely rather than raising.

Revision ID: 0046
Revises: 0045
"""

import sqlalchemy as sa
from alembic import op

revision = "0046"
down_revision = "0045"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("user", sa.Column("theme", sa.String(length=32), nullable=True))
    op.add_column("event_config", sa.Column("default_theme", sa.String(length=32), nullable=True))


def downgrade() -> None:
    op.drop_column("event_config", "default_theme")
    op.drop_column("user", "theme")
