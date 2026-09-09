# Spec 027 — Map Layout Portability

Status: **approved** (2026-09-08)
Phase: 2/3 boundary
Depends on: 021 (authored zone positions and the map editor)

021 made the dungeon layout authorable by dragging. It made it authorable in
*one database*. The layout that now exists locally cannot reach the deployed
instance except by dragging all 22 zones again, from memory, on a different
screen.

This adds export and import of the layout as a small JSON file.

## Why it cannot key on category ID

Categories are seeded by migration 0021 with `gen_random_uuid()`, so **every
environment has different category IDs for the same zones**. A layout file
carrying IDs would import as 22 unmatched rows against a deployed database, and
the failure would be silent — every position simply skipped.

The file keys on **slug**, which is stable by construction: it is seeded from the
same migration everywhere, and it is already the thing that binds a zone to its
artwork.

## The file

```json
{
  "version": 1,
  "zones": { "intro": { "x": 640, "y": 40 }, "networking": { "x": 320, "y": 400 } }
}
```

Only zones with an authored position appear. A zone left to the derived layout is
absent rather than written out with its computed coordinates — otherwise
exporting would silently freeze every automatic position, and a later change to
the layout algorithm would never reach a map that had once been exported.

`version` is there so a future field does not have to guess at the shape.

## API

- `GET /api/admin/map/layout` — the file above, for the zones that have one.
- `POST /api/admin/map/layout` — applies it, and returns what happened:
  `applied`, plus `unknown` for slugs with no matching category here.

Import is **additive and non-destructive**: it sets the positions it names and
leaves every other zone alone. Clearing a layout already has a verb —
`POST /api/admin/map/reset-layout` from 021 — and quietly wiping unlisted zones
would make import a much sharper tool than it looks.

An unknown slug is reported, not an error. Environments drift; a file exported
before a category was renamed should still place the other 21 zones.

## The admin UI

Two controls on the existing Map page, beside "Reset layout":

- **Export layout** — downloads the JSON.
- **Import layout** — file picker, then a line saying how many zones were placed
  and naming any that were not recognised.

## Edge cases

- **A slug in the file that does not exist here** — reported in `unknown`, the
  rest still applied.
- **A zone here that the file does not mention** — untouched.
- **Malformed JSON, or `x`/`y` that are not integers** — refused whole, with the
  reason. Nothing is applied.
- **Importing onto a map that already has authored positions** — overwrites the
  named ones. That is the point: this is how a local layout reaches production.
- **Coordinates far outside the current map** — accepted. The map sizes itself
  from its content and the viewport fits to it, so a wide layout still renders.

## Testing

- Export contains only zones with authored positions.
- Export → reset → import restores the same layout.
- Import matches on slug, not ID: a file whose slugs match applies cleanly even
  though the IDs in it (if any) are meaningless here.
- An unknown slug is reported and does not block the rest.
- Malformed input applies nothing.
- Only admins may import; export is staff-readable.

## Non-goals

- Exporting anything but positions — not gates, not fog, not artwork. Gates are
  022's editor; artwork is files in the repo.
- Merging two layouts, or any conflict resolution beyond last-write-wins.
- Automatic sync between environments.
