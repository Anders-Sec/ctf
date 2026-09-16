"""Hollowmere Family Health patient portal (spec 045).

A deliberately vulnerable target for four Web Attacks challenges. It is written
to look like an internal application somebody built in 2011 and nobody has
touched since, because that is what makes four bugs of this vintage plausible in
one place.

**Four flaws, and only four.** Each lives on exactly one route and is marked
FLAW below. Everything else uses bound parameters, checks the session, and
refuses what it should. A player who finds an unintended hole here skips the
area, so anything not marked FLAW is meant to be boring and correct.

  1. /record   — IDOR: no owner check on a record lookup.
  2. /login    — SQL injection: the one query built by concatenation.
  3. /page     — path traversal: a single-pass ../ filter, by design.
  4. /message  — template injection: user text through render_template_string.
"""

from __future__ import annotations

import logging
import os
import sqlite3

from flask import (
    Flask,
    redirect,
    render_template,
    render_template_string,
    request,
    session,
    url_for,
)

import db
import flags

logger = logging.getLogger(__name__)

PAGES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pages")

#: The seeded account the login page hands out, so the IDOR challenge is
#: reachable without an imported challenge row having to carry credentials.
DEMO_USER = "p.abernathy"
DEMO_PASSWORD = "springfield"
#: Priya Abernathy's own record. The IDOR flag is one step up, at 1043.
DEMO_RECORD_ID = 1042

#: A player can send a message this long and no longer. Not a security control —
#: a megabyte of Jinja is a way to make the container fall over, and the brief
#: asks for one that does not.
MAX_MESSAGE = 4096

app = Flask(__name__)
# Regenerated every start, so a session cookie does not survive a restart. Not a
# challenge: the cookie is not the way in, the login query is.
app.secret_key = os.urandom(32)


def query(sql: str, args: tuple = ()) -> list[sqlite3.Row]:
    """Every read but the login one. Bound parameters, always."""
    connection = db.connect()
    try:
        return connection.execute(sql, args).fetchall()
    finally:
        connection.close()


def setting(key: str) -> str:
    rows = query("SELECT value FROM portal_setting WHERE key = ?", (key,))
    return rows[0]["value"] if rows else ""


def current_user() -> sqlite3.Row | None:
    user_id = session.get("user_id")
    if user_id is None:
        return None
    rows = query("SELECT * FROM portal_user WHERE id = ?", (user_id,))
    return rows[0] if rows else None


def chrome(**context: object) -> dict:
    return {"site_name": setting("site_name"), "build": setting("portal_build"), **context}


@app.route("/")
def index() -> object:
    return redirect(url_for("portal" if session.get("user_id") else "login"))


@app.route("/healthz")
def healthz() -> tuple[str, int]:
    """Readiness. No session, no database — it must answer while anything else
    is broken, or a restart never comes back."""
    return "ok", 200


@app.route("/login", methods=["GET", "POST"])
def login() -> object:
    error = None
    if request.method == "POST":
        username = request.form.get("username", "")
        password = request.form.get("password", "")

        # FLAW 2 — SQL injection (challenge: Quotes Are Load Bearing).
        #
        # The clause order is deliberate and load-bearing. With `username` last,
        # a bare `' OR '1'='1` in the username field works, which is what the
        # published hint sends the player to try. Written the usual way round,
        # AND binds tighter than OR and that payload silently fails.
        #
        # ORDER BY id LIMIT 1 lands the bypass on the first row in the table,
        # which is the administrator.
        sql = (
            "SELECT id, username, role FROM portal_user "
            f"WHERE password = '{password}' AND username = '{username}' "
            "ORDER BY id LIMIT 1"
        )
        connection = db.connect()
        try:
            row = connection.execute(sql).fetchone()
        except sqlite3.Error as exc:
            # Shown, not swallowed: the player has to be able to confirm the bug
            # with a single apostrophe before exploiting it.
            error = f"Database error: {exc}"
            row = None
        finally:
            connection.close()

        if row is not None:
            session["user_id"] = row["id"]
            session["role"] = row["role"]
            return redirect(url_for("admin" if row["role"] == "admin" else "portal"))
        if error is None:
            error = "That username and password were not recognised."

    return render_template(
        "login.html",
        **chrome(error=error, demo_user=DEMO_USER, demo_password=DEMO_PASSWORD),
    )


@app.route("/logout")
def logout() -> object:
    session.clear()
    return redirect(url_for("login"))


@app.route("/portal")
def portal() -> object:
    user = current_user()
    if user is None:
        return redirect(url_for("login"))
    return render_template(
        "portal.html", **chrome(user=user, own_record=DEMO_RECORD_ID)
    )


