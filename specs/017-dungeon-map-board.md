# Spec 017 — Dungeon-Map Challenge Board

Status: **draft** (2026-09-07) — awaiting sign-off
Phase: 2 (D&D Mechanics)
Covers: `Plan.md` Phase 2 → dungeon-map challenge board (and completes the
value-based unlock types 014 left open)
Depends on: 003 (challenges, visibility, release), 014 (prerequisite unlocks),
015 (XP, levels, skills — the new gates)
Read by (later): 018 (boss encounters) — a boss will want to sit in a zone.

This spec has **two halves**: the map itself, and the XP/skill-level unlock gates
that make its topology interesting. They ship as separate commits.

---

# Part 1 — The map

## What this is, and what it is not

The challenge board today is a category-grouped list of cards. This spec adds a
**map view**: rooms joined by corridors, laid out so a player can see the shape of
the dungeon — what is cleared, what is open, and what is still shut.

**It is a view, not a new rule.** The gates are challenge state, scheduled
release, 014's prerequisites, and (Part 2) XP/skill thresholds. The map *renders*
those; it never invents its own. Same discipline as 015 (one XP number) and 016
(class never scores).

The corollary that matters for a live event: **the map applies exactly the same
visibility rules as the challenge list**, through the same helper — not a second
implementation. A hidden, draft or unreleased challenge must not appear as a room,
an edge, or a silhouette. This is a leak surface and is tested as one.

## Zones are categories

A **zone** is a wing of the dungeon, and a zone is a **category**.

`challenge.category_id` is non-nullable with `ON DELETE RESTRICT`, so every
challenge always has exactly one category — there is no unplaceable challenge and
no fallback wing needed. Zones are ordered by the category's `display_order` then
name, which admins already control.

Each zone reports **cleared / total** over the rooms the player can actually see.

## Layout: derived by default, overridable

**Nothing may fall off the map.** Challenges get added mid-event; a map of only
hand-placed rooms would silently hide them.

- **Derived by default.** Every visible challenge is a room, placed
  automatically. A new challenge appears the moment it is published, with no admin
  action.
- **Deterministic.** Computed from stable inputs so **every player sees the same
  map** and it does not shuffle between reloads. Players will say "the room top
  left" to each other; that has to mean one thing.
- **Overridable.** An admin may pin a room to explicit coordinates — optional
  polish, never a prerequisite for appearing.

Layout is computed **server-side**, so it is one implementation rather than one
per client, and so overrides have somewhere to live.

### The algorithm (deliberately simple)

Within a zone, rooms are laid out in **layers by prerequisite depth**: a challenge
with no prerequisites is depth 0; a challenge's depth is one past its deepest
*visible* prerequisite. Depth is one axis, position within the layer the other.

Ordering within a layer is **title, then id** — `Challenge` has no
`display_order` column, and id is the final tie-break that makes the result
totally deterministic. Cycles are impossible (014 refuses them).

Only **visible** prerequisites count toward depth, so a player who cannot see a
gating challenge does not get a mysterious gap where it would have been.

## Room state

Derived from existing rules only:

- **cleared** — solved by this player.
- **open** — visible, unlocked, not yet solved.
- **shut** — visible but locked by unmet requirements; the room shows *what* would
  open it, exactly as the locked card does today.

Rooms the player may not see are simply absent.

## Corridors

An **edge** joins a prerequisite challenge to the challenge it gates — corridors
are 014's `challenge_solved` requirements. An edge is returned only when **both**
endpoints are visible, so a corridor can never imply a room the player cannot see.

Part 2's XP and skill gates have no source room, so they are **not** edges: they
render as a requirement badge on the shut room itself.

---

# Part 2 — XP and skill-level unlock gates

014 built `challenge_unlock_requirement` with an open `requirement_type` and a
nullable `required_challenge_id`, explicitly so "Phase 2's value-based types (min
XP, skill level) fit the same table without one". 015 now provides both. This
completes that extension point, and gives the map gates that are not corridors.

## The new types

- **`min_xp`** — unlocks at a total XP threshold. Uses 015's `total_xp`.
- **`skill_level`** — unlocks at a level in one named skill. Uses 015's
  `skill_xp_for_user` + `level_for_xp`.

A challenge still unlocks when **all** of its requirements are met, unchanged.

## Data model

Two nullable columns on `challenge_unlock_requirement`:

- **`threshold`** (nullable int) — the XP amount for `min_xp`, the level for
  `skill_level`. One column serves both; which one it means is the row's type.
- **`required_skill_id`** (nullable FK → `skill`, **`ON DELETE CASCADE`**) — set
  for `skill_level`.

`CASCADE` rather than `SET NULL` deliberately: a gate pointing at a deleted skill
is meaningless, and would either always pass or always fail. Dropping the row
matches 014's existing rule that "a prerequisite that is removed simply stops
gating its dependents".

Validation lives in the service: `min_xp` requires a `threshold`; `skill_level`
requires both a `threshold` and a `required_skill_id`; `challenge_solved` requires
a `required_challenge_id` and neither of the others.

## The requirement response changes shape

