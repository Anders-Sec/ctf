# Spec 014 — Challenge Editor Completion, Prerequisites & Event Settings

Status: **approved** (2026-09-07) — build
Phase: 1 cleanup (before Phase 2)
Covers: the gaps in the admin challenge editor, per-player prerequisite gating, and the event-settings page
Depends on: 003 (challenges/scoring), 004 (hints), 009 (container templates), 006 (admin CRUD), 002 (event config)

## Why

The admin challenge editor is **read-only** for almost everything: it shows
points, decay, and attempts as static text and lets an admin change only the
state and the answer rules. Everything else the backend already supports —
description, points, scoring mode, decay, difficulty, attempts, the release
schedule, hints, and the container-template link — has **no way to be set from
the UI.** On a fresh event that means a challenge cannot really be authored.

Most of this spec is therefore **exposing what already exists.** Two pieces are
genuinely new: assigning a container template (a small backend gap plus a
template-management surface), and **prerequisite locks** — "solve X before this
unlocks."

## 1. The edit form (exposing existing fields)

`PATCH /api/admin/challenges/{id}` already accepts `title`, `slug`, `category`,
`body`, `difficulty`, `release_at`, `pre_release_state`, `initial_points`,
`minimum_points`, `decay_threshold`, `scoring`, `decay_basis`, `max_attempts`.
The editor gains a form that edits all of them:

- **Description / task** (`body`) — the missing "what do I do" field.
- **Points** — `initial_points` and `minimum_points` (the floor).
- **Type & decay** — `scoring` (`dynamic` | `static`), and for dynamic:
  `decay_basis` (`players` | `teams`) and `decay_threshold`.
- **Difficulty**, **max attempts** (blank = unlimited), and the **release
  schedule** (`release_at` + whether it shows `hidden` or `locked` before then).

No backend change — this is a form wired to the existing endpoint, with the
scoring validation the endpoint already enforces surfaced as inline errors.

## 2. Hints (exposing spec 004)

Full hint CRUD already exists at
`/api/admin/challenges/{id}/hints` (create, edit, delete, with `cost`,
`display_order`, an optional `prerequisite_hint_id`, and an optional
`available_after`). The editor gains a **Hints** section listing them and letting
an admin add, edit the cost/text, reorder, and delete — the same shape as the
existing answer-rules section. No backend change.

## 3. Container assignment & templates

**Backend gap:** `challenge.container_template_id` exists on the model but is
**not** in `UpdateChallengeRequest`, so it can never be set. Add it (nullable —
setting `null` detaches the container), validated to reference a real template.

**Templates need a UI.** `POST/GET/DELETE /api/admin/templates` exist (spec 009)
but nothing calls them. Add a small **template-management** surface — create
(name, image, tag, port, TTL, CPU/memory, `injects_answer`), list, delete — and a
**selector on the challenge editor** to attach one. A container-backed challenge
is then authorable end to end from the admin UI: make a template, point a
challenge at it, publish.

The player-facing `has_container` flag (spec 009) already drives the "Launch"
panel, so once a challenge has a template assigned and is published, players can
spin it up — closing the "no place to spin them up" gap.

## 4. Prerequisite locks (new)

### The model, built to extend

"What locks a challenge" is, for Phase 1, **other challenges being solved.** XP,
skill and level requirements are Phase 2 (that system does not exist yet), so the
model is a general **unlock requirement** with a type discriminator, and only the
`challenge_solved` type is implemented now:

`challenge_unlock_requirement`: `challenge_id` (the gated challenge),
`requirement_type` (`challenge_solved`; Phase 2 adds `min_xp`, `skill_level`, …),
`required_challenge_id` (nullable — set for `challenge_solved`).

A challenge unlocks for a player when **all** of its requirements are met. Phase 2
adds columns and enum members without touching the gating logic below.

### Per-player gating

Prerequisites make "locked" a **per-player** condition rather than a global state.
Layered on top of the existing schedule-driven `effective_state`:

- A challenge whose effective state is `published` but whose requirements a given
  player has **not** met is presented to that player as **locked** — exactly the
  existing locked presentation (title, category and points visible; body,
  artifacts, hints and submission withheld).
