# Spec 016 — Character Classes

Status: **draft** (2026-09-07) — awaiting sign-off
Phase: 2 (D&D Mechanics)
Covers: `Plan.md` Phase 2 → classes
Depends on: 015 (character sheet, XP, levels, skills), 013 (System AI persona —
the voice the class nudge is written in)
Read by (later): 018 (boss encounters), 019 (loot) — a class is an archetype
those specs can gate or theme on.

## Why this, and why it must stay light

015 built the sheet — one XP pool, an overall level, and skills as slices of that
pool. A **class** is the archetype layered on top: *Rogue*, *Wizard*, *Cleric*.
It is the answer to "what kind of adventurer am I," not a second scoreboard.

The hard rule carried from 015: **class must not touch scoring.** XP stays one
number, counted once. A class does not grant XP, does not change a level, and does
not reorder the board. If it did, we would be back to the "two totals to
reconcile" confusion 015 deliberately removed. A class's payoff is **identity now**
and **mechanical hooks later** (a boss that favours one class, loot themed to it) —
never a scoring edge.

## What a class is

- An **admin-defined archetype**: a name, a short description/flavour line, a
  display order, and an optional **affinity skill** (the skill this class is
  "about" — Rogue→Hacking, Wizard→Crypto). Managed exactly like skills in 015.
- A **player has at most one class**, chosen by the player from the roster the
  admins publish. Nullable — a player without a class is simply "Classless" /
  "Adventurer" on the sheet until they pick one.
- The affinity skill is **flavour and a nudge**, not a multiplier. It drives the
  *suggested* class (below) and gives later specs something to theme on; it never
  changes how much a solve in that skill is worth.

## Choosing a class

- **Earned at a level.** A class is a milestone, not a starting choice: a player
  cannot pick one until their **overall level** reaches `CLASS_UNLOCK_LEVEL`
  (config, default **3**). Below that the sheet shows the class as locked with the
  level needed. The gate reads the same overall level 015 derives from total XP —
  no new computation.
- **Self-service, and freely changeable once unlocked.** Above the threshold a
  player sets, changes, or clears their own class from the character sheet, as
  often as they like. No admin approval and no lock-in — there is nothing to
  exploit because class has no scoring effect, and re-speccing is part of the fun.
  A change rewrites `user.character_class_id`; nothing downstream is recomputed.
  (A player who unlocked and chose a class does not lose it if a later admin
  adjustment drops them back below the threshold — the gate is on *changing* the
  class, not on keeping one already earned.)
- **Optional.** Classless is a valid, permanent state; nothing blocks a player who
  never picks. A player past the threshold who clears their class simply returns
  to Classless.
- A **suggested class** is computed for the sheet: the class whose affinity skill
  is the player's **highest-XP skill**. It is a hint shown next to the picker,
  never applied automatically, and shown even while the picker is still locked
  (something to aim at). Ties break on the skill's, then the class's, display
  order. A player with no skill XP, or whose top skill maps to no class, gets no
  suggestion.

## The nudge is the System AI speaking

Narratively the suggestion is **not** a neutral UI tooltip — it is the **System
AI** (spec 013) commenting on what it has watched the player do. The System AI
built every challenge and takes dry satisfaction in watching people work against
it; noticing that someone keeps going after the same kind of target, and naming
the archetype that fits, is exactly its voice.

Two rules make this safe and cheap:

- **Deterministic copy, not a model call.** The line is a server-side template in
  the System AI's persona — filled from the structured suggestion (the top skill
  and the class it points to). No LLM request, so no latency, no token cost, no
  guardrail surface, and no path for a challenge answer to reach a prompt. It is
  the System AI's *voice*, not its *reasoning*.
- **Persona, per spec 013.** Terse, plain text (no markdown), real security terms
  over adventure-game metaphor. e.g. *"You keep hammering web and injection
  targets. The Rogue build fits — take it or don't."* The copy lives in **one
  place** server-side so the coming narrative overhaul can own and restyle every
  narrated line at once; 016 adds just this first one.

The frontend renders the line **attributed to the System AI** — the same name and
persona treatment the assistant panel already uses — not as anonymous grey hint
text.

## Data model

- **`character_class`** — `name` (unique, CITEXT), `display_order`, `description`
  (nullable), `affinity_skill_id` (nullable FK → `skill`, `ON DELETE SET NULL`,
  so deleting a skill un-links it rather than deleting the class).
- **`user.character_class_id`** — nullable FK → `character_class`,
  `ON DELETE SET NULL`, so deleting a class un-assigns its players (they become
  Classless) rather than cascading into user rows.
- **Config**: `CLASS_UNLOCK_LEVEL` (default 3) — the overall level at which a
  player may choose a class.
- No change to solves, scoring, or the scoreboard. This spec adds one column to
  `user` and one new table.

## Backend changes

- **Class service** mirroring 015's skill service: list / create / update /
  delete classes; a helper to compute a player's suggested class from
  `skill_xp_for_user` (reuse 015 — do not recompute skill XP a second way).
- **A narrator seam** — one small server-side helper that turns the structured
  suggestion (top skill + class) into the System AI's voiced line. Deterministic,
  no model call. It is deliberately the *only* place this copy lives, so the
  narrative overhaul can later route every narrated mechanic through the same
  seam without a rewrite here.
