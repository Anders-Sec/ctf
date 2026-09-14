"""Remove the seven non-monotone achievements (spec 039).

Each of these asserts something the player's own later actions falsify — *never*
took a hint, *every* solve was very-easy, *still* has no class. Awards are
insert-only by design, so the retraction that would keep them honest does not
exist, and building one would make an award mutable for the first time. They
come out instead.

Revision ID: 0040
Revises: 0039
"""

import sqlalchemy as sa
from alembic import op

revision = "0040"
down_revision = "0039"
branch_labels = None
depends_on = None


#: code, name, earned_by, description, box type, rarity, no-loot line.
#: Everything needed to put a row back exactly as 0030, 0038 and 0039 left it.
REMOVED = [
    (
        "no_help_needed",
        "No Help Needed",
        "Ten solves without ever taking a hint.",
        "Ten encounters, no hints purchased. Stubbornness that happened to work "
        "is still stubbornness.",
        "purist",
        "gold",
        None,
    ),
    (
        "unassisted",
        "Unassisted",
        "Fifty solves having never bought a hint.",
        "Fifty encounters and not one hint purchased. The audience finds this "
        "either admirable or obstinate. So do I.",
        "purist",
        "legendary",
        None,
    ),
    (
        "low_hanging_fruit",
        "Low Hanging Fruit",
        "Twenty solves, every one of them very-easy.",
        "Twenty encounters, every one rated very easy. Efficient. The audience "
        "noticed the pattern before I did.",
        None,
        None,
        "No box. Twenty of the easiest rooms in the dungeon is efficient. It is not decorated.",
    ),
    (
        "vampire",
        "Vampire",
        "Every solve between 22:00 and 06:00.",
        "Every piece of loot claimed after dark. The surface has a day shift. You are not on it.",
        "pathfinder",
        "gold",
        None,
    ),
    (
        "undefined",
        "Undefined",
        "Reaching level 15 without ever choosing a class.",
        "Level fifteen and still no designation. You have declined to be "
        "anything in particular, at length.",
        None,
        None,
        "No box. You have declined to be anything in particular, so there is nothing to dress.",
    ),
    (
        "wide_not_deep",
        "Wide, Not Deep",
        "Reaching level 10 without clearing a single zone.",
        "Level ten without finishing a single wing. Broad, shallow, and "
        "entirely your own business.",
        None,
        None,
        "No box. Broad and shallow is a strategy. It is not one the stores recognise.",
    ),
    (
        "proud",
        "Proud",
        "Twenty attempts, no hints, no solves.",
        "Twenty attempts, no hints bought, nothing opened. Purity of method, "
        "unburdened by results.",
        None,
        None,
        "No box. Purity of method, unburdened by results, and unburdened by loot.",
    ),
]


def upgrade() -> None:
    bind = op.get_bind()
    # Awards and loot boxes referencing these cascade. In development that is a
    # handful of rows; before the event there are none at all, which is why this
    # runs now rather than later.
    bind.execute(
        sa.text("DELETE FROM achievement WHERE code = ANY(:codes)"),
        {"codes": [row[0] for row in REMOVED]},
    )


def downgrade() -> None:
    bind = op.get_bind()
    # The rows come back; the awards do not. Deleting an achievement cascaded
    # them away, and there is nothing left to reconstruct them from. Anyone who
    # had earned one loses it permanently — stated plainly rather than implied
    # by a silent re-insert.
    for code, name, earned_by, description, box_type, rarity, no_loot in REMOVED:
        bind.execute(
            sa.text(
                "INSERT INTO achievement "
                "(id, code, name, description, earned_by, display_order, "
                " loot_box_type, loot_rarity, no_loot_line) "
                "VALUES (gen_random_uuid(), :c, :n, :d, :e, "
                " (SELECT COALESCE(MAX(display_order), 0) + 1 FROM achievement), "
                " CAST(:bt AS loot_box_type), CAST(:r AS loot_rarity), :nl) "
                "ON CONFLICT (code) DO NOTHING"
            ),
            {
                "c": code,
                "n": name,
                "d": description,
                "e": earned_by,
                "bt": box_type,
                "r": rarity,
                "nl": no_loot,
            },
        )
