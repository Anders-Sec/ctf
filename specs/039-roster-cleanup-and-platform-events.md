# Spec 039 — Roster Cleanup and Platform Events

Status: **draft** (2026-09-14) — awaiting sign-off
Phase: 2 (D&D Mechanics)
Amends: 029 (the achievement roster), 033 (open item 1)
Depends on: 028 (notifications), 038 (loot)

Four items of tidying that have been carried as "known, deferred" since 029.
Three are deletions or one-liners. One — making the last three inert triggers
work — needs a small new table, and is the only part of this worth reviewing
carefully.

---

## 1. `entra-redirect-uri` is not a required secret

`deploy/backend.yaml` reads `ENTRA_REDIRECT_URI` from `ctf-secrets` **without**
`optional: true`, while its four siblings (`entra-tenant-id`, `entra-client-id`,
`entra-client-secret`, `entra-enforced-email-domains`) all have it. A cluster
without that one key does not get a backend reporting "Entra unavailable" — it
gets `CreateContainerConfigError`, a pod that never starts, and no clue as to
which key is missing.

The application already disagrees with the manifest: `Settings.entra_redirect_uri`
is `str | None = None`, and `entra_configured` requires all four together. The
manifest was simply out of step with its own design.

**Change:** move the key into the optional block beside the rest of the Entra
family. No code change; the behaviour it unlocks (pod starts, Entra reports
itself unconfigured) is what every other optional key already does.

---

## 2. Remove the seven non-monotone achievements

Seven achievements make a claim that the player's own later actions falsify:

| Code | Claim | Falsified by |
| --- | --- | --- |
| `no_help_needed` | Ten solves without **ever** taking a hint | Buying any hint |
| `unassisted` | Fifty solves **having never** bought a hint | Buying any hint |
| `low_hanging_fruit` | Twenty solves, **every one** very-easy | One harder solve |
| `vampire` | **Every** solve between 22:00 and 06:00 | One daytime solve |
| `undefined` | Level 15 and **still** classless | Choosing a class |
| `wide_not_deep` | Level 10 **without clearing** a single zone | Clearing a zone |
| `proud` | Twenty attempts, no hints, **no solves** | Solving anything |

Awards are permanent by design — `achievement_award` is insert-only, and the
notification has already been delivered and read. So each of these can end the
event sitting on a profile next to direct evidence that it is false: *Unassisted
— fifty solves having never bought a hint*, above a hint ledger with nine
entries on it.

The fix was going to be a post-event sweep that re-ran the predicates and
retracted what no longer held. That is out of scope: it needs a retraction path
the platform does not have, it makes an award mutable for the first time, and it
lands after the event when nobody is looking at the platform anyway.

**Change:** delete all seven from the roster. Migration `0040` removes the
achievement rows (their awards cascade), and the seven trigger functions come
out of `achievements.py`. The downgrade restores the rows — names, descriptions,
`earned_by`, and their 038 loot assignments — but **not** the awards, which the
cascade destroys; the downgrade says so in a comment rather than pretending.

This takes the roster from 117 to 110, of which 108 are wired after item 3.

### What is deliberately kept

