# Spec 050 — Event Metrics

Status: **approved** (2026-09-17)
Phase: 3 (Polish & Operability)
Depends on: 049 (a home in the sidebar under Operations)
Related: 007 (anti-cheat signals — deliberately a different question), the dashboard in 006

A metrics page whose single purpose is **spotting a problem early enough to fix it
mid-event**. Not observability, not a post-event report, and not anti-cheat.

## 1. The question this page answers, and the three it does not

The dashboard already answers *"is anything on fire right now?"* — a five-minute
solve pulse and a needs-attention list. That is a smoke alarm. It catches a
challenge with zero solves and 90 attempts, and nothing subtler.

This page answers the slower question: **"is anything drifting?"** A challenge
that is twice as hard as intended still produces solves, so it never trips the
alarm; it just quietly eats a day. A player who stopped playing on Tuesday
afternoon is invisible in every aggregate. Both are fixable on Tuesday and not on
Friday.

Explicitly not this page:

- **Platform observability.** No latency histograms, no queue depth, no pod
  health. For a five-day single-instance event a Prometheus/Grafana stack is not
  repaid; staff-facing platform health is one page (spec 057).
- **Anti-cheat.** Spec 007 already asks "is this player cheating?" and has its own
  page with dismissals and a review workflow. This page asks "is this player
  *stuck*?" Similar data, opposite intent, and merging them would make every
  stalled player look like a suspect.
- **Final results.** Standings and awards are the admin scoreboard (051) and the
  export (056).

## 2. Layout

One page, four bands, densest-signal first. Everything is scoped by a time-window
control (**last hour · last 4 hours · today · whole event**, defaulting to today)
except where a metric is inherently cumulative, which is marked in place.

```
┌───────────────────────────────────────────────────────────┐
│ Metrics                       [1h] [4h] (Today) [Event]   │
├───────────────────────────────────────────────────────────┤
│ ① Event pulse    solves/hr · attempt→solve · active · hints│
├───────────────────────────────────────────────────────────┤
│ ② Challenges drifting            (table, ranked by concern)│
├───────────────────────────────────────────────────────────┤
│ ③ Players stalled                (table, ranked by concern)│
├───────────────────────────────────────────────────────────┤
│ ④ Progression & economy    zone spread · levels · hint use │
└───────────────────────────────────────────────────────────┘
```

## 3. Band ① — Event pulse

Six numbers, each with its change against the previous equal-length window,
because a rate without a direction is not actionable.

| Metric | Why |
| --- | --- |
| Solves per hour | The headline. |
| **Attempt-to-solve ratio** | Wrong answers per solve, event-wide. The single best early warning: it climbs before solves fall. |
| Active players | Distinct players who submitted in the window. |
| **Participation** | Active players as a share of approved accounts. 40 active out of 200 approved is a different event from 40 out of 45. |
| Hints unlocked | The cost side of the economy. |
| First-time solvers | Players landing their first solve in the window — the on-ramp working or not. |

## 4. Band ② — Challenges drifting

A table, one row per challenge, **ranked by concern** rather than alphabetically.
Concern is a derived ordering, not a score shown to the user — the columns are
what an admin reads, the ordering is just what floats the interesting rows up.

| Column | Reads as |
| --- | --- |
| Challenge, zone, difficulty | Identity and what it claims to be. |
| Attempts / solves | Raw volume, so a 3-attempt challenge is not read as a trend. |
| **Attempt-to-solve ratio** | Effort per success. |
| **Ratio vs. its difficulty band** | The drift signal. Compared against the median ratio of every challenge sharing its difficulty label — a "very easy" challenge behaving like a "hard" one is the thing to catch. |
| **Median time-to-solve** | From first attempt by that player to their solve. Long medians with a healthy ratio means slow, not broken. |
| **Near-miss rate** | Wrong submissions within a small edit distance of a correct answer. See §4.1. |
| Hint uptake | Share of solvers who bought a hint first. |
| Abandonment | Players who attempted at least once, never solved, and have not submitted to it in over an hour. |

Filterable by zone, difficulty and state; the difficulty comparison is always
against the whole event, not the filtered set.

### 4.1 Near-miss rate is the one worth building carefully

A challenge where players repeatedly submit something *almost* right is not too
hard — it has a **format problem**. Case, whitespace, a wrapper the description
did not mention, a hyphen where players type an underscore.

Computed as: of the wrong submissions on a challenge, the share within
Levenshtein distance ≤ 2 (or differing only by case/whitespace) of any of its
correct answers. A high near-miss rate with a high attempt ratio is the clearest
"fix the answer rule, not the challenge" signal available, and it is the metric
most likely to actually save a day.

Two constraints that follow from it:

- Computed **server-side only**, never sent to the client. The wrong strings and
  their distances are as good as a hint. The page receives a rate, never an
  example.
- Computed against the same normalisation the answer checker uses, so a
  near-miss that the checker would have accepted is not counted.

