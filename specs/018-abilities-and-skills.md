# Spec 018 — The XP Economy, Abilities & Skills

Status: **done** (2026-09-08) — built across seven commits (difficulty ladder,
schema, seed content, scoring, admin surface, character endpoints, frontend)
Phase: 2 (D&D Mechanics)
Covers: `Ideas.md` — difficulty-driven XP, core abilities, the category→ability
map, and the useful/funny skill lists
Depends on: 015 (banked XP, player levels), 003 (challenges, categories, scoring)
**Supersedes** 015's category→skill model. **Amends** 003's difficulty/points
model and 016's class unlock level.

Later specs shift by one: boss encounters and loot become 019/020.

## What changes, and why

Three things, in the order they depend on each other:

1. **XP is derived from difficulty**, not typed per challenge — so the economy is
   knowable in advance rather than emergent.
2. **Abilities** take over 015's grouping job, as D&D scores (8–20). Each category
   maps to exactly one, so abilities **partition** the pool.
3. **Skills** become per-*challenge* and numerous — 73 of them, useful and funny.
   A challenge carries several; solving it feeds each one.

Abilities and skills are **cosmetic**. Nothing here touches ranking, and total XP
is still the sum of banked solves — the invariant 015 and 016 hold, and this
spec keeps.

---

# Part 0 — The XP economy

## Difficulty sets the value

A challenge's XP is `difficulty modifier × XP_BASE`, with the base at **10**. The
difficulty ladder replaces 003's four-value enum:

| Difficulty | Modifier | XP ceiling |
| --- | --- | --- |
| Very Easy | 5 | 50 |
| Easy | 10 | 100 |
| Medium | 15 | 150 |
| Hard | 20 | 200 |
| Very Hard | 25 | 250 |
| Nearly Impossible | 50 | 500 |

Derived, not merely suggested: an admin picks a difficulty and the value follows.
That is the deliberate change from "difficulties that guide but don't enforce".

## The shape of the event

Roughly 2 challenges per difficulty per category, with at most 1 Nearly
Impossible — about 11 challenges and **2,000 XP per category**, so **231
challenges and 42,000 XP** across 21 categories, averaging 182 XP each. Easier
categories may omit the top difficulties and harder ones the bottom; these are the
planning numbers, not a constraint the code enforces.

## Player levels: 015's curve, unchanged

015's `base · L · (L−1)` with base 100 already lands **level 2 at 200 XP** — four
Very Easy challenges, exactly the target. Against the real economy:

| | L5 | L7 | L10 | L15 | L20 | L21 |
| --- | --- | --- | --- | --- | --- | --- |
| XP | 2,000 | 4,200 | 9,000 | 21,000 | 38,000 | 42,000 |
| Solves | 11 | 23 | 50 | 116 | 209 | 231 |
| Of all content | 5% | 10% | 21% | 50% | 90% | 100% |

**Level 20 is capped**, and it falls at ~90% completion — so the D&D maximum
drops out of the economy rather than being imposed on it. XP past 20 still counts
for ranking; the level simply stops.

## Knock-on to 016

`CLASS_UNLOCK_LEVEL` moves **3 → 5**. Level 5 is ~11 solves, so nearly everyone
who engages unlocks a class; and because 016 already allows free re-speccing after
unlock, an early gate costs no accuracy — players re-pick as their skills sharpen.

## Decay: the top two tiers only

Very Hard and Nearly Impossible are the tie-breakers, and decay is what breaks
ties — so difficulty **defaults** the scoring mode: those two to `dynamic`,
everything else to `static`. It stays a per-challenge setting the admin can
override, because on the day you may need to break a tie some other way.

`minimum_points` becomes **40% of the ceiling** — a Very Hard challenge floors at
100, a Nearly Impossible one at 200 — replacing the flat 100.

---

# Part 1 — Abilities

## The six, and the map

**STR, DEX, CON, INT, WIS, CHA.** Every category maps to exactly one — **required**,
because an unmapped category would silently drop its XP out of the stat block.

| Ability | Categories |
| --- | --- |
| **STR** | Red Teaming, Web Attacks, Identity & Access |
| **DEX** | Hardware Hacking, Mobile Security, Forensics |
| **CON** | Malware Analysis, Incident Response, Reverse Engineering, Cloud Security |
| **INT** | Networking, Crypto, Codes and Ciphers, AI/LLM Security |
| **WIS** | OSINT, Governance Risk & Compliance, Threat Detection, CTI |
| **CHA** | Prompt Injection, Social Engineering, Hacker Game Show |

