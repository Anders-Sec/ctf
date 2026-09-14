# Spec 042 — Bulk Challenge Operations

Status: **done** (2026-09-14)
Phase: 2/3 boundary (tooling)
Depends on: 041 (the challenge manager, its selection column and its filters)

041 makes 242 challenges findable. This makes them changeable in one go.

The motivating complaint is exact: removing a challenge today costs a click into
the row, a scroll past seven sections and two more clicks. That is tedious at
eight and not realistically possible for a wing. The same is true of publishing —
setting up an event means moving whole zones from draft to published, and doing
that 242 times is not a workflow.

**This page is a setup tool.** It is used to build the event before anyone plays.
So the design goal here is *low friction*, not ceremony: one confirm where the
consequence is real, none where it is not.

## 1. Selection

041 puts the checkbox column in place. This gives it meaning.

- **Click** a checkbox to toggle one row.
- **Shift-click** to select the range between it and the last one clicked.
- **A zone header checkbox** selects everything in that zone, and shows a
  partial state when some of its rows are selected.
- **"Select all N matching"** — the one that matters. When a filter is active the
  toolbar offers to select every row the *filter* found, not merely the ones
  rendered. This is why 041 filters server-side.

The selection survives collapsing a zone and clearing a filter, because
otherwise "select all in Crypto, then all in Forensics" is impossible. It is
cleared by an explicit **Clear** and by any operation that completes.

A toolbar appears when anything is selected, pinned to the bottom of the list:

```
  14 selected · all of Networking + 3   [Clear]
  [Set state ▾] [Set difficulty ▾] [Set XP…] [Skills ▾] [Move zone ▾] [Delete]
```

## 2. The operations

| Operation | Notes |
| --- | --- |
| **Set state** | draft / hidden / locked / published. Expected to be the most used — a zone goes live as a unit. |
| **Set difficulty** | One of the six. Does **not** touch XP (spec 040). |
| **Set XP** | An absolute value, or a relative adjustment (`+25`, `-10%`). Retuning a zone is the case this exists for. |
| **Add / remove skills** | Additive and subtractive, not "replace" — applying a shared skill across a zone is the real use, and replace would silently wipe per-challenge mappings. |
| ~~**Move to zone**~~ | *Deferred — see §8.2.* Would reassign the category, and can empty a zone. |
| **Set release time** | One timestamp across a timed wave, or clear it. |
| **Delete** | See §3. |

Not included, deliberately: **bulk flag, hint and boss editing.** A flag is
per-challenge by nature, a hint is prose, and there is one boss per zone so
"bulk" is meaningless. Those stay in the drawer.

Every bulk operation writes **one audit entry** naming the action, the count and
the affected challenge ids — not N entries. A bulk edit is one decision, and 242
rows in the audit log would bury the rest of it.

## 3. Delete

One confirm. It names what is going and what else goes with it:

```
Delete 11 challenges?

  · 11 challenges in Networking
  · This empties Networking, so the zone will be deleted too.
    Its 6 skills will be kept but lose their zone grouping.
  · 2 cannot be deleted — players have solved them. They will be skipped.

                                      [Cancel]  [Delete 9]
```

No typed confirmation, no second step. The dialog's job is to tell you the blast
radius, and once it has, a second click adds nothing.

### Partial results, not all-or-nothing

