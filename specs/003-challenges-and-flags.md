# Spec 003 — Challenges, Answers & Dynamic Scoring

Status: **draft (revision 2) — awaiting sign-off**
Phase: 1
Covers: `Plan.md` → Challenge & Flag System (except hints, which are spec 004)
Depends on: 001 (skeleton), 002 (identity, the `play` gate, audit log)

## Purpose

The game itself: challenges to attempt, answers to submit, and points that decay as
more people solve. Every gameplay action added here sits behind the `require_play`
gate from spec 002, so an unapproved guest or a pre-event visitor cannot touch any
of it.

Done when an admin can create a challenge with one or more answer rules and a
release schedule, a player can browse the challenges they are allowed to see and
submit an answer, a correct submission records a solve worth the challenge's
current value, every attempt is logged, and brute force is stopped by a
per-player rate limit.

## Non-goals

- **Hints** (004) — the hint tables reference challenges, so they come next.
- **The scoreboard** (005). This spec produces the raw material; 005 aggregates
  and caches it. `GET /api/me/score` exists here only so a player can see their own.
- **Container-backed challenges** (008/009). `container_template_id` is added now
  as a nullable column so 009 needs no schema change; nothing reads it yet.
- **The full scoring model.** Modifiers, XP and the rest are yours to design
  later. This spec ships a working, configurable decay curve with a floor, built
  so that additional modifiers layer on top rather than replace it.
- **Admin UI** (006), beyond a minimal challenge editor without which the event
  cannot be set up at all.
- **Anti-cheat detection** (007). This records the evidence; 007 interprets it.

## Decisions taken (revision 2)

Superseding the first draft after review:

- **Answers are stored in plaintext**, not hashed. Regex and computed answers are
  a core requirement and a primary reason for building this platform rather than
  using CTFd; hashing forecloses them. The database is not reachable by players,
  and the residual risk of an insider dumping it is accepted as an HR matter
  rather than a platform one.
- **Answer matching is pluggable**, with several match types out of the box and
  room for more. Where a choice exists, the platform offers the wider option.
- **Decay can be driven by distinct players *or* distinct teams**, configurable
  per challenge with a global default.
- **Visibility has three player-facing tiers**: hidden, locked, published.
- **`max_attempts` is off by default**, available per challenge, and shown plainly
  to the player when it is set.
- Rate limiting is the primary brute-force defence.

## Data model

### `category`

`name` (citext, unique), `slug`, `display_order`, `description`.

A table rather than a string column: Phase 2 ties stat blocks to categories, and
attaching that to free text later means a migration that first has to invent the
missing rows.

### `challenge`

| Column | Type | Notes |
| ------ | ---- | ----- |
| `title` | text | |
| `slug` | citext, unique | Stable player-facing identifier |
| `category_id` | FK `category` | |
| `body` | text | Markdown, rendered client-side |
| `difficulty` | enum `easy` \| `medium` \| `hard` \| `insane` | Display now; XP weighting in Phase 2 |
| `state` | enum `draft` \| `hidden` \| `locked` \| `published` | See "Visibility" |
| `release_at` | timestamptz, nullable | When the challenge opens up |
| `pre_release_state` | enum `hidden` \| `locked` | What players see before `release_at`. Default `hidden` |
| `initial_points` | int | Value at zero solves |
| `minimum_points` | int, default 100 | The floor, before later modifiers |
| `decay_threshold` | int | Solves at which the floor is reached |
| `scoring` | enum `dynamic` \| `static` | Static pins the value at `initial_points` |
| `decay_basis` | enum `players` \| `teams` | Whose solves drive the curve. Default configurable globally |
| `max_attempts` | int, nullable | Null (default) means unlimited, still rate limited |
| `container_template_id` | uuid, nullable | Reserved for spec 009 |
| `author_user_id` | FK `user`, nullable | Who to ask when it breaks |

`state` is an enum rather than a boolean because "not written yet" (`draft`),
"players see nothing" (`hidden`), "players see it exists" (`locked`) and "live"
(`published`) are four genuinely different situations an admin needs to tell apart
at a glance mid-event.

### `challenge_answer`

One challenge may have any number of answer rules; **a submission is correct if it
satisfies any of them.**

