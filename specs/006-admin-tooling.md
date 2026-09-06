# Spec 006 — Admin Tooling

Status: **approved** (2026-09-06) — implementing
Phase: 1
Covers: `Plan.md` → Admin Tooling (except anti-cheat surfacing, which is 007)
Depends on: 002 (roles, audit log, event config), 003 (challenges, adjustments,
submission log), 004 (hints), 005 (boards)

## Purpose

The console an organiser actually runs the event from: watch what is happening,
notice what is broken, and fix it without a database client.

Done when an organiser can see at a glance which challenges are being solved,
which look broken, and what has been changed; and an admin can compensate a
player or a whole party for a broken challenge in one action, with a reason
attached and an audit trail that explains it afterwards.

## What already exists

This spec is more assembly than construction. Already built and needing only a
screen:

- Challenge, answer, category, artifact and hint CRUD, plus the answer dry-run (003, 004)
- Instant state changes — draft, hidden, locked, published (003)
- User approval, disabling, roles, event config (002)
- The submission log endpoint (003) and the admin scoreboard (005)
- `audit_log`, written to by everything above, with a minimal read endpoint (002)
- `score_adjustment` — the table exists and the scoreboard already includes it,
  but **nothing can create one yet**. That is the largest genuine gap.

## Non-goals

- **Anti-cheat detection (007).** This spec surfaces raw activity; 007 decides
  what is suspicious.
- **The container error feed.** `Plan.md` lists it in this dashboard, but
  container instances do not exist until 009. The dashboard is built with a slot
  for it rather than pretending.
- **Container template CRUD**, for the same reason — 009 owns it.
- Historical charts beyond the event's own timeline.

## Scoring overrides — where `Plan.md` and the scoring model disagree

`Plan.md` says "adjust a **team's** points directly". Under the model we settled
on, a party has no points of its own: its standing is an aggregate over its
members. So a literal team adjustment has nowhere to live.

**Resolution: an adjustment targets either a player or a party, and a party
adjustment belongs to the party itself** — one row with a `team_id`, no
`user_id`. The boards already sum adjustments; the party board additionally
sums those scoped to it.

This was reached in two steps, and the discarded ones are worth recording.

**Not fanning out to every member.** The first draft wrote one row per current
member. It works, but it smears a single decision across eight people's personal
scores, which is the opposite of treating it as a party-level fact.

**Not routing through the party leader either.** The proposal after that was to
apply it to the leader, as a constant the party can be adjusted through. Two
problems, both fatal:

- **The leader is not a constant.** Leadership transfers, and a departing leader
  hands off automatically (002). An adjustment attached to the person would leave
  the party when they did — precisely when the compensation still applies.
- **It inflates the leader's personal score.** Party score sums its members'
  adjustments, so routing 100 points through the leader also moves them 100
  points up the *player* board for something they did not earn.

A `team_id` on the adjustment gets the intent exactly: applied once, at party
level, unsmeared across individuals, surviving every roster and leadership change,
and leaving personal scores alone. It is also closer to `Plan.md`'s literal
"adjust a team's points directly" than either alternative.

`score_adjustment` therefore gains a nullable `team_id`, `user_id` becomes
nullable, and a `CHECK` enforces that exactly one of the two is set — an
adjustment belonging to both or to neither is meaningless, and the database is
the right place to say so.

`reason` is already required on the table and stays required.

## Broken-challenge reporting

`Plan.md` wants the dashboard to show "currently-flagged-as-broken challenges".
Something has to do the flagging, and an admin marking it is just `state =
hidden`, which already exists. The useful signal comes from players, who find out
first.

New table `challenge_report`: `challenge_id`, `user_id`, `message`,
`status` (`open` | `acknowledged` | `dismissed` | `resolved`), `resolved_by_user_id`,
`resolved_at`. One open report per player per challenge, enforced by a partial
unique index — a frustrated player clicking twice is not two problems.

Players get a "something's wrong with this challenge" action on the challenge
page, rate limited. Organisers see the queue; admins triage it.

**This is an addition to `Plan.md`'s letter, in service of its intent.** Flagged
as an open question in case you would rather flag broken challenges by hand.

## The dashboard

One screen, refreshed on a timer rather than pushed. The scoreboard needs to be
live to the second because players are watching it; an operations console does
not, and a second WebSocket channel is machinery for no gain. Ten seconds.

**Event pulse** — solves in the last 5/15/60 minutes, submissions per minute,
players active in the last 15 minutes, current event phase and time remaining.

**Challenge health**, the part that earns the screen. Per challenge: solve count,
attempt count, and the ratio between them. Three states worth surfacing loudly:

- **Nobody has solved it** despite many attempts — the answer rule is probably
  wrong. A challenge with 80 attempts and 0 solves at hour two is the single most
  valuable thing this dashboard can tell you.
