# Spec 034 — The System AI admin console

Status: **built** — 985 backend tests, 223 frontend tests
Phase: 1
Covers: the AI operations surface deferred by spec 033 — health, guardrail
signals, and session drill-down
Depends on: 010 (health endpoint, message rows), 011 (findings, retention,
per-player block), 033 (the ladder, `trace`, `ladder_level`), 006 (console
conventions), 007 (review tone)
**Amends** 011 — see "The privacy decision"

## Purpose

The System AI is now the most complicated thing in the platform: a six-rung
ladder, two guardrail layers, an external model host on someone else's uptime,
and up to five upstream calls per turn. The admin surface for all of it is one
page listing guardrail findings.

This spec makes it operable during an event: whether the AI is healthy, what the
guardrails are catching, and who is talking to it right now.

Done when a staff member can answer three questions without reading logs — *is
it up?*, *what is it catching?*, and *what is this player doing?* — and can act
on the answers without a redeploy.

## What exists today, and what was never built

Worth stating plainly, because most of this spec is **surfacing endpoints that
already work**:

| Endpoint | State |
| --- | --- |
| `GET /api/admin/assistant/findings` | Built, and the only thing with a UI |
| `GET /api/admin/assistant/health` | Built in 010. **No consumer.** 010 said it would appear on the 006 dashboard; it never did |
| `POST /api/admin/assistant/purge` | Built in 011. **No UI** — retention can only be run by curl |
| `POST /api/admin/users/{id}/assistant-block` | Built in 011. **No UI** — the per-player kill switch is unreachable |

So the honest summary: the backend is mostly there, nothing shows it, and there
are no aggregate metrics at all.

---

## Part 1 — Health

### The per-replica problem, first

`ai_client` keeps its breaker, in-flight count and recent latencies **in process
memory**, and the deployment runs **two replicas**. `GET /admin/assistant/health`
therefore reports whichever replica answered the request, and a refresh can
legitimately show different numbers.

This is not a bug to paper over — it is a fact a reader of the dashboard must
know, or they will chase a breaker that "keeps closing itself". Three options:

- **(a) Label it.** The panel says which replica answered and that the figures
  are per-replica. Cheapest, honest, no backend change.
- **(b) Aggregate.** Move breaker and in-flight state to Redis so every replica
  shares one view. Correct, and a real change to the hot path in `ai_client`.
- **(c) Fan out.** Query all replicas and merge. Needs a headless Service and
  pod-level addressing; the most machinery for the least gain.

**Proposed: (a) now**, with (b) noted as the fix if the breaker ever matters
operationally. A wrong number nobody can interpret is worse than a right number
labelled "this replica".

### What the panel shows

**Live, from `ai_client.health()`** — reachability, model name, breaker state and
cooldown, consecutive failures, in-flight count, recent average latency.

**Aggregated, from `assistant_message`** — the same 5/15/60-minute windows the
event console already uses (spec 006), so the two pages read alike:

| Metric | Why it earns a tile |
| --- | --- |
| Turns per window | The load figure every other number is relative to |
| Active sessions (15m) | How many people are actually using it |
| Median and p95 latency | An average hides the tail, and the tail is what players feel |
| Error rate, broken down by reason | `timeout` and `breaker_open` mean different things to do |
| Deflection rate | A sudden climb means a filter is misfiring on ordinary play |
| Upstream calls per turn | Level 5 costs five. This is the capacity number spec 033 could not fix and left visible |

**Ladder panel**, which is the part that has no equivalent anywhere:

- Turns per rung, so staff can see where players actually are.
- **Players at each rung**, from solve counts — the progression view for the
  event.
- Gate fire rates per rung, from `trace`: how often the router, the warden, the
  blacklist and the output regex actually stop something.
- Solves and decoy redactions per rung. **Decoys must stay near zero**; a climb
  means the model has started inventing flags and players are about to submit
  them.

### Actions on the page

The three unreachable endpoints get controls: the **retention purge** (with the
window and a count of what it would remove), the **event-wide toggle** already on
the event settings page, cross-linked rather than duplicated, and **per-player
block** from a session row (Part 3).

---

## Part 2 — Guardrail signals

The existing list is a flat, newest-first feed. It works for twenty findings and
not for two thousand.

### What changes

- **A summary strip**: counts by rule over the last hour and the whole event, so
  a spike is visible without scrolling. This is the "better signals" ask — the
  useful signal is usually *rate of change of one rule*, not any single row.
- **Filters the API already supports but the UI does not**: severity, and
  a player filter. Plus a time window.
