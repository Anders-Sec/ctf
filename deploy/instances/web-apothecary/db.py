"""The portal's database: built at start, read-only thereafter (spec 045).

Two of the four flags live inside it, and those are minted per team, so it
cannot be baked at image build time. The entrypoint builds it under /tmp — the
only writable mount the pod has — and the app then opens it read-only for the
rest of its life. Nothing a player does through the app can corrupt it, and a
restart rebuilds exactly the same thing.
"""

from __future__ import annotations

import os
import sqlite3

import flags

SEED_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "seed.sql")

#: The record carrying the IDOR flag — one step up from the player's own 1042,
#: so incrementing finds it.
FLAG_RECORD_ID = 1043


def build(minted: dict[str, str], path: str = flags.DATABASE_PATH) -> None:
    """Create the database from the seed, with this instance's flags in it."""
    if os.path.exists(path):
        os.remove(path)

    with open(SEED_PATH, encoding="utf-8") as handle:
        seed = handle.read()

    connection = sqlite3.connect(path)
    try:
        connection.executescript(seed)
        # Parameterised, unlike the login query. The injectable one is the
        # challenge; everything else in this image is written properly.
        connection.execute(
            "UPDATE record SET notes = ? WHERE id = ?",
            (
                "Results discussed with the patient. Filing reference "
                f"{minted[flags.IDOR]} — do not share outside the practice.",
                FLAG_RECORD_ID,
            ),
        )
        connection.execute(
            "UPDATE portal_setting SET value = ? WHERE key = ?",
            (minted[flags.SQLI], "admin_notice"),
        )
        connection.commit()
    finally:
        connection.close()


def connect(path: str = flags.DATABASE_PATH) -> sqlite3.Connection:
    """A read-only handle. The app never opens this database any other way."""
    connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True, check_same_thread=False)
    connection.row_factory = sqlite3.Row
    return connection
