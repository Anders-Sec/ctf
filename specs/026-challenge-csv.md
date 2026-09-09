# Spec 026 — Challenge Import & Export (CSV)

Status: **approved** (2026-09-08)
Phase: 2/3 boundary
Depends on: 018 (difficulty ladder and the XP economy), 019 (the 22 categories)

Authoring 240-odd challenges through a web form one at a time is the wrong tool.
This adds a CSV round-trip: download a template with every row pre-filled with
its category and difficulty, plan the event in a spreadsheet, upload it back.

## The template

`GET /api/admin/challenges/template.csv` returns a ready-to-fill file: **every
category, 11 rows each, 242 rows**, with `category` and `difficulty` already
filled and the rest blank.

The 11-row difficulty spread per category is not arbitrary — it reproduces the
018 economy:

| Difficulty | Rows | XP each | XP |
| --- | --- | --- | --- |
| Very easy | 2 | 50 | 100 |
| Easy | 2 | 100 | 200 |
| Medium | 3 | 150 | 450 |
| Hard | 2 | 200 | 400 |
| Very hard | 1 | 250 | 250 |
| Nearly impossible | 1 | 500 | 500 |
| **Total** | **11** | | **1,900** |

1,900 per category across 22 categories is **41,800 XP**, against the ~2,000 and
~42,000 that 018 budgeted. So an admin who simply fills in the template gets an
event whose economy already matches the curve the levels and abilities were
tuned against.

**Intro is the exception**: as the tutorial wing it gets a gentler ladder (no
very-hard or nearly-impossible), because a nearly-impossible challenge in the
zone that gates the whole dungeon would be a wall at the front door.

Difficulty is a *suggestion in a spreadsheet cell*. Change any of it.

## Columns

Required to create a challenge:

| Column | Notes |
| --- | --- |
| `category` | Pre-filled. Must match an existing category name or slug. |
| `title` | Yours. Must be unique within the category. |
| `difficulty` | Pre-filled. One of the six ladder values. |
| `description` | The challenge body. |
| `flag` | The answer. Case-insensitive exact match, which is the basic case. |

Optional, blank in the template, defaulted on import:

| Column | Default |
| --- | --- |
| `state` | `draft` |
| `initial_points` / `minimum_points` / `scoring` | Derived from `difficulty`, exactly as the editor does |
| `max_attempts` | blank = unlimited |
| `release_at` | blank = available immediately |
| `skills` | Semicolon-separated skill names, blank = none |

Hints and prerequisites are **not** in the CSV — those are being handled in the
platform, and both are relational enough that a flat file would fight them.

## Import

`POST /api/admin/challenges/import` takes the file and returns a per-row report.

- **Validated in full before anything is written.** A file with an error in row
  200 writes nothing at all — a half-imported event is worse than a rejected
  one, because you cannot tell what landed without reading all 242 rows.
- **A dry-run flag** returns the same report without writing, so a file can be
  checked before committing to it.
- **Matching is on `(category, title)`.** A row whose challenge already exists
  updates it; a new row creates. So the same file can be re-uploaded after edits
  without duplicating, which is how a spreadsheet actually gets used.
- **Blank rows are skipped**, so an admin can leave unused template rows alone
  rather than deleting them.
- Errors name the row number and the column, because "invalid difficulty" alone
  in a 242-row file is useless.

Import never deletes. A challenge removed from the CSV stays in the platform —
deletion is deliberate and belongs in the UI, not in a file diff.

## Export

`GET /api/admin/challenges/export.csv` returns the current challenges in exactly
the template's shape, so export → edit → import round-trips cleanly. This is
also the backup that makes import safe to experiment with.

## The admin UI

A panel on the Manage page: download template, download export, upload with a
dry-run checkbox, and the report rendered as a table when it comes back.

## Edge cases

- **A flag containing a comma or quote** — handled by the CSV writer/reader
  rather than by hand-rolled splitting.
- **Duplicate `(category, title)` within the file** — refused up front, since
  the second row would silently overwrite the first.
- **An unknown category** — refused with the row number. The template makes this
  hard to hit, but a hand-edited file can.
- **A skill name that does not exist** — refused rather than skipped, so a typo
  cannot silently produce a challenge that feeds nothing.
- **Re-importing a solved challenge** — updating title or description is fine;
  changing `difficulty` changes future awards, never banked XP, which stays
  monotonic per 015.

## Testing

- The template has 242 rows, every category present, 11 each.
- The prefilled difficulty spread totals 1,900 XP per non-Intro category.
- A valid file imports and creates challenges with derived points.
- A file with one bad row writes nothing.
- Dry run writes nothing and reports the same as the real thing would.
- Re-importing the same file updates rather than duplicates.
- Export round-trips: export → import is a no-op.
- Only admins may import or export.

## Non-goals

- Hints and prerequisites in the CSV.
- Container-backed challenge fields.
- Multiple answers or non-exact match types — "basic for the initial push".
- Deleting challenges by omission.

## Decision

**Import defaults new challenges to `draft`.** 242 challenges appearing live in
one request is hard to undo. `state` is a column for anyone who wants otherwise.
