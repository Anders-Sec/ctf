# Spec 018 — Abilities & Skills

Status: **draft** (2026-09-08) — awaiting sign-off
Phase: 2 (D&D Mechanics)
Covers: `Ideas.md` — core abilities, the category→ability map, and the useful/funny
skill lists
Depends on: 015 (banked XP, player levels), 003 (challenges, categories)
**Supersedes** 015's category→skill model and switches off 016's class nudge.

Later specs shift by one: boss encounters and loot become 019/020.

## What changes, and why

015 made a *skill* a coarse grouping that categories fed into — a slice of the one
XP pool. `Ideas.md` splits that idea in two, and both halves are better:

- **Abilities** take over the grouping job, as D&D scores (8–20) rather than
  levels. Each category maps to exactly one ability, so abilities still
  **partition** the pool.
- **Skills** become per-*challenge* and much more numerous — 73 of them, useful
  and funny. A challenge carries several; solving it feeds each one.

Both are **cosmetic**. Nothing here touches ranking, and total XP is still the sum
of banked solves — the invariant 015 and 016 both hold, and this spec keeps.

## The XP tracks, stated plainly

| Track | Relationship to the pool | Visible? |
| --- | --- | --- |
| **Player level** | The pool itself | Level **and** an XP bar |
| **Ability score** | A **partition** — one category, one ability | Score only, **no** progress |
| **Skill level** | **Parallel and overlapping** — every attached skill gets the *whole* solve | Level only, **no** XP |

Skills deliberately break "counted once". A challenge with three skills gives its
full XP to all three; splitting it would punish players for challenges that happen
to carry more funny skills. This is safe precisely because **skill XP is never
shown** — there is no number for a player to reconcile against anything.

Abilities and skills both bank the **post-hint** XP, i.e. whatever 015 actually
stored on the solve. There is one XP figure in the system and everything reads it.

---

# Part 1 — Abilities

## The six, and the map

The D&D six: **STR, DEX, CON, INT, WIS, CHA**. Every category maps to exactly one
— **required**, not nullable, because an unmapped category would silently drop its
XP out of the stat block.

| Ability | Categories |
| --- | --- |
| **STR** | Red Teaming, Web Attacks, Identity & Access |
| **DEX** | Hardware Hacking, Mobile Security, Forensics |
| **CON** | Malware Analysis, Incident Response, Reverse Engineering, Cloud Security |
| **INT** | Networking, Crypto, Codes and Ciphers, AI/LLM Security |
| **WIS** | OSINT, Governance Risk & Compliance, Threat Detection, CTI |
| **CHA** | Prompt Injection, Social Engineering, Hacker Game Show |

This is `Ideas.md`'s map with three moves — CTI→WIS, Hacker Game Show→CHA, Cloud
Security→CON — made after modelling the spread: INT originally held 7 of 21
categories, which put nearly every player on INT 18 with flat 13–14 secondaries.
The rebalance gives 4/4/4/3/3/3 and varied stat blocks.

## The score curve

```
score = 8 + floor(sqrt(ability_xp / ABILITY_SCORE_DIVISOR))      capped at 20
```

With the divisor at **28**:

| Score | 8 | 10 | 12 | 14 | 16 | 18 | 20 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Ability XP | 0 | 112 | 448 | 1,008 | 1,792 | 2,800 | 4,032 |

Quadratic, so each point costs more than the last — the D&D feel. At player level
10 (9,000 XP) a main ability holding ~45% of the pool reaches **20**, and a
secondary at ~13% reaches **14**, which are the two anchors from `Ideas.md`.

20 is a **hard display cap**; XP past it still counts toward the player level.

## What players see

The sheet shows a **stat block** — six abilities with their current scores, as a
D&D character sheet would. The score is visible; **progress toward the next point
is not**. No bars, no XP, no "120 to go". A score simply ticks up.

---

# Part 2 — Skills

