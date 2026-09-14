# Spec 035 — System AI terms of use

Status: **built** — 954 backend tests, 210 frontend tests.
**The terms text still needs management approval**; the mechanism does not
depend on the wording, and revising the file is a supported operation.
Phase: 1
Covers: a first-use acceptance gate for the System AI, with the terms held in a
local file
Depends on: 011 (the assistant gate), 033 (the ladder), 002 (capabilities, audit)
**Blocks** 034's session drill-down — see "Ordering"

## Purpose

Before a player can talk to the System AI, they accept its terms of use once.
The terms live in a file, so the wording can go through management review and be
changed without touching code.

The substance is that **the conversation is not private**: event staff can read
it, and it may be quoted in the post-event write-up on trends and learning
opportunities.

Done when a first-time user is shown the terms, cannot send a message until they
accept, and their acceptance is recorded against the version they saw.

## Ordering, and why this comes first

Spec 034 opens full transcripts to admins. That decision is sound **because
players know** — and this is the thing that makes them know. A briefing everyone
half-hears is not the same as a notice in the product.

So the sequencing matters: **this ships before 034's session drill-down opens.**
It is the same shape as 010 shipping staff-gated until 011's guardrails landed,
and for the same reason — the capability and the thing that makes it acceptable
should not be separated by a week of real traffic.

This spec is small. Building it first costs little and removes the question.

## The terms file

`backend/app/content/system-ai-terms.md`, rendered as markdown in the panel (the
renderer arrived with 033).

- **Path is configurable** — `AI_TERMS_PATH`, defaulting to that file — so the
  manifests can mount a ConfigMap over it later and management can revise the
  wording without a rebuild. Not doing that now; the setting is what makes it
  possible without a migration.
- **Read at startup and cached**, with the cache keyed on the file's modification
  time so a mounted change is picked up without a restart.
- **If the file is missing or empty, the assistant is unavailable** rather than
  open. A terms gate that fails open is not a terms gate. It surfaces on the
  health panel (034) so the cause is visible rather than mysterious.

### Versioning

The version is the **SHA-256 of the file contents**, truncated to 12 characters.
Nobody has to remember to bump anything, and a whitespace-only edit is a new
version — which is the safe direction.

**A changed file means everyone accepts again.** That is the point: if the terms
change, prior acceptance was to different words. Worth knowing before an edit
mid-event, so the admin screen shows the current version and how many have
accepted it.

## Data model

### `assistant_terms_acceptance`

`user_id`, `version`, `accepted_at`, `id`. Unique on `(user_id, version)`.

A table rather than columns on `user`, because this is a compliance record and
the question management will ask is "who accepted what, and when" — including
across revisions. Overwriting a column loses exactly that.

Not purged by 011's retention job: it is a record of consent, and it holds no
conversation content.

## The gate

`require_assistant` (spec 011) gains one check, after the existing two:

```
event toggle → per-player block → terms accepted
```

An unaccepted user gets `403` with code **`assistant_terms_required`**, which is
the same shape the panel already handles for `assistant_unavailable` and
`assistant_blocked`.

**Only the chat is gated.** Nothing else in the platform is affected — a player
who never accepts simply has no System AI, keeps every other challenge, and is
not blocked from the ladder's six challenges if a teammate hands them a flag.

Staff are **not** exempt. They are the ones who will be reading transcripts, and
a term they never read is a bad look.

## API surface

| Method | Path | Gate | Notes |
| --- | --- | --- | --- |
| GET | `/api/assistant/terms` | Player | The text, the version, and whether this user has accepted it |
| POST | `/api/assistant/terms/accept` | Player | Body carries the version; a stale one is refused |
| GET | `/api/admin/assistant/terms` | Staff | Current version, acceptance count, who has not accepted |

`/api/auth/me` gains `assistant_terms_accepted`, so the panel knows on load
rather than after a failed send.

**Accepting names the version.** If the file changes between the page loading and
the click, the acceptance is refused and the new text shown. Otherwise a player
can accept terms they were never displayed, which is the one failure that would
make the whole record worthless.

## Frontend