- The gate is enforced **server-side on submission**, not just hidden: a submit
  to a challenge with unmet prerequisites is refused with the existing
  `challenge_locked` error, so the lock is real, not cosmetic.
- The AI context assembler (spec 010) already excludes locked challenges; a
  per-player-locked challenge is excluded for that player too, so the System AI
  cannot describe a challenge the player has not unlocked.

### What the player sees

A locked-by-prerequisite challenge shows **why**: the titles of the required
challenges and whether each is solved ("Unlock by solving: Recon 1 ✓, Recon 2").
This guides players rather than leaving them at a dead end. Required challenges
they cannot see at all (hidden/draft) are omitted from the hint rather than
revealed.

### Guards

- A challenge cannot require **itself**, and cycles are rejected at save time (a
  reachability check over the prerequisite graph), so an admin cannot create a
  set of challenges that mutually lock each other into being unsolvable.
- Removing or deleting a challenge that is a prerequisite of others is allowed;
  the requirement rows referencing it are cleaned up (its dependents simply lose
  that requirement).

### Admin surface

On the editor, a **Prerequisites** section: add a required challenge (picker over
other challenges), list the current ones, remove them.
`POST` / `DELETE /api/admin/challenges/{id}/prerequisites` — the same
add/remove shape as answers and hints.

## 5. Event settings page

Same story as the editor: `GET` / `PATCH /api/admin/event-config` exist (spec
002, extended in 011) and support `name`, `starts_at`, `ends_at`,
`registration_open` and `assistant_enabled` — but there is **no UI**, so start and
end times cannot be changed from the app at all. This is the gate that opens and
closes the whole event, so it needs a home.

A new admin **Event settings** page (its own route and admin-nav tab) over the
existing endpoint:

- **Event name.**
- **Start** and **end** times — `datetime-local` inputs, shown and edited in the
  admin's local zone and sent as UTC ISO; the response's `server_time` is shown
  alongside so an admin sets the window against the clock that actually decides.
- **Registration open** — the toggle that lets new guests sign up.
- **System AI** — the `assistant_enabled` runtime switch (spec 011), surfaced here
  as the natural home for an event-wide toggle rather than only living in config.

The endpoint already validates that the end cannot precede the start; that error
surfaces inline. No backend change — purely the missing frontend.

## Data model summary

- **New:** `challenge_unlock_requirement` (above).
- **Changed:** `UpdateChallengeRequest` gains `container_template_id`.
- The admin challenge detail response gains `container_template_id` and the
  prerequisite list; the player challenge response gains, for a locked-by-prereq
  challenge, the requirement summary.

## Testing

- Every editor field round-trips through the PATCH and comes back changed.
- Hints can be created, edited, reordered and deleted from the editor.
- A template can be created and assigned; a challenge with a template reports
  `has_container` and offers the launch panel; detaching sets it null.
- The event-settings page loads the current config, saves a changed start/end,
  and surfaces the end-before-start validation error inline.
- A player who has not solved the prerequisite sees the challenge **locked**,
  cannot submit to it (server-side `challenge_locked`), and it is absent from
  their AI context.
- Solving the prerequisite unlocks it — the same challenge becomes fully visible
  and submittable.
- A challenge requiring several prerequisites unlocks only when **all** are
  solved.
- Self-reference and cycles are rejected at save.
- Deleting a prerequisite challenge drops the requirement from its dependents.

## Commit plan

1. Backend: the `challenge_unlock_requirement` model + migration;
   `container_template_id` in the update; the prerequisite endpoints; per-player
   gating in the challenge list/detail, the submission path, and the AI context.
2. Frontend: the challenge edit form (description, points, type/decay, difficulty,
   attempts, schedule).
3. Frontend: the hints management section.
4. Frontend: template management + the container selector on the editor.
5. Frontend: the prerequisites section, and the player-facing "locked — unlock by
   solving …" display.
6. Frontend: the event-settings page (name, start/end, registration, System AI)
   and its admin-nav tab.

## Non-goals

- XP / skill / level lock types — Phase 2, once that system exists. The model
  leaves room for them.
- Reordering challenges on the board, bulk edits, or a challenge-dependency
  visualisation — not needed to author an event.

## Decision

- **Show prerequisite names to players** on a locked challenge (guides them),
  omitting any required challenge they cannot otherwise see. Signed off.
