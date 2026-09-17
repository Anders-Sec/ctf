# Spec 057 — Platform Health

Status: **approved** (2026-09-17)
Phase: 3 (Polish & Operability)
Depends on: 049 (sidebar placement)
Related: 034 (AI health, which this links to rather than duplicates)

One page answering "is the platform itself unwell, or is it the event?" — the
first question when players say the site is slow, and currently one the admin
cannot answer from inside the app.

## 1. Scope, and why this is not observability

`Plan.md` rules out a Prometheus/Grafana stack for a five-day single-instance
event. This page is the thing that ruling-out implies: **a single screen, read by
one person, when something feels wrong.** Not dashboards, not time series, not
alerting rules.

The bar it has to clear is low and specific: when a player says "it's broken",
the admin should be able to tell within ten seconds whether the problem is the
platform, one challenge, or that one player. Today there is nothing to look at.

## 2. What exists

- [`/health`](../backend/app/api/routes/health.py) — liveness, deliberately
  checks nothing, so a database blip cannot restart every pod mid-event.
- `/health/ready` — readiness: Postgres and Redis, returning 503 when degraded.
  Kept cheap and container-local on purpose.
- `/version` — version and environment.
- [`StatusPage.tsx`](../frontend/src/routes/StatusPage.tsx) — the public,
  unauthenticated status page.
- Spec 034 built AI health and guardrail signals into the System AI console.

Everything here is either public-facing or per-pod. There is no staff view that
puts them together, and several dependencies that can fail are represented
nowhere: the model host, the container orchestrator, the mail relay, and the
WebSocket fan-out.

## 3. The page — `/admin/health`

Under Operations. One screen, no navigation within it.

```
┌───────────────────────────────────────────────────────────┐
│ Platform Health                    checked 14:31:02  [↻]  │
├───────────────────────────────────────────────────────────┤
│ ● Postgres      ok     6ms                                │
│ ● Redis         ok     2ms                                │
│ ● Model host    ok    340ms   →  System AI                │
│ ● Orchestrator  ok     22ms   →  Live Instances           │
│ ● Mail relay    ok            →  Email Delivery           │
│ ● Scoreboard    ok    fresh 3s ago                        │
├───────────────────────────────────────────────────────────┤
│ Connections   scoreboard 47 · notifications 51            │
│ Build         v1.9.2 · production · up 2d 4h              │
│ Load          142 req/min · p95 180ms · 0 5xx in 15m      │
└───────────────────────────────────────────────────────────┘
```

**Dependency checks**, each a state (`ok` / `degraded` / `down` / `not
configured`) and a round-trip time:

| Check | How |
| --- | --- |
| Postgres | `SELECT 1`, as readiness does. |
| Redis | `PING`. |
| **Model host** | The AI client's health call from spec 034. Slow is the interesting state here — a model host at 8 seconds is not down, but every player's chat feels broken. |
| **Orchestrator** | Kubernetes API reachability for the instances namespace. Reports `not configured` when `INSTANCES_ENABLED` is off, rather than red — off is a valid state and a red light for a deliberate setting trains you to ignore red lights. |
| **Mail relay** | Derived from spec 055's recent failure rate, not a live SMTP connection. Probing the relay on every page load is a good way to get rate-limited by Proton. |
| **Scoreboard cache** | How long since the Redis scoreboard projection was refreshed. A stale projection is the failure that looks exactly like "the site is frozen" to players. |

Each check with a related page links to it, because the next action after a red
light is always to go and look at that thing.

**Connections** — current WebSocket subscriber counts for the scoreboard and
notification sockets. These are the closest thing to a live "how many people are
actually connected" number, and a sudden drop is a real signal.

**Build** — version, environment and process uptime. Uptime answers "did
something restart?", which is the second question after every unexplained
weirdness.

**Load** — requests per minute, p95 latency and 5xx count over the last 15
minutes, from in-process counters. See §4.

## 4. In-process counters, and their honest limits

Load figures come from counters held in the application process: a rolling
15-minute window of request count, a latency reservoir, and a 5xx count.

Two things this means, both of which the page states rather than hides:

- **They reset when the process restarts.** Which is itself informative, and the
  uptime figure beside them makes it legible.
- **They are per-pod.** With more than one replica, the page reports the pod that
  served the request. The page says which pod it is rather than implying a
  cluster-wide view. Aggregating across replicas is what a metrics stack is for,
  and the decision not to run one is upstream of this page.

This is the right trade for the event. It is not the right trade for a permanent
platform, and that is worth writing down here so nobody later mistakes this page
for monitoring.

## 5. Refresh

Polled every 15 seconds while the page is open, with a manual refresh. The checks
run server-side in one request and in parallel, with a short timeout each
(2 seconds) so one hanging dependency does not make the health page itself hang —
a health page that times out is worse than no health page. A check that times out
reports `down` with the timeout as its reason.

**The page is not polled when it is not open.** No background health sweep, no
stored history. This is a screen you look at, not a system that watches.

## 6. API

- `GET /api/admin/health` — every check, connections, build, load. `Staff`.

One endpoint, because the page is one screen and a partial render of a health
page is a misleading health page.

The existing `/health` and `/health/ready` are **untouched**. They are Kubernetes
probes with deliberate properties (liveness checks nothing; readiness stays
cheap and container-local), and this page must not become a reason to make them
expensive. Spec `Keep readiness cheap, and local to the container` is a decision
already taken, and this spec inherits it.

## 7. Testing

- Each check reports `ok` against a working dependency and `down` against a
  broken one.
- A check that exceeds its timeout reports `down` with a timeout reason, and the
  overall response still returns within its own budget.
- The orchestrator reports `not configured` — not `down` — when instances are
  disabled.
- Mail relay state derives from spec 055's rows and makes no SMTP connection,
  asserted by the absence of a connection attempt.
- Scoreboard freshness reflects the actual last refresh time of the Redis
  projection.
- Checks run in parallel: the total is bounded by the slowest, not the sum.
- 5xx and latency counters reflect requests served, and reset on restart.
- `/health` and `/health/ready` are byte-for-byte unchanged — the existing probe
  tests pass untouched.
- Staff may read; a player gets 403.

## 8. Open questions

Signed off 2026-09-17. Each recommendation below was accepted as written
unless a **Decision** line says otherwise.

1. **Should this page show anything about the cluster itself** — node pressure,
   pod restarts, the instances namespace's resource quota? It is genuinely useful
   during the container-heavy zones, and it is also the boundary `CLAUDE.md` draws:
   the cluster is owned by the platform session. Recommend staying on our side of
   it — report whether *we* can reach the orchestrator, not how the cluster is
   feeling — and raise quota visibility with the platform session separately if it
   is wanted.
2. **Is a WebSocket connection count actually obtainable cheaply?** The scoreboard
   broadcaster holds its subscribers in-process, so per-pod it is a length. If it
   turns out to need Redis bookkeeping to be meaningful across replicas, recommend
   dropping the number rather than building the bookkeeping — it is a nice-to-have
   on a page whose other rows carry the weight.