## Shape

A **skill** belongs to a category (for admin convenience only) and is either
**useful** or **funny**. `Ideas.md` defines 31 useful and 42 funny — 73 in total.

A **challenge carries any number of skills**, chosen by the admin. The category a
skill belongs to does not constrain which challenges can carry it; it only orders
the picker.

Solving a challenge grants that solve's XP to **every** skill on it.

## The level curve

```
level = 0                                          when skill_xp == 0
level = 1 + floor(sqrt(skill_xp / SKILL_LEVEL_DIVISOR))   otherwise, soft cap 15
```

With the divisor at **15**:

| Level | 1 | 2 | 3 | 5 | 10 | 15 |
| --- | --- | --- | --- | --- | --- | --- |
| Skill XP | any | 15 | 60 | 240 | 1,215 | 2,940 |

Fast at the bottom as intended — one 300-XP solve takes a fresh skill to level 5.

**A tuning risk to watch:** with 73 skills across the event's challenges, most
skills will sit on only a handful of challenges, so the XP available to any one
skill is small. If skills end up thinly spread, level 15 becomes unreachable and
the divisor wants lowering. Both divisors are **config**, tunable mid-event
without a migration.

## What players see

A **skills table**: name and current level, nothing else. No XP, no source, no
indication of which challenge fed what. Plus:

- **Locked skills show blurred** at level 0, so a player can see there is more to
  find without learning what. The name stays in the DOM (a CSS blur), which keeps
  it readable to a screen reader — these are flavour, not secrets, and hiding them
  from assistive tech would be a real exclusion for a cosmetic tease.
- **Search** and a **hide funny skills** filter, per `Ideas.md`.

The challenge→skill mapping is never exposed to players on the challenge itself.

## Authoring

The challenge editor's skill picker is a **searchable multi-select over all 73**,
ordered:

1. This category's **useful** skills
2. This category's **funny** skills
3. Everything else, grouped by category

Nothing is pre-selected — the ordering does the work, and search covers the rest.

---

# Part 3 — Seed content

The 21 categories (with ability mappings and descriptions) and all 73 skills ship
as **seed data in a migration**, so a fresh deploy comes up with the real event
structure rather than an empty board.

**Known cost, flagged deliberately:** every test database will then carry 21
categories and 73 skills. A few existing tests assert on exact list contents (e.g.
`test_admin_skills` expects `["Hacking"]`) and will need to assert *membership*
instead. That is a one-time fix and arguably makes those tests better, but it is a
real cost of seeding this way rather than via a separate admin command.

---

## Data model

- **`Ability`** — a Postgres enum (`str`, `dex`, `con`, `int`, `wis`, `cha`).
- **`category.ability`** — the enum, **NOT NULL**. Migration backfills existing
  rows before applying the constraint.
- **`category.skill_id`** — **dropped**; abilities replace it.
- **`skill`** — keeps `name`, `display_order`, `description`; gains
  `category_id` (nullable FK, `ON DELETE SET NULL` so deleting a category leaves
  its skills as "other" rather than destroying them) and `kind`
  (`useful` | `funny`, not null).
- **`challenge_skill`** — the join: `challenge_id`, `skill_id`, unique together,
  both `ON DELETE CASCADE`.
- **`character_class.affinity_skill_id`** — **dropped**. It pointed at 015's
  category-skills, which no longer exist in that shape, and 016's nudge is off
  until the class recommender is designed.
- **Config**: `ABILITY_SCORE_DIVISOR` (28), `ABILITY_SCORE_CAP` (20),
  `SKILL_LEVEL_DIVISOR` (15), `SKILL_LEVEL_CAP` (15).

## Backend

- **Scoring** gains `ability_xp_for_user` (banked XP grouped by the category's
  ability) and a rewritten `skill_xp_for_user` (banked XP joined through
  `challenge_skill`), plus `ability_score()` and `skill_level()`. 015's
  category-based skill XP is removed.
