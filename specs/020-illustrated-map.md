# Spec 020 — The Illustrated Zone Map

Status: **draft** (2026-09-08) — awaiting sign-off
Phase: 2/3 boundary (mechanics done in 019; this is the art pass over it)
Depends on: 019 (22 zones, authored positions, the progression graph)

019 makes the map *drawable*. This makes it drawn.

## The architecture: keep the art and the state apart

Three layers, and the separation is the whole idea:

1. **Painted art (static).** A base plate plus one illustrated tile per zone.
   Pure assets — cacheable, zero runtime cost, as detailed as you like. The art
   never knows anything about game state.
2. **SVG interaction (dynamic).** Transparent hotspot paths over the art carrying
   everything stateful: locked/open, cleared/total ring, hover, focus, click.
   This is real DOM, which is what gives keyboard navigation and screen-reader
   labels for free — a canvas would make us rebuild that, worse.
3. **Ambience (budgeted).** Torch flicker, drifting fog, water shimmer as CSS
   transforms on transparent layers; **Lottie** for the set pieces.

Because the art carries no state, you can redraw any zone without touching logic,
and a zone's lock state cannot disagree with the list view — both read the same
API.

**The map must work before the art exists.** A zone with no tile falls back to
017's procedural stone chamber. Art arrives zone by zone; nothing is blocked on a
complete set.

## Asset contract

See **`art.md`** at the repo root for the style guide, master prompt and all 22
subject inserts — that is the copy-paste source for generating these.

**Per-zone tile** — one per zone, 22 in all:

- `frontend/public/map/zones/<category-slug>.webp`
- **1024×1024** square (what ChatGPT emits; downscaled at build if wanted)
- **Not transparent — faded to pure black at the edges.** ChatGPT will not give
  reliable transparency, and fighting for it is wasted effort: a heavy vignette
  into black composites seamlessly onto the dark base plate, needs no
  post-processing, and matches the reference, which vignettes anyway. Tiles are
  drawn with `mix-blend-mode: screen` so black reads as empty.
- No separate locked variant — a locked zone is the same art, desaturated and
  dimmed by the SVG layer, which is what keeps "greyed out but readable" honest.

**Base plate** — `frontend/public/map/base.webp`, **1536×1024** landscape: the
void, floor texture and grid the tiles sit on.

**Naming is the contract**: the slug wires a tile to its zone, so a tile lands
automatically the moment the file exists. A typo means the zone silently keeps
its fallback, which is the failure mode worth knowing about.

## The prompts

They live in **`art.md`**, not here — one file to copy from, so there is no second
copy to drift out of step with the one actually being used.


## Motion

**Ambient (CSS/SVG, always on unless reduced-motion):** torch flicker as slow
opacity drift, fog as a translating transparent layer, a pulsing rim on newly
unlocked zones, hover lift.

**Set pieces (Lottie):** the one that earns the dependency is a **gate grinding
open** when a zone unlocks — the moment the dungeon rewards you. Plus water churn
for Networking and ember drift for Incident Response.

**Budget, enforced:** at most 6 concurrent ambient animations and 1 set piece;
everything pauses when the tab is hidden; everything stops under
`prefers-reduced-motion`, which must leave the map fully usable, not merely still.

## Drill-down

Clicking a zone slides a **panel over the map** — the map stays visible behind,
so you never lose your place in the dungeon. The panel is the existing challenge
board filtered to that category, with its locked/solved treatment unchanged.
Escape and a close button both dismiss it; focus moves into the panel on open and
returns to the zone on close.

## Testing

- A zone with no tile renders the procedural fallback and stays clickable.
- Locked zones render dimmed but readable, with their unlock condition legible.
- The panel traps and restores focus, and closes on Escape.
- `prefers-reduced-motion` disables every animation and the map stays fully
  usable.
- Zone state on the map always matches the list view for the same player.
- Missing or failed art never blocks interaction.

## Commit plan

1. The layered map shell: base plate, tile slots, procedural fallback.
2. SVG hotspot layer over the art: state, progress, hover, focus, keyboard.
3. The drill-down panel.
4. CSS ambience plus the reduced-motion and visibility budget.
5. Lottie set pieces, starting with the unlock gate.

## Non-goals

- **Per-zone interiors.** Zooming into a zone and walking rooms is a bigger idea;
  the panel covers the need now.
- Sound design (Phase 3).
- Boss encounters and loot (021/022).

## What is needed from you

The 22 tiles and the base plate, at the paths above. I can build every layer
against the procedural fallback and drop the art in as it arrives — so this is
not blocking, and the map improves one tile at a time.
