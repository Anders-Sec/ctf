# Spec 030 — Admin Achievement Management

Status: **approved** (2026-09-13)
Phase: 2 (D&D Mechanics)
Depends on: 028 (the engine), 029 (the roster this page manages)

Full CRUD over achievements, so the roster seeded by 029 is a starting point
rather than a fixed list. The intended use is concrete: the seeded set arrives
pre-populated, and the descriptions get hand-written one at a time before the
event opens.

## Why this is not just another admin table

The Skills and Classes pages are close twins and this borrows their shape, with
one difference that drives the whole design: **an achievement is half data and
half code.** The name and description are editable text. The `code` names a
trigger that lives in `app.services.achievements`, and no amount of admin UI can
conjure one.

So the page has to make that seam visible rather than hide it:

- Every row shows whether its code has a **registered trigger**. One without is
  inert — it will never fire — and that must be obvious at a glance instead of
  being discovered after the event when nobody earned it.
- Creating a row offers the **unused registered codes** as suggestions, because
  the useful new achievement is nearly always one whose trigger already exists.
- A free-typed code is still allowed. Writing the row first and the trigger
  afterwards is a reasonable order to work in; it just has to be marked.

## The page

`/admin/achievements`, beside Skills and Classes in the admin nav.

A table of the full roster: code, name, earned-by, trigger status, display order,
and how many players hold it. Edit is inline, matching the Skills page.

- **Create** — code, name, earned-by, description, display order, secret flag.
- **Edit** — everything except the code. A code is the join to a trigger *and*
  to every award already granted; renaming it would silently orphan both. Fixing
  a typo in a code is a delete and a create, which is the honest cost.
- **Delete** — refused outright once anyone holds it. Taking an achievement back
  from a player who earned it is worse than living with a badly-named one, and
  a cascade that quietly removed awards would do exactly that. Use the secret
  flag to hide it instead.
- **Reorder** — display order, as the Skills page does it.

## The description is deliberately unfinished

029 seeds `description` as a visible placeholder because it is the one field
being hand-written per achievement. The page leans into that:

- Rows still holding the placeholder are **flagged as needing copy**, with a
  count at the top — the working list for an afternoon of writing.
- The filter "needs copy" narrows the table to exactly those.

This is the difference between a table an admin has to audit by eye and one that
tells them what is left to do.

## API

| Endpoint | Who | Does |
| --- | --- | --- |
| `GET /api/admin/achievements` | staff | The roster, with hold counts and trigger status. |
| `POST /api/admin/achievements` | admin | Create. |
| `PATCH /api/admin/achievements/{id}` | admin | Update everything but the code. |
| `DELETE /api/admin/achievements/{id}` | admin | Delete, refused if held. |
| `GET /api/admin/achievements/triggers` | staff | Registered codes and which are unused. |

Every write is audited, as the skills and classes routers already do.

## Edge cases

- **A code with no trigger** saves and is marked inert. It is a legitimate
  work-in-progress state, not an error.
- **A trigger with no achievement row** is the mirror image, and is surfaced on
  the triggers endpoint as unused — that is the suggestion list.
- **A duplicate code or name** is refused; both are unique in the database and
  the error should say which one clashed.
- **Editing a held achievement's name** is allowed and changes it everywhere,
  including on sheets where it is already earned. That is the point of being
  able to edit.
- **The secret flag on a held achievement** hides it from players who have not
  earned it; holders keep seeing it. 028 already reads it that way.
- **Deleting is refused, not cascaded.** The error names how many players hold it.

## Testing

- Create, edit, reorder and delete round-trip.
- The code cannot be changed by a PATCH.
- Delete is refused while held, and permitted once not.
- A row whose code has no registered trigger is marked inert.
- The triggers endpoint lists registered codes and excludes ones already used.
- Placeholder descriptions are counted and filterable.
- Duplicate code and duplicate name are refused distinguishably.
- Staff may read; only admins may write.

## Non-goals

- Editing trigger logic from the UI. A trigger is code, reviewed and tested like
  code; a rules builder is a much larger thing and probably a worse one.
- Manually granting an achievement to a player. Tempting, and a trapdoor around
  every guarantee 028 makes about awards being earned. If it is ever wanted it
  should be its own decision, with its own audit trail.
- Bulk import/export. The seed migration covers the initial load, and 026 shows
  what a CSV round-trip costs when it is actually needed.
