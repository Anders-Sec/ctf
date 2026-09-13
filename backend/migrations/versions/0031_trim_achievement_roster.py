"""Remove the seventeen achievements cut during review (spec 029).

The roster was seeded over-long on purpose, to be trimmed once it could be read
in the platform. These are the ones that did not survive that pass.

Deleting is safe here because none is held: the trim happened before the event,
which is the only window in which removing an achievement is not taking
something away from a player.

Revision ID: 0031
Revises: 0030
"""

import sqlalchemy as sa
from alembic import op

revision = "0031"
down_revision = "0030"
branch_labels = None
depends_on = None

CUT = [
    "cartographer",
    "comic_relief",
    "eager",
    "enough",
    "impatient",
    "investment",
    "it_was_the_easy_one",
    "paid_for_nothing",
    "post_mortem",
    "rattling_the_handle",
    "read_and_left",
    "slow_burn",
    "slow_down",
    "solo_act",
    "someone_has_to_be",
    "told_twice",
    "wrong_desk",
]


def upgrade() -> None:
    bind = op.get_bind()
    # Refuse to delete one somebody has earned. Nothing should be held at this
    # point; if that is ever false, losing the award is worse than a stale row.
    held = (
        bind.execute(
            sa.text(
                "SELECT a.code FROM achievement a "
                "JOIN achievement_award w ON w.achievement_id = a.id "
                "WHERE a.code = ANY(:codes) GROUP BY a.code"
            ),
            {"codes": CUT},
        )
        .scalars()
        .all()
    )
    removable = [code for code in CUT if code not in set(held)]
    if removable:
        bind.execute(
            sa.text("DELETE FROM achievement WHERE code = ANY(:codes)"),
            {"codes": removable},
        )


def downgrade() -> None:
    # These were seed data, not user content. 0030 puts them back.
    pass