- Opening the panel for an unaccepted user shows the terms in place of the
  transcript: the text, scrollable, with an **Accept** button and no way to type.
  A modal over the rest of the app would be heavier than this deserves.
- Accepting invalidates the conversation query and the chat appears.
- Declining is just not accepting — the panel closes. No separate refusal state
  to store.
- A **persistent one-line footer** in the chat panel afterwards: *this
  conversation is visible to event staff*. The acceptance is a moment; the footer
  is the reminder, and it is what someone sees on day three.
- Re-acceptance after a version change reuses the same screen.

## Edge cases

- **The file is missing.** Assistant unavailable, with a distinct health reason.
- **The file changes mid-event.** Everyone re-accepts. The admin screen shows the
  version so this is a decision rather than a surprise.
- **A player accepts twice** (two tabs). The unique constraint makes the second a
  no-op, not an error.
- **A stale version is submitted.** Refused with the current text, as above.
- **A blocked player.** The block is checked first; they see the block, not terms.
- **The event has not started.** The play gate refuses first, as it does today.
- **A guest account.** Same terms, same gate. Nothing here is employee-specific.
- **Terms accepted, then `AI_ENABLED=false`.** Unavailable, as before; acceptance
  is untouched and still stands when it comes back.

## Testing

- An unaccepted player is refused with `assistant_terms_required`, on every chat
  endpoint rather than only the send.
- Accepting lets the same player through.
- A changed file re-gates an already-accepted player.
- Accepting a stale version is refused.
- Accepting twice is idempotent.
- A missing terms file makes the assistant unavailable, not open.
- The block and the event toggle both take precedence over the terms gate.
- `/api/auth/me` reports acceptance.
- The acceptance record survives a retention purge.
- Staff are gated too.

## Commit plan

1. Migration and model: `assistant_terms_acceptance`
2. The terms file, its loader, hashing and caching
3. The gate, the endpoints, and `auth/me`
4. Frontend: the acceptance screen and the persistent footer
5. The admin view of version and acceptance count

## The terms text

A **first draft** lives at `backend/app/content/system-ai-terms.md`. It is written
to be readable by a player in under a minute, and it is **not legal advice** —
the project owner is taking it to management for review.

Three parts most likely to need input from someone other than me:

1. **The monitoring notice.** "Staff can read this" is the core of it. Depending
   on jurisdiction and whether a works council or equivalent is involved, the
   wording and the prominence may be prescribed rather than a matter of taste.
2. **Retention.** The draft says conversations are kept for the event and a short
   period after, matching `AI_RETENTION_DAYS` (default 30). If policy says
   something different, the number in the file and the setting should agree — and
   the file is the promise, so the setting should follow it.
3. **The post-event write-up.** The draft says conversations may be quoted. If
   anything will be quoted **attributably** rather than anonymised, that is a
   materially different statement and should say so explicitly.

## What changed during implementation

**The test fixtures needed a default.** Every API-level chat test now runs into
the gate, so `sign_in` records acceptance unless a test passes
`accept_terms=False`, and the frontend `me()` helper defaults
`assistant_terms_accepted` to true. That is the state a player is in for all but
their first visit, so the default matches reality rather than papering over the
gate — and the gate's own tests opt out.

**`/auth/me` swallows a missing terms file.** The gate fails closed, but the call
the whole SPA boots on cannot; it reports `assistant_terms_accepted: false` and
lets the gate do the refusing.

Nothing else deviated.

## Open questions

1. **Does declining need to be recorded?** Proposed no — absence of acceptance is
   the state, and a player who never opens the panel has not declined anything.
2. **Should the admin screen name who has not accepted?** Useful for chasing
   before the event; mildly surveillance-shaped during it. Proposed: a count by
   default, the list behind a click.
3. **Re-acceptance mid-event is disruptive.** If management revises the wording on
   day two, 200 people get a modal. Is that acceptable, or should a
   `minor: true` marker exist for typo fixes that do not re-gate? Proposed:
   accept the disruption, because deciding which edits are "minor" is exactly the
   judgement a consent record should not be making.
