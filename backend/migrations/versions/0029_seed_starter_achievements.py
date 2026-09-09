"""The starter achievement set (spec 028).

Enough to prove the machinery end to end. Each `code` names a trigger registered
in ``app.services.achievements``; the real roster arrives as more rows of the
same shape, and an achievement whose code has no trigger simply never fires,
which is the safe failure.

Revision ID: 0029
Revises: 0028
"""

import sqlalchemy as sa
from alembic import op

revision = "0029"
down_revision = "0028"
branch_labels = None
depends_on = None

ACHIEVEMENTS = [
    ("first_blood", "First Blood", "Solved your first challenge."),
    ("ten_solves", "Getting Comfortable", "Solved ten challenges."),
    ("zone_cleared", "Clean Sweep", "Cleared every published challenge in a zone."),
    ("persistent", "Stubborn", "Threw ten wrong flags at a single challenge."),
    ("blitz", "Blitz", "Solved three challenges inside five minutes."),
    ("unaided", "No Help Needed", "Solved ten challenges without taking a hint."),
    ("broad_church", "Well Rounded", "Solved something in five different zones."),
]


def upgrade() -> None:
    bind = op.get_bind()
    for order, (code, name, description) in enumerate(ACHIEVEMENTS):
        bind.execute(
            sa.text(
                "INSERT INTO achievement (id, code, name, description, display_order) "
                "VALUES (gen_random_uuid(), :c, :n, :d, :o) "
                "ON CONFLICT (code) DO NOTHING"
            ),
            {"c": code, "n": name, "d": description, "o": order},
        )


def downgrade() -> None:
    bind = op.get_bind()
    for code, *_ in ACHIEVEMENTS:
        bind.execute(sa.text("DELETE FROM achievement WHERE code = :c"), {"c": code})
