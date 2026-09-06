# Spec 003 — Challenges, Flags & Dynamic Scoring

Status: **draft — awaiting sign-off**
Phase: 1
Covers: `Plan.md` → Challenge & Flag System (except hints, which are spec 004)
Depends on: 001 (skeleton), 002 (identity, the `play` gate, audit log)

## Purpose

The game itself: challenges to attempt, flags to submit, and points that decay as
more people solve. Every gameplay action added here sits behind the `require_play`
gate from spec 002, so an unapproved guest or a pre-event visitor cannot touch any
of it.

Done when an admin can create a challenge with a hashed flag and a release time, a
player can browse released challenges and submit a flag, a correct submission
records a solve worth the challenge's current value, every attempt is logged for
later review, and brute force is stopped by a per-player rate limit.

## Non-goals

- **Hints** (004) — the hint tables reference challenges, so they come next.
- **The scoreboard** (005). This spec produces the raw material; 005 aggregates
  and caches it. There is a `GET /api/me/score` here only so the player can see
  their own total.
- **Container-backed challenges** (008/009). The `container_template_id` column is
  added now as a nullable reference so 009 does not need a schema change, but
  nothing reads it yet.
- **Admin UI** (006). Endpoints ship here; screens ship in 006, apart from a
  minimal challenge editor without which the event cannot be set up at all.
- **Anti-cheat detection** (007). This spec records the evidence; 007 interprets it.

## The load-bearing decision, restated

Spec 002 established that **a solve belongs to the player, not the party**. This
spec is where that first bites:

- `solve` is keyed on `(user_id, challenge_id)`. There is no `team_id` on it.
- Rate limiting is **per player per challenge**, not per team. `Plan.md` says "per
  team/challenge", which was written before scores became personal — a per-team
  limit would now let one player consume a teammate's attempts, and would not
  slow a single brute-forcing player at all.
- Dynamic scoring decays on **distinct players who have solved**, for the same
  reason. See the open question below; this is the one I most want confirmed.

## Data model

### `category`

`name` (citext, unique), `slug`, `display_order`, `description`.

A table rather than a string column on `challenge`: Phase 2 ties stat blocks to
categories, and attaching that to a free-text string later means a migration that
first has to invent the missing rows.

### `challenge`

| Column | Type | Notes |
| ------ | ---- | ----- |
| `title` | text | |
| `slug` | citext, unique | Stable player-facing identifier |
| `category_id` | FK `category` | |
| `body` | text | Markdown, rendered client-side |
| `difficulty` | enum `easy` \| `medium` \| `hard` \| `insane` | Display and, in Phase 2, XP weighting |
| `state` | enum `draft` \| `published` \| `hidden` | See "Visibility" |
| `release_at` | timestamptz, nullable | Null means "as soon as published" |
| `initial_points` | int | Value at zero solves |
| `minimum_points` | int | Floor the curve decays to |
| `decay_threshold` | int | Solves at which the floor is reached |
| `scoring` | enum `dynamic` \| `static` | Static pins the value at `initial_points` |
| `max_attempts` | int, nullable | Null means unlimited (still rate limited) |
| `container_template_id` | uuid, nullable | Reserved for spec 009; unused here |
| `author_user_id` | FK `user`, nullable | Who to ask when it breaks |

`state` is a three-way enum rather than a boolean because "not written yet"
(`draft`) and "was live, pulled mid-event because it is broken" (`hidden`) need to
be distinguishable — `Plan.md` explicitly wants instant hiding without deletion,
and an admin needs to see at a glance which is which.

### `challenge_flag`

`challenge_id`, `flag_hash`, `comparison` (enum `exact` \| `case_insensitive`),
`label` (admin-facing note).

**Multiple flags per challenge, not one.** Real challenges routinely accept more
than one spelling, and a set of hashed alternatives is the only way to do that
once flags are hashed. It also leaves room for spec 009's per-instance flags to
attach here with an added nullable scope column rather than a new table.

**Hashing:** HMAC-SHA256 under a server-side pepper (`FLAG_PEPPER`), not a bare
digest and not Argon2.

- A bare SHA-256 of a flag is brute-forceable offline from a database dump —
  real flags are short, structured, and often guessable (`flag{...}`).
- Argon2 resists that, but flag submission is the hottest path in the event and
  the one we are explicitly load-testing; putting a deliberately slow KDF in it,
  multiplied by every accepted flag on the challenge, is the wrong trade.
- HMAC with a pepper held outside the database gives offline resistance at
  negligible cost. The pepper lives in config, never in source, and rotating it
  requires re-entering flags — which is the documented cost of that choice.

