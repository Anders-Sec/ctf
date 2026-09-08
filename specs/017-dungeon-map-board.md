# Spec 017 — Dungeon-Map Challenge Board

Status: **draft** (2026-09-07) — awaiting sign-off
Phase: 2 (D&D Mechanics)
Covers: `Plan.md` Phase 2 → dungeon-map challenge board (and completes the
value-based unlock types 014 left open)
Depends on: 003 (challenges, visibility, release), 014 (prerequisite unlocks),
015 (XP, levels, skills — the new gates)
Read by (later): 018 (boss encounters) — a boss will want to sit in a zone.

This spec has **three parts**, shipping as separate commits:

1. **The map** — a spatial view of the challenges that already exist.
2. **The unlock system, generalised** — new gate types, and gates on zones.
3. **Fog of war** — locked areas greyed out, so the dungeon opens up as you go.

---

# Part 1 — The map

## What this is, and what it is not

The challenge board today is a category-grouped list of cards. This spec adds a
**map view**: rooms joined by corridors, laid out so a player can see the shape of
the dungeon — what is cleared, what is open, and what is still shut.

**It is a view, not a new rule.** The gates are challenge state, scheduled
release, 014's prerequisites, and Part 2's thresholds and zone locks. The map
*renders* those; it never invents its own. Same discipline as 015 (one XP number)
and 016 (class never scores). Concretely: every lock lands in
`prerequisite_status`, which the list, the detail page **and submission** already
consult — so a lock is never merely cosmetic, and never bypassable by switching to
the list view.

The corollary that matters for a live event: **the map applies exactly the same
visibility rules as the challenge list**, through the same helper. A hidden, draft
or unreleased challenge must not appear as a room, an edge, or a silhouette. This
is a leak surface and is tested as one.

The distinction that runs through this spec:

- **Invisible** (hidden / draft / unreleased) → absent entirely. Unchanged.
- **Locked** (requirements unmet) → present, readable, not enterable. This is what
  fog greys out.

## Zones are categories

A **zone** is a wing of the dungeon, and a zone is a **category**.

`challenge.category_id` is non-nullable with `ON DELETE RESTRICT`, so every
challenge always has exactly one category — no unplaceable challenge, no fallback
wing needed. Zones are ordered by the category's `display_order`, then name.

Each zone reports **cleared / total** over the rooms the player can see.

## Layout: derived by default, overridable

**Nothing may fall off the map.** Challenges get added mid-event; a map of only
hand-placed rooms would silently hide them.

- **Derived by default.** Every visible challenge is a room, placed
  automatically, the moment it is published, with no admin action.
- **Deterministic.** Computed from stable inputs so **every player sees the same
  map** and it does not shuffle between reloads. Players will say "the room top
  left" to each other; that has to mean one thing.
- **Overridable.** An admin may pin a room to explicit coordinates — optional
  polish, never a prerequisite for appearing.

Layout is computed **server-side**: one implementation rather than one per client,
and somewhere for overrides to live.

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

- **cleared** — solved by this player.
- **open** — visible, unlocked, not yet solved.
- **shut** — visible but locked by unmet requirements; the room shows *what* would
  open it, exactly as the locked card does today.

Rooms the player may not see are simply absent.

## Corridors

An **edge** joins a prerequisite challenge to the challenge it gates — corridors
are `challenge_solved` requirements. An edge is returned only when **both**
endpoints are visible, so a corridor can never imply a room the player cannot see.

Value gates and zone gates have no source room, so they are **not** edges: they
render as a requirement badge on the shut room or zone.

---

# Part 2 — The unlock system, generalised

014 built `challenge_unlock_requirement` with an open `requirement_type` and a
nullable `required_challenge_id`, explicitly so "Phase 2's value-based types (min
XP, skill level) fit the same table without one". 015 now provides them. This part
adds the new types *and* lets a **zone** be gated the same way, which is what makes
the dungeon open up as players progress.

## One table gates both things

Rather than a second, near-identical `category_unlock_requirement` table, the
existing table is generalised to name **what it gates**:

- `challenge_unlock_requirement` becomes **`unlock_requirement`**, with a nullable
  `challenge_id` **XOR** a nullable `category_id` — exactly the one-owner pattern
  already used by `challenge_instance` (`ck_challenge_instance_one_owner`), with
  the same style of `CHECK` constraint.

One table means **one evaluator, one admin API shape, one set of validation and
tests**, instead of two that must be kept in step forever. The migration renames
the table, relaxes `challenge_id` to nullable, adds `category_id`, and adds the
XOR check. The event has not run, so there is no production data at risk.

