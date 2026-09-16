"""Where this instance's four flags live, and how they get there (spec 047).

The platform hands the container `INSTANCE_ANSWERS` — a JSON object of challenge
slug to minted flag (spec 046). The entrypoint materialises them, scrubs the
variable, and only then starts either service.

**The boss flag is handled differently from the other three, on purpose.** Flags
1 to 3 go into a runtime file that the API and the maintenance service read at
startup, because each of them has to serve one. The boss flag goes to its own
file and is deliberately left out of that runtime file: neither process ever
loads it, so neither process can disclose it. The only thing in this container
that can reach it is code the player is running.
"""

from __future__ import annotations

import json
import logging
import os

logger = logging.getLogger(__name__)

#: The variable the platform sets. Scrubbed before either service starts.
ANSWERS_ENV = "INSTANCE_ANSWERS"

#: Challenge slugs, exactly as the CSV spells them.
PROMOTED = "promoted"
SIGNED = "signed-by-me"
FETCH = "fetch-it-for-me"
BOSS = "no-route-to-it"
SLUGS = (PROMOTED, SIGNED, FETCH, BOSS)

#: /tmp is the only writable mount under the pod's read-only root filesystem.
RUNTIME_DIR = os.environ.get("REGISTRY_RUNTIME", "/tmp")
SERVED_FLAGS_PATH = os.path.join(RUNTIME_DIR, "runtime", "flags.json")
DATABASE_PATH = os.path.join(RUNTIME_DIR, "runtime", "registry.db")
#: The boss. A file, and nothing else — no route serves it, and no process reads
#: it. Finding the path is part of the boss, so nothing advertises it.
BOSS_FLAG_PATH = os.path.join(RUNTIME_DIR, "registry", "secrets", ".flag")

#: Used when the platform is not there: a local `docker run`, or the tests.
LOCAL_FALLBACK = {
    PROMOTED: "flag{i_promoted_myself_local}",
    SIGNED: "flag{signed_by_me_local}",
    FETCH: "flag{the_server_fetched_it_local}",
    BOSS: "flag{trust_no_object_local}",
}


def load() -> dict[str, str]:
    """This instance's flags, or the local fallback when there is no platform."""
    raw = os.environ.get(ANSWERS_ENV)
    if not raw:
        logger.warning(
            "%s is not set — using local development flags. If you are seeing "
            "this in a real instance, every team has the same flags.",
            ANSWERS_ENV,
        )
        return dict(LOCAL_FALLBACK)

    try:
        parsed = json.loads(raw)
    except ValueError:
        logger.warning("%s is not valid JSON — using local development flags.", ANSWERS_ENV)
        return dict(LOCAL_FALLBACK)

    minted = dict(LOCAL_FALLBACK)
    for slug in SLUGS:
        value = parsed.get(slug)
        if isinstance(value, str) and value:
            minted[slug] = value
        else:
            # One missing key must not take the other three down with it.
            logger.warning("No flag for %r in %s — falling back for that one.", slug, ANSWERS_ENV)
    return minted


def served() -> dict[str, str]:
    """The three flags a service is allowed to know.

    Read once at startup by whichever process serves them. The boss flag is not
    in here and never will be — see the module docstring.
    """
    try:
        with open(SERVED_FLAGS_PATH, encoding="utf-8") as handle:
            return json.load(handle)
    except OSError:
        logger.warning("no runtime flag file — falling back for every challenge")
        return {slug: LOCAL_FALLBACK[slug] for slug in (PROMOTED, SIGNED, FETCH)}


def scrub() -> None:
    """Remove the flags from the environment, before either service starts."""
    os.environ.pop(ANSWERS_ENV, None)
