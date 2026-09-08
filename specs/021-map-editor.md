# Spec 021 — Authored Map Layout

Status: **done** (2026-09-08)
Phase: 2/3 boundary
Depends on: 019 (zones, derived layout), 020 (tiles, the map view)

Closes the item 019 and 020 both left open: positions are derived, so corridors
sprawl across the map because a grid cannot express a graph that is not a tree.

**This is a pre-event step done once.** The layout is locked in before the event
and does not change during it, so the design goal is *least effort that gets an
organic result* — not a general-purpose diagram editor.

## Free placement

`category.map_x` / `map_y` (nullable ints) hold authored positions. Free
placement, snapped to **8px** — fine enough to feel unconstrained and place
zones in organic clusters, coarse enough that saved values stay tidy and two
zones nudged to "the same" spot actually match.

A zone with no authored position keeps the derived layout from 019, so a newly
added category still appears rather than piling up at the origin.

## Organic corridors, without authoring them

Corridors become **quadratic curves** rather than straight lines. The control
point is the midpoint pushed perpendicular to the line, with the distance and
direction derived from a hash of the two zone ids.

That is deliberately not a waypoint editor. It gives every corridor its own
consistent bend for **zero authoring effort per corridor**, is stable across
reloads and identical for every player, and costs nothing to maintain. If a
particular corridor ever needs a specific route, waypoints can be added later —
but paying for that up front, for a layout authored once, is not worth it.

## The editor

An admin **Map** tab rendering the same map component in edit mode:

- Drag a zone; it follows the pointer and saves on drop.
- The map's own pan and zoom still work, so a large dungeon can be laid out
  without fighting the viewport.
- A **Reset layout** action clears authored positions and returns everything to
  the derived layout.
- Players see the new positions on their next load. No publish step — the layout
  is data, and a half-finished layout mid-authoring is not a state worth
  modelling for a pre-event task.

## API

- `PATCH /api/admin/categories/{id}/position` — `{x, y}` or nulls to clear.
- `POST /api/admin/map/reset-layout` — clears every authored position.
- `GET /api/map` returns authored coordinates where set, derived otherwise.

## Testing

- An authored position wins over the derived one; clearing it restores the
  derived position.
- A category with no position still appears on the map.
- Curve geometry is deterministic: the same edge yields the same path across
  calls and for different players.
- Only admins can move zones.

## Non-goals

- Waypoint routing for individual corridors.
- Layout versioning, drafts or publishing.
- Auto-layout beyond the existing derived fallback.