## The gate types

| Type | Means | Needs |
| --- | --- | --- |
| `challenge_solved` | Solve a specific challenge | `required_challenge_id` |
| `min_xp` | Reach a total XP figure | `threshold` |
| `skill_level` | Reach a level in one skill | `required_skill_id`, `threshold` |
| `solves_in_category` | Clear N rooms in a zone | `required_category_id`, `threshold` |

`min_xp` uses 015's `total_xp`; `skill_level` uses `skill_xp_for_user` +
`level_for_xp`; `solves_in_category` counts the player's solves in that category.
`solves_in_category` is what expresses "clear most of the starter area before the
next wing opens" directly, rather than approximating it with an XP number.

Validation lives in the service and refuses any row that does not match its type's
row in that table.

## Columns

On `unlock_requirement`, all nullable:

- **`threshold`** (int) — the XP amount, the level, or the count. The row's type
  says which.
- **`required_skill_id`** (FK → `skill`, `ON DELETE CASCADE`)
- **`required_category_id`** (FK → `category`, `ON DELETE CASCADE`)

`CASCADE` throughout, matching the existing `required_challenge_id`: a gate
pointing at a deleted skill or category is meaningless and would either always
pass or always fail. Dropping the row matches 014's rule that "a prerequisite that
is removed simply stops gating its dependents".

## The unlock rule

> A challenge is unlocked iff **its own** requirements are met **and its zone's**
> requirements are met.

Computed inside `prerequisite_status`, which the list, the detail page and
**submission** already consult. So a locked zone is genuinely locked — you cannot
step around it by switching to the list view or posting a flag directly. The map
still only renders what the domain decided.

**A zone with no requirements is open to everyone** — which is how the starting
area is authored: leave the first category ungated, gate the rest on XP, a skill
level, or clearing N rooms in the starter zone. The guided progression is data,
not a special case.

## The requirement response changes shape

Today a locked challenge advertises `{challenge_id, title, solved}`, which cannot
express "reach 500 XP". It becomes a tagged shape:

```
{ type, met, description, challenge_id?, title?, skill_id?, skill_name?,
  category_id?, category_name?, threshold?, progress? }
```

- `description` is the human-readable line ("Solve Warm-Up", "Reach 500 XP",
  "Hacking level 3", "Clear 5 rooms in Web") so the client renders any type
  without a per-type branch.
- `progress` is what the player currently has, so a shut room shows "320 / 500".
- `solved` becomes `met`, the general word.

A **deliberate breaking change to an internal API**; the frontend ships with it in
the same commit, and nothing outside this repo consumes it.

---

# Part 3 — Fog of war

The dungeon should open up as players go: **a small starting area with the easy
challenges, and harder areas and new categories unlocking as they progress.**
Part 2 provides the gating; this part is how it reads on screen.

**Locked areas are greyed out, not hidden, and stay fully readable** — zone name,
room titles, and the condition that opens them. Seeing what is down there, and what
it costs, gives players a target instead of a blank space, and it is what keeps
this fair on a competitive board.

So **fog is presentation, not redaction.** The map returns the same data whether
fog is on or off; the setting decides whether locked zones are dimmed to emphasise
progression or drawn like everything else. That is a deliberate simplification —
it means fog adds **no leak surface at all**, and the map and list views cannot
disagree about what exists.

- **`event_config.fog_of_war`** (bool, **default on**) — the setting, on the event
  settings page. It is inert until zone gates exist, so a fresh event is
  unaffected until you author gating.
- `GET /api/map` reports the flag so the client knows whether to dim.

---

## API

- **`GET /api/map`** — `fog_of_war`, zones (`id`, `name`, `locked`,
  `unlock_requirements`, `cleared`, `total`), rooms (`challenge_id`, `title`,
  `zone_id`, `x`, `y`, `state`, `value`, `unlock_requirements`), edges
  (`from_challenge_id`, `to_challenge_id`).
- **`PATCH /api/admin/challenges/{id}/map-position`** — set or clear pinned
  coordinates. Admin-only.
- **Admin unlock-requirement endpoints** — one shape, targeting a challenge or a
  category, replacing 014's challenge-only add/remove prerequisite pair.
- **Existing** `/api/challenges` and `/api/challenges/{id}` carry the new
  requirement shape and respect zone locks.
- **`/api/admin/event-config`** carries `fog_of_war`.

## Frontend

- **`/challenges` opens on the map**, with a map/list toggle remembered per
  player. The list remains complete and equivalent — it is what people use to
  scan, filter and search 200+ challenges, and it is the fallback path. It shows
  zone locks too, so the two views never disagree.