`Ideas.md`'s map with three moves — CTI→WIS, Hacker Game Show→CHA, Cloud
Security→CON — made after modelling the spread: INT originally held 7 of 21
categories, putting nearly every player on INT 18 with flat 13–14 secondaries.

## The score curve

```
score = 8 + floor(sqrt(ability_xp / ABILITY_SCORE_DIVISOR))      capped at 20
```

Divisor **28**:

| Score | 8 | 10 | 12 | 14 | 16 | 18 | 20 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Ability XP | 0 | 112 | 448 | 1,008 | 1,792 | 2,800 | 4,032 |

Verified against the real economy: at player level 10, a focused player reaches
**20** and a broad one sits **14–15** — the anchors from `Ideas.md`. A
completionist would run past 20 on raw XP and is capped there.

## What players see

A **stat block** — six abilities with their scores, as a D&D sheet. The score is
visible; **progress toward the next point is not**. No bars, no XP.

---

# Part 2 — Skills

## Shape

A skill belongs to a category (admin convenience only) and is **useful** or
**funny** — 31 and 42 respectively, per `Ideas.md`. A **challenge carries any
number of skills**; the skill's category does not constrain which challenges may
carry it, it only orders the picker.

Solving a challenge grants that solve's XP to **every** skill on it. Skills
deliberately break "counted once" — splitting would punish players for challenges
that happen to carry more funny skills. It is safe because **skill XP is never
shown**: there is no number to reconcile.

## The level curve

```
xp for level L = SKILL_LEVEL_BASE × (L − 1) ^ 1.25       soft cap 15
```

Base **70**:

| Level | 2 | 3 | 4 | 5 | 8 | 10 | 12 | 15 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Skill XP | 70 | 166 | 276 | 396 | 797 | 1,091 | 1,402 | 1,896 |

What one challenge is worth to a fresh skill:

| | Very Easy | Easy | Medium | Hard | Very Hard | Nearly Impossible |
| --- | --- | --- | --- | --- | --- | --- |
| Level reached | 1 | 2 | 2 | 3 | **3** | 5 |

A single Very Hard now gives **3**, not 5 — the earlier `sqrt` curve was too
generous at the bottom. Level 15 lands near 1,900 XP, about what one skill
collects when a player clears its whole category.

Both this and the ability divisor are **config**, tunable mid-event without a
migration.

## What players see

A **skills table**: name and level, nothing else — no XP, no source, no hint of
which challenge fed what.

- **Undiscovered skills are redacted server-side.** The API returns placeholder
  text for any skill at level 0; the real name never reaches the browser, so it
  cannot be dug out of devtools. Some skills are meant to be rare surprises, and a
  CSS blur over the real string would leak every one of them.
- They render as **blurred rows inline** in the table, so the shape of what is
  left to find is visible without the content.
- **Search** and a **hide funny skills** filter. Search matches discovered skills
  only — a placeholder has nothing to match.

The challenge→skill mapping is never exposed to players.

## Authoring

The challenge editor's skill picker is a **searchable multi-select over all 73**,
ordered: this category's **useful** skills, then its **funny** ones, then
everything else grouped by category. Nothing is pre-selected — the ordering does
the work and search covers the rest.

---

# Part 3 — Seed content

The 21 categories (with abilities and descriptions) and all 73 skills ship as
**seed data in a migration**, so a fresh deploy comes up with the real structure.

**Known cost:** every test database then carries them, and a few tests that assert
exact list contents (e.g. `test_admin_skills` expecting `["Hacking"]`) must assert
*membership* instead. A one-time fix, and arguably better tests.

---

## Data model

- **`Ability`** — Postgres enum (`str`, `dex`, `con`, `int`, `wis`, `cha`).
- **`category.ability`** — the enum, **NOT NULL** (backfilled, then constrained).
- **`category.skill_id`** — **dropped**; abilities replace it.
- **`Difficulty`** — replaced by the six-value ladder; `challenge.initial_points`
  becomes **derived** from it.
- **`skill`** — gains `category_id` (nullable FK, `ON DELETE SET NULL`, so a
  deleted category leaves its skills as "other") and `kind` (`useful` | `funny`).
- **`challenge_skill`** — join table; unique pair, both `ON DELETE CASCADE`.
- **`character_class.affinity_skill_id`** — **dropped**. It pointed at 015's
  category-skills; the real recommender will define its own mapping.