**Consequence, stated plainly:** hashing makes regex or pattern flags impossible.
Multiple exact alternatives cover the common cases. If a challenge genuinely needs
a computed flag, it needs the per-instance mechanism in 009, not a regex.

### `challenge_artifact`

`challenge_id`, `filename`, `content_type`, `size_bytes`, `storage_key`,
`checksum_sha256`, `display_order`.

Bytes live behind a small storage interface, not in Postgres — challenge downloads
can be tens of megabytes and would bloat every backup and replication stream. See
the open question on which backend.

### `solve`

`user_id`, `challenge_id`, `submitted_at`, `attempt_id`.
**Unique on `(user_id, challenge_id)`** — a database constraint, because two
concurrent submissions of the same correct flag would otherwise both pass a
read-then-write check and award two solves.

Deliberately **no `points` column**: a solve's value is a function of the
challenge's current solve count, computed at read time, exactly as party standing
is computed over current members. Storing it would make the decay curve a lie the
moment the next player solves.

### `submission`

Every attempt, correct or not: `user_id`, `challenge_id`, `is_correct`,
`submission_hash`, `submitted_value`, `ip`, `request_id`, `created_at`.

- `submission_hash` is the same HMAC used for flags, on every attempt. It is what
  makes spec 007's "unrelated players submitted the identical wrong string"
  detection possible without storing anything sensitive.
- `submitted_value` holds the raw text **only for incorrect attempts**, capped at
  256 characters. A correct attempt is by definition the flag, and writing it in
  plaintext next to the hashed column would defeat the point of hashing it. We
  already know what a correct submission was.

### `score_adjustment`

`user_id`, `points` (signed), `reason`, `created_by_user_id`.

Introduced here rather than in 006 because a player's total is
`sum(current value of solved challenges) + sum(adjustments)`, and 005 needs that
whole expression. Spec 006 adds the admin UI and the granting endpoint; this spec
only defines the table and includes it in the total.

## Scoring

For a `dynamic` challenge, with `s` = number of distinct players who have solved it:

```
value(s) = max(
    minimum_points,
    ceil(initial_points - (initial_points - minimum_points) * (s / decay_threshold)^2)
)
```

Quadratic decay: the value holds up for early solvers and falls away as a
challenge turns out to be easy, reaching `minimum_points` at `decay_threshold`
solves and staying there. Defaults, globally configurable and overridable per
challenge: `initial_points` 500, `minimum_points` 100, `decay_threshold` 40 (a
fifth of the expected field).

**The value is the same for everyone at any instant**, including players who
solved earlier — the standard CTF model. A player's total therefore moves when
someone else solves, which is intended: it is what keeps a challenge everybody
cracked from dominating the board.

`static` scoring pins the value at `initial_points`, for challenges where decay
would be wrong (a participation flag, a sponsor challenge).

## Visibility

A challenge is visible to a player when **all** hold:

- `state = published`
- `release_at` is null, or `now >= release_at`
- the caller's `capabilities.play` is true (spec 002's gate: approved, and the
  event is running)

Staff see everything, in every state, with the unpublished ones marked — someone
has to be able to check a challenge before the doors open.

Unreleased challenges are **hidden entirely**, not shown as locked. A locked entry
leaks title, category and point value, which is a hint in itself; and a countdown
of "3 challenges unlock at 14:00" is better served by the event schedule than by
teasing each one. Flagged as an open question in case you want teasers.

## API surface

### Player

| Method | Path | Gate | Notes |
| ------ | ---- | ---- | ----- |
| GET | `/api/challenges` | play | Visible challenges, with current value, solve count, and whether the caller has solved it. Never includes flags. |
| GET | `/api/challenges/{id}` | play | Full body and artifact list |
| POST | `/api/challenges/{id}/submit` | play | `{flag}` → `{correct, points_awarded, message}` |
| GET | `/api/challenges/{id}/artifacts/{artifact_id}` | play | Streams the file |
| GET | `/api/me/score` | play | Own total and solve list |

### Admin

| Method | Path | Gate | Notes |
| ------ | ---- | ---- | ----- |
| GET/POST | `/api/admin/challenges` | staff read / admin write | Includes drafts |
| GET/PATCH/DELETE | `/api/admin/challenges/{id}` | staff / admin | Delete refuses once solves exist — hide it instead |
| POST | `/api/admin/challenges/{id}/flags` | admin | Accepts plaintext, stores only the hash |
| DELETE | `/api/admin/challenges/{id}/flags/{flag_id}` | admin | |
| POST | `/api/admin/challenges/{id}/artifacts` | admin | Multipart upload |
| POST | `/api/admin/challenges/{id}/state` | admin | Publish / hide, instantly |
| GET/POST | `/api/admin/categories` | staff / admin | |
| GET | `/api/admin/submissions` | staff | Filterable attempt log — the raw material for 007 |