- **The character service** returns the stat block and the skills table.
- Nothing touches submission, the scoreboard, or ranking.

## API

- `GET /api/character/me` — replaces `skills` with:
  - `abilities`: `[{ability, score}]` — score only, no XP, no progress
  - `skills`: `[{skill_id, name, kind, level}]` — **no XP field at all**, so the
    numbers cannot leak through the API even though the UI would not show them
- `GET /api/character/{user_id}` — carries the **stat block only**. Another
  player's skills stay private; the block is the public D&D-character face.
- `GET`/`PATCH` `/api/admin/skills` — gains `kind` and `category_id`.
- `PUT /api/admin/challenges/{id}/skills` — set the challenge's skills in one
  call, `{skill_ids: [...]}`.
- `PATCH /api/admin/categories/{id}` — set a category's ability.

## Frontend

- **Character sheet**: a six-box **stat block** replacing 015's skill bars. Scores
  only. The class line stays; 016's suggested-class nudge is **removed** for now.
- **Skills page**: the table — name and level, blurred at 0, with search and a
  "hide funny skills" toggle.
- **Admin**: the challenge editor's grouped, searchable skill picker; an ability
  selector on categories; `kind`/category on the skills admin page. The class
  page loses its affinity-skill selector.
- **Sample data** is rebuilt on the real categories, abilities and skills.

## Testing

- Abilities **partition**: a solve's XP lands in exactly one ability, and the six
  ability totals sum to the XP from categorised solves.
- Skills **overlap**: a challenge with three skills gives its **full** XP to each.
- Both curves hit the documented thresholds, and both caps hold.
- A skill with no XP is level 0; the first XP takes it to 1.
- The player-facing skill payload contains **no XP field**.
- Another player's sheet has abilities and **no skills**.
- A category cannot be created or saved without an ability.
- Post-hint XP is what feeds abilities and skills, not the challenge's face value.
- The seed migration lands all 21 categories with their abilities and all 73
  skills with the right `kind`.
- **The invariant, again:** total XP, player level, and board rank are unchanged
  by anything in this spec.

## Commit plan

1. Schema: `Ability`, `category.ability`, `skill.kind`/`category_id`,
   `challenge_skill`, drops, config + migration.
2. Seed migration: the 21 categories and 73 skills.
3. Scoring: ability/skill XP and both curves.
4. Admin: category ability, skill CRUD, challenge↔skill assignment.
5. `/character` abilities + skills; 016's nudge switched off.
6. Frontend: stat block, skills page, admin pickers; sample data rebuilt.

## Non-goals

- **The class recommender.** Your class list is still being written. When it
  lands, my strong recommendation is a **deterministic ranking over the player's
  top skills, voiced by the System AI** through 016's narrator seam — reproducible,
  no latency or cost, no guardrail surface, and it cannot recommend a class that
  does not exist. The LLM should narrate the choice, not make it.
- **Abilities or skills doing anything mechanical.** Cosmetic for now, by
  decision; the boss/loot specs can read them.
- **District themes for the map.** Now unblocked (the categories exist), but it is
  its own spec.

## Decisions — resolved (2026-09-08)

1. Skills are a **parallel overlapping track**; abilities **partition**; player
   total is still solves only.
2. Abilities are **scores** (8–20, soft-capped at 20), not levels, with the
   progress hidden and the score shown.
3. Category→ability is **required**, using the rebalanced map above.
4. Abilities and skills are **cosmetic**.
5. Skills start at **0 and render blurred**, soft cap **15**.
6. Players see **name and level only**, with search and a funny-skill filter.
7. Content ships as **seed data in a migration**.
8. The skill picker is **searchable with category skills sorted to the top**,
   nothing pre-selected.
9. 016's class **suggestion is switched off** until the recommender is designed.
10. Sample data is **wiped and rebuilt**.
