"""The registry's data: seeded at start, read-write for the API (spec 047).

SQLite rather than a dict in memory, because challenge 1 promotes a user and
that promotion has to survive the next request landing on a different gunicorn
worker. Built by the entrypoint under /tmp, which is the only writable mount.

Every query here is parameterised. There is no SQL injection challenge on this
container, so there is no reason for one to exist.
"""

from __future__ import annotations

import os
import sqlite3

import flags

#: The user whose private record carries the JWT-forgery flag. An admin cannot
#: read it — that is what keeps challenges 1 and 2 independent.
SIGNED_FLAG_OWNER = "m.calloway"

#: The account the challenge hands the player.
DEMO_USER = "t.brennan"
DEMO_PASSWORD = "bureau2019"

SEED_USERS = [
    # username, password, role, display name, department
    (DEMO_USER, DEMO_PASSWORD, "clerk", "Tomas Brennan", "Intake"),
    (SIGNED_FLAG_OWNER, "aH7#kq2Lm9$xZ", "archivist", "Maeve Calloway", "Archive"),
    ("r.desmond", "qX4!vn8Rt3@wB", "clerk", "Rosalind Desmond", "Intake"),
    ("s.oyelowo", "pK9%bz5Wd1&yN", "admin", "Segun Oyelowo", "Bureau Office"),
]

SEED_RECORDS = [
    # reference, owner, title, body, private
    ("RB-4401", DEMO_USER, "Transfer of deeds, Halloway parcel",
     "Filed and indexed. Awaiting counter-signature from the county office.", 0),
    ("RB-4402", "r.desmond", "Boundary amendment, Ferncross",
     "Amended plan received. Superseded the 1998 survey.", 0),
    ("RB-4403", SIGNED_FLAG_OWNER, "Archive retrieval log",
     "Routine retrievals for the quarter. Nothing outstanding.", 0),
    ("RB-4404", DEMO_USER, "Intake queue notes",
     "Backlog cleared on Tuesday. Two items referred to the archive.", 1),
    # RB-4405 is Calloway's private record; its body is written at start.
    ("RB-4405", SIGNED_FLAG_OWNER, "Archivist's private memorandum",
     "PLACEHOLDER — overwritten at container start.", 1),
    ("RB-4406", "r.desmond", "Correspondence, Pell estate",
     "Solicitor's letter acknowledged. No action required this quarter.", 1),
]


def build(minted: dict[str, str], path: str = flags.DATABASE_PATH) -> None:
    """Create the database, with this instance's flags where they belong."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if os.path.exists(path):
        os.remove(path)

    connection = sqlite3.connect(path)
    try:
        connection.executescript(
            """
            CREATE TABLE user (
                username   TEXT PRIMARY KEY,
                password   TEXT NOT NULL,
                role       TEXT NOT NULL,
                display    TEXT NOT NULL,
                department TEXT NOT NULL
            );
            CREATE TABLE record (
                reference TEXT PRIMARY KEY,
                owner     TEXT NOT NULL,
                title     TEXT NOT NULL,
                body      TEXT NOT NULL,
                private   INTEGER NOT NULL
            );
            """
        )
        connection.executemany(
            "INSERT INTO user (username, password, role, display, department) "
            "VALUES (?, ?, ?, ?, ?)",
            SEED_USERS,
        )
        connection.executemany(
            "INSERT INTO record (reference, owner, title, body, private) VALUES (?, ?, ?, ?, ?)",
            SEED_RECORDS,
        )
        connection.execute(
            "UPDATE record SET body = ? WHERE reference = ?",
            (
                "Held under archivist's seal. Retrieval reference "
                f"{minted[flags.SIGNED]} — not to be quoted outside the archive.",
                "RB-4405",
            ),
        )
        connection.commit()
    finally:
        connection.close()


def connect(path: str = flags.DATABASE_PATH) -> sqlite3.Connection:
    """A read-write handle. The API updates profiles, which is challenge 1."""
    connection = sqlite3.connect(path, check_same_thread=False, timeout=5)
    connection.row_factory = sqlite3.Row
    return connection
