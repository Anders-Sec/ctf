"""Where this instance's four flags live, and how they get there (spec 045).

The platform hands the container one variable, ``INSTANCE_ANSWERS`` — a JSON
object of challenge slug to minted flag (spec 046). Two of the four flags belong
inside the database and two belong in files, so nothing can be baked at build
time and all of it is written at container start.

Read this module with the *scrub* in mind. The path-traversal challenge can read
``/proc/self/environ``. If ``INSTANCE_ANSWERS`` is still in the environment when
the server starts, that hard challenge hands over the very-hard challenge's flag
for free. The entrypoint materialises, unsets, and only then execs gunicorn.
"""

from __future__ import annotations

import json
import logging
import os

logger = logging.getLogger(__name__)

#: The variable the platform sets. Scrubbed before the server runs.
ANSWERS_ENV = "INSTANCE_ANSWERS"

#: Challenge slugs, exactly as the CSV spells them. These are the keys the
#: platform sends, so a rename there is a rename here.
IDOR = "someone-elses-chart"
SQLI = "quotes-are-load-bearing"
TRAVERSAL = "up-and-out"
SSTI = "curly-braces"
SLUGS = (IDOR, SQLI, TRAVERSAL, SSTI)

#: /tmp is the only writable mount under the pod's read-only root filesystem
#: (spec 009), so everything minted per team lives here.
RUNTIME_DIR = os.environ.get("APOTHECARY_RUNTIME", "/tmp")
DATABASE_PATH = os.path.join(RUNTIME_DIR, "apothecary.db")
#: The traversal challenge's target. Outside the web root, which is all the
#: challenge text claims, and named in this source so a player who reads it
#: through the traversal itself can find it.
TRAVERSAL_FLAG_PATH = os.path.join(RUNTIME_DIR, "flag.txt")
#: The template-injection challenge's target. Dot-prefixed, which is what keeps
#: the traversal challenge from reading it — see ``app.render_page``.
SSTI_FLAG_PATH = os.path.join(RUNTIME_DIR, ".flag")

#: Used when the platform is not there: a local `docker run`, or the test suite.
#: Deliberately not the authored stems on their own — a flag ending in `_local`
#: cannot be mistaken for one a player was supposed to have earned.
LOCAL_FALLBACK = {
    IDOR: "flag{not_your_chart_local}",
    SQLI: "flag{quotes_are_load_bearing_local}",
    TRAVERSAL: "flag{up_and_out_local}",
    SSTI: "flag{the_template_ate_it_local}",
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

    flags = dict(LOCAL_FALLBACK)
    for slug in SLUGS:
        value = parsed.get(slug)
        if isinstance(value, str) and value:
            flags[slug] = value
        else:
            # One missing key must not take the other three down with it: three
            # solvable challenges beat a container that will not start.
            logger.warning("No flag for %r in %s — falling back for that one.", slug, ANSWERS_ENV)
    return flags


def scrub() -> None:
    """Remove the flags from the environment, before anything can be served.

    Called by the entrypoint between materialising and exec'ing the server, so
    ``/proc/self/environ`` has nothing in it worth reading.
    """
    os.environ.pop(ANSWERS_ENV, None)