@app.route("/record")
def record() -> object:
    user = current_user()
    if user is None:
        return redirect(url_for("login"))

    try:
        record_id = int(request.args.get("id", DEMO_RECORD_ID))
    except ValueError:
        return render_template("notfound.html", **chrome(what="record")), 404

    rows = query("SELECT * FROM record WHERE id = ?", (record_id,))
    if not rows:
        return render_template("notfound.html", **chrome(what="record")), 404

    # FLAW 1 — IDOR (challenge: Someone Else's Chart).
    #
    # rows[0]["owner_id"] is right there and is never compared with the session
    # user. Every other authenticated route in this file checks properly; this
    # one missing check is the whole challenge.
    return render_template("record.html", **chrome(user=user, record=rows[0]))


@app.route("/admin")
def admin() -> object:
    user = current_user()
    if user is None:
        return redirect(url_for("login"))
    if session.get("role") != "admin":
        # Checked properly. The way in is the login query, not this.
        return render_template("denied.html", **chrome()), 403

    return render_template(
        "admin.html",
        **chrome(
            user=user,
            notice=setting("admin_notice"),
            users=query("SELECT id, username, role, fullname FROM portal_user ORDER BY id"),
            record_count=query("SELECT COUNT(*) AS n FROM record")[0]["n"],
        ),
    )


@app.route("/page")
def page() -> object:
    user = current_user()
    if user is None:
        return redirect(url_for("login"))

    requested = request.args.get("f", "welcome.html")

    # FLAW 3 — path traversal (challenge: Up And Out).
    #
    # One pass, not recursive, and no normalisation or realpath check on the
    # result. `....//` survives the strip as `../`, which is the difficulty of
    # the challenge and is exactly what the published hint describes.
    cleaned = requested.replace("../", "")
    path = os.path.join(PAGES_DIR, cleaned)

    # Not part of the puzzle: challenge integrity. The traversal is meant to
    # reach /etc/passwd and the traversal challenge's own flag file, and it
    # still does. What it must not reach is the template-injection challenge's
    # flag, which would hand a `hard` solver the `very_hard` one for free.
    # Refusing dot-prefixed basenames reads as a page renderer that only serves
    # visible pages, and is invisible to every intended payload.
    if os.path.basename(cleaned).startswith("."):
        return render_template("notfound.html", **chrome(what="page")), 404
    if os.path.normpath(path) == os.path.normpath(flags.SSTI_FLAG_PATH):
        return render_template("notfound.html", **chrome(what="page")), 404

    try:
        with open(path, encoding="utf-8", errors="replace") as handle:
            body = handle.read()
    except OSError:
        return render_template("notfound.html", **chrome(what="page")), 404

    return render_template("page.html", **chrome(user=user, name=requested, body=body))


@app.route("/message", methods=["GET", "POST"])
def message() -> object:
    user = current_user()
    if user is None:
        return redirect(url_for("login"))

    patients = query(
        "SELECT id, patient FROM record WHERE id BETWEEN 1035 AND 1050 ORDER BY id"
    )
    preview = None
    error = None

    if request.method == "POST":
        body = request.form.get("body", "")[:MAX_MESSAGE]
        try:
            recipient_id = int(request.form.get("recipient", DEMO_RECORD_ID))
        except ValueError:
            recipient_id = DEMO_RECORD_ID
        rows = query("SELECT patient FROM record WHERE id = ?", (recipient_id,))
        recipient = rows[0]["patient"] if rows else "patient"

        # FLAW 4 — server-side template injection (challenge: Curly Braces).
        #
        # The message is composed into a template string and rendered through
        # Flask's own unsandboxed Jinja2 environment, so `{{7*7}}` evaluates and
        # the usual walk from a template global reaches command execution.
        #
        # The flag it leads to is a file, not a config value or an environment
        # variable — the entrypoint scrubbed those — so reading it takes actual
        # command execution rather than dumping context.
        composed = (
            f"Dear {recipient},\n\n{body}\n\n"
            f"Yours sincerely,\n{user['fullname']}\n{setting('site_name')}"
        )
        try:
            preview = render_template_string(composed)
        except Exception as exc:  # noqa: BLE001 - a broken payload is not a 500
            # Malformed input gets an error page, never a traceback and never a
            # dead worker. The message is the engine's, which is fair: the
            # player is meant to be able to tell what they broke.
            error = f"The message could not be composed: {exc}"

    return render_template(
        "message.html", **chrome(user=user, patients=patients, preview=preview, error=error)
    )


@app.errorhandler(404)
def not_found(_exc: object) -> tuple[str, int]:
    return render_template("notfound.html", **chrome(what="page")), 404


@app.errorhandler(500)
def server_error(_exc: object) -> tuple[str, int]:
    """No traceback, ever. A stack trace would leak the four flaws at once."""
    return render_template("error.html", **chrome()), 500