| Column | Type | Notes |
| ------ | ---- | ----- |
| `challenge_id` | FK | |
| `match_type` | enum — see below | |
| `value` | text | Interpretation depends on `match_type` |
| `options` | jsonb | Per-type settings (tolerance, flags, ordering) |
| `label` | text | Admin-facing note, e.g. "accepts the British spelling" |
| `display_order` | int | Evaluation order |

**Match types shipped in Phase 1:**

| Type | `value` holds | `options` | Notes |
| ---- | ------------- | --------- | ----- |
| `exact` | The literal answer | `strip_whitespace` (default true) | |
| `case_insensitive` | The literal answer | as above | |
| `regex` | A pattern | `ignore_case`, `anchored` (default true), `timeout_ms` | See safety below |
| `numeric` | A number | `tolerance`, `min`, `max` | Accepts `1000`, `1,000`, `1e3`; tolerance absolute or `tolerance_percent` |
| `set` | Comma-separated members | `ordered` (default false), `case_insensitive`, `separator` | Multi-part answers, e.g. three CVEs in any order |
| `any_of` | Newline-separated alternatives | `case_insensitive` | Sugar for a long list of accepted spellings |

The list is deliberately open: `match_type` is an enum with a resolver registry,
so adding a type later is a new resolver plus one enum value, not a redesign.
**Reserved for spec 009:** a `dynamic` type whose expected value is computed from
the player's container instance. The column shape already allows it; nothing
implements it here.

**Regex safety.** An admin-authored pattern meeting attacker-controlled input is a
denial-of-service waiting to happen — `^(a|a)*$` against sixty characters will
occupy a worker indefinitely. Three defences:

1. Matching runs through the `regex` package rather than `re`, which supports a
   real `timeout=`. Verified: the pattern above raises `TimeoutError` after the
   configured 250 ms instead of hanging.
2. Patterns are compiled and validated when saved, so a broken pattern fails in
   the editor rather than at 09:00 on event day.
3. Submitted values are length-capped (1 KB) before matching.

A timeout is treated as a non-match and logged at warning level with the
challenge id, so a pathological pattern surfaces in the admin dashboard rather
than silently eating attempts.

### `challenge_artifact`

`challenge_id`, `filename`, `content_type`, `size_bytes`, `storage_key`,
`checksum_sha256`, `display_order`. Bytes live behind a storage interface — see
the open question, which now has a concrete recommendation.

### `solve`

`user_id`, `challenge_id`, `team_id_at_solve`, `submitted_at`, `submission_id`.

**Unique on `(user_id, challenge_id)`** — enforced by the database, because two
concurrent correct submissions would otherwise both pass a read-then-write check.

`team_id_at_solve` records which party the player was in at that moment. It is
**not** used for scoring — the solve is the player's, and their score travels with
them — but a team-basis decay curve needs to count distinct teams, and anti-cheat
in 007 wants to know who someone was sitting with. It is history, not ownership.

Deliberately **no `points` column**: a solve's value is a function of the
challenge's current solve count, computed at read time. Storing it would make the
decay curve a lie the moment the next player solves.

### `submission`

Every attempt: `user_id`, `challenge_id`, `is_correct`, `submitted_value`,
`matched_answer_id`, `ip`, `request_id`, `created_at`.

Values are stored as submitted (capped at 1 KB) whether right or wrong. With
answers in plaintext anyway there is nothing to protect by redacting them, and
having the exact text is what makes 007's "two unrelated players submitted the
identical unusual string" detection work.

### `score_adjustment`

`user_id`, `points` (signed), `reason`, `created_by_user_id`.

Introduced here rather than in 006 because a player's total is
`sum(current value of solved challenges) + sum(adjustments)`, which 005 needs
whole. Spec 006 adds the admin UI and granting endpoint.

## Scoring

For a `dynamic` challenge, with `s` = distinct solvers on the configured basis
(players or teams):

```
value(s) = max(
    minimum_points,
    ceil(initial_points - (initial_points - minimum_points) * (s / decay_threshold)^2)
)
```

Quadratic decay: value holds up for early solvers and falls away as a challenge
turns out to be easy, reaching the floor at `decay_threshold` solves and staying
there. `minimum_points` defaults to **100** — the floor before the modifiers you
will layer on later.