## 5. Band ③ — Players stalled

Ranked by concern, aimed at "who should I go and talk to", which at a 200-person
work event is a real and useful action.

| Column | Reads as |
| --- | --- |
| Player, party | Who, and who to ask about them. |
| Solves, XP, level | Where they are. |
| **Last solve** | The stall signal. |
| **Last submission** | Distinguishes *stopped playing* from *stuck and trying*. A player with a recent submission and no recent solve is stuck on something; one with neither has left. |
| **Current wall** | The challenge they have most recently attempted without solving. The single most useful field on the page. |
| Attempts since last solve | How hard they are hitting the wall. |
| Hints used | Whether they know hints exist — a stuck player with zero hints is a different conversation. |

Three canned filters, which is how this actually gets used:

- **Stuck** — submitting, not solving, for over an hour.
- **Gone quiet** — active earlier today, nothing for two hours.
- **Never started** — approved, signed in, zero submissions all event. The
  easiest group to rescue and the easiest to never notice.

## 6. Band ④ — Progression & economy

Shape-of-the-event charts, for the "is the difficulty curve working" question.

- **Zone spread** — players per zone by furthest unlocked. Reveals a wall where
  the whole event piles up, and a zone nobody has reached.
- **Level distribution** — a histogram against the level curve's expectation at
  this point in the event. XP moved onto the challenge in spec 040, so the curve
  can drift out of tune without anything complaining; this is where that shows.
- **Hint economy** — hints unlocked per player, and the share of solves preceded
  by a hint. Hints costing points (spec 004) means an unused hint system and an
  over-used one are both problems.
- **Category health** — attempt-to-solve ratio per category, which is where "the
  Crypto zone is miserable" becomes visible as a fact rather than a hunch.

Charts follow the `dataviz` conventions and read correctly in every theme from
spec 048 — no metric encoded in colour alone.

## 7. API

One endpoint per band, so a slow band cannot block the page:

- `GET /api/admin/metrics/pulse?window=today`
- `GET /api/admin/metrics/challenges?window=…&category_id=…&difficulty=…`
- `GET /api/admin/metrics/players?window=…&filter=stuck|quiet|never_started`
- `GET /api/admin/metrics/progression?window=…`

All `Staff`. All read-only.

**Caching.** These are aggregates over the full submission history — by day five
that is on the order of 10⁵ rows, which is small for Postgres but not small
enough to recompute on every 10-second poll. Each response is cached in Redis for
60 seconds, keyed by endpoint and parameters, with the cache timestamp returned
in the payload and shown on the page. A metrics page that is a minute stale and
says so is strictly better than one that is live and costs a query storm.

**Indexes.** `submission (challenge_id, is_correct, created_at)` and
`submission (user_id, created_at)` — both these access patterns are new, and the
near-miss computation in particular scans wrong answers per challenge.

## 8. Testing

- Every metric has a fixture-driven test asserting the arithmetic, including the
  empty case (no submissions must yield zeroes, not a division error).
- Attempt-to-solve is per window, and a solve outside the window does not count.
- The difficulty-band comparison uses the median of the whole event, not the
  filtered subset.
- Near-miss counts a case-only and whitespace-only difference, counts an
  edit-distance-2 difference, does not count an unrelated string, and **does not
  count a submission the answer checker would have accepted**.
- **No answer value or wrong-submission string appears in any metrics response.**
  This gets its own test; it is the one security property of the page.
- "Stuck" and "gone quiet" separate correctly for a player with a recent
  submission and no recent solve.
- "Never started" excludes players still pending approval.
- A cached response is served on a second call within the window and the payload
  reports the cache timestamp.
- Challenge and player bands issue a constant number of queries, not one per row.
- Staff may read; a player may not.

## 9. What this spec does not do

- **No alerting.** No thresholds, no notifications, no "tell me when a challenge
  drifts." The page is looked at, not subscribed to. Thresholds also need a
  baseline nobody has yet — revisit after the event with real numbers.
- **No per-player drill-down.** Clicking a player goes to the roster's player
  detail (spec 052), which is where per-player history belongs; duplicating it
  here would be a second thing to keep correct.
- **No historical retention or comparison across events.** There is one event.

## 10. Open questions

Signed off 2026-09-17. Each recommendation below was accepted as written
unless a **Decision** line says otherwise.

1. **Is "attempt-to-solve ratio vs. difficulty band" meaningful with 242
   challenges spread over ~11 per zone?** The bands (very easy → hard) have enough
   members, but early in the event most have too few attempts to compare. Recommend
   suppressing the comparison below a minimum attempt count and showing "not enough
   data" rather than a misleading multiple.
2. **Should band ③ respect the time window at all?** "Stalled" is inherently about
   the recent past, and a whole-event window makes the filters meaningless.
   Recommend band ③ ignores the window control and uses its own fixed thresholds,
   with the control visibly not applying to it.