- The map renders as inline SVG: rooms as nodes (cleared / open / shut), corridors
  as lines, zones as labelled groupings with cleared/total. A **locked zone is
  greyed, still readable, with its unlock condition on it.** Clicking an open or
  cleared room navigates; a shut room or zone shows what unlocks it.
- **Because the map is now the front door, accessibility is load-bearing.** Rooms
  are focusable and keyboard-reachable with real labels ("Sensitive Logs — shut,
  needs Warm-Up"); a locked zone announces its condition; greying is never the
  *only* signal that something is locked; the map is a labelled figure; the list
  toggle is prominent and keyboard-reachable.
- It must stay usable at **event scale** — a few hundred rooms across a dozen-plus
  zones — so zones lay out as a grid of wings that pans, rather than shrinking
  rooms to dots.
- The requirements editor gains the new gate types and can target a **category**
  as well as a challenge; the event settings page gains the fog toggle.
- Art, theming and room shapes are Phase 3; this pass is structural.

## Testing

**Map**
- Only challenges the player may see appear: hidden/draft/unreleased yields **no
  room and no edge**. (The leak test.)
- Room state matches the list's truth for the same player.
- An edge appears only when both endpoints are visible; depth ignores invisible
  prerequisites.
- Layout is **deterministic**: two calls, and two different players, get identical
  coordinates for the same rooms.
- A challenge behind two prerequisites sits deeper than both.
- A pinned override wins; clearing it restores the derived position.
- Zones are categories ordered by `display_order`; cleared/total counts only
  visible rooms; a challenge with no prerequisites still appears.

**Gates**
- Each type blocks below its condition and unlocks at/above it: `min_xp` on banked
  XP, `skill_level` on that skill only (XP elsewhere does not open it),
  `solves_in_category` on solves in that category only.
- All requirements must be met: a solve gate plus an XP gate opens only when both
  are.
- Deleting a skill or category drops the gates pointing at it rather than leaving
  them unsatisfiable.
- The XOR constraint holds: a requirement targets a challenge or a category, never
  both or neither.
- Service validation refuses malformed rows (a `min_xp` with no threshold, a
  `skill_level` with no skill, and so on).
- The response reports `met`, a `description`, and `progress`.

**Zones and fog**
- A challenge in a locked zone is locked **even if its own requirements are met**,
  and unlocks when the zone's condition is met.
- A locked zone blocks **submission**, not just display — the list view and a
  direct flag POST are both refused. (The bypass test.)
- A zone with no requirements is open to everyone (the starting area).
- The map returns **identical data** with fog on and off — fog is presentation
  only; the flag is reported so the client can dim.

## Commit plan

1. Schema: generalise `unlock_requirement` (rename, nullable `challenge_id`,
   `category_id` + XOR check, `threshold`, `required_skill_id`,
   `required_category_id`), `challenge.map_x`/`map_y`, `event_config.fog_of_war`
   + migration.
2. Gates: the new types in the unlock evaluator, service validation, the reshaped
   requirement response, and the generalised admin endpoints.
3. Zone gating: category requirements folded into `prerequisite_status`, plus the
   submission-bypass tests.
4. Map service: zones, depth layout, room state, edges.
5. `GET /api/map` + the admin pin endpoint.
6. Frontend: map view defaulting to map, list toggle, zone summaries and greying,
   the new gate types and category targeting in the editor, the fog toggle.

## Non-goals

- **Art, theming, room shapes, animation** — Phase 3.
- **Boss rooms** (018) and **loot** (019). A zone is a first-class thing with an
  id so a boss can later be placed in one; nothing is built for that here.
- **Per-room fog.** Fog operates at the **zone** level; individual challenges are
  already gated by their own requirements and read as "shut".
- **Hiding anything behind fog.** Fog dims; it never withholds. Withholding is what
  the hidden/draft/unreleased states are for.

## Decisions — resolved (2026-09-07)

1. **Zones are categories**, not skills.
2. **The value-based gates are in 017**, with `solves_in_category` added so zone
   progression can be expressed directly.
3. **Fog of war is in**, event-level, **default on**, and means **greyed out but
   fully readable** — presentation only, no redaction.
4. **The map is the default view** at `/challenges`, list one toggle away.

## Open sub-questions

- The map/list toggle preference is stored **per player in the browser**
  (localStorage). Say if you would rather it be a server-side account preference.
- Generalising 014's table (rename + XOR target) is an engineering call made to
  avoid two parallel requirement systems. Say if you would rather keep
  `challenge_unlock_requirement` untouched and add a separate category table.