Deleting a challenge with solves is refused
([admin_challenges.py:408](../backend/app/api/routes/admin_challenges.py#L408));
hiding is the operation that is actually wanted there. So a bulk delete can be
*partly* impossible.

The CSV importer is all-or-nothing and that is right for it — a half-imported
file cannot be read back. A bulk delete is the opposite: refusing to remove 9
deletable challenges because 2 have solves would be obstructive, and the admin
can see exactly which 2 survived. **So: skip the refusable ones, delete the rest,
and report per-item.** The count in the confirm button already reflects it.

The response reports every id with its outcome, and the toolbar renders the
failures rather than a bare "some failed".

## 4. The zone-deletion hazard

Per spec 013, **a category exists exactly as long as something is in it** —
deleting its last challenge deletes the zone
([challenges.py:433](../backend/app/services/challenges.py#L433)). One at a time
that is a sensible tidy-up. In bulk it is a surprise: selecting a zone's eleven
rows and pressing Delete removes the zone, its `display_order`, its ability
mapping and its authored map position, and `SET NULL`s its skills' `category_id`
so the skill picker and `SKILLS.md` lose their grouping.

This is not a mid-event worry — it is a real, immediate loss at setup time, and
it is invisible from the selection. So the confirm names it, as above.

The same applies to **Move to zone**, which can empty the source zone by moving
everything out of it. That confirm says so too.

The pruning behaviour itself is unchanged. This spec surfaces it, it does not
argue with it.

## 5. API

One endpoint rather than seven:

```
POST /api/admin/challenges/bulk
{
  "challenge_ids": ["…", "…"],
  "action": "set_state" | "set_difficulty" | "set_xp" | "add_skills"
          | "remove_skills" | "move_category" | "set_release_at" | "delete",
  "value": <shape depends on action>
}
```

Returns per-item results:

```
{
  "succeeded": 9,
  "failed": 1,
  "results": [{"challenge_id": "…", "ok": false, "reason": "3 players have solved this."}],
  "categories_deleted": ["Networking"]
}
```

`categories_deleted` is there so the UI can say what actually happened rather
than what it predicted in the confirm.

**A cap of 500 ids per request.** Not a safety rail — a request-size and
transaction-length bound. 242 fits comfortably inside it.

Selecting by filter sends ids, not the filter. The client already holds them
(041 does not paginate), and re-running a filter server-side to decide what to
delete means the set can shift between the confirm and the act.

## 6. Non-goals

- **Undo.** Bulk state changes are trivially reversible by another bulk state
  change, and delete is not undoable one-at-a-time either. Building an undo log
  for this is a much larger feature than the problem justifies.
- **Bulk flag / hint / boss editing.** §2.
- **Cross-page selection.** 041 does not paginate, so there is no such thing.
- **Scheduled or deferred bulk operations.**

## 7. Testing

- Shift-click selects the inclusive range between two rows.
- A zone header checkbox selects that zone and shows partial state.
- "Select all N matching" selects rows the filter found but the viewport has not
  rendered.
- Selection survives collapsing a zone and clearing a filter.
- Each action applies to every selected challenge and to nothing else.
- Setting difficulty in bulk does **not** change XP.
- A relative XP adjustment (`+25`, `-10%`) computes per challenge from its own
  value, and never lands below 1.
- Adding skills in bulk is additive — a challenge's existing skills survive.
- Bulk delete removes the deletable ones and reports the solved ones as failed,
  in one request.
- Emptying a zone deletes the zone, and the response names it in
  `categories_deleted`.
- Moving every challenge out of a zone deletes the source zone and reports it.
- A bulk operation writes exactly one audit entry, carrying the count.
- Over 500 ids is refused with a clear message.
- Only admins may perform a bulk operation; staff are refused.

## 8. Open questions

1. **Should `set_xp` accept relative adjustments**, or only an absolute value?
   Relative is what a zone retune actually wants (`everything in Crypto +25`),
   but it is more surface and more to test. Recommend including it — it is the
   difference between one action and eleven.
2. ~~**Should "move to zone" be in the first cut?**~~ **Deferred** (2026-09-14).
   It is the only action that changes a challenge's identity in the dungeon, and
   it interacts with unlock requirements pointing at the zone. Not built: the
   `BulkAction` enum has no `move_category` member, and §2's table describes an
   action that does not exist yet. Say the word and it is a small addition.
3. **Does bulk delete need to offer "hide instead" for the refused ones?** The
   error already says hiding is what is wanted. Offering it as a one-click
   follow-up in the result toast is cheap. Recommend yes.
