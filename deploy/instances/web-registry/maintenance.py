"""The bureau's internal maintenance console — loopback only (spec 047).

Bound to `127.0.0.1` and `::1` and never to `0.0.0.0`. A player's browser cannot
reach it; the API can. That asymmetry is the basis of challenges 3 and 4.

  3. `GET /status/flag` is challenge 3's flag, reachable with a plain GET once
     the player has talked the API into fetching from here.
  4. `POST /jobs` is the area boss: a base64 pickle, unpickled with no
     validation.

**What must never appear in this file:** a command parameter, a diagnostics
endpoint that shells out, a file-read parameter, or anything else that turns
"reached the maintenance service" into "ran a command". If reaching this service
were enough, the boss would collapse into challenge 3 with extra steps, and the
brief names that as the one thing that breaks the design. The only way out of
here is a gadget the player builds.
"""

from __future__ import annotations

import base64
import binascii
import logging
import pickle  # noqa: S403 - the unsafe deserialization is the challenge

import jwt
from flask import Flask, jsonify, request

import flags

logger = logging.getLogger(__name__)

app = Flask(__name__)

#: Shared with the API: the maintenance service has no user store of its own, so
#: it trusts the token. A player who has promoted themselves and signed in
#: again, or who has forged a token, has one that says admin.
JWT_SECRET = "changeme"
JWT_ALGORITHM = "HS256"

#: A submitted job is small. A player sending a megabyte is not submitting a job.
MAX_JOB_BYTES = 64 * 1024

SERVED = flags.served()


@app.route("/healthz")
def healthz():
    return jsonify({"status": "ok"}), 200


@app.route("/")
def index():
    """Identifies itself, and says what it offers.

    The second hint on challenge 3 promises it "identifies itself as soon as you
    reach it", so it does — and the path holding that flag is listed here,
    because the brief says the player finds it by reading this response.
    """
    return jsonify(
        {
            "service": "Ridgeline Bureau maintenance console",
            "warning": "Internal interface. Bound to loopback. Not for external use.",
            "endpoints": {
                "GET /status": "service status",
                "GET /status/flag": "maintenance verification token",
                "POST /jobs": (
                    "submit a maintenance job. Body is a base64-encoded serialized "
                    "job object. Administrator token required."
                ),
            },
        }
    )


@app.route("/status")
def status():
    return jsonify(
        {
            "service": "maintenance",
            "queue": "idle",
            "last_run": "never",
            "note": "Scheduled jobs are submitted by the bureau's own tooling.",
        }
    )


@app.route("/status/flag")
def status_flag():
    """Challenge 3's flag. A plain GET, so the SSRF is complete on its own."""
    return jsonify({"verification_token": SERVED[flags.FETCH]})


def _admin_claims() -> dict:
    header = request.headers.get("Authorization", "")
    if not header.startswith("Bearer "):
        return {}
    try:
        claims = jwt.decode(header[7:], JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except jwt.PyJWTError:
        return {}
    return claims if claims.get("role") == "admin" else {}


@app.route("/jobs", methods=["POST"])
def jobs():
    """FLAW 4 — deserialization (challenge: No Route To It). The area boss.

    The body is a base64-encoded serialized job, and it is unpickled without any
    validation of what it contains. A pickle executes on load, so a crafted one
    runs whatever the player wants inside this process.

    The result is returned. That is deliberate: this challenge has no hints at
    all, and fully blind execution with no feedback channel would be unfair on
    one that gives the player nothing to go on.
    """
    if not _admin_claims():
        return jsonify({"error": "An administrator token is required for job submission."}), 403

    raw = request.get_data(cache=False)[: MAX_JOB_BYTES + 1]
    if len(raw) > MAX_JOB_BYTES:
        return jsonify({"error": "Job too large."}), 413
    if not raw:
        return jsonify({"error": "A base64-encoded job object is required."}), 400

    try:
        blob = base64.b64decode(raw, validate=True)
    except (binascii.Error, ValueError):
        return jsonify({"error": "Job object is not valid base64."}), 400

    try:
        job = pickle.loads(blob)  # noqa: S301 - this is the challenge
    except Exception as exc:  # noqa: BLE001 - a malformed job is not a 500
        # Reported, not swallowed. A boss with no hints has to at least tell the
        # player their payload was wrong rather than failing silently.
        return jsonify({"error": f"Job could not be deserialized: {exc}"}), 400

    return jsonify({"accepted": True, "result": str(job)})
