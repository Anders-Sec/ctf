# Spec 023 — Map Atmosphere & Fit

Status: **approved** (2026-09-08)
Phase: 2/3 boundary
Depends on: 020 (tiles, ambience), 021 (layout, viewport), 022 (gate editor)

Five fixes to the map now that all 22 tiles are in. A full UI overhaul comes
later; nothing here should make that harder, so everything stays in the existing
token/filter layer rather than inventing new structure.

## 1. The background repeats

`base.png` is 1536×1024 tiled through an SVG `<pattern>`. The map is roughly
1556×2500, so the plate tiles once across and about two and a half times down —
and a photographic texture repeating on a fixed grid is obvious the moment you
see it.

Options considered:

| Approach | Verdict |
| --- | --- |
| Stretch one plate over the whole map | 2.5× vertical distortion, and blurry. No. |
| Mirror alternate tiles | Kills the seam, but the mirror symmetry reads as a butterfly. No. |
| A bigger or per-cell-randomised plate | Works, but it is more art to generate and more megabytes on a page already carrying 52MB. |
| **Break the repeat with non-repeating layers on top** | **Chosen.** No new assets, no download cost. |

The plate keeps tiling, but three things go over it, none of which repeat:

- **A large-scale fractal-noise field** (`feTurbulence`, low frequency, one
  octave) as a soft dark mottle at low opacity. Its cell is the whole map, so
  there is no second copy of it to notice.
- **Irregular darkening pools** — a handful of large, very soft radial
  gradients placed from the map's own dimensions, breaking the grid rhythm.
- **A grain pass** at high frequency and very low opacity, which hides the seam
  line itself.

The plate is also drawn at **2× scale**, halving how many times it repeats
before any of that is applied.

**Transparent overlay art** slots into the same layer. `map/overlays/*.png` are
drawn once each at large scale over the plate and under the zones — drifts of
rubble, cracks, scorch, standing water. Because each is placed once rather than
tiled, any number of them breaks the grid further, and the map works with none,
one or all of them. Prompts live in `art.md` alongside the tiles.

## 2. The normal view is too small

- The map goes **full-bleed on the challenges page**: it breaks out of that
  page's `max-w-6xl` and runs edge to edge, with the heading above it staying in
  the column. The admin Map tab keeps its column — it has a header, a warning
  strip and controls that read better contained.
- Height goes from `70vh` to `80vh` with a floor of `520px`, so it is not
  crushed on a short laptop screen.
- **Fit to content on first load**: the viewport picks the scale that shows the
  whole dungeon and centres it, rather than opening at 1× on the top-left
  corner. Reset returns to that fit, not to 1×.

## 3. It reads as a dark rectangle

The map is near-black with a hard border on a parchment page. Instead:

- **Feathered edges.** A CSS mask fades the map's outer ~40px to transparent, so
  it dissolves into the page instead of stopping at a line. The hard border and
  square corners go.
- A **warm rim glow** just inside the fade, so the transition reads as torchlight
  falling off rather than an image ending.

Fullscreen keeps its hard edges — there is nothing to blend into there.

## 4. Hover glow on sealed zones

`.dungeon-zone:hover` glows regardless of state, so a sealed zone lights up as
invitingly as an open one. The glow becomes conditional on the zone being
unlocked.

The **focus ring stays on every zone**, sealed included: it is keyboard
navigation, not an invitation, and removing it would strand keyboard users. A
sealed zone gets a cool, dim hover instead of the warm glow — feedback that the
cursor is on something, without implying it is open.

## 5. Corridors are smooth

They are flat strokes, so they read as drawn rather than carved. Asset art was
considered and rejected: a texture stroked along a curved path does not follow
the path's direction, so it would smear.

Instead the corridors get the **`feTurbulence` + `feDisplacementMap` treatment
already used by the procedural chamber** — the same roughening that gives those
their hewn edge, at a lower scale so corridors stay readable. Over that, a
grain overlay clipped to the stroke, and slight per-corridor width variation
derived from the same hash that already bends them, so no two are identical.

## 6. Fog of war, and other life

Fog stops being decoration and becomes the thing it is named after: **the
unexplored map is fogged, and unlocking a zone clears it.**

- A fog layer sits over each **sealed** zone — two offset turbulence fields at
  low opacity, drifting slowly in different directions so they never line up
  into a visible cycle.
- When a zone unlocks, its fog **fades out over ~1.2s** rather than popping.
  Players will rarely catch it live, but a map that visibly opens up is worth
  more than one that is merely different on reload.
- Fog is driven by the same `fog_of_war` event setting that already dims locked
  zones. With the setting off, there is no fog — the map is simply all lit.

**Fog never hides what opens a wing.** 017 and 019 both hold the line that fog
puts the torches out but never conceals the unlock condition, so the fog layer is
drawn *under* the zone labels and condition text. This is a layering rule, not a
judgement call — the text must stay legible through it.

Alongside it, kept deliberately small:

- **Torch flicker** on the light pools already exists and stays.
- **Dust motes**: a dozen faint circles drifting upward on staggered delays, in
  the lit areas only, so open ground feels occupied.

020's budget rule holds — every animation off under `prefers-reduced-motion`,
and paused when the tab is hidden. Nothing here is interactive, so losing all of
it costs nothing but atmosphere.

## Testing

- The map still renders every zone, corridor and label with the new filters.
- Hover glow applies to an unlocked zone and not to a sealed one; the focus ring
  applies to both.
- Fit-to-content picks a scale that fits the whole map, and Reset returns to it.
- Decorative layers are `pointer-events: none` — no new element may swallow a
  click meant for a zone.
- Reduced-motion disables every animation added here.
- Fog covers sealed zones and not open ones, and clears when one unlocks.
- Unlock conditions stay readable through the fog.

## Decisions

1. **Break the repeat with non-repeating layers**, with transparent overlay art
   as an optional extra layer rather than a bigger or randomised base plate.
2. **Full-bleed on the challenges page only.** The admin Map tab keeps its
   column.
3. **Fog follows progression** rather than drifting everywhere: sealed zones are
   fogged, and the fog clears as they unlock.

## Non-goals

- Re-generating or re-compressing the tile art (a separate, real concern — 52MB).
- Retheming the surrounding page; that is the later UI overhaul.
- Per-zone bespoke effects (slime bubbling, embers) — district theming is its own
  piece of work.