Today a locked challenge advertises `{challenge_id, title, solved}`, which cannot
express "reach 500 XP". It becomes a tagged shape:

```
{ type, met, description, challenge_id?, title?, skill_id?, skill_name?,
  threshold?, progress? }
```

- `description` is the human-readable line ("Solve Warm-Up", "Reach 500 XP",
  "Hacking level 3") so the client renders any type without a per-type branch.
- `progress` is what the player currently has (their XP, or their level in that
  skill) so a shut room can show "320 / 500".
- `solved` becomes `met`, which is the general word.

This is a **deliberate breaking change to an internal API**; the frontend ships
with it in the same commit. Nothing outside this repo consumes it.

---

## API

- **`GET /api/map`** — zones (`id`, `name`, `cleared`, `total`), rooms
  (`challenge_id`, `title`, `zone_id`, `x`, `y`, `state`, `value`,
  `unlock_requirements`), edges (`from_challenge_id`, `to_challenge_id`).
- **`PATCH /api/admin/challenges/{id}/map-position`** — set or clear pinned
  coordinates (`{x, y}` or nulls). Admin-only.
- **Existing** `/api/challenges` and `/api/challenges/{id}` carry the new
  requirement shape.
- **Admin requirement endpoints** (014's add/remove prerequisite) accept the new
  types.

## Frontend

- **`/challenges` opens on the map**, with a map/list toggle remembered per
  player. The list remains complete and equivalent — it is what people use to
  scan, filter and search 200+ challenges, and it is the fallback path.
- The map renders as inline SVG: rooms as nodes (cleared / open / shut), corridors
  as lines, zones as labelled groupings with cleared/total. Clicking an open or
  cleared room navigates to the challenge; a shut room shows what unlocks it.
- **Because the map is now the front door, accessibility is load-bearing.** Rooms
  are focusable and keyboard-reachable with real labels ("Sensitive Logs — shut,
  needs Warm-Up"); the map is a labelled figure; the list toggle is prominent and
  keyboard-reachable. The list view stays a complete equivalent of everything the
  map shows.
- It must stay usable at **event scale** — a few hundred rooms across a dozen-plus
  zones — so zones lay out as a grid of wings rather than one sprawl, and the view
  scrolls/pans rather than shrinking rooms to dots.
- The challenge editor's requirements section gains the two new gate types.
- Art, theming and room shapes are Phase 3; this pass is structural, on existing
  tokens.

## Testing

**Map**
- Only challenges the player may see appear: a hidden, draft or unreleased
  challenge yields **no room and no edge**. (The leak test.)
- Room state matches the list's truth for the same player.
- An edge appears only when both endpoints are visible; depth ignores invisible
  prerequisites.
- Layout is **deterministic**: two calls, and two different players, get identical
  coordinates for the same rooms.
- Depth layering is right: a challenge behind two prerequisites sits deeper than
  both.
- A pinned override wins; clearing it restores the derived position.
- Zones are categories, ordered by category `display_order`; cleared/total counts
  only visible rooms.
- A challenge with no prerequisites still appears (nothing falls off the map).

**Gates**
- `min_xp` blocks below the threshold and unlocks at/above it, using banked XP.
- `skill_level` blocks below the level in *that* skill and unlocks at/above it;
  XP in a different skill does not open it.
- All requirements must be met: a challenge with a solve gate and an XP gate opens
  only when both are.
- Deleting a skill drops its `skill_level` gates rather than leaving them
  unsatisfiable.
- Service validation refuses a malformed requirement (an `min_xp` with no
  threshold, a `skill_level` with no skill).
- The requirement response reports `met`, a `description`, and `progress` for the
  value types.

## Commit plan

1. Schema: `challenge.map_x`/`map_y`, `challenge_unlock_requirement.threshold` and
   `required_skill_id` + migration.
2. Gates: the two new requirement types in the unlock logic, service validation,
   and the reshaped requirement response (+ admin endpoints accepting them).
3. Map service: zones, depth layout, room state, edges — reusing the existing
   visibility helper.
4. `GET /api/map` + the admin pin endpoint.
5. Frontend: the map view, the map/list toggle defaulting to map, zone summaries,
   and the new gate types in the challenge editor.

## Non-goals

- **Fog of war** (hiding distant rooms until you approach) — new gating on a
  competitive board where players should see what is on offer; the existing
  hidden/pre-release states already cover surprises. See Decision 3.
- **Art, theming, room shapes, animation** — Phase 3.
- **Boss rooms** (018) and **loot** (019). A zone is a first-class thing with an
  id so a boss can later be placed in one; nothing is built for that here.

## Decisions — resolved (2026-09-07)

1. **Zones are categories**, not skills. *(Chosen.)* Every challenge has a
   non-null category, so no fallback wing is needed.
2. **The XP / skill-level gates are in 017**, as Part 2 above, kept to their own
   commits. *(Chosen.)*
3. **No fog of war.** *(Recommended default — confirm if you disagree.)*
4. **The map is the default view** at `/challenges`, with the list one toggle
   away and fully equivalent. *(Chosen.)*

## Open sub-question

- The map/list toggle preference is stored **per player in the browser**
  (localStorage). Say if you would rather it be a server-side account preference.
