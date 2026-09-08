# Spec 015 — Character Sheet, XP, Levels & Skills

Status: **approved** (2026-09-07) — build
Phase: 2 (D&D Mechanics — the foundation)
Covers: `Plan.md` Phase 2 → character sheets, stat blocks tied to categories, leveling/XP
Depends on: 003 (challenges/scoring/categories), 004 (hints), 005 (scoreboard)

## Why this is first

Classes, the dungeon-map board, boss encounters and loot all read from one thing:
a character with XP, a level, and skills. This spec builds that. Everything is
**one number** — XP — so there is nothing confusing to reconcile: XP is the score,
the ranking, and what levels are derived from.

## XP is one number, banked at solve

- **Each challenge awards XP.** How much is the challenge's own value: a **flat**
  challenge (static scoring) is worth its points to everyone; a **decaying**
  challenge (dynamic scoring) is worth its value *at the moment you solve*. This
  is exactly the `static` / `dynamic` mode a challenge already has — nothing new
  to configure.
- **A hint reduces the reward, not your balance.** Unlocking a hint costs nothing
  when you take it; instead, when you solve, the hints you unlocked on that
  challenge are subtracted from the XP that solve awards. So a hint on a challenge
  you never solve is free, and a hint you do use is paid for out of the reward —
  "the cost is the smaller prize." This replaces Phase 1's charge-immediately
  hint economy.
- **XP awarded** on a solve = `max(0, challenge value at solve − hints unlocked
  on it)`, **banked** on the solve row and never changed afterward.

Banked XP is **monotonic**: solving only ever adds, and nobody de-levels because a
challenge they cleared later got easier. This is the deliberate departure from
Phase 1's live-recomputed board, and it is the only model under which levels make
sense. (Admin score adjustments still apply and can move a total — a correction is
allowed to.)

## Skills: categories feed them, many-to-one

A **skill** is a distinct thing a player can be good at — *Hacking*, *Forensics*,
*Crypto*. **Categories map into skills**, and several categories can feed the same
one: "AI Prompt Injection" and "Red Teaming" both feed **Hacking**.

- A solve's XP flows to the skill its challenge's category maps to.
- **Skill XP** = the sum of a player's banked XP for solves whose category maps to
  that skill.
- A category that is not yet mapped to a skill (a fresh one typed during challenge
  creation) still contributes to the player's **overall** XP; it just does not
  appear under a named skill until an admin maps it.

## One pool, counted once

**Total XP = the sum of every banked solve, full stop.** Skill XP is a *slice* of
that same pool — each solve belongs to one category, which maps to at most one
skill, so the skill totals partition the whole and nothing is counted twice.

- **Overall level** is derived from **total XP** — this is the ranking.
- **Skill level** is derived from that **skill's XP** — this shows where a player
  excels.

They are never summed together; they are two views of one pool.

## Levels: a standard curve

Level `L` is reached at cumulative XP `base · L · (L − 1)` (with `base` = 100 by
default and configurable): L2 at 200, L3 at 600, L4 at 1200, L5 at 2000, L10 at
9000 — a standard quadratic ramp that makes each level harder than the last. The
same curve maps XP → level for both the overall total and each skill, so a level
means the same amount of work wherever it appears. The sheet shows progress to the
next level.

## Parties

Unchanged in spirit from Phase 1 — union of distinct solves, identical ceiling for
a party of 1 and of 8. Applied to XP: over the party's distinct solved challenges,
each contributes the banked XP of the **earliest** party solve; the party's
overall level and skill levels derive from those unions. The party board shows
combined level and the party's **strongest skills**.

## Data model

- **`solve.xp_awarded`** (int, not null) — the banked snapshot. Backfilled for any
  existing solves as the challenge's value at migration time minus hints (best
  effort; the event has not run for real yet).
- **`skill`** — `name` (unique), `display_order`, `description` (nullable, for
  later flavour).
- **`category.skill_id`** — nullable FK to `skill`. `ON DELETE SET NULL`, so
  deleting a skill un-maps its categories rather than destroying them.
- **Config**: `XP_LEVEL_BASE` (default 100).
- **User** gains nothing here; `character_class` is spec 016.

## Backend changes

- **Submission** banks `xp_awarded` (value − hints) on the solve, and the hint
  economy moves here — Phase 1's immediate hint deduction from score is removed.
- **Scoring** becomes: total XP = `sum(solve.xp_awarded) + adjustments`; skill XP
  grouped by the category→skill map; the level curve; overall and skill levels.
  The live decay curve is kept only for **display of a challenge's current value**
  (what a new solver would earn) and for computing the snapshot at solve time.
- **Scoreboard** ranks by total XP and carries each entry's overall level; the
  party board carries combined level and top skills.

## API

- `GET /api/character/me` — total XP, overall level and progress, and per-skill
  `{skill, xp, level, progress}`, plus board rank.
- `GET /api/character/{user_id}` — another player's public sheet (level, skills).
- `GET`/`POST`/`PATCH`/`DELETE` `/api/admin/skills` and a way to map a category to
  a skill.
- Scoreboard responses gain `level`.

## Frontend

- A **Character sheet** page (own, and viewable for others via a name on the
  board): overall level with an XP bar, and a row per skill with its level and
  bar. Class is a labelled placeholder until 016.
- An admin **Skills** page: create/rename/delete skills, and assign each category
  to a skill (a list of categories each with a skill selector).
- The **scoreboard** shows each entry's level beside its XP.

## Testing

- A solve banks XP equal to the challenge's value at that instant minus the hints
  used; a later solve by someone else does not change it (monotonic).
- A hint taken but not used (challenge unsolved) costs nothing; a hint used
  reduces that solve's award and cannot push it below zero.
- Total XP is the full sum; skill XP partitions it; an unmapped category's XP is
  in the total but under no skill.
- The curve maps XP → level at the documented thresholds, for both overall and
  skills.
- Two categories mapped to one skill both raise it; deleting a skill un-maps its
  categories without losing their XP.
- Party XP counts a shared challenge once and holds the equal-ceiling rule.
- The sheet returns correct skills/levels; another player's sheet omits private
  fields.

## Commit plan

1. Schema: `solve.xp_awarded`, `skill`, `category.skill_id`, config; migration +
   backfill.
2. Submission banks XP and the deferred-hint economy.
3. Scoring & scoreboard: total/skill XP, the curve, levels, ranking by XP.
4. Admin skills API + the category→skill mapping.
5. The `/character` endpoints.
6. Frontend: the character sheet, the admin skills page, level on the board.

## Non-goals (later Phase 2 specs)

- **Classes** (016), **dungeon-map board** (017), **boss encounters** (018),
  **loot** (019). This spec is the sheet they read.

## Decisions to confirm

1. **The hint rework** — hints stop charging immediately and instead reduce the
   XP a solve awards (free until used). Confirmed by your description; flagging
   because it changes spec 004's economy.
2. **The curve** `base · L · (L−1)`, base 100 — confirm the shape / speed, or a
   different standard curve.
3. **Admin score adjustments still move total XP** (and so can change a level) —
   recommended, since they are deliberate corrections. Confirm, or keep
   adjustments off the XP/level track.
