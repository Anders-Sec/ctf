# Spec 022 — Zone Connection & Gate Editor

Status: **approved** (2026-09-08)
Phase: 2/3 boundary
Depends on: 017 (gate types, admin CRUD), 019 (progression graph), 021 (map editor)

Closes the item 017 left open — "admin gate-editing UI still to do" — and makes
the progression graph editable without a migration.

## The one idea this rests on

**A connection *is* a requirement.** `dungeon._edges()` draws a corridor for any
gate carrying a `required_category_id`; nothing else creates one. So "add a
connection between two areas" and "change an area's requirements" are the same
operation, and this is one editor, not two.

A gate with no source zone — `min_xp`, `player_level`, `skill_level` — is a real
requirement that draws no corridor. The editor must show those too, or an admin
will not understand why a zone is sealed.

## Backend

The CRUD already exists in `admin_unlocks.py` (list / add / delete, per category).
Re-posting a gate of the same type and source updates its threshold, so changing
"50% of Intro" to "75% of Intro" needs no new endpoint. Three gaps to close:

**1. Cycle detection for category gates.** Today there is none — only
`challenge_solved` on a *challenge* delegates to 014. Gate A on B and B on A and
both zones are sealed forever, with no error and no symptom until a player asks
why a wing never opened. `add_requirement` walks the existing category graph and
refuses an edge that would close a loop.

**2. Self-gating.** A zone gated on a percentage of itself can never open. Refuse
it — same failure, one node long.

**3. Orphan warning, not an error.** A zone unreachable from Intro is legal (an
admin may be mid-edit) but is almost always a mistake. `GET /api/map` gains
nothing; instead the admin list endpoint reports, per zone, whether it is
reachable from the start. Advisory only — it never blocks a save.

New: `GET /api/admin/map/graph` — every zone with its gates resolved to names
plus a `reachable` flag, so the editor needs one call rather than 22.

## The editor

Extends the **Map** tab from 021 rather than adding a tab. In edit mode a zone
already drags; a *click* (no drag — the 021 slop threshold already tells them
apart) opens a gate panel for that zone:

- Its current gates, each in plain words, with a remove control.
- Add a gate: pick a type, then the fields that type needs — a source zone and a
  threshold for the percentage and count gates, a skill and level for
  `skill_level`, a number for `min_xp` and `player_level`.
- Thresholds are editable in place; saving re-posts the gate.
- A rejected save (cycle, self-gate) explains which loop it would close.

Unreachable zones are marked on the map itself in edit mode, since that is where
an admin will notice. Players see no such marking.

## Edge cases

- Removing the last gate on a zone makes it open from the start. That is a
  legitimate thing to want; no confirmation, it is one click to put back.
- Deleting a category that another zone's gate points at — already handled by the
  FK; the editor refreshes so the dangling corridor disappears.
- A gate whose source zone has zero published challenges can never reach 100%.
  Worth a warning: it is exactly the Intro-sealed-the-dungeon bug from 019, and
  the percentage gates make it easy to recreate.
- Changing gates mid-event re-locks zones for players who had them open. Out of
  scope to solve — this is a pre-event tool — but the panel says so plainly when
  the event is running.

## Testing

- A cycle is refused, naming the loop; a self-gate is refused.
- A legal edge across the existing graph still saves.
- Re-posting an existing gate updates its threshold rather than duplicating.
- Removing a gate removes the corridor from `GET /api/map`.
- `reachable` is false for a zone with no path from Intro.
- Only admins can write; staff can read.

## Decisions

1. **Panel-only.** The source zone is picked from a list, not drawn by dragging
   zone-to-zone. The list handles the sourceless gate types, which dragging
   cannot express, and 22 zones is a short list.
2. **A zero-challenge source zone is a warning, not a refusal.** It is
   unsatisfiable in practice but legal while challenges are still being added to
   that zone.

## Non-goals

- Editing challenge-level gates (014/017 already covers those elsewhere).
- Bulk import/export of the graph.
- Versioning or previewing a graph change against player progress.
