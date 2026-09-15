"""Six achievements for the daily puzzles (spec 044 §8).

Puzzles pay flat XP whether you scrape a Wordle on the sixth guess or take it on
the third, which was a deliberate choice: two variables moving at once — decay
and performance — makes "why did I get 140?" unanswerable. Skill is recognised
here instead.

``description`` is written here rather than seeded as a placeholder. 0030's
convention was to defer it, but 0038 filled every one of those in and the suite
now holds the line that no row may ship without its copy — a placeholder reaching
the roster would show a player a TODO. Six lines, in the System's voice.

Revision ID: 0044
Revises: 0043
"""

import sqlalchemy as sa
from alembic import op

revision = "0044"
down_revision = "0043"
branch_labels = None
depends_on = None

#: (code, name, description, earned_by, box_type, rarity). The boxes follow
#: 0039's tiering: bronze for turning up, silver for playing well, gold for the
#: sweep.
ROSTER = [
    (
        "puzzle_first",
        "Studio Audience",
        "You finished one of the dailies. The applause is recorded. It is still applause.",
        "Finishing any daily puzzle.",
        "adventurer",
        "bronze",
    ),
    (
        "wordle_sharp",
        "Three Letters In",
        "Five letters, three guesses. Either you know the field or you know the vowels. "
        "I have not decided which is worse.",
        "Solving a Wordle in three guesses or fewer.",
        "specialist",
        "silver",
    ),
    (
        "connections_flawless",
        "No Loose Threads",
        "Sixteen tiles, four groups, not one wrong turn. I built that board to be misleading. "
        "You declined to be misled.",
        "Solving a Connections without a single mistake.",
        "specialist",
        "silver",
    ),
    (
        "crossword_clean",
        "Pen, Not Pencil",
        "You filled the grid and checked it once. Confidence like that is usually misplaced. "
        "On this occasion it was not.",
        "Solving a crossword right on the first check.",
        "specialist",
        "silver",
    ),
    (
        "game_show_regular",
        "Regular Contestant",
        "All three games, all three cleared. You have found the one wing of this place that "
        "is trying to be pleasant. Enjoy it while it lasts.",
        "Solving a puzzle of all three kinds.",
        "adventurer",
        "silver",
    ),
    (
        "game_show_sweep",
        "Undefeated",
        "Every puzzle on the board, and not one of them got you. The house always wins. "
        "The house would like to see some identification.",
        "Solving every published puzzle, having lost none of them.",
        "adventurer",
        "gold",
    ),
]


def upgrade() -> None:
    bind = op.get_bind()
    # display_order continues from whatever the roster already holds, so these
    # land at the end rather than shuffling the existing list.
    base = (
        bind.execute(sa.text("SELECT COALESCE(MAX(display_order), 0) FROM achievement"))
    ).scalar() or 0

    for offset, (code, name, description, earned_by, box, rarity) in enumerate(ROSTER, start=1):
        # Idempotent on code, and deliberately leaves `description` alone on a
        # re-run: once somebody has edited the copy in the platform, this
        # migration is not the authority on it any more.
        bind.execute(
            sa.text(
                "INSERT INTO achievement "
                "(id, code, name, description, earned_by, display_order, "
                " loot_box_type, loot_rarity) "
                "VALUES (gen_random_uuid(), :c, :n, :d, :e, :o, "
                " CAST(:b AS loot_box_type), CAST(:r AS loot_rarity)) "
                "ON CONFLICT (code) DO UPDATE SET "
                "name = EXCLUDED.name, "
                "earned_by = EXCLUDED.earned_by, "
                "loot_box_type = EXCLUDED.loot_box_type, "
                "loot_rarity = EXCLUDED.loot_rarity"
            ),
            {
                "c": code,
                "n": name,
                "d": description,
                "e": earned_by,
                "o": base + offset,
                "b": box,
                "r": rarity,
            },
        )


def downgrade() -> None:
    bind = op.get_bind()
    codes = [code for code, *_ in ROSTER]
    # Never delete one somebody holds: a stale row is a smaller problem than an
    # award disappearing from a player's sheet.
    held = set(
        bind.execute(
            sa.text(
                "SELECT a.code FROM achievement a "
                "JOIN achievement_award w ON w.achievement_id = a.id "
                "WHERE a.code = ANY(:codes) GROUP BY a.code"
            ),
            {"codes": codes},
        )
        .scalars()
        .all()
    )
    removable = [code for code in codes if code not in held]
    if removable:
        bind.execute(
            sa.text("DELETE FROM achievement WHERE code = ANY(:codes)"),
            {"codes": removable},
        )
