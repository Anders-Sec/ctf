# Spec 004 — Hints

Status: **draft — awaiting sign-off**
Phase: 1
Covers: `Plan.md` → Challenge & Flag System (hint system)
Depends on: 002 (identity, the `play` gate, audit log), 003 (challenges, scoring)

## Purpose

Let a stuck player buy a nudge, at a cost. Small spec: one table for hints, one
for who has unlocked what, and a subtraction in the score expression.

Done when an admin can attach hints to a challenge with costs and ordering, a
player can see what a hint would cost before paying for it, unlocking deducts
the cost and reveals the text, and every unlock is recorded.

## Non-goals

- Per-team hint currency. `Plan.md` offers "points **or** a per-team
  hint-currency"; with solves personal, a party pool would let one member spend
  another's earnings. Points it is.
- The scoreboard (005) — it consumes the score expression this changes.
- Admin hint UI beyond a minimal editor (006 owns the full tooling).

## Decisions taken

Confirmed in review, plus two that follow from them:

- **Hints cost points**, deducted from the player who unlocks them.
- **A hint unlocked after solving that challenge is free.** This is a work
  education event: reading the hint afterwards to understand what you missed is
  a thing people should be encouraged to do, not charged for. It also removes
  the only case where unlocking is pure loss.
- **Costs are stored per unlock**, not read live from the hint. See below.

## Data model

### `hint`

| Column | Type | Notes |
| ------ | ---- | ----- |
| `challenge_id` | FK `challenge` | Cascades on delete |
| `title` | text | Shown before unlocking, e.g. "Where to look" |
| `body` | text | Withheld until unlocked |
| `cost` | int, default 0 | Points. Zero is a free hint, which is allowed |
| `display_order` | int | |
| `prerequisite_hint_id` | uuid, nullable, self-FK | Must be unlocked first |
| `available_after` | timestamptz, nullable | Not offered before this time |

`prerequisite_hint_id` and `available_after` are both optional and independent,
so a challenge can have a ladder of hints, a hint that only appears late on day
two, or neither.

### `hint_unlock`

`user_id`, `hint_id`, `cost_charged`, `unlocked_at`.
**Unique on `(user_id, hint_id)`** — a database constraint, so a double-clicked
unlock cannot charge twice.

**`cost_charged` is a snapshot, and challenge values are live.** That looks
inconsistent, so the reasoning: a challenge's value is a shared function of a
rule everyone is playing under, and moving it is the mechanic working. A hint's
cost is a number one admin typed. Editing it later must not silently rewrite
what someone already paid.

This table *is* the log `Plan.md` asks for; unlocks do not also write to
`audit_log`. Admin edits to hints do.

### Scoring

`user_score` becomes:

```
sum(current value of solved challenges)
  + sum(score adjustments)
  - sum(hint costs charged)
```

Hint costs stay out of `score_adjustment` deliberately: that table is the record
of admin intervention, and spec 006 renders it as such. Mixing automatic game
mechanics into it would make a scoring dispute harder to read, not easier.

A score can go negative — a player who buys hints and solves nothing has spent
more than they earned. That is the correct arithmetic and the scoreboard should
show it rather than clamping at zero.

## API surface

### Player

| Method | Path | Gate | Notes |
| ------ | ---- | ---- | ----- |
| GET | `/api/challenges/{id}` | play | Gains a `hints` array: id, title, cost, `unlocked`, `available`, `body` (null until unlocked) |
| POST | `/api/challenges/{id}/hints/{hint_id}/unlock` | play | `{body, cost_charged, new_total}` |

Hint bodies are withheld server-side, exactly as a locked challenge's body is.
The `cost` a player sees before unlocking is what they will be charged, and the
response says what was actually taken.

### Admin

| Method | Path | Gate | Notes |
| ------ | ---- | ---- | ----- |
| GET | `/api/admin/challenges/{id}/hints` | staff | Bodies included |
| POST | `/api/admin/challenges/{id}/hints` | admin | |
| PATCH/DELETE | `/api/admin/challenges/{id}/hints/{hint_id}` | admin | Delete refuses once unlocked — people paid for it |

## Edge cases

- **Unlocking twice.** The unique constraint decides; the second call returns the
  body with `cost_charged: 0` rather than an error. Players double-click.
- **Unlocking after solving.** Free, and recorded with `cost_charged: 0`.
- **A hint whose prerequisite is not unlocked.** `403 hint_locked`, and the body
  is absent from the listing, not merely hidden.
- **A hint not yet available.** Listed with `available: false` and no body, so a
  player can see something is coming without reading it.
- **Cost edited after people paid.** Existing unlocks keep their charge. The edit
  is audit-logged.
- **A hint on a locked challenge.** Unreachable: the challenge detail route
  already refuses.
- **Deleting a hint people paid for.** Refused. Hide the challenge or accept the
  hint exists; refunding is a `score_adjustment` an admin makes deliberately.
- **A player unlocks a hint on a challenge they later leave a party over.**
  Nothing happens. Costs are personal, like everything else.

## Testing

- Cost is deducted exactly once, and a second unlock charges nothing.
- Unlocking after solving is free.
- Prerequisites and availability windows both gate the body server-side.
- A body never appears in a listing response before it is unlocked.
- Score arithmetic: solves minus hints plus adjustments, including a negative total.
- Editing a cost does not change what past unlockers were charged.
- Concurrency: two simultaneous unlocks charge once.

## Commit plan

1. Migration: `hint`, `hint_unlock`; scoring updated to subtract hint costs
2. Player hint listing and unlock endpoint
3. Admin hint CRUD
4. Frontend: hints on the challenge page, with an explicit cost confirmation
