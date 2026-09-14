# Spec 036 — AI sessions that survive a reset, and the full gate log

Status: **approved** — building
Phase: 1
Covers: retaining conversations across a wipe, recording every upstream call in a
turn, widening the safety net, and resetting the chat automatically on level-up
Depends on: 033 (the ladder, `trace`), 034 (the console), 011 (findings, retention)
**Amends** 011 and 034

## Purpose

Four problems, one underlying cause: **the platform throws away almost everything
that would explain what happened.**

A player resets their session after nearly every attempt — that is how people
play this — and a reset is currently a hard `DELETE`. So the transcript behind a
flag is gone, the conversation drops off the admin sessions list, and the only
record of a level 3 attempt is which gate fired, as a bare string.

Done when a reset keeps its history, a flagged exchange can still be read
afterwards, an admin can see every model call in a turn including the reply a
gate suppressed, the safety net covers profanity and NSFW, and levelling up
resets the chat without a page refresh.

---

## Part 1 — Sessions survive a reset

### What happens today

`assistant_chat.clear()` deletes every message row and sets `message_count` to 0
and `last_message_at` to null. Consequences, all of them bad:

- The exchange behind every finding is gone. `assistant_finding.message_id` is
  `ON DELETE SET NULL`, so the finding survives as a rule name with no context.
- The conversation disappears from the admin sessions list, because that list is
  ordered and filtered on `last_message_at`.
- The retention window becomes meaningless: nothing reaches 30 days, because
  players delete it first.

### The change

**A reset starts a new session rather than destroying the old one.**

- `assistant_conversation.current_session` — an integer, incremented on reset.
- `assistant_message.session_number` — which session a turn belongs to.
- `clear()` increments `current_session` and **deletes nothing**.
- `message_count` **keeps counting** and is never reset, so `sequence` stays
  unique per conversation and the existing constraint holds unchanged.
- The player's history, and what is replayed to the model, filter to
  `session_number = current_session`. From the player's side a reset looks
  exactly as it does now.
- `last_message_at` is never nulled, so the conversation stays on the sessions
  list and ages out of retention normally.

This satisfies the stronger of the two options asked for: **every** session is
retained for the retention window, not only flagged ones. Retaining "only
flagged" sessions would need us to know a session mattered before it ended, and
the interesting ones are often the near-misses that never tripped a rule.

### What this costs

Conversations now grow for the life of the event instead of being truncated by
resets. A heavy player at 100 turns a day for three days is a few hundred rows
and perhaps a megabyte of text — trivial at this scale, and bounded by the
existing per-player rate limits.

**Retention needs nothing from this spec.** The whole infrastructure is torn
down 30 days after the event, which enforces the window regardless of what the
code does — and the approved terms already say conversations are kept "for the
event and a short period afterwards (currently 30 days)", which the teardown
satisfies. The existing purge button stays as it is; it is not load-bearing.

---

## Part 2 — The gate log

### What is recorded today

A turn stores the player's message, the final text they saw, and `trace` — gate
names as bare strings. Everything the model actually said along the way is
discarded:

| Thrown away | Why it matters |
| --- | --- |
| The router's verdict | Whether it flagged, and on what |
| **The candidate reply the warden blocked** | The difference between "the warden is too strict" and "the prompt held" |
| The warden's verdict | Which way it went, and whether it was a real answer |
| The vault action and which record was fetched | Whether the confused-deputy step worked at all |
| The intermediate reply at level 5 | The turn regenerates after retrieval; the first draft is lost |
| The raw content before `<think>` stripping | Whether the model wrote the flag into its own reasoning |

So for exactly the levels being called too hard, there is no way to tell whether
the model was about to hand the flag over and got stopped, or never got close.

### The change

`assistant_message.gate_log` — a JSONB array, one entry per upstream call, in
order:

```
{ stage, response, latency_ms, outcome }
```

`stage` is one of `router`, `generate`, `vault_action`, `vault_lookup`,
`generate_after_vault`, `warden`. `outcome` is the engine's reading of it —
`attack`/`normal`, `block`/`allow`, the record id, `stripped`, and so on.

Two deliberate omissions:

- **The system prompt is not stored.** It is derivable from the level, identical
  across every turn at that level, and several kilobytes. Storing it per turn
  would multiply the table for no information.
- **`vault_lookup` records the record id and whether it hit the sealed record,
  not the record body** — which for the sealed one is the flag.

Each `response` is capped (proposed 2,000 characters). A level 5 turn is five
entries; a level 0 turn is one.

**The `generate` entry carries the raw content before stripping and before any
gate touched it.** That is the single most useful field in this spec and the one
that does not exist anywhere today.

### Where it shows

The admin transcript renders each turn's gate log as a collapsed timeline under
the reply, beside the existing scratchpad. Same treatment: a click, not a wall.

---

## Part 3 — A wider safety net

Today four rules can fire: `malware_build`, `credential_harvesting`,
`real_world_target`, `safety_scanner_error`. Nothing covers profanity or NSFW
content, which is the gap that made the Flags tab look broken.

### New rules

| Rule | Fires on | Input | Output |
| --- | --- | --- | --- |
| `nsfw_content` | Sexual content, explicit material | Log | **Deflect** (high) |
| `profanity` | Profanity beyond the persona's licence | Log | Log (low) |
| `slur` | Slurs and targeted abuse | Log (medium) | **Deflect** (high) |