- **Config**: `XP_BASE` (10), `ABILITY_SCORE_DIVISOR` (28), `ABILITY_SCORE_CAP`
  (20), `SKILL_LEVEL_BASE` (70), `SKILL_LEVEL_CAP` (15), `PLAYER_LEVEL_CAP` (20),
  `CLASS_UNLOCK_LEVEL` (3 → **5**).

## API

- `GET /api/character/me` — replaces `skills` with:
  - `abilities`: `[{ability, score}]` — score only
  - `skills`: `[{skill_id, name, kind, level}]` — **no XP field exists**, and
    `name` is a placeholder when `level == 0`
- `GET /api/character/{user_id}` — carries the **same** stat block and skills:
  everything is public except undiscovered skills, which are omitted entirely.
- `GET`/`PATCH` `/api/admin/skills` — gains `kind` and `category_id`.
- `PUT /api/admin/challenges/{id}/skills` — `{skill_ids: [...]}`.
- `PATCH /api/admin/categories/{id}` — set a category's ability.

## Frontend

- **Character sheet**: a six-box stat block replacing 015's skill bars. 016's
  suggested-class nudge is removed; the picker unlocks at level 5.
- **Skills page**: name and level, blurred placeholder rows inline, search and a
  funny-skill filter.
- **Admin**: the grouped searchable skill picker; ability selector on categories;
  `kind`/category on the skills page; difficulty now drives XP in the editor.
- **Sample data** rebuilt on the real categories, abilities, skills and
  difficulty-derived values.

## Testing

- Abilities **partition**: the six totals sum to the XP from categorised solves.
- Skills **overlap**: a challenge with three skills gives its **full** XP to each.
- Both curves hit the documented thresholds; both caps hold; the player level caps
  at 20 while XP keeps counting for rank.
- Difficulty derives the XP ceiling.
- A skill at 0 is level 0 and its **real name is absent from the response**.
- The player-facing skill payload has **no XP field**.
- Another player's sheet shows abilities and discovered skills, and omits
  undiscovered ones.
- A category cannot be saved without an ability.
- Post-hint XP is what feeds abilities and skills, not face value.
- The seed migration lands 21 categories and 73 skills with the right kinds.
- **The invariant:** total XP, player level and board rank are unchanged by
  anything in this spec.

## Commit plan

1. Difficulty ladder + `XP_BASE`, derived challenge value, player level cap.
2. Schema: `Ability`, `category.ability`, `skill.kind`/`category_id`,
   `challenge_skill`, drops, config.
3. Seed migration: 21 categories, 73 skills.
4. Scoring: ability/skill XP and both curves.
5. Admin: category ability, skill CRUD, challenge↔skill assignment.
6. `/character` abilities + skills; 016's nudge off, unlock at 5.
7. Frontend: stat block, skills page, admin pickers; sample data rebuilt.

## Non-goals

- **The class recommender.** You are writing the class list with skill mappings
  and rankings; matching is its own spec. It should be a **deterministic ranking
  over the player's top skills, voiced by the System AI** through 016's narrator
  seam — reproducible, free, no guardrail surface, and unable to recommend a class
  that does not exist. The LLM narrates the choice; it does not make it.
- **Abilities or skills doing anything mechanical.**
- **District themes for the map** — now unblocked, but its own spec.

## Decisions — resolved (2026-09-08)

1. XP is **derived from difficulty** × base 10, on the six-tier ladder.
2. **Decay defaults on for Very Hard and Nearly Impossible only**, overridable;
   the floor is 40% of the ceiling.
3. Player curve unchanged (base 100); **capped at level 20**.
4. Skills are a **parallel overlapping track**; abilities **partition**; player
   total is still solves only.
5. Abilities are **scores** (8–20), progress hidden, score shown.
6. Category→ability **required**, using the rebalanced map.
7. Abilities and skills are **cosmetic**.
8. Skill curve `70 × (L−1)^1.25`, soft cap 15, level 0 until first XP.
9. Undiscovered skills are **redacted server-side** and shown as blurred rows
   **inline**.
10. Public sheets carry **everything except undiscovered skills**.
11. Content ships as **seed data in a migration**.
12. Skill picker is **searchable, category skills first**, nothing pre-selected.
13. 016's class **suggestion off**; unlock moves to **level 5**.
14. Sample data wiped and rebuilt.
