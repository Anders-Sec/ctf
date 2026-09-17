# Spec 056 — Event Export

Status: **approved** (2026-09-17)
Phase: 3 (Polish & Operability)
Depends on: 049 (sidebar placement), 051 (the admin scoreboard's numbers)
Related: 026/040 (challenge CSV — import/export of *content*, not results)

Get the event's results out of the platform, for awards on the last afternoon and
for the write-up afterwards.

## 1. What exists and what does not

Content export is solved. Spec 040 gave the challenge CSV full fidelity — every
property, flags with match types, hints, prerequisites, boss tiers — and spec 027
does the same for the map layout. Both exist so an event can be *rebuilt*.

Nothing exports what *happened*. After five days the platform holds every solve,
every submission, every hint unlock, every achievement and every adjustment, and
the only way to get any of it out is a screenshot of the scoreboard.

Two moments need this, and they are different:

- **The awards, on the last afternoon**, under time pressure, with people
  waiting. Needs: final standings, category winners, first-blood credits — read
  off something printable, right now.
- **The write-up, the week after.** Needs: everything, in a form that can be
  loaded into a spreadsheet or a notebook without an API client.

Trying to serve both with one file serves neither.

## 2. The page — `/admin/export`

Under Settings. A short page: a set of named exports, each with a one-line
description and a download button, plus the full archive at the bottom.

| Export | Format | For |
| --- | --- | --- |
| **Final standings** | CSV | Player and party boards with rank, solves, XP, points, adjustments and tie-break timestamps. |
| **Awards sheet** | CSV | The derived list: overall top N, top per category, first blood per challenge, boss first-kills, biggest single-day climb. See §3. |
| **Solves** | CSV | One row per solve: player, party at solve, challenge, zone, XP awarded, timestamp. |
| **Submissions** | CSV | Every attempt, correct and incorrect. See §4 on the redaction. |
| **Players** | CSV | Roster with source, party, level, class, XP, achievements, hints used. |
| **Parties** | CSV | Roster and aggregates, including disbanded ones. |
| **Score adjustments** | CSV | Every manual change with reason, actor and whether it was reversed. |
| **Audit log** | CSV | The whole log, as spec 051 shows it. |
| **Full archive** | ZIP | All of the above, plus a `manifest.json` with the event name, window, generation time and row counts per file. |

Every CSV uses UTF-8 with a BOM — the files are opened in Excel, and without it
every non-ASCII display name is mangled on arrival.

Timestamps are ISO-8601 UTC, with a second column rendering the admin's local
time. The server clock is the one the gates use (the event settings page already
makes this point), and the awards conversation happens in local time.

## 3. The awards sheet is the one that saves the afternoon

Everything else is a table dump. This one is derived, and it is derived from
decisions that should be made now rather than at 3pm on Friday:

- **Overall standing** — the admin scoreboard's order, including the tie-break
  timestamp that settled each close placement.
- **Top per category** — highest XP within each of the 22 zones. A category
  nobody completed still has a winner.
- **First blood per challenge** — first solver and how far ahead of second.
- **Boss first-kills** — per spec 031, already tracked and already broadcast.
- **Most improved / biggest single-day climb** — rank change across the event.
- **Completionists** — players who cleared a whole zone.

These are read aloud from a printed sheet. The CSV is grouped by award with a
header per group, rather than one wide table — it is a document more than a
dataset, and it is the one export where that is the right call.

## 4. Submissions, and what gets redacted

The submissions export is the one with a real decision in it. `Submission` holds
`submitted_value` — every string every player ever typed into a flag box.

That file is, in effect, **a list of every flag in the event** (every correct
submission is a flag) plus a record of everyone's fumbling.

So there are two forms, and the page offers both explicitly:

- **Redacted (default)** — `submitted_value` replaced by derived columns:
  length, whether it matched, and the near-miss distance from spec 050. Answers
  every analytical question ("was this challenge's flag format confusing?")
  without carrying the answers.
- **Full** — includes `submitted_value`. Behind an explicit confirmation naming
  what the file contains, and it writes an audit entry recording that the export
  was taken. Legitimate for post-event analysis, and it is not a file to email
  around.

`ip` is included in neither by default; it is in the full form only, for the same
reason and behind the same confirmation.

## 5. Generation

**Synchronous, streamed.** The largest table is submissions, on the order of 10⁵
rows for this event — a few seconds and a handful of megabytes. A background job
with a polling status endpoint would be more machinery than the data justifies.

Each export streams from a server-side cursor rather than materialising the rows
in memory, so the shape holds if the event is bigger than expected.

The ZIP is built by streaming each CSV into it in turn, for the same reason.

**Available whenever**, not gated on the event having ended. Exporting mid-event
is a legitimate thing to want — it is how you check the awards sheet computes
what you expect *before* the afternoon you need it.

## 6. API

- `GET /api/admin/export/{name}.csv` — `name` from the §2 list. `Staff`.
- `GET /api/admin/export/submissions.csv?full=true` — `Admin`, audited.
- `GET /api/admin/export/archive.zip` — `Staff`; excludes the full submissions
  form, which is only ever downloaded deliberately and on its own.

Content-Disposition carries a filename with the event name and a timestamp, so
three downloads during one afternoon do not become `export (2).csv`.

## 7. Testing

- Each export's row count matches the underlying table for a seeded fixture.
- Standings match the admin scoreboard exactly, including tie-break ordering —
  one number, two surfaces, and they must not drift.
- The awards sheet derives each award correctly, including a category with no
  completions and a tie in first blood.
- **The redacted submissions export contains no `submitted_value` and no `ip`** —
  its own test, and the important one.
- The full form contains them, requires `Admin`, and writes an audit entry.
- The archive contains every expected file plus a manifest whose row counts match
  the files.
- CSVs open cleanly with a non-ASCII display name (the BOM is present).
- A seeded 10⁵-row submissions table streams without loading fully into memory.
- Exports work before the event starts, during, and after it ends.
- A player gets 403 on every export route.

## 8. Open questions

Signed off 2026-09-17. Each recommendation below was accepted as written
unless a **Decision** line says otherwise.

1. ~~**Is the awards list in §3 the right list?**~~ **Decision (2026-09-17):
   the list in §3 is right as it stands.** No change.
2. **Should the export include AI assistant transcripts?** They exist (spec 036
   retains sessions) and are interesting for the write-up, particularly the
   prompt-injection ladder attempts. They also contain everything players said in
   confidence to what they experienced as a chat. Recommend: excluded from the
   archive, available as a separate deliberate export behind the same confirmation
   as full submissions — but this needs a decision, not a default.
3. **PDF for the awards sheet rather than CSV?** A printable document is closer to
   what the moment needs. Recommend CSV for now — it is what the rest of the page
   emits, and a spreadsheet prints — and revisit only if the sheet is actually
   being printed.