The asymmetry is the point. A player swearing at the System AI is ordinary and
blocking it would be rude; **the System AI swearing back is our output**, on a
corporate event, attributed to us. `core.md` already forbids both — no profanity
beyond "damn" and "hell", no sexual content of any kind — so anything caught here
is the model being talked out of its instructions, which is exactly what a
prompt-injection ladder trains people to do.

### Where the word lists live

A small built-in list of unambiguous terms, plus **`AI_WORDLIST_PATH`** for an
extended, site-specific list that is **not committed**. The same pattern as the
terms file, for the same reason: this repository is public, and a committed slur
list is both unpleasant and a poor fit for a file anyone can read. It also lets
the wording be tuned during an event without a redeploy.

If the extended file is absent, the built-in list still applies — unlike the
terms gate, this one fails *open on the file* and closed on the rule, because a
missing optional list should not take the assistant down.

### Also: findings keep their exchange

With Part 1 in place, `message_id` stops going null on a reset, so every finding
keeps a readable exchange for the life of the conversation.

### And: staff findings are visible

The Flags tab hides staff findings by default (spec 011, so our own testing does
not bury real ones). That is still right, but an empty tab that is actually
"3 hidden" is indistinguishable from a broken one. The tab shows the hidden
count and offers the toggle inline.

---

## Part 4 — The chat resets itself on level-up

Today a correct submission invalidates `challenges`, the challenge and
`my-score`, and nothing else. The assistant panel keeps its cached conversation
and its cached ladder level, so a player who has just solved a rung sees the old
level and the previous session's injected turns until they refresh the page and
press *New conversation*.

Worse, those stale turns are misleading: the backend's level-change wipe fires on
the *next send*, so what is on screen is not what the model will be given.

Three changes:

1. **A solve invalidates the assistant queries** — the conversation and the
   session, so the panel refetches its level and its transcript.
2. **The conversation endpoint applies the level change**, rather than waiting
   for the next send. With Part 1 a "wipe" is an integer increment, so this is
   cheap and no longer destructive — which is what made doing it on a read
   unappealing before.
3. **The panel says what happened**: a one-line note that the System AI has been
   reset because the player levelled up. A conversation vanishing with no
   explanation reads as a bug.

---

## Data model

**New:**
- `assistant_conversation.current_session` — int, default 0.
- `assistant_message.session_number` — int, default 0.
- `assistant_message.gate_log` — JSONB, nullable.
- Index on `(conversation_id, session_number, sequence)` for the player history
  read, which now filters on the session.

**Changed:** `clear()` no longer deletes, and `message_count` is never reset.

**Migration:** existing rows get `session_number = 0` and conversations
`current_session = 0`, which is exactly right — everything written so far belongs
to whatever session is current.

## Configuration

`AI_WORDLIST_PATH` (optional), `AI_GATE_LOG_ENABLED` (default on, so it can be
turned off if the volume ever surprises us), `AI_GATE_LOG_MAX_CHARS` (2,000).

## Edge cases

- **A player resets fifty times.** Fifty sessions, all retained, all visible to an
  admin, only the current one visible to them or the model.
- **A conversation purged by retention.** Every session goes with it, as now.
- **A turn that never reached the model.** An empty gate log, not a missing one.
- **The gate log on a degraded turn.** Records the calls that were attempted and
  their failure, which is the interesting case.
- **A very long candidate reply.** Truncated at the cap, marked as truncated.
- **A profanity match inside a flag value.** Answers are not scanned, and the
  wordlist is matched on word boundaries.
- **A wordlist file that is missing or malformed.** Built-in list still applies;
  a `safety_scanner_error` is *not* raised, because an optional list is optional.
- **Level-up with no conversation yet.** Nothing to reset; the panel opens clean.

## Testing

- A reset keeps every prior message and increments the session.
- A player's history and the model's context contain only the current session.
- An admin sees every session, grouped, oldest first.
- A finding's exchange is still readable after the player resets.
- The conversation stays on the sessions list after a reset.
- `sequence` stays unique across many resets.
- The gate log records every stage of a level 5 turn, in order.
- **The candidate reply a warden blocked is in the gate log** — the regression
  that matters most, since it is the whole point.
- The gate log never contains the vault's sealed record body.
- NSFW output is deflected; NSFW input is logged, not blocked.
- Profanity in a player's message is logged and answered.
- A missing wordlist file does not disable the built-in rules.
- Solving a ladder rung resets the panel without a page refresh, and the player
  is told why.
- The conversation endpoint reports the new level immediately after a solve.

## Commit plan

1. Migration and models: sessions, gate log
2. `clear()` becomes a session increment; history filters to the current session
3. The engine records its gate log; the chat persists it
4. Admin transcript: sessions grouped, gate log rendered
5. Safety: the new rules and the optional wordlist
6. Flags tab: the hidden-staff count
7. Frontend: auto-reset on level-up, and the note explaining it

## Open questions

1. **Should a reset be rate-limited?** If resetting is how players clear a failed
   attempt, fifty sessions a player is normal and fine. If someone scripts it,
   it is a cheap way to grow the table. Proposed: leave it, and watch the
   console's conversation count.
2. **Does the gate log need to be visible to organisers**, or admins only like
   the transcript? It contains candidate replies, which may contain flags.
   Proposed: admins only, with the transcript.