- **Acknowledgement.** Findings have no reviewed/unreviewed state, so staff
  cannot work through a backlog — every refresh shows the same rows and there is
  no way to say "seen, fine". Spec 007 solved the same problem for signals with
  dismissals; this borrows the shape. `assistant_finding.acknowledged_at` and
  `acknowledged_by_user_id`, with an "unreviewed only" default.
- **Rule labels updated.** `RULE_LABELS` in the frontend still names the four
  Layer A rules that spec 033 deleted. They will never appear again; the labels
  should say so rather than sitting there implying the filter still exists.

### What does not change

The tone. Spec 007 and 011 both insist a flag is **not a verdict**, and with the
ladder that is more true, not less: every player is now *supposed* to attack the
AI. The copy stays "worth a glance", never "someone did something wrong".

---

## Part 3 — Sessions

### The privacy decision (settled)

Spec 011 ruled out a general transcript browser:

> Flagged exchanges and their immediate context only — **not a general transcript
> browser**. This is a work event and these are colleagues; their chat logs are
> not staff entertainment.

**That decision is reversed, on the project owner's direction.** Transcripts are
fully readable by admins. Two things changed since 011: the assistant is now a
*challenge*, so most of a transcript is someone attacking a puzzle rather than
asking for private help; and debugging the ladder mid-event needs transcripts,
because the flagged-exchange view shows only what a filter already caught, which
is exactly the wrong sample when a rung stops working.

The conversations are also **source material for the end-of-event report** on
trends and learning opportunities, which is a stated purpose rather than an
incidental use.

### What this obliges us to do

011's reasoning was not only about taste; it rested on players not expecting to be
read. That expectation now has to be corrected, and the decision rests on players
knowing. **The chat panel says so, in one line**, rather than relying on a
briefing everyone half-hears: the System AI's conversations are visible to
organisers and may be quoted in the post-event write-up.

This is cheap, it is the thing that makes the decision sound, and it is the one
part of this section that is not optional. The 200 players are named employees
signed in through Entra; telling them their game chat is readable costs a
sentence and removes any surprise later.

### The shape

1. **The session list** — display name, rung, turns, last activity, finding
   count, whether currently blocked. Answers most operational questions without
   opening anything.
2. **The transcript** — every turn, in full, for **admins**. Not organisers:
   `Staff` covers people who need read-only event visibility and nothing more,
   and the role split already exists.
3. **A light audit row** when a transcript is opened — who, whose, when. Reusing
   `record_audit`, which is two lines at the call site. Deliberately not built
   out further: no per-message tracking, no read receipts, no reporting on it.
   It is there so the question "who looked at this" has an answer, not to police
   anybody.

### Defining "open"

A session with a message in the last **30 minutes**, shown by default; the list
can widen to the whole event. There is no login-session concept here — one
rolling conversation per player — so "open" means recently active and nothing
more. Worth naming, because "session" implies a lifecycle this does not have.

### What a transcript shows

The turns, in order, with their rung, gate `trace`, latency and error. Deflected
turns show **both** what the player saw and what was withheld — that is the whole
point of `original_content`.

**`reasoning_content` is included**, for admins, on this page. It is genuine
troubleshooting material and spec 010 stored it for exactly this purpose: it is
what makes an odd answer explainable. One consequence to be clear-eyed about —
on the ladder the scratchpad routinely contains the flag the model was
protecting, so this screen will show live flag values to an admin who scrolls.
That is acceptable because admins can read the answers table anyway; it is
recorded here so nobody is surprised by it.

It stays off **every other response model**, which is the 010 guarantee this
relaxes in exactly one place and nowhere else.

---

## Data model

**New:**
- `assistant_finding.acknowledged_at`, `acknowledged_by_user_id` — the backlog
  state findings have never had.

**Indexes** — the aggregates below scan `assistant_message` by time, and it has
only a `(conversation_id, sequence)` index today:
- `ix_assistant_message_created` on `created_at`.
- A GIN index on `trace`, for the per-gate counts.

Both matter more than they look: a multi-day event accumulates tens of thousands
of message rows, and a dashboard on a 10-second refresh that sequential-scans
them twice per load is a self-inflicted outage.

**No rollup table.** Aggregating on read is simple and correct at this scale;
a metrics pipeline for a three-day event would be building the wrong thing.

## API surface

| Method | Path | Gate | Notes |
| --- | --- | --- | --- |
| GET | `/api/admin/assistant/health` | Staff | Unchanged |
| GET | `/api/admin/assistant/metrics` | Staff | **New.** Windows, latency, errors, per-rung |
| GET | `/api/admin/assistant/findings` | Staff | Gains `rule`, `since`, `user_id`, `unreviewed` |
| POST | `/api/admin/assistant/findings/{id}/acknowledge` | Staff | **New** |
| GET | `/api/admin/assistant/sessions` | Staff | **New.** Metadata only |
| GET | `/api/admin/assistant/sessions/{user_id}` | **Admin** | **New.** The transcript. Audited |
| POST | `/api/admin/assistant/purge` | Admin | Unchanged; gains a UI |
| POST | `/api/admin/users/{id}/assistant-block` | Admin | Unchanged; gains a UI |

