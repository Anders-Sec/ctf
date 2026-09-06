# Spec 005 — Real-Time Scoreboard

Status: **draft — awaiting sign-off**
Phase: 1
Covers: `Plan.md` → Real-Time Scoreboard
Depends on: 002 (identity, parties), 003 (solves, values), 004 (hint costs)

## Purpose

Two live boards — players and parties — pushed over WebSocket rather than polled,
backed by Redis, with Postgres remaining the source of truth.

Done when a player can watch both boards update as the field solves, a party of
one and a party of eight have the same attainable maximum, and a restart loses
nothing but the cache.

## Non-goals

- XP, levels and skill breakdowns. Phase 2. The aggregate shape here is built so
  they layer on as extra derived columns rather than a rewrite.
- Anti-cheat surfacing (007), admin dashboards (006).
- Historical score graphs. Nice, and not Phase 1.

## Party scoring — the decision this spec turns on

**A party's score is the sum of the current value of each *distinct* challenge
solved by any current member, minus the cost of each *distinct* hint unlocked by
any current member.**

Both halves are a union, counted once. The consequences are exactly what you
asked for:

- **A party of one and a party of eight have the same ceiling** — the sum of every
  challenge's value. Eight people splitting fifty challenges score what one
  person solving all fifty would.
- **Team size buys speed and coverage, never a higher maximum.** The advantage of
  a party is finishing more of the board in the time available, not scoring more
  for the same work.
- **A second member solving something already solved adds nothing** to the party.
  Duplicated effort is wasted effort, which is the correct signal.

### Why the hint half has to be a union too

Without it there is a hole: hint costs are personal, so a party's score would be
untouched by them. A party could buy every hint on the board, solve everything,
and still hit the ceiling, while a solo player doing the same pays for every
hint out of their own total. Charging the party once per distinct hint closes
that and keeps the ceiling identical — and it preserves a real teamwork
advantage, since eight people can share one purchased hint between them.

### Rejected alternatives, and why

| Model | Why not |
| ----- | ------- |
| **Average of member scores** | Your instinct about averages, followed through, ends badly: it makes a weak member a liability and creates a direct incentive to kick people to raise the average. At a work event that is a bad thing to build. |
| **Sum of member scores** | The thing you ruled out — eight members, eight times the ceiling. |
| **Best-N members** | Same kicking incentive, plus an arbitrary N. |
| **Union, valued at first-solve time** | Freezes each challenge at whatever it was worth when the party first got it. Defensible, but inconsistent with everything else, which is live. |

### Two consequences worth naming

**Manual score adjustments are summed, not unioned**, and are the one thing that
can push a party past the nominal ceiling. That is correct: if a broken challenge
cost eight people an hour, compensating all eight is the point, and it is a
deliberate admin action with a reason and an audit trail.

**Late recruitment is a real strategy.** A joiner brings their solves with them,
which spec 002 established deliberately. So a party that recruits a strong player
on the final afternoon gains everything that player has solved. Given open
rosters and portable scores this follows unavoidably; the alternative — counting
only solves earned while in the party — would break the rule you already chose.
`solve.team_id_at_solve` records the party at solve time, so 007 can surface a
late roster change if it ever becomes contentious. Flagged, not fixed.

**Pair this with `decay_basis = teams`** on challenges where you care: on the
player basis, eight teammates solving the same thing decay it eight times for
everyone else while gaining their own party nothing.

## Player scoring

Unchanged from 003/004: `sum(value of solved challenges) + adjustments − hint
costs`. Both boards are computed from the same primitives.

## Ordering and ties

Both boards order by score descending, then by **the time the entry last
gained points**, ascending — whoever got there first is ahead. A party that
reached 3,000 at noon outranks one that reached 3,000 at three. Alphabetical is
the final fallback so ordering is total and stable across refreshes.

Negative scores are shown as they are.

## Projection and push

Dynamic scoring makes this less trivial than it looks: **one solve changes the
value of that challenge for everyone who has solved it**, so a single event can
move hundreds of scores. Incremental updates are therefore not worth attempting.

- A scoring event (solve, hint unlock, adjustment, roster change) sets a dirty
  flag in Redis.
- A recompute runs **debounced, at most once per second**, under a short Redis
  lock so only one pod does the work. A full recompute at this scale is one
  grouped query over a few thousand rows — tens of milliseconds, far cheaper
  than reasoning about deltas.
- Results are written to Redis (a sorted set per board plus a rendered payload)
  and a notification published on a channel.
- Every pod subscribes and pushes the payload to its own connected clients.

Redis holds only the cache and the pub/sub bus. Losing it costs a rebuild on the
next request, never data — `Plan.md`'s non-functional requirement.

## API surface

| Method | Path | Gate | Notes |
| ------ | ---- | ---- | ----- |
| GET | `/api/scoreboard/players` | scoreboard | Ranked players, paginated |
| GET | `/api/scoreboard/teams` | scoreboard | Ranked parties, with member count and per-member contribution |
| GET | `/api/scoreboard/me` | play | Own rank and party rank, for a compact header |
| WS | `/api/ws/scoreboard` | scoreboard | Pushes both boards on change |
| GET | `/api/admin/scoreboard` | staff | Adds raw solve timestamps and tie-break detail |

`capabilities.view_scoreboard` from spec 002 already gates this: approved
accounts once the event has started, staff always.

The WebSocket authenticates from the session cookie at handshake. It sends the
current boards on connect, then changes; a client that misses messages can
reconnect and be whole again, because every message is a complete board rather
than a diff.

## Edge cases

- **A player leaves a party.** Their unique solves leave with them. Challenges a
  teammate also solved stay. Recomputes on the next tick.
- **A party disbands.** Drops off the board; its members keep their own scores.
- **Two parties tie exactly.** Broken by time-of-last-gain, then name.
- **Everyone at zero before the first solve.** Ordered by name, not randomly.
- **A challenge is hidden mid-event.** Existing solves keep scoring, per 003.
- **Redis is down.** Boards fall back to computing from Postgres per request, and
  WebSocket pushes stop until it returns. Degraded, not broken.
- **A thousand messages a second.** Prevented by the debounce; the board updates
  at most once per second no matter how fast flags land.
- **A pre-event visitor.** `view_scoreboard` is false, so the board is not
  readable before the doors open.

## Testing

- The ceiling property, stated as a test: a solo party solving everything and an
  eight-person party splitting the same challenges score **identically**.
- A duplicate solve inside a party adds nothing.
- A duplicate hint unlock inside a party charges once.
- A leaver removes only their unique contribution.
- Tie-breaking by first-to-reach, and a stable order at zero.
- WebSocket: connect receives a board, a solve elsewhere pushes an update, and
  an unauthenticated handshake is refused.
- Debounce: twenty solves in a burst produce at most a couple of recomputes.
- Redis unavailable: endpoints still answer from Postgres.

## Commit plan

1. Party and player aggregate queries, with the union semantics
2. Redis projection, debounce and cache
3. REST endpoints
4. WebSocket push
5. Frontend: both boards, live
