# Spec 041 — Challenge Manager

Status: **draft** (awaiting sign-off)
Phase: 2/3 boundary (tooling)
Depends on: 013 (admin challenge CRUD), 040 (per-challenge XP, the CSV)
Paired with: 042 (bulk selection and operations) — **not in this spec**

Spec 013 built the admin challenge list for a handful of challenges. The event
has 242. What worked at eight does not work at 242, and the gap is not cosmetic:

- A flat `<ul>` of **every** challenge ([AdminChallengesPage.tsx:100](../frontend/src/routes/AdminChallengesPage.tsx#L100)).
  No search, filter, sort or grouping.
- Clicking a row expands the **entire editor inline** — seven stacked sections,
  ~850 lines of component — pushing everything below it down the page. Your place
  in the list is gone, and so is the row you were comparing against.
- Delete is at the *bottom* of that stack behind a two-step confirm. Removing
  eight challenges is tedious; removing a wing is not realistically possible.
- `answer_count` is in the payload and **is always 0** — see §6. So the one
  signal that would tell you which challenges still have no flag is inert.

This spec rebuilds the list, the finding, and the editing. **Bulk selection and
operations are spec 042**, which builds on the selection column this one
introduces.

## 1. The shape

A dense, full-width table grouped by zone, with the editor in a **drawer** over
the right-hand side.

```
┌──────────────────────────────────────────┬─────────────┐
│ Search…        [Zone▾][State▾][Problems▾]│ Airmail   ✕ │
│                                          │             │
│ ▼ Networking   8/11 · 1,050/1,900 XP ⚠  │ Title       │
│   ☐ Port of Call   v.easy   50   ● live │ [Airmail  ] │
│   ☐ Quad Damage    easy    100   ○ draft│ Difficulty  │
│   ☐ Airmail        hard    200   ○ draft│ [hard    ▾] │
│ ▶ OSINT       11/11 · 1,900 XP   ✓ boss │ ▸ Flags (3) │
│ ▶ Crypto       0/11 · —                 │ ▸ Hints (2) │
└──────────────────────────────────────────┴─────────────┘
```

The drawer rather than an inline expander is the load-bearing choice: **the list
does not move**. You keep your scroll position, the row you are editing stays
visible, and you can open one challenge after another without re-finding your
place each time. It is also what makes a selection column usable in 042 — an
inline editor that shoves rows around under a set of ticked checkboxes is a
misclick waiting to happen.

The page goes full-width. `max-w-5xl` is right for a form and wrong for a table.

## 2. The row

| Column | Notes |
| --- | --- |
| ☐ | Selection. Inert in this spec beyond selecting a row to edit; 042 gives it meaning. Present now so 042 is not a re-layout. |
| Title | Plus a small marker when the challenge is a boss or an AI-ladder rung. |
| Difficulty | Editable in place. |
| XP | Editable in place. |
| State | Editable in place. |
| ⚑ / ? / ◆ | Counts of flags, hints, skills. Dots or small numerals, not words — they exist to be scanned, and a zero is the signal. |
| Solves | Read-only. |

**Inline editing of difficulty, XP and state** is deliberate and is expected to
remove most reasons to open the drawer at all. Setting up an event is mostly
passes over the whole set — retuning XP across a zone, moving a wing from draft
to published, relabelling difficulty after reading the area back. None of those
should cost a drawer, a scroll and a save, once per challenge.

Everything else — body, flags, hints, skills, prerequisites, container, boss
tier, the decay group — lives in the drawer.

## 3. Grouping

Grouped by zone, collapsible, with the group header carrying what an admin would
otherwise have to work out by hand:

```
▼ Networking      8/11 written · 1,050/1,900 XP · no boss · 6 draft
```

- **`n/11 written`** — how much of the zone exists. 11 is the template's spread
  (spec 026), not a limit; a zone with 14 reads `14/11` and that is fine.
- **XP against 1,900.** This matters more than it did. Spec 040 moved XP onto the
  challenge, so a zone can now drift off the budget the level curve was tuned
  against without anything complaining. The header is where that shows up.
- **Boss set or not**, since there is exactly one per zone and it is easy to
  forget one.
- **How many are still draft**, which is the "is this ready" number.

Zones are ordered by `display_order`, matching the dungeon map rather than the
alphabet. Collapsed/expanded state persists per admin in `localStorage` — a
per-viewer convenience, not shared state.

## 4. Finding

**Search** over title, slug and body. Not over flags: an admin hunting for a flag
value has the drawer, and a search box that matches answers is a search box that
leaks them into a screenshot.

**Filters**, combinable: zone, state, difficulty, boss tier, has-a-container.

**Problem filters** — the part that earns its keep at 242. Canned queries for the
questions actually asked in the week before an event:

| Filter | Finds |
| --- | --- |
| No flag | A challenge nobody can solve. |
| No skills | XP that lands nowhere on a character sheet. |
| No description | A title and nothing else. |
| No hints | Only useful combined with a difficulty filter — a hard challenge with no hint is a deliberate choice or an oversight. |
| Still draft | The pre-launch checklist. |
| Zone has no boss | Per spec 031, one per zone, and a zone without one is a wing that merely ends. |
| XP off the ladder | The value does not match what its difficulty suggests. Not wrong — 040 made it deliberate — but worth being able to review. |

Filtering happens **server-side**, so 042 can offer "select all 47 rows this
filter found" without the client having to hold every row.

## 5. The drawer

The editor's seven sections become **essentials always visible, everything else
collapsed**:

- **Always open**: title, body, difficulty, XP, state.
- **Collapsed, with a count in the heading**: Flags (3), Hints (2), Skills (3),
  Prerequisites (1), Advanced.
- **Advanced** holds what is almost never touched: slug, minimum XP, scoring
  mode, decay threshold and basis, release time, pre-release state, max attempts,
  container template, boss tier, AI ladder rung.

Delete moves out of a "danger zone" at the bottom of a long scroll and into the
drawer header, behind a single confirm. Today it costs a click into the row, a
scroll past seven sections and then two more clicks; the distance was the
problem, not the absence of a second confirmation.

Closing the drawer with unsaved changes warns rather than discarding.

## 6. The `answer_count` bug

`AdminChallengeSummary.answer_count` is computed as:

```python
answer_count=len(c.answers) if "answers" in c.__dict__ else 0
```

`Challenge.answers` is `lazy="raise"` and the query eager-loads only
`category` — so the guard is never true and **the value is always 0**. Verified
against the running API: a challenge with three answer rules reports
`answer_count: 0`. It is typed in the frontend and displayed nowhere, so nothing
broke visibly; it has simply never worked.

This spec needs it, along with hint and skill counts, and they must not be an
N+1 across 242 rows. All three become aggregate subqueries on the list query, and
each gets a test — the current value has none, which is why it stayed wrong.

## 7. API changes

`GET /api/admin/challenges` gains:

- **Query parameters**: `search`, `category_id`, `state`, `difficulty`,
  `boss_tier`, `problem` (one of the §4 canned filters), `sort`.
- **Response fields**: `answer_count` (fixed), `hint_count`, `skill_count`,
  `prerequisite_count`, `boss_tier`, `initial_points`, `ai_ladder_level`,
  `has_body`.

A **zone summary** endpoint, `GET /api/admin/categories/summary`, returns per
zone: challenge count, total XP, boss challenge id or null, and a count by state.
Computed in one grouped query rather than by the client summing a list it may
only hold a filtered page of.

**No pagination.** 242 rows of this shape is well within what a browser renders
happily, and paginating would make "select all matching" in 042 meaningfully
harder for no benefit at this size. If the event ever triples, revisit.

## 8. What this spec does not do

- **Bulk anything.** Spec 042. The checkbox column exists; it selects nothing yet.
- **Reordering challenges** by drag. Display order within a zone is not currently
  a stored property of a challenge and inventing one is its own decision.
- **Creating a challenge.** The existing create form stays as it is; authoring at
  volume is the CSV's job (spec 040).
- **The readiness dashboard** — a per-zone completeness grid. The problem filters
  in §4 answer the same questions one at a time and are the cheap 80%. Worth
  revisiting once the filters exist and it is clear which ones get used.

## 9. Testing

- The list groups by zone in `display_order`, not alphabetically.
- A zone header's XP total is the sum of its challenges' XP, and flags when it is
  not 1,900.
- A zone header reports no boss when none of its challenges carries a tier.
- `answer_count`, `hint_count` and `skill_count` are correct — the regression test
  the current code never had.
- Counting three challenges' flags, hints and skills issues a constant number of
  queries, not one per challenge.
- Each problem filter returns exactly the challenges with that problem.
- `search` matches title, slug and body, and **does not** match an answer value.
- Editing XP inline saves without opening the drawer, and does not disturb the
  row's other fields.
- The drawer opens over the list without changing its scroll position.
- Closing the drawer with unsaved changes warns.
- Only admins may edit; staff may view the list and the drawer read-only.

## 10. Open questions

1. **Does "XP off the ladder" belong as a problem filter?** Spec 040 made a
   per-challenge XP deliberate, so this filter flags intent as though it were a
   mistake. It is genuinely useful while *reviewing* a generated file. Recommend
   keeping it, worded as "XP differs from difficulty" rather than as a problem.
2. **Is `has_body` worth a field, or should "no description" filter server-side
   only?** Recommend server-side only; a boolean that exists to power one filter
   is a field that will drift.
