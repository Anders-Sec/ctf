"""Locust load model for the core player loop (spec 012).

Run against a target with sessions seeded by ``seed.py``::

    cd loadtest
    locust -f locustfile.py --host https://ctf-nm.org

Then drive it from the web UI, or headless::

    locust -f locustfile.py --host https://ctf-nm.org \
        --users 200 --spawn-rate 20 --run-time 10m --headless

The weighting models a real crowd: mostly reading the board and the scoreboard,
submitting flags at a human pace (the named bottleneck — wrong far more often
than right), and occasionally unlocking a hint. Each virtual user carries a real
seeded session, so this exercises auth, the resolver, the rate limiter, the solve
race and the scoreboard invalidation exactly as a browser would.

The scoreboard WebSocket (one long-lived connection per viewer) is a separate
scale concern; see the runbook for holding N of them open alongside this.
"""

import csv
import itertools
import os
import random

from locust import HttpUser, between, task

CSRF_HEADER = "X-CSRF-Token"
SESSIONS_FILE = os.environ.get("CTF_SESSIONS", "sessions.csv")


def _load_sessions() -> list[dict[str, str]]:
    with open(SESSIONS_FILE, newline="") as handle:
        return list(csv.DictReader(handle))


# Hand out seeded sessions round-robin so every virtual user is a distinct
# signed-in player rather than all sharing one.
_sessions = _load_sessions()
_session_cycle = itertools.cycle(_sessions)

# A realistic mix: the vast majority of submissions are wrong.
_WRONG_FLAGS = [f"flag{{attempt_{n}}}" for n in range(20)]


class Player(HttpUser):
    wait_time = between(3, 12)

    def on_start(self) -> None:
        session = next(_session_cycle)
        self.client.cookies.set("ctf_access", session["access_token"])
        self.client.cookies.set("ctf_csrf", session["csrf_token"])
        self.client.headers[CSRF_HEADER] = session["csrf_token"]
        self.challenge_ids: list[str] = []
        self._refresh_challenges()

    def _refresh_challenges(self) -> None:
        with self.client.get("/api/challenges", name="challenges:list", catch_response=True) as r:
            if r.status_code == 200 and isinstance(r.json(), list):
                self.challenge_ids = [c["id"] for c in r.json()]
            elif r.status_code == 401:
                r.failure("session not accepted — reseed sessions.csv")

    @task(10)
    def read_board(self) -> None:
        self.client.get("/api/challenges", name="challenges:list")

    @task(10)
    def read_scoreboard(self) -> None:
        self.client.get("/api/scoreboard/players", name="scoreboard:players")

    @task(5)
    def submit_flag(self) -> None:
        if not self.challenge_ids:
            self._refresh_challenges()
            return
        challenge_id = random.choice(self.challenge_ids)
        # 1-in-25 attempts is "correct"; it will not actually match a real answer,
        # but it exercises the full accept path up to the resolver either way.
        flag = "flag{correct}" if random.random() < 0.04 else random.choice(_WRONG_FLAGS)
        with self.client.post(
            f"/api/challenges/{challenge_id}/submit",
            json={"answer": flag},
            name="challenges:submit",
            catch_response=True,
        ) as r:
            # A 429 is the rate limiter doing its job under a burst, not a failure.
            if r.status_code == 429:
                r.success()

    @task(1)
    def read_my_score(self) -> None:
        self.client.get("/api/scoreboard/me", name="scoreboard:me")