The curve lives behind a single `challenge_value(challenge, solve_count)`
function so a richer model can replace it without touching submission handling,
the scoreboard, or anything else.

**The value is identical for everyone at any instant**, including earlier solvers.
A player's total therefore moves when someone else solves, which is the point: it
stops a challenge everybody cracked from dominating the board.

`decay_basis = teams` counts distinct `team_id_at_solve` values, so eight
teammates solving the same challenge move the curve once rather than eight times.
`players` counts solvers. Both are available per challenge because they answer
different questions — "how many people found this" versus "how many groups did".

## Visibility

Three player-facing tiers, plus `draft` for work in progress:

| State | Player sees | Can submit |
| ----- | ----------- | ---------- |
| `draft` | Nothing. Staff only | No |
| `hidden` | Nothing | No |
| `locked` | Title, category, difficulty, current value, solve count | **No** |
| `published` | Everything, including body and artifacts | Yes |

`release_at` schedules the transition: before it, a challenge behaves according to
`pre_release_state` (`hidden` by default, `locked` where you want players to see
what is coming); at or after it, its actual `state` applies. This is what supports
the multi-day format — a wave of challenges set to `locked` with a shared
`release_at` shows the field what unlocks tonight without leaking the questions.

A locked challenge returns its summary from the detail endpoint with `body` and
`artifacts` omitted, and its submit endpoint returns `403 challenge_locked`.
Enforced server-side; the client is not trusted to hide the body it was never sent.

Staff see every state, labelled.

## API surface

### Player

| Method | Path | Gate | Notes |
| ------ | ---- | ---- | ----- |
| GET | `/api/challenges` | play | Visible challenges (locked ones summarised), current value, solve count, whether the caller solved it, attempts remaining when capped |
| GET | `/api/challenges/{id}` | play | Full detail; body and artifacts omitted when locked |
| POST | `/api/challenges/{id}/submit` | play | `{answer}` → `{correct, points_awarded, attempts_remaining, message}` |
| GET | `/api/challenges/{id}/artifacts/{artifact_id}` | play | Streams the file; refused when locked |
| GET | `/api/me/score` | play | Own total and solve list |

### Admin

| Method | Path | Gate | Notes |
| ------ | ---- | ---- | ----- |
| GET/POST | `/api/admin/challenges` | staff read / admin write | Includes drafts |
| GET/PATCH/DELETE | `/api/admin/challenges/{id}` | staff / admin | Delete refuses once solves exist — hide it instead |
| GET/POST/DELETE | `/api/admin/challenges/{id}/answers` | admin | Full CRUD on answer rules |
| POST | `/api/admin/challenges/{id}/answers/test` | admin | **Dry-run a candidate answer against the rules without recording a submission.** Non-negotiable for regex: authoring a pattern blind and finding out during the event is how challenges break |
| POST | `/api/admin/challenges/{id}/artifacts` | admin | Multipart upload |
| POST | `/api/admin/challenges/{id}/state` | admin | Change state instantly |
| GET/POST | `/api/admin/categories` | staff / admin | |
| GET | `/api/admin/submissions` | staff | Filterable attempt log — raw material for 007 |

Every admin write is audit-logged through spec 002's `record_audit`.

## Rate limiting

Redis, per player, in two tiers:

- **10 attempts per minute** per `(user, challenge)` — stops scripted guessing
  without troubling a person typing carefully.
- **60 attempts per minute** per user across all challenges — stops a script
  spreading itself across many challenges to dodge the first limit.

Exceeding either returns `429 rate_limited` with `retry_after_seconds`. Both
limits are configurable globally.

This limiter **fails closed** when Redis is unavailable, unlike the magic-link
limiter which fails open. That one guards against nuisance; this one guards the
integrity of the scoreboard, and an event running with brute-force protection
silently switched off is worse than one that briefly refuses submissions.

`max_attempts`, where set, is a hard per-challenge cap counted in Postgres, not
Redis, so it survives a cache flush. When set it is shown in the challenge detail
and in every submission response, so a player is never surprised by running out.

## Edge cases

- **Two correct submissions racing.** The unique constraint decides; the loser is
  told "already solved", not shown an error.
- **Submitting again after solving.** Accepted and logged, no second solve, no
  points. Players do re-submit to check.