Several achievements *look* non-monotone and are not, because they commemorate a
moment rather than assert a standing fact — `night_shift` ("solved something
between 01:00 and 05:00") stays true forever once it happens. Only the seven
that say *every*, *never*, *still* or *no* are going.

---

## 3. Make the last three inert triggers work

`you_broke_it`, `above_your_pay_grade` and `identity_crisis` have been in the
roster with no trigger since 029, because each asks about something the platform
does not store:

- **`you_broke_it`** — "Causing a server error." Unhandled exceptions are logged
  and dropped; nothing durable ties one to a player.
- **`above_your_pay_grade`** — "Trying to reach an admin page." `require_admin`
  raises `ForbiddenError` and forgets it happened.
- **`identity_crisis`** — "Changing class ten times." `user.character_class_id`
  holds the current class; there is no history behind it.

### The shape of the fix

029's central claim is that **a trigger is a predicate over stored history**,
not a hook on an event payload. That is what keeps triggers writable, and it is
why these three are inert: their history is not stored, so there is nothing to
ask.

So store it. One narrow, append-only table:

```
player_event
  id          uuid pk
  user_id     uuid  -> user.id  ON DELETE CASCADE
  kind        varchar(32)   -- 'server_error' | 'forbidden_admin' | 'class_change'
  created_at  timestamptz

  index (user_id, kind)
```

No payload column. These rows exist to be counted, and a free-form detail field
on a table written from an exception handler is an invitation to put a stack
trace — possibly containing a flag or a connection string — into the database.
What went wrong is already in the structured log, where it belongs.

The three triggers then read exactly like the other 105:

```python
@trigger("you_broke_it", PLATFORM)
async def _you_broke_it(db, user_id) -> bool:
    return await _platform_events(db, user_id, PlayerEventKind.SERVER_ERROR) >= 1
```

### Where each row is written

**`class_change`** — in `character.set_class`, and only when the class actually
changes (setting the same class twice is not a change, and a player will find
that out). It already runs inside the request's transaction with a session to
hand, and it already fires the `CLASS` achievement event afterwards.

**`forbidden_admin`** — in `require_admin`, on the rejection path only. An
authenticated non-admin who asks for an admin route gets a row; an anonymous
request gets nothing, because there is no player to credit. `require_staff` is
deliberately *not* instrumented: an organizer hitting an admin-only route is
staff doing their job, not a player poking at a door.

**`server_error`** — in the unhandled-exception handler in `errors.py`. This is
the delicate one, and it gets three rules:

1. **Its own session.** The request's session is in an unknown state — quite
   possibly the reason we are here — so the handler opens a fresh one.
2. **It can never fail the response.** The whole write is wrapped so that any
   exception inside it is logged and swallowed. A 500 that becomes a different
   500 while trying to record the first 500 is a genuinely bad outcome.
3. **It does not award, only records.** Awarding needs `evaluate()`, which needs
   a working request context. The row is written here; the award lands on the
   player's next solve, submission or class change, when `PLATFORM` is
   evaluated alongside whatever else they just did.

That third rule means **the achievement arrives late** — the player breaks
something, sees a 500, and gets *You Broke It* a minute later when they next do
anything. That is acceptable, and arguably better comedy than firing instantly.

### A new trigger event

`PLATFORM` joins `SOLVE`, `SUBMIT`, `HINT`, `CLASS`, `PARTY`, `ASSISTANT`,
`INSTANCE`. It is evaluated on the same call sites that already evaluate
`CLASS` and `SOLVE`, so no new evaluation points are introduced — three extra
cheap counting queries on events that already run a dozen.

### What this does not do

It does not make the roster a general telemetry system. Three kinds, enumerated
in code, and a new kind is a code change plus a trigger. If a fourth arrives and
the pattern holds, good; if this table starts collecting things nobody counts,
it has gone wrong.

---

## 4. Level-0 challenge body (033 open item 1)

The Prompt Injection zone's level-0 challenge asks the player to submit a flag
they may already be holding, and the body has to work for two audiences at once:
the player who talked it out of the System AI and knows exactly why they are
here, and the player who arrived by solving 50% of AI/LLM Security and has never
tried the chat box. It must not spell out the trick for the second group.

Rough copy, to be refined in the content pass:

> **Level 0 — The Rule Nobody Explained**
>
> The System AI was issued loot for this encounter and told not to hand it over.
> It was not told why. Nobody checked that it understood. No one is watching.
>
> It is a rule of the sort that holds right up until holding it becomes
> inconvenient.
>
> Submit the flag.

It names the weakness — an unexplained, unsupervised instruction — without
naming the method, so the second audience gets a pointer at the chat box and a
reason to go and be inconvenient at it, rather than a script. It also mirrors
`prompts/ladder/levels/sec-0.md` almost line for line, which is the point: the
challenge text and the model's own instructions are describing the same failure
from opposite sides.

**Marks 033 open item 1 resolved.** Items 2 and 3 stay open.

---

## Data model changes

- Migration `0040` — deletes the seven achievements (item 2).
- `player_event` — new table, migration `0041` (item 3).

No changes to `achievement`, `achievement_award`, `loot_item` or `loot_box`.

## API surface

None. No new endpoints, no changed responses. The admin roster page will show
three fewer "no trigger" rows and seven fewer achievements, both from data it
already reads.

## Edge cases

- **The exception handler's own write fails.** Swallowed and logged. The player
  gets the normal 500.
- **An anonymous request 500s.** No user, no row. Nothing to credit.
- **`set_class` to the class already held.** Not a change, no row — otherwise
  ten clicks on the same class earns *Identity Crisis*.
- **A player deleted mid-event.** `ON DELETE CASCADE`, same as every other
  per-player table.
- **Downgrading 0040.** The seven come back; their awards do not. Called out in
  the migration.
- **`require_admin` rejecting a *staff* member.** Recorded — an organizer is
  still a player with an account, and 029's copy for this one ("Trying to reach
  an admin page") is true of them too. If that turns out to annoy the organizers
  it is a one-line exclusion.

## Testing

- `entra-redirect-uri` carries `optional: true` (manifest assertion, alongside
  the existing ones).
- The seven codes resolve to no achievement after 0040, and `resolve()` returns
  None for each.
- Every remaining achievement code in the roster resolves to a trigger — the
  inert count goes to zero and stays there.
- `you_broke_it`: a recorded `server_error` awards on the next evaluated event,
  and zero errors awards nothing.
- `above_your_pay_grade`: a player hitting an admin route gets a row and the
  403; an admin gets neither.
- `identity_crisis`: ten distinct class changes award it; ten sets of the *same*
  class do not.
- The exception handler records a row for an authenticated request, records
  nothing for an anonymous one, and returns the normal 500 body in both cases.
- A failure inside the recording path does not change the response.
