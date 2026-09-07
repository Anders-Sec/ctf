# Spec 012 — Load and Non-Functional Verification

Status: **done** — harness + runbook + 3 automated NFR tests; the live 200-player run is the operator's step
Phase: 1 (the last item)
Covers: `Plan.md` → Non-Functional Requirements, and the Definition-of-Done load line
Depends on: everything — this verifies the finished platform

## Purpose

The three non-functional requirements from `Plan.md`, turned into things that are
actually checked rather than asserted:

1. **200+ concurrent players across a multi-day event, no data loss on restart**
   (Postgres the source of truth, Redis only a cache).
2. **Load-test flag submission and container provisioning specifically** — the
   two named bottlenecks.
3. **Audit logging on every admin action.**

The honest boundary: a true 200-player test runs against the live cluster with
the GPU box and the instance namespace, and the project owner executes it — this
session has no cluster access. So this spec delivers **a harness anyone can point
at the cluster, a scaled version that runs in CI as a regression guard, two
automated NFR tests, and a runbook** for the real run. The load *tooling* and the
NFR *guarantees* are the deliverable; pressing "go" on 200 real users is an
operational step, documented here.

## 1. The load harness (Locust)

`loadtest/locustfile.py`, Locust (chosen for stack fit — scenarios are plain
Python that reuse nothing secret and read like the app). It models a player's
core loop, weighted the way a real crowd behaves:

| Task | Weight | Why |
| --- | --- | --- |
| Read the challenge board | high | What players do most |
| Read the scoreboard | high | Open on a second monitor all event |
| Submit a flag (mostly wrong, occasionally right) | medium | **The named bottleneck.** Exercises the resolver, the rate limiter, the solve race and the scoreboard invalidation |
| Unlock a hint | low | Touches the scoring side-effect path |
| Hold the scoreboard WebSocket open | a fraction of users | The live board is a long-lived connection per viewer |

**Authentication without a backdoor.** A load test needs many signed-in sessions,
and this platform has no password to script and will not grow a "log in as anyone"
endpoint. Instead `loadtest/seed.py` creates N load users and mints real sessions
with the app's own `issue_session`, writing a CSV of cookies; the locustfile loads
it and each virtual user carries a real session. The seed is gated to a load-test
run against a disposable database and never touches production data.

**Out of the local harness, into the runbook:** the **AI chat** (needs the GPU
box) and **instance provisioning** (needs the cluster and gVisor) are load-tested
against real infrastructure per the runbook, not from a laptop. `Plan.md` names
container provisioning specifically, so the runbook gives it its own scenario:
ramp concurrent launches to the per-owner cap across many owners, watch pod
scheduling throughput and the reconciler, confirm the quota degrades gracefully
to "no capacity" rather than erroring.

### Proposed SLOs (the pass/fail line)

At 200 concurrent virtual users on the cluster:

| Flow | Target |
| --- | --- |
| Flag submission | p95 < 400 ms, zero 5xx, correct solves recorded exactly once |
| Challenge/scoreboard reads | p95 < 250 ms |
| Scoreboard WebSocket | stays connected, updates within a couple of seconds of a solve |
| Instance launch | returns `pending` in < 1 s; readiness follows the pod, not the request |

Numbers are a starting point to confirm; the harness reports the real ones.

## 2. The CI concurrency smoke

A fast, deterministic test in the normal suite — no cluster, no 200 users — that
guards the property the load test is really about: **concurrent flag submissions
to one challenge produce exactly one solve and one correct score.** Dozens of
simultaneous correct submits for the same player and challenge, asserting a single
`Solve`, a single scoring event, and no double-award. This extends the solve-race
coverage from spec 003 (which proved two racers) to a crowd, and it fails if a
future change breaks the savepoint/unique-constraint guard under real concurrency.

## 3. The two NFR tests

**Redis is a cache, provably.** The durability NFR is really one architectural
claim: nothing of record lives only in Redis. The test seeds solves, hints and
adjustments, **flushes Redis entirely**, and asserts the scoreboard and every
score reconstruct identically from Postgres — the live board is recomputed, not
lost. This is the meaningful, deterministic half of "no data loss on restart";
Postgres's own crash durability (committed = fsync'd) is inherent and gets a
manual pod-restart step in the runbook rather than a fake in CI.

**Every admin action is audited.** A test drives a representative admin mutation
of each kind — score adjustment, challenge create/edit/state/delete, category
change, template create/delete, user approve/disable/role, instance
force-teardown, assistant purge/block — and asserts each writes an `AuditLog` row
with the actor and target. This pins `Plan.md`'s "audit logging on all admin
actions" so a new admin endpoint that forgets to log fails the test.

## 4. The runbook

`loadtest/README.md`: how to seed users, run Locust against the cluster at a given
user count, which dashboards/metrics to watch (submission latency, DB connection
count, WebSocket count, instance pod scheduling), the SLO table above as the
pass/fail line, and the **manual durability check** — restart the backend and a
datastore pod mid-load and confirm committed solves survive and the board
recovers. It is the script for the project owner's real 200-player run.

## Commit plan

1. The CI concurrency smoke and the two NFR tests (Redis-cache-only, audit
   coverage).
2. The Locust harness and the seed script.
3. The runbook, and mark Phase 1 done in `specs/README.md` / `plan.md`.

## Non-goals

- Running the real 200-player test from this session (no cluster access).
- Autoscaling or capacity tuning — the platform is a single node by design; this
  verifies it holds, it does not make it bigger.
- Load-testing the AI model itself (its throughput was already measured in 010);
  the harness exercises *our* mediation path, not the GPU box.

## Open questions

1. **SLO numbers** — the table is a proposal. Confirm or adjust the pass/fail
   targets, especially the 400 ms submission p95.
2. **Load-user count for the seed** — default 250 (a margin over 200). Fine?
