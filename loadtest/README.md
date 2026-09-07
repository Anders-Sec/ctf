# Load testing & NFR runbook (spec 012)

The automated half of the non-functional requirements lives in the test suite
(`backend/tests/test_nfr.py`): the concurrent-submission smoke, the
"Redis is a cache" durability proof, and the audit-coverage check. This directory
is the other half — the real 200+ player load test, which runs against the live
cluster and is executed by hand.

## What this proves

Phase 1's Definition of Done: *"Platform sustains a 200+ player load test across
the core flows without data loss or crash."* Plus `Plan.md`'s call to load-test
**flag submission** and **container provisioning** specifically.

## Prerequisites

1. A target with the event **running** (start/end window open) and a handful of
   **published challenges** with answers — the harness reads the real board.
2. Session seeds. From the backend project, against the target's database:
   ```bash
   cd backend
   uv run python ../loadtest/seed.py --count 250 --out ../loadtest/sessions.csv
   ```
   `sessions.csv` holds real session tokens — it is gitignored; treat it like a
   secret and delete it after.
3. Locust in its own environment:
   ```bash
   cd loadtest
   python -m venv .venv && . .venv/bin/activate
   pip install -r requirements.txt
   ```

## Core load run

```bash
cd loadtest
CTF_SESSIONS=sessions.csv locust -f locustfile.py --host https://ctf-nm.org \
    --users 200 --spawn-rate 20 --run-time 15m --headless --csv=run
```

Ramp to 200 users over ~10s, hold 15 minutes. `run_stats.csv` and the console
give the latencies. Add `--users 300` to find the ceiling.

### Pass/fail SLOs (confirm/adjust with the project owner)

| Flow | Target |
| --- | --- |
| `challenges:submit` | p95 < 400 ms, **zero 5xx**, a 429 under burst is fine |
| `challenges:list`, `scoreboard:players` | p95 < 250 ms |
| Any endpoint | no 5xx, no rising error rate as users climb |

The submission path is the one to watch — it does the most work (resolver, rate
limiter, solve insert, scoreboard invalidation). A 429 rate is expected and
healthy; a 5xx is not.

## Scoreboard WebSocket load

Each viewer holds one long-lived connection at `/api/ws/scoreboard`. Locust does
not model these well, so hold a batch open separately while the core run drives
solves, and watch that they all receive updates and none are dropped:

```bash
# a quick holder — N connections, printing each board push
python - <<'PY'
import asyncio, websockets
async def hold(i):
    async with websockets.connect("wss://ctf-nm.org/api/ws/scoreboard") as ws:
        async for _ in ws:  # blocks, receiving pushes
            pass
asyncio.run(asyncio.wait([hold(i) for i in range(200)]))
PY
```

Watch: connection count holds steady, memory on the backend pods is flat, and a
solve during the run reaches every socket within a couple of seconds.

## Container provisioning (the second named bottleneck)

`Plan.md` singles this out. With `INSTANCES_ENABLED=true` and a
`container_template` pointing at a real image (e.g. `ctf-demo`):

- Ramp concurrent launches across **many distinct owners** up toward the
  namespace `ResourceQuota` (80 pods). Each owner is capped at 2, so use enough
  seeded users.
- Confirm: launches return `pending` in well under a second (readiness follows
  the pod, not the request); pod scheduling keeps up; the reconciler reaps
  expired instances; and hitting the quota returns a clean *"no capacity, try
  again"* rather than a 5xx.
- Watch gVisor pod start latency and node memory — gVisor adds ~15–50 Mi per
  sandbox, so heavy images may need a raised per-template memory limit.

## The durability check (manual)

The suite proves Redis is disposable. This proves Postgres is the source of
truth across a real restart:

1. Under load, record a few solves and note the scoreboard.
2. `kubectl -n ctf rollout restart deploy/ctf-backend` — and separately restart
   the Redis pod.
3. Confirm: the recorded solves and scores are unchanged, the board recovers
   within a recompute, and no committed data is lost. (Redis losing its cache is
   fine; a solve disappearing is not.)

## Cleanup

```bash
cd backend
uv run python ../loadtest/seed.py --purge   # removes every loadtest+ user
rm ../loadtest/sessions.csv
```

## Recording the result

Keep the `run_stats.csv`, the observed p95s against the SLO table, the WS and
provisioning observations, and the durability-check outcome. That record is the
evidence for the Definition-of-Done load line.