- **Character sheet** (`/character/me`) gains the player's `class` (id, name,
  affinity skill) and their `suggested_class` — the structured suggestion
  (`class_id`, `name`, `from_skill`) **plus** the System AI's voiced
  `narration` string. The public sheet (`/character/{user_id}`) gains `class`
  only — the suggestion is the player's own business, like their fine-grained
  progress.
- **Set-class endpoint** validates the class exists, enforces the unlock level
  (a player below `CLASS_UNLOCK_LEVEL` who does not already have a class is
  refused with a clear "reach level N first" error), and writes
  `character_class_id`; setting it to null clears it.
- The sheet reports whether the picker is unlocked (`class_unlocked` +
  `class_unlock_level`) so the frontend can show the gate without re-deriving it.

## API

- `GET`/`POST`/`PATCH`/`DELETE` `/api/admin/classes` — admin CRUD (reads open to
  organizers, writes admin-only), same shape as `/api/admin/skills`.
- `PUT /api/character/class` — body `{class_id: uuid | null}`; the player sets or
  clears **their own** class. (Not an admin route; acts on the caller.)
- `/api/character/me` response gains `class`, `suggested_class`, `class_unlocked`
  and `class_unlock_level`; `/api/character/{user_id}` gains `class`.

## Frontend

- **Character sheet**: replace the "Class TBD" placeholder from 015 with the real
  class — the chosen class name in the header, and a **picker** (a select of the
  published classes plus "Classless") that saves on change. Below the unlock
  level the picker is disabled with a "Reach level N to choose a class" note; the
  suggested-class nudge shows either way, **attributed to the System AI** (its
  name and persona treatment, reusing the assistant panel's styling), not as
  anonymous hint text. Another player's sheet shows their class as a static label,
  no picker and no nudge.
- **Admin Classes page**: create / rename / delete classes and set each class's
  affinity skill (a skill selector per class) — the twin of the 015 Skills page.
  A "Classes" link in the admin nav.

## Testing

- A player at or above `CLASS_UNLOCK_LEVEL` sets their own class and it appears on
  their sheet; setting it to null clears it back to Classless.
- A player **below** the unlock level is refused with the "reach level N" error and
  the sheet reports `class_unlocked: false`; a player who already earned a class
  keeps it even if an adjustment later drops them below the threshold.
- A player cannot set another player's class; a non-existent class id is refused.
- Admin CRUD: only admins write, organizers read; deleting a class un-assigns its
  players (they read back Classless) and deleting a skill un-links it as an
  affinity without deleting the class.
- The suggested class tracks the player's **top skill**; solving into a different
  skill enough to overtake changes the suggestion; no skill XP → no suggestion.
- The suggestion's `narration` is **deterministic** (identical for the same
  suggestion across calls — asserting it makes no model call), names the suggested
  class, and is plain text (no markdown), i.e. in the System AI persona. It is
  absent when there is no suggestion.
- Class has **no scoring effect**: a player's total XP, level, and board rank are
  identical before and after choosing, changing, or clearing a class. (This is the
  regression that guards the one-number invariant.)
- The public sheet shows class but not the suggestion.

## Commit plan

1. Schema: `character_class` table, `user.character_class_id`, migration.
2. Admin classes API + service (CRUD, affinity skill).
3. Player set-class endpoint + sheet fields (`class`, `suggested_class` incl. the
   System AI `narration`) + the narrator seam.
4. Frontend: class picker on the sheet, the System-AI-attributed nudge, admin
   Classes page, admin nav link.

## Non-goals (later Phase 2 specs)

- **Class abilities / mechanical effects** — a class doing something (a boss that
  is weak to Rogues, class-locked loot) belongs to the specs that introduce those
  systems (018 boss encounters, 019 loot), which will *read* the class this spec
  stores. 016 is identity + roster only.
- **The dungeon-map board** (017) is independent and can land before or after this.
- **The narrative overhaul** — a broader pass that routes game events through the
  System AI's voice — is its own coming spec. 016 adds only the single voiced
  class nudge, deliberately behind a one-place narrator seam so that pass can own
  and expand it without reworking this spec.

## Decisions — resolved (2026-09-07)

1. **Identity-only, no mechanical effect in 016.** A class is flavour + an
   archetype later specs read; it never changes scoring, protecting 015's
   one-number model. *(Confirmed — recommended default.)*
2. **Selection policy: unlocked at a level.** A player cannot choose a class until
   overall level `CLASS_UNLOCK_LEVEL` (default 3); once unlocked it is
   self-service and freely changeable. *(Chosen.)*
3. **The suggested-class nudge: included.** The sheet shows "your deeds suggest…"
   from the player's top skill's affinity class. *(Chosen.)*
4. **A class is optional.** Classless is a valid, permanent state; nothing blocks a
   player who never picks. *(Chosen.)*
5. **Parties have no class.** Class is personal; a party is a mix of archetypes.
   *(Confirmed — recommended default.)*

## Open sub-question

- **`CLASS_UNLOCK_LEVEL` default** is set to **3** (config-tunable without a
  migration). Say if you want a different starting value; it can also be changed
  live once the config surface exists.
