"""Materialise this team's flags, scrub the environment, then serve (spec 045).

Order matters, and step 3 is the reason this is an entrypoint rather than
application startup code:

  1. Read ``INSTANCE_ANSWERS`` — the four flags the platform minted for whoever
     launched this container (spec 046).
  2. Write each one where its challenge needs it: two into the database this
     builds under /tmp, two into files.
  3. **Unset the variable**, then exec gunicorn, which inherits the scrubbed
     environment.

Without step 3 the path-traversal challenge reads ``/proc/self/environ`` and
walks away with the template-injection challenge's flag — a `hard` solver
collecting the `very_hard` one for nothing.
"""

from __future__ import annotations

import logging
import os
import stat
import sys

import db
import flags

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("entrypoint")

#: Serving details. Two workers is enough for one party and keeps the memory
#: limit comfortable; threads absorb a player hammering the thing.
BIND = os.environ.get("APOTHECARY_BIND", "0.0.0.0:8080")
WORKERS = os.environ.get("APOTHECARY_WORKERS", "2")
THREADS = os.environ.get("APOTHECARY_THREADS", "4")


def materialise(minted: dict[str, str]) -> None:
    """Put each flag where its challenge expects to find it."""
    # Challenges 1 and 2 live in the database: the IDOR flag in a record's
    # clinical notes, the SQLi flag on the admin dashboard.
    db.build(minted)

    # Challenge 3: an ordinary file, outside the web root, reachable by the
    # traversal. Readable — finding it is the challenge, not opening it.
    with open(flags.TRAVERSAL_FLAG_PATH, "w", encoding="utf-8") as handle:
        handle.write(minted[flags.TRAVERSAL] + "\n")
    os.chmod(flags.TRAVERSAL_FLAG_PATH, stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)

    # Challenge 4: restrictive-looking, readable by this uid, and dot-prefixed
    # so the traversal challenge's page renderer refuses it. Reading this takes
    # command execution, which is the challenge.
    with open(flags.SSTI_FLAG_PATH, "w", encoding="utf-8") as handle:
        handle.write(minted[flags.SSTI] + "\n")
    os.chmod(flags.SSTI_FLAG_PATH, stat.S_IRUSR)

    logger.info("flags materialised for %d challenges", len(flags.SLUGS))


def main() -> None:
    materialise(flags.load())

    # Everything is on disk now. Nothing that follows needs the variable, and
    # anything that can read the environment must not find it.
    flags.scrub()

    os.execvp(  # noqa: S606 - fixed argv, no shell
        "gunicorn",
        [
            "gunicorn",
            "--bind",
            BIND,
            "--workers",
            WORKERS,
            "--threads",
            THREADS,
            # A player can wedge a worker with a pathological payload; gunicorn
            # replaces it rather than letting the container sit there dead.
            "--timeout",
            "30",
            "--worker-tmp-dir",
            flags.RUNTIME_DIR,
            "--access-logfile",
            "-",
            "app:app",
        ],
    )


if __name__ == "__main__":
    sys.exit(main())
