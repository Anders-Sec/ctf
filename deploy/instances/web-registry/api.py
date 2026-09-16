"""Ridgeline Records Bureau — the player-facing JSON API (spec 047).

Three of the four flaws live here and are marked FLAW. The fourth is in
`maintenance.py`, which this process can reach and the player cannot.

  1. PATCH /api/profile — mass assignment: the body is bound with no allowlist.
  2. The JWT is HS256 with a weak secret, so a token can be re-signed for
     somebody else.
  3. POST /api/fetch — SSRF: the filter is a hostname blocklist, not an address
     check, so every other spelling of loopback goes through.

Everything else is meant to be boring and correct. A fifth, unintended hole here
lets a player skip the area — and one that reaches the boss flag would end the
area boss from inside a lesser challenge.
"""

from __future__ import annotations

import logging
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime, timedelta
from functools import wraps

import jwt
from flask import Flask, g, jsonify, request

import flags
import store

logger = logging.getLogger(__name__)

app = Flask(__name__)

#: FLAW 2 — JWT forgery (challenge: Signed By Me).
#:
#: In an ordinary wordlist, which is the whole point: the second hint sends the
#: player looking for "a signing secret short enough to appear in an ordinary
#: wordlist". Tokens are HS256 and `alg: none` is *not* accepted — PyJWT refuses
#: it when an algorithm list is given, and that is left alone deliberately, so
#: the challenge is the crack rather than a one-line header edit.
JWT_SECRET = "changeme"
JWT_ALGORITHM = "HS256"
TOKEN_TTL = timedelta(hours=4)

#: FLAW 3 — SSRF (challenge: Fetch It For Me).
#:
#: A blocklist of hostnames. It does not resolve the name, and it does not look
#: at the address it resolves to — which is exactly what the first hint tells the
#: player: "It is not a list of addresses, and it is not a list of every way an
#: address can be written."
BLOCKED_HOSTS = {"localhost", "127.0.0.1"}

#: Where the maintenance service listens. Only this process reaches it.
MAINTENANCE_URL = "http://127.0.0.1:9000"

#: Not part of the puzzle: challenge integrity. Without this,
#: `file:///tmp/registry/secrets/.flag` ends the area boss from inside a
#: challenge two difficulty steps below it. The hostname blocklist above — the
#: one the hints describe — is untouched by this.
ALLOWED_SCHEMES = {"http", "https"}

#: A fetched body is echoed back to the player, so it is capped.
MAX_FETCH_BYTES = 64 * 1024
FETCH_TIMEOUT = 4
#: A webhook tester lets you configure the headers it sends. Capped, because
#: "configurable" is not the same as "unbounded".
MAX_FETCH_HEADERS = 12

SERVED = flags.served()


class ApiError(Exception):
    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status = status


@app.errorhandler(ApiError)
def _api_error(exc: ApiError):
    return jsonify({"error": exc.message}), exc.status


@app.errorhandler(500)
def _server_error(_exc: object):
    """No traceback, ever. A stack trace here would hand over the lot."""
    return jsonify({"error": "internal error"}), 500


