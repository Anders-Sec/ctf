# Spec 062 — The Challenge Board

Status: **draft**
Phase: 3 (Polish & Operability) — quality of life, player-facing
Depends on: 017 (unlock requirements), 019 (zone progression), 040 (authored XP),
044 (puzzles), 049 (the sticky sidebar this copies)

The screen players spend the event inside, and the one that currently throws them
back to the top of the page every time they win.

Two problems, and the second is the one nobody has named yet:

1. **Solving costs you your place.** The detail page is a route, so clearing a
   challenge means a full navigation back to a list that re-renders at the top.
2. **The list moves on its own.** Solving invalidates `["challenges"]`, which
   refetches the whole board. Any ordering derived from live XP therefore
   reshuffles under the player as the event runs — so fixing (1) alone would
   leave the board still sliding around.

## 1. What it is today

- **Opens on the map.** `storedView()` defaults to `"map"`; the list is a toggle.
- **Cards in a two-column grid**, grouped by category, groups sorted
  alphabetically.
- **Ordered by title.** `list_for_player` ends `.order_by(Challenge.title)` — not
  random, but alphabetical, which relative to difficulty reads as random.
- **Difficulty renders raw**: `very_easy`, straight from the enum, on both the
  card and the detail header.
- **One filter button per category.** At 21 zones that is 22 buttons above the
  list.
- **Locked challenges show their titles.** `_list_item` sends
  `title=challenge.title` unconditionally; only `body` and hints are withheld.
- **Hints outweigh the description.** `HintList` renders as a full section below
  the body, and is routinely taller than it.