- **Submitting to a locked challenge.** `403 challenge_locked`, and the attempt is
  still logged — someone probing locked challenges is worth seeing in 007.
- **A challenge is hidden mid-event after people solved it.** Solves stand and keep
  scoring. Hiding stops new attempts; it does not rewrite history. An admin who
  wants points removed uses a `score_adjustment` with a reason.
- **An answer rule is corrected after publication.** Existing solves stand. The
  change is audit-logged, because this is exactly what looks like tampering later.
- **A regex times out.** Non-match, logged with the challenge id, surfaced to
  admins. The player is not told their answer was "wrong" because of our bug —
  they simply see no match, and the admin sees the real reason.
- **`decay_threshold` of zero or one.** Rejected at validation; the curve divides
  by it.
- **`minimum_points` above `initial_points`.** Rejected at validation.
- **Numeric answers.** `1,000`, `1000`, `1e3` and `1000.0` all compare equal;
  tolerance is absolute or percentage.
- **A player solves, then leaves their party.** Nothing happens to the solve.
  `team_id_at_solve` keeps the history; the points were never the party's.
- **Team-basis decay when a solver had no party.** Counted as its own distinct
  solver rather than being dropped, otherwise a partyless player's solve would be
  invisible to the curve.

## Testing

- The decay curve, table-driven: zero solves, one, threshold-minus-one, exactly
  threshold, beyond, `static`, and both bases.
- Every match type, including the awkward cases: regex anchoring, regex timeout,
  numeric tolerance boundaries, unordered sets, whitespace, unicode.
- A catastrophic-backtracking pattern is contained rather than hanging the worker.
- Rate limiting, including that it fails **closed** when Redis is unavailable.
- Concurrency in the style of 002's party tests: two simultaneous correct
  submissions produce exactly one solve, and the test must fail if the unique
  constraint is dropped.
- Visibility, per state: a hidden challenge 404s on direct access so its id cannot
  be guessed for early access; a locked one returns a summary but never the body,
  and refuses submissions.
- The `play` gate is asserted on every player endpoint individually.

## Open questions

Only one remains.

**Artifact storage.** The question is where the bytes of a downloadable file live,
and it matters because the API will run more than one pod. Restated plainly:

- A Kubernetes `PersistentVolumeClaim` has an *access mode*. `ReadWriteOnce`
  (RWO) means the volume attaches to **one node at a time** — the usual default,
  and what most block storage supports. `ReadWriteMany` (RWX) means many pods
  across many nodes can mount it at once, which needs a filesystem-type backend
  (NFS, CephFS, Longhorn RWX).
- If the API runs two replicas on different nodes and files sit on an RWO volume,
  a file uploaded through pod A is invisible to pod B, and downloads fail
  depending on which pod answers. That is the failure I was worried about.

Everything below runs inside the cluster, as you want:

| Option | Trade-off |
| ------ | --------- |
| **MinIO in-cluster** (recommended) | S3-compatible object storage running as a pod. Any number of API replicas share it, no RWX needed. Cost: one more component in the IaC repo |
| **Postgres bytea** | Zero new infrastructure — Postgres is already there and already backed up. Cost: artifact bytes bloat every backup and replication stream, and the database ends up serving file downloads. Fine for a handful of small files, poor for 50 MB VM images |
| **RWX PersistentVolume** | Feels simplest, but only works if your storage class actually offers RWX, which many do not |

My recommendation is **MinIO in-cluster**, with the storage interface written so
the Postgres-backed implementation is a drop-in if you would rather not run it.
Either way the application code is identical — this decision only changes which
implementation is wired in, and it can be deferred until commit 5.

Tell me which, or tell me your storage class supports RWX and I will take the
volume route.

## Commit plan

1. Migration: `category`, `challenge`, `challenge_answer`, `challenge_artifact`,
   `solve`, `submission`, `score_adjustment`
2. Answer-matching resolvers (all six types) and the scoring curve
3. Player challenge listing and detail, with the three visibility tiers
4. Submission: validation, rate limiting, attempt cap, solve recording, logging
5. Artifact storage interface and download endpoint
6. Admin challenge, answer and category CRUD, including the answer dry-run
7. Frontend: challenge board and detail with submission
8. Frontend: minimal admin challenge editor with the answer tester
