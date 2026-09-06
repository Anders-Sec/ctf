"""Initial revision.

Creates no tables — spec 001 has no domain model. This exists so that Alembic's
version table is established and spec 002's migration has a parent revision.

Enables the extensions later specs rely on: ``citext`` for case-insensitive
emails and team names (spec 002), ``pgcrypto`` for gen_random_uuid().

Revision ID: 0001
Revises:
Create Date: 2026-09-06
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS citext")
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")


def downgrade() -> None:
    # Extensions are left in place: dropping them would fail against any column
    # still typed citext, and they are harmless when unused.
    pass