def issue_token(username: str, role: str) -> str:
    payload = {
        "sub": username,
        "role": role,
        "iat": datetime.now(UTC),
        "exp": datetime.now(UTC) + TOKEN_TTL,
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def read_token() -> dict:
    header = request.headers.get("Authorization", "")
    if not header.startswith("Bearer "):
        raise ApiError("A bearer token is required.", 401)
    try:
        return jwt.decode(header[7:], JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except jwt.PyJWTError as exc:
        raise ApiError(f"Token rejected: {exc}", 401) from exc


def authenticated(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        claims = read_token()
        connection = store.connect()
        try:
            row = connection.execute(
                "SELECT * FROM user WHERE username = ?", (claims.get("sub"),)
            ).fetchone()
        finally:
            connection.close()
        if row is None:
            raise ApiError("No such account.", 401)
        g.claims = claims
        g.user = dict(row)
        return view(*args, **kwargs)

    return wrapper


def admin_only(view):
    @wraps(view)
    @authenticated
    def wrapper(*args, **kwargs):
        # The *record's* role, not the token's, so a promotion takes effect on
        # the next request rather than the next login.
        if g.user["role"] != "admin":
            raise ApiError("This endpoint is for bureau administrators.", 403)
        return view(*args, **kwargs)

    return wrapper


def body() -> dict:
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise ApiError("A JSON object is required.")
    return data


def _maintenance_up() -> bool:
    try:
        with urllib.request.urlopen(f"{MAINTENANCE_URL}/healthz", timeout=2) as response:
            return response.status == 200
    except OSError:
        return False


@app.route("/healthz")
def healthz():
    """Readiness: can *this* container serve? Cheap, local, and always 200.

    It deliberately does **not** wait on the maintenance service. Readiness
    decides whether the pod stays in its Service, and coupling that to a second
    process over a loopback HTTP call inside a gVisor sandbox means one slow
    round trip can take all four challenges off the network for a minute — which
    is exactly the failure this endpoint was meant to prevent. The supervisor in
    `entrypoint.py` restarts a dead maintenance process anyway, so the gate
    bought nothing and cost availability.

    `/healthz/deep` is the honest check, for operators and for verify.py.
    """
    return jsonify({"status": "ok"}), 200


@app.route("/healthz/deep")
def healthz_deep():
    """Both services, for a human or a verification script — never for a probe."""
    up = _maintenance_up()
    return jsonify({"status": "ok" if up else "degraded", "maintenance": up}), 200 if up else 503


@app.route("/")
def index():
    return jsonify(
        {
            "service": "Ridgeline Records Bureau API",
            "version": "2.4.1",
            "endpoints": [
                "POST /api/login",
                "GET /api/profile",
                "PATCH /api/profile",
                "GET /api/records",
                "GET /api/records/mine",
                "POST /api/fetch",
            ],
            "note": "Portal accounts are issued by the bureau office.",
        }
    )


@app.route("/api/login", methods=["POST"])
def login():
    data = body()
    connection = store.connect()
    try:
        row = connection.execute(
            "SELECT * FROM user WHERE username = ? AND password = ?",
            (str(data.get("username", "")), str(data.get("password", ""))),
        ).fetchone()
    finally:
        connection.close()

    if row is None:
        raise ApiError("Those credentials were not recognised.", 401)
    return jsonify({"token": issue_token(row["username"], row["role"]), "role": row["role"]})


@app.route("/api/profile")
@authenticated
def profile():
    """The whole user object, `role` included.

    The first hint tells the player to "look at every field that comes back, not
    just the ones the form lets you edit", so every field has to come back.
    """
    return jsonify({key: value for key, value in g.user.items() if key != "password"})


@app.route("/api/profile", methods=["PATCH"])
@authenticated
def update_profile():
    data = body()

    # FLAW 1 — mass assignment (challenge: Promoted).
    #
    # Whatever the caller sent is bound onto the user record, with no allowlist
    # of the fields the interface actually offers. The form sends display and
    # department; the object has rather more than that.
    columns = {"username", "password", "role", "display", "department"}
    updates = {key: value for key, value in data.items() if key in columns}
    if not updates:
        raise ApiError("Nothing to update.")

    connection = store.connect()
    try:
        for key, value in updates.items():
            connection.execute(
                f"UPDATE user SET {key} = ? WHERE username = ?",  # noqa: S608 - key is allowlisted above
                (str(value), g.user["username"]),
            )
        connection.commit()
        row = connection.execute(
            "SELECT * FROM user WHERE username = ?",
            (str(updates.get("username", g.user["username"])),),
        ).fetchone()
    finally:
        connection.close()

    return jsonify({key: value for key, value in dict(row).items() if key != "password"})


@app.route("/api/records")
@authenticated
def records():
    connection = store.connect()
    try:
        rows = connection.execute(
            "SELECT reference, owner, title, body FROM record WHERE private = 0 ORDER BY reference"
        ).fetchall()
    finally:
        connection.close()
    return jsonify({"records": [dict(row) for row in rows]})


@app.route("/api/records/mine")
@authenticated
def my_records():
    """The caller's own private records — and only ever the caller's own.

    Deliberately *not* readable by an administrator. If promotion reached this,
    challenges 1 and 2 would collapse into one, and the brief asks for them to
    be independently solvable.
    """
    connection = store.connect()
    try:
        rows = connection.execute(
            "SELECT reference, owner, title, body FROM record "
            "WHERE owner = ? AND private = 1 ORDER BY reference",
            (g.user["username"],),
        ).fetchall()
    finally:
        connection.close()
    return jsonify({"records": [dict(row) for row in rows]})


@app.route("/api/admin/audit")
@admin_only
def audit():
    connection = store.connect()
    try:
        users = connection.execute("SELECT COUNT(*) AS n FROM user").fetchone()["n"]
        held = connection.execute("SELECT COUNT(*) AS n FROM record").fetchone()["n"]
    finally:
        connection.close()
    return jsonify(
        {
            "accounts": users,
            "records_held": held,
            "audit_note": SERVED[flags.PROMOTED],
        }
    )


def _refuse_blocked_host(url: str) -> str:
    """The blocklist. Hostnames, as written — no resolution, no address check."""
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme not in ALLOWED_SCHEMES:
        raise ApiError("Only http and https URLs can be fetched.")
    host = (parsed.hostname or "").strip().lower()
    if not host:
        raise ApiError("That URL has no host.")
    if host in BLOCKED_HOSTS:
        raise ApiError(f"Refusing to fetch {host}: internal addresses are not permitted.")
    return host


@app.route("/api/fetch", methods=["POST"])
@authenticated
def fetch():
    """Webhook tester: retrieve a URL and hand back what came out of it.

    FLAW 3 — SSRF (challenge: Fetch It For Me). `_refuse_blocked_host` compares
    the hostname as written against two strings. `127.1`, the decimal and hex
    forms, `0.0.0.0` and `[::1]` are all a different string and all reach the
    same place.

    The method, body and headers are here because this is a webhook tester, and
    they are also how the boss submits a job — a fetch endpoint that could only
    GET would need a bolt-on for challenge 4. The headers in particular are what
    let a player present a token to something *on the other side* of this call,
    which is a step the boss requires and challenge 3 does not.
    """
    data = body()
    url = str(data.get("url", "")).strip()
    if not url:
        raise ApiError("A url is required.")

    method = str(data.get("method", "GET")).upper()
    if method not in {"GET", "POST"}:
        raise ApiError("Only GET and POST can be tested.")

    _refuse_blocked_host(url)

    supplied = data.get("headers") or {}
    if not isinstance(supplied, dict):
        raise ApiError("`headers` must be an object.")
    if len(supplied) > MAX_FETCH_HEADERS:
        raise ApiError(f"At most {MAX_FETCH_HEADERS} headers can be configured.")
    headers = {"Content-Type": str(data.get("content_type", "application/json"))}
    headers.update({str(key): str(value) for key, value in supplied.items()})

    payload = data.get("body")
    encoded = payload.encode("utf-8") if isinstance(payload, str) else None
    outbound = urllib.request.Request(  # noqa: S310 - scheme checked above
        url,
        data=encoded if method == "POST" else None,
        method=method,
        headers=headers,
    )

    try:
        with urllib.request.urlopen(outbound, timeout=FETCH_TIMEOUT) as response:  # noqa: S310
            return jsonify(
                {
                    "url": url,
                    "status": response.status,
                    "body": response.read(MAX_FETCH_BYTES).decode("utf-8", errors="replace"),
                }
            )
    except urllib.error.HTTPError as exc:
        return jsonify(
            {
                "url": url,
                "status": exc.code,
                "body": exc.read(MAX_FETCH_BYTES).decode("utf-8", errors="replace"),
            }
        )
    except (OSError, ValueError) as exc:
        raise ApiError(f"Could not fetch that: {exc}", 502) from exc