Every admin write is audit-logged through spec 002's `record_audit`.

## Rate limiting

Redis, per player per challenge, in two tiers:

- **10 attempts per minute** per `(user, challenge)` — stops scripted guessing
  without troubling a person typing carefully.
- **60 attempts per minute** per user across all challenges — stops a script
  spreading itself thinly across many challenges to dodge the first limit.

Exceeding either returns `429 rate_limited` with a `retry_after_seconds` detail.
Unlike the magic-link limiter, this one **fails closed** if Redis is unavailable:
the magic-link limiter protects against nuisance, this one protects the integrity
of the scoreboard, and an event with brute-force protection silently disabled is
worse than one that briefly refuses submissions.

`max_attempts`, where set, is a hard per-challenge cap enforced in Postgres, not
Redis — it must survive a cache flush.

## Edge cases

- **Two correct submissions racing.** The unique constraint on `(user_id,
  challenge_id)` decides; the loser gets "already solved", not an error.
- **Submitting a flag for an already-solved challenge.** Accepted and logged, but
  no second solve and no points. Players do re-submit to check.
- **Submitting after the event ends.** Refused by the `play` gate.
- **A challenge is hidden mid-event after people solved it.** Solves stand and
  keep scoring. Hiding stops new attempts, it does not rewrite history — and an
  admin who wants the points removed uses a `score_adjustment` with a reason.
- **A flag is corrected after publication.** The old flag is deleted and a new one
  added; existing solves stand. Flagged in the audit log, because this is exactly
  the kind of change that looks like tampering afterwards.
- **Decay threshold reached and then a solve is removed.** Value recomputes
  upward. Correct, and only reachable through an admin action.
- **`decay_threshold` of zero or one.** Rejected at validation; the curve divides
  by it.
- **Whitespace and case.** Submissions are stripped of leading/trailing whitespace
  before comparison. Case-insensitive matching is per flag, and lowercases before
  hashing on both sides.
- **A player solves, then leaves their party.** Nothing happens to the solve. It
  was never the party's.

## Testing

- The decay curve as a table-driven test: zero solves, one, threshold-minus-one,
  exactly threshold, beyond threshold, and the `static` case.
- Flag comparison: exact, case-insensitive, whitespace, multiple accepted flags,
  wrong flag, near-miss.
- Rate limiting, including that it fails **closed** when Redis is unavailable.
- Concurrency, in the style of 002's party tests: two simultaneous correct
  submissions produce exactly one solve — and the test must fail if the unique
  constraint is dropped.
- Visibility: an unreleased challenge is absent from the list *and* 404s on direct
  access, so the id cannot be guessed for early access.
- A correct submission's plaintext never reaches the `submission` table.
- The `play` gate is enforced on every player endpoint, checked per endpoint
  rather than assumed from the dependency.

## Open questions

1. **Decay on distinct players, not teams** — my recommendation, following from
   personal solves. Confirming this is the one thing that blocks implementation.
2. **Artifact storage.** Options: (a) a PVC on the on-prem cluster behind a
   storage interface — simplest, no new infrastructure, but needs
   ReadWriteMany if the API scales past one replica; (b) MinIO or similar
   on-prem object storage — the usual answer, but it is infrastructure someone
   has to run; (c) Azure Blob, which contradicts the on-prem posture. I lean
   towards (a) behind an interface, with (b) as a drop-in later. Your call, and
   it touches the IaC repo.
3. **Scoring defaults** — 500/100/40 as proposed, or different numbers? Easy to
   change later, but the field size (200+) makes 40 a guess worth checking.
4. **Teaser entries for unreleased challenges?** Spec says hidden entirely.
5. **A global attempt cap per challenge**, or rate limiting only? Currently
   `max_attempts` is available per challenge and unset by default.

## Commit plan

1. Migration: `category`, `challenge`, `challenge_flag`, `challenge_artifact`,
   `solve`, `submission`, `score_adjustment`
2. Flag hashing and comparison service, plus the scoring curve
3. Player challenge listing and detail, with the visibility rules
4. Flag submission: validation, rate limiting, solve recording, attempt logging
5. Artifact storage interface and download endpoint
6. Admin challenge, flag and category CRUD
7. Frontend: challenge board and challenge detail with submission
8. Frontend: minimal admin challenge editor