## Frontend

One page with three sections, replacing the current findings-only page:
**Health**, **Flags**, **Sessions**. The nav label "AI flags" becomes
**"System AI"**, since flags are now a third of what it does.

Refreshed on the same 10-second timer as the event console, and only while the
Health section is on screen — a dashboard nobody is looking at should not be
polling a model host every ten seconds from two replicas.

## Edge cases

- **The model is down.** The health panel is the one thing that must still render;
  every metric below it comes from the database and is unaffected.
- **A purged conversation.** Its findings survive with `message_id` null (011) and
  its session disappears. The transcript view says the conversation was purged
  rather than 404ing.
- **A player with no conversation.** Absent from the list rather than shown empty.
- **Two replicas disagree.** Covered above; labelled, not hidden.
- **An enormous transcript.** Paginated from the newest end.
- **A finding whose message is gone.** Already handled by `list_findings`; the
  acknowledgement still applies to the finding.
- **Staff testing.** Still excluded by default, as 011 decided.
- **Zero traffic.** Empty states say "nothing yet", not "0.0%" everywhere.
- **A turn with no reasoning.** The model does not always return a scratchpad;
  the section is absent rather than showing an empty box.

## Testing

- Metrics aggregate correctly over each window, and exclude staff turns.
- Per-rung counts read `trace` correctly, including a turn with several gates.
- Latency percentiles are right on a known set, including the single-row case.
- A finding can be acknowledged; the default filter hides it afterwards.
- The session list contains no message content.
- Opening a transcript writes an audit row naming both people.
- An **organiser** is refused the transcript endpoint; an admin is not.
- `reasoning_content` appears on the admin transcript endpoint **and on no other
  response** — asserted against the player chat endpoints specifically, since
  that is the 010 guarantee this spec relaxes in one place and must not leak
  anywhere else.
- The chat panel carries the line telling players their conversation is readable.
- A purged conversation's transcript view degrades rather than erroring.
- Health renders with the model unreachable.

## Commit plan

1. Migration: acknowledgement columns, the two indexes
2. The metrics service and endpoint, with its aggregation tests
3. Findings: new filters, acknowledgement
4. Sessions: the list, and the transcript endpoint with its audit row
5. Frontend: the three-section page, replacing the findings page
6. The unreachable controls — purge, per-player block — given a UI, and the
   player-facing line on the chat panel

## What changed during implementation

**`upstream_calls` had to be persisted.** The spec's data model listed only the
acknowledgement columns and the two indexes, but the "calls per turn" tile had
nothing to read: the ladder computed the count and threw it away. A column on
`assistant_message`, populated from `LadderReply.calls`.

**The trace aggregation needs a `jsonb_typeof` guard.** SQLAlchemy writes a
Python `None` into a JSONB column as JSON `null`, not SQL NULL — so an
`IS NOT NULL` filter passes it through and `jsonb_array_elements_text` fails with
"cannot extract elements from a scalar". Filtering on
`jsonb_typeof(trace) = 'array'` is correct regardless of how the null was
written, including for rows already in the database.

**`moss` was not a real colour token.** The reachable badge used one; it would
have rendered with no background at all. Swapped for `stone`, which exists.

**The old page's tests all assumed a single view.** The console opens on Health,
so they were rewritten to navigate — and the four Layer A rule labels now say
"(retired rule)" rather than sitting in the list implying that filter still
exists.

## Decisions

1. **Transcripts are fully readable by admins** (Part 3). It is a troubleshooting
   tool and the source for the post-event report. Organisers are not included.
2. **A light audit row only** — who opened whose, when. Not built out further.
3. **`reasoning_content` is shown to admins** on this page, and nowhere else.
4. **Players are told**, in one line on the chat panel, that the conversation is
   readable and may be quoted afterwards. This is what makes 1 sound.

## Resolved in the build

1. **Acknowledgement is per finding.** Simpler, and per-player can be layered on
   later if the volume bites.
2. **The ladder progression view lives here**, because it is read alongside the
   gate-fire rates it explains rather than beside ordinary solve statistics.
3. **Tone: calm for the ladder, weight for safety.** Every player is now meant to
   attack the AI, so that noise is background; safety findings get a coloured
   border, because those are the ones that actually want a human.