- **Everyone solves it first try** — the answer probably leaked, which 007 will
  have opinions about.
- **Open broken reports** against it.

**Attention queue** — open broken reports, guests awaiting approval, challenges
still in draft after the event started, and challenges published with **no answer
rules**, which is unsolvable by construction.

**Recent activity** — the audit log, readable: actor name resolved, action in
plain words, reason shown, filterable by actor, action and time. Not raw JSON.

**Containers** — a placeholder panel that 009 fills in.

## Release scheduling

`Plan.md` asks for release schedules under CRUD. A wave is several challenges
sharing a `release_at`, so the operation that matters is bulk: select challenges,
set a release time and a pre-release state, apply. One audit entry per challenge,
sharing a batch id.

A timeline view lists what unlocks when, so an organiser can see the shape of the
multi-day event without opening each challenge.

## API surface

New endpoints only; everything else is already built.

| Method | Path | Gate | Notes |
| ------ | ---- | ---- | ----- |
| POST | `/api/admin/adjustments` | admin | `{user_id \| team_id, points, reason}` — exactly one target |
| GET | `/api/admin/adjustments` | staff | Reversals shown against their original |
| POST | `/api/admin/adjustments/{id}/reverse` | admin | Reason required |
| GET | `/api/admin/dashboard` | staff | The whole screen in one response |
| GET | `/api/admin/challenge-health` | staff | Per-challenge attempt/solve ratios |
| POST | `/api/admin/challenges/release` | admin | Bulk `release_at` + `pre_release_state` |
| GET | `/api/admin/reports` | staff | Broken-challenge queue |
| POST | `/api/admin/reports/{id}/status` | admin | Triage |
| POST | `/api/challenges/{id}/report` | play | A player reports a problem |
| GET | `/api/admin/audit-log` | staff | Extended: actor names, filters, pagination |

The dashboard is one request rather than six because it refreshes on a timer and
six parallel polls from every open console is a self-inflicted load test.

## Edge cases

- **A party's roster changes after it was adjusted.** The adjustment belongs to
  the party, so it stays put through joins, departures and leadership handovers.
  This is the whole reason it is not attached to a person.
- **A party is adjusted and then disbands.** The row survives with the
  soft-deleted party; the party is simply off the board.
- **Adjusting a party with no members.** Allowed — the party still exists and may
  be rejoined. It contributes nothing to a board it is not on.
- **Reversing an already-reversed adjustment.** Refused, with the original named.
- **An admin adjusts their own score.** Allowed but always audit-logged, and the
  dashboard marks self-adjustments, because an event runs on the organisers being
  seen to be fair. Staff are excluded from the boards anyway (005).
- **A player reports a challenge twice.** The partial unique index makes the
  second a no-op returning the existing report.
- **Reports on a hidden challenge.** Still accepted — a player may have been
  mid-attempt when it was pulled.
- **Challenge health with zero attempts.** Reported as "untouched", not as a
  divide-by-zero or a 0% success rate.
- **Dashboard with an empty event.** Renders zeroes and an empty queue, not an
  error.
- **An organiser opening a write control.** The UI hides admin-only actions, and
  the API refuses them regardless — the client is not the gate.

## Testing

- A party adjustment writes exactly one row, moves the party's board score, and
  moves **no** member's personal score — including the leader's.
- A party adjustment survives a leadership transfer and the original leader
  leaving.
- The database refuses an adjustment targeting both a user and a party, or neither.
- A reversal cancels the original exactly and leaves both rows in place.
- Adjustments cannot be deleted through any endpoint.
- `reason` is required, and reaches the audit log.
- Organizers can read every dashboard endpoint and write to none of them —
  checked per endpoint rather than assumed.
- Challenge health flags a many-attempts-no-solves challenge and reports an
  untouched one without dividing by zero.
- A duplicate report is a no-op.
- The dashboard answers with an empty database.

## Open questions

1. **Player-reported broken challenges** — an addition beyond `Plan.md`'s letter.
   Worth it, I think: players find out first, and admin-marking is already
   covered by hiding. Say if you would rather not have it.
2. **Should an admin be able to adjust their own score at all?** Currently
   allowed and flagged. The alternative is refusing outright, as with
   self-disabling and self-demotion in 002.
3. **Dashboard refresh interval** — 10 seconds proposed. Faster is possible; it
   is a single query either way.

## Commit plan

1. Migration: `challenge_report`, plus `batch_id` and `reverses_id` on `score_adjustment`
2. Adjustment service and endpoints, including reversal
3. Broken-challenge reporting: player endpoint and admin triage
4. Dashboard and challenge-health aggregation
5. Bulk release scheduling
6. Extended audit-log reading
7. Frontend: dashboard
8. Frontend: adjustments, reports triage, release timeline