One thing that is already right and must stay right: **`_is_visible` filters
`ai_ladder_leak` out of every player-facing requirement list** (spec 033's secret
route into the ladder's zone). Making criteria more prominent must not go around
it.

## 2. The list becomes the board

The map stops being the default. `storedView()` returns `"list"` unless the
player has explicitly chosen the map, and the map stays one toggle away,
untouched, for a later pass.

```
┌ Zones ────────┬ Challenges ───────────────── [search] ─┐
│ Web      8/12 │ ▾ Web Attacks                8/12      │
│ Crypto    2/9 │   ✓ Injection Artistry   120  Very Easy│
│ Forensics 0/8 │     Auth Bypass          200  Easy     │
│ 🔒 Vaults     │     Log Divination       200  Easy  ⬤  │
│ 🔒 The Depths │   🔒 ░░░░░░░░░░░░        350  Hard     │
│ …             │      └ Solve Auth Bypass first         │
│               │ ▸ Crypto                      2/9      │
│               │ 🔒 The Vaults                          │
│               │    Clear 70% of Web Attacks (8/12)     │
│               │    12 challenges · 2,400 XP            │
└───────────────┴────────────────────────────────────────┘
```

### 2.1 The zone sidebar

Sticky, the same shape spec 049 gave the admin shell, and it replaces the 22
filter buttons. Each zone carries **`cleared/total`**, which is not decoration:
spec 019 gates zones on *percent of a zone cleared*, so "I need 70% of Web" is
currently something a player works out by counting rows.

Clicking a zone scrolls to its group and opens it. A sealed zone is marked and
still listed — knowing there is more is the point.

Below `lg` it collapses to a drawer, as the admin sidebar does.

### 2.2 One challenge per row

Title · XP · difficulty · status, on one line. Everything else that is on a card
today moves into the row's second line only when it applies (attempts remaining)
or into the drawer.

**Difficulty is a label, not a value**: `Very Easy`, not `very_easy`. Defined
once, client-side, since the enum is a closed set of six.

**The puzzle-kind badge survives** — "this is a Wordle, not a flag hunt" changes
how a player approaches a row, so it earns its width.

### 2.3 Groups collapse

Per zone, remembered per browser, the same `localStorage` treatment spec 058's
`ContentGroupList` uses. A collapsed zone still shows `cleared/total`, which is
what makes collapsing safe.

## 3. Ordering

**Zone display order → difficulty → authored XP → title.**

Sorted **in the service, in Python**, not in SQL, for two reasons: the rank of a
difficulty is an explicit map rather than a dependency on the enum's declaration
order, which somebody could reorder without realising what it moved; and
`list_for_player` already materialises every row to compute values, so there is
no round trip to save.

**Authored XP, never live XP.** `Challenge.initial_points` is what the author
set; `value` decays as people solve. Ordering on `value` would mean the board
reshuffles under a player mid-event — the same complaint as losing your scroll
position, wearing a different hat. The ladder a player learns on Monday is the
one they still see on Friday.

`title` last so the order is total: two challenges at the same tier and price
must not swap between refreshes.

## 4. What a sealed thing shows

### 4.1 A sealed zone: one row

When **every** challenge in a zone is locked, the zone renders as a single
closed row carrying its unlock criteria and a carrot — `12 challenges ·
2,400 XP`. No per-challenge rows at all.

The size is deliberate. It is the reason to go and unlock it, and it gives away
nothing about *what* is in there.

### 4.2 A sealed challenge inside an open zone: no title

The row stays in place, in order, showing **XP, difficulty and its unlock
criteria** — and no title. How big and how hard it is, is the carrot; the name is
the content.

**The title is withheld server-side**, exactly as `body` already is. Sending it
and hiding it in CSS would be theatre: it would sit in the payload for anybody
who opened devtools, which is the failure mode specs 028 and 018 already refuse.

`title` therefore becomes `str | None` on `ChallengeListItem`, and on
`ChallengeDetail` too — the detail endpoint is reachable for a locked challenge
(it is what renders the criteria), so withholding in one place and not the other
would be a hole rather than a rule.

## 5. The challenge opens in place

`/challenges/:challengeId` stays a **real route**, rendered as an **overlay on
top of the list** rather than as a page of its own.

That keeps three things at once:

- **Scroll position, by construction.** The list never unmounts, so there is no
  position to save and restore — the class of bug that is easy to write and easy
  to get subtly wrong.
- **Deep links.** A shared challenge URL still opens that challenge. A modal held
  in component state would break every link anybody has already sent.
- **Back closes it.** Which is what a browser's back button means to a person
  looking at an overlay.

Solving still invalidates the board; §3's ordering is what stops that being
visible.

### 5.1 Hints shrink

`HintList` becomes a **single collapsed line** — `Hints · 3 available · 2
unlocked` — that expands on click. Inside, each hint shows its **XP cost**
before it is bought, because a hint costs real points and an affordance that
cheap to hit must not be cheap to hit *by accident*.

The title and the description take the room they should have had all along.

## 6. Backend

| Change | Why |
| --- | --- |
| `list_for_player` sorts by §3's key | Stable, authored order |
| `title` withheld when locked, on list **and** detail | §4.2, and honestly |
| `ChallengeListItem.title: str \| None` | Follows from the above |

No new endpoint and no new query. The zone grouping, the `cleared/total` counts
and the "is this zone entirely sealed" test are all derivable from the list the
client already has, and deriving them there keeps the server's contract unchanged
apart from the redaction.

`ZonePanel` also calls `listChallenges` and must keep working with a nullable
title.

## 7. Testing

- **Ordering**: a fixture of mixed difficulties and prices comes back
  zone → difficulty → authored XP → title, and a solve that changes a live value
  does not change the order.
- **A locked challenge's title is absent from the payload**, on both the list and
  the detail endpoint — asserted by scanning the serialised body for the title,
  not by reading the field.
- An unlocked challenge's title is present, and solving one does not hide it.
- `ai_ladder_leak` still appears in no player-facing requirement list.
- Frontend: a zone whose challenges are all locked renders one row with criteria
  and a count, and none of its challenges.
- Frontend: a locked row inside an open zone shows XP, difficulty and criteria,
  and no title.
- Frontend: difficulty renders as `Very Easy`; no raw enum value appears.
- Frontend: opening a challenge does not unmount the list; closing it returns to
  the same scroll offset; the URL is the challenge's own.
- Frontend: hints start collapsed and show each cost when opened.
- Frontend: zone collapse survives a remount; a collapsed zone still shows its
  count.
- Frontend: the list is the default view, and the map is still reachable.

## 8. What this spec does not do

- **Touch the map.** It stops being the default and is otherwise untouched. A
  map pass is its own spec, if it happens at all.
- **Change scoring, unlocking or hints' economics.** Only what is shown, in what
  order, and where.
- **Add zone-level unlock requirements.** A "sealed zone" is derived — every
  challenge in it is locked — not a new gate. Spec 019's percent gates already do
  this work.
- **Rebuild the puzzle, instance or report panels.** They move into the overlay
  as they are.

## 9. Open questions

1. **Should a solved challenge stay in place, or sink?** Sinking solved rows to
   the bottom of their zone keeps the working set at the top, but moves a row the
   moment you solve it — which is the thing §3 exists to stop. Recommend
   **staying in place**, with the existing *Hide solved* toggle for players who
   want them gone.
2. **Does the overlay need its own mobile treatment?** At phone width an overlay
   covering the list is indistinguishable from a page, which is fine, but it
   makes the back button the only way out. Recommend **a full-screen sheet with
   an explicit close**, since a player mid-challenge should not have to guess.
