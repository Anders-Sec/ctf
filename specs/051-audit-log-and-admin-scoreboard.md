# Spec 051 — Audit Log & Admin Scoreboard

Status: **approved** (2026-09-17)
Phase: 3 (Polish & Operability)
Depends on: 049 (sidebar placement)
Closes: two gaps against Phase 1's Definition of Done

Two read-only pages over endpoints that **already exist and are rendered
nowhere**. Specced together because they are the same shape of work — a table
over a finished API — and separating them would be two reviews of one idea.

## 1. Why these are defects rather than features

`Plan.md`'s Phase 1 Definition of Done says:

> Admin can manually adjust a team's score and see an audit trail of the change.

and, under Real-Time Scoreboard:

> Public scoreboard view + admin view (may show more detail, e.g., raw solve
> timestamps for tie-breaking).

Neither is true in the UI:

- `GET /api/admin/audit-log` exists at
  [`admin_ops.py:302`](../backend/app/api/routes/admin_ops.py#L302), resolves
  actor names rather than returning raw uuids, and has a typed client at
  [`adminOps.ts:104`](../frontend/src/api/adminOps.ts#L104). **Nothing calls it.**
- `GET /api/admin/scoreboard` exists at
  [`scoreboard.py:94`](../backend/app/api/routes/scoreboard.py#L94) and returns
  both boards in full with tie-break timestamps. **Nothing calls it.**

The audit log is written to correctly all over the backend — approvals, kicks,
event config, score adjustments, challenge edits, instance teardowns. The record
is there. It has simply never been readable without a database client.

## 2. Audit Log — `/admin/audit`

A dense, reverse-chronological table. The reading task is almost always "what
happened to *this thing*" or "what did I do around *this time*", so the page is
built around filtering to those.

| Column | Notes |
| --- | --- |
| When | Absolute local time plus a relative hint. Absolute is primary — reconstructing a timeline from "3 hours ago" is not possible. |
| Actor | Resolved display name; **"system"** where `actor_user_id` is null, which is scheduled cleanup and automatic leadership transfer, not an unknown person. |
| Action | The dotted verb (`user.approve`, `team.kick`, `event_config.update`). Rendered as-is — it is the real vocabulary and inventing friendly names for 30-odd verbs creates a translation table to keep in sync. |
| Target | Type plus a resolved name where one can be resolved, falling back to the id. |
| Reason | Free text where supplied. Score adjustments require it. |
| Details | The `metadata` JSONB, collapsed to a row-expander. |

**Filters**: action (a select populated from the distinct actions present, not a
hardcoded list), actor, target type, and a date range. Combinable. Filtering is
server-side.

**Free-text search** over `reason` and the resolved target name.

**Not editable, and not deletable.** The table is append-only by design; the page
offers no affordance that suggests otherwise.

### 2.1 What the endpoint needs added

The endpoint currently takes only an optional `action` and returns a bare list.
It needs:

- Query parameters: `actor_user_id`, `target_type`, `since`, `until`, `search`,
  `limit`, `offset`.
- A `total` alongside the rows, so the page can paginate honestly.
- A companion `GET /api/admin/audit-log/actions` returning the distinct actions
  present, for the filter select.

Pagination rather than spec 041's "no pagination" call: the challenge list is 242
rows with a known ceiling, whereas the audit log grows unbounded across five days
of approvals, kicks and edits, and has no natural grouping to collapse under.

### 2.2 Cross-links

The audit log is most useful arrived at from context, not from the sidebar:

- A player's detail page (spec 052) links to the log filtered to that target.
- A party's detail page (spec 053) does the same.
- The adjustments list on Reports & Adjustments links each adjustment to its
  audit entry.

## 3. Admin Scoreboard — `/admin/scoreboard`

The public scoreboard exists and is good. This is the version for settling
questions, and it differs in four ways:

1. **Tie-break timestamps are visible.** The endpoint already returns them. Two
   players on equal points are ordered by who got there first, and the page shows
   the timestamp that decided it rather than asking anyone to trust the sort.
2. **Adjustments are broken out.** A player's total splits into solve points and
   manually adjusted points, with the adjustment reason on hover. When someone
   asks why a score looks wrong, this is the answer, and on the public board it
   is deliberately invisible.
3. **Hidden and disabled accounts are shown**, marked as such. The public board
   filters them; an admin settling a placement needs to see that the account
   above someone is disabled.
4. **It does not hide behind the event gate.** The public board can be closed by
   event state; this one is always readable by staff, including before the start
   and after the end.

Both boards — players and parties — on one page, side by side on a wide screen
and stacked below it, matching what the endpoint already returns.

**Exportable to CSV from the page**, for the awards conversation. The full event
export is spec 056; this is the one-click "give me the standings as they are right
now", which is a different and more frequent need.

**Polling, not a socket.** The public board holds a WebSocket because 200 players
watching it rank-shuffle is the experience. One admin settling a placement does
not need sub-second updates, and a second socket subscriber class is a second
thing to get wrong. A 15-second poll with a manual refresh.

### 3.1 What the endpoint needs added

`GET /api/admin/scoreboard` returns `_payload(db, redis)` — the same shape the
public board gets. It needs, per entry:

- `solve_points` and `adjustment_points` split out of the total.
- `status` and `role`, so disabled and staff accounts are visible as such.
- Tie-break timestamps surfaced in the response rather than only used for
  ordering, if they are not already.

## 4. Testing

**Audit log**

- Each filter narrows correctly, and filters combine.
- `search` matches reason text and resolved target names.
- A null actor renders as "system", not as a blank or an id.
- A target whose row has since been deleted renders the id rather than erroring —
  the log outlives its targets and this is the common case for a deleted
  challenge.
- `total` is the count of matching rows, not of the returned page.
- The actions endpoint returns only actions actually present.
- Staff may read; a player gets 403.

**Admin scoreboard**

- Two equal-point players are ordered by tie-break timestamp, and the page shows
  it.
- A player with an adjustment shows the split, and solve + adjustment equals the
  displayed total.
- A disabled account appears and is marked; the same account is absent from the
  public board.
- The board is readable by staff before the event starts and after it ends, with
  a test for each.
- CSV export contains one row per entry with the same numbers the table shows.

## 5. What implementation changed

Recorded per `CLAUDE.md`.

1. **Spec 049's sidebar had no entry for this scoreboard.** Its §3 table lists
   every admin page and omitted this one, so the page would have existed with no
   way to reach it. Added to Operations, below Anti-Cheat Signals.
2. **Unranked accounts are a separate section, not marked rows inside the
   ranking.** §3.3 said disabled and staff accounts are "shown, marked as such",
   which read as inline. Inline is not possible without breaking the property
   §3's opening paragraph depends on: ranks here must equal the public board's,
   and weaving an unranked account in shifts every position below it. They are
   listed underneath with their reason instead, and an account that never played
   is left out entirely — otherwise every staff account and pending signup would
   bury the one disabled player the section exists for.
3. **The solve/adjustment split is derived by subtraction**, not recomputed.
   `score` comes from the public board's computation and `solve_points` is
   `score - adjustment_points`, so the two halves cannot drift from the total.
4. **`GET /api/admin/audit-log` now returns an envelope**, not a bare list. The
   two existing tests asserting on a list were updated.
5. **Search covers reason and action, not resolved target names.** §2.1 asked
   for target names too; they live across half a dozen tables and resolving them
   in SQL would mean a union over all of them for a box that is used on reasons.
   Target names are still resolved for display.

## 6. Open questions

Signed off 2026-09-17. Each recommendation below was accepted as written
unless a **Decision** line says otherwise.

1. **Should the audit log expose `request_id`?** It ties an entry to the
   application logs, which is genuinely useful when debugging, but it is noise in
   a table read for human reasons. Recommend: inside the expanded details row
   only, not as a column.
2. **How far back should the default view reach?** Recommend: the last 24 hours by
   default with the range control visible, rather than page one of everything —
   during an event the recent past is nearly always the question.
