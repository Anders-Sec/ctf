# Spec 060 — The Character Sheet

Status: **approved** (2026-09-18)
Phase: 3 (Polish & Operability) — quality of life, player-facing
Depends on: 016/024 (classes), 018 (abilities and skills), 028 (achievements),
038 (loot), 059 (rank, and the XP rule)
Scope: **the player's own sheet only.** Somebody else's sheet is the next pass.

The second-most-looked-at screen, and the one that reads least like what it is
meant to be. A 5e character sheet spreads its information across the page in
groups you learn the shape of; ours is one 2xl-wide column of nine sections
stacked vertically, so finding your skills means scrolling past your loot.

This is a layout spec. Almost nothing here is new data.

## 1. What is wrong with it now

`OwnSheet` renders nine blocks in a single `max-w-2xl` column, in this order:

> Header → Class → Level/XP → Abilities → Stars → Loot → Achievements → Skills

- **It is a feed, not a sheet.** Everything is the same width, stacked, in an
  order nobody chose. The page height varies with how much loot you are holding.
- **Related things are far apart.** Level is in the header *and* in its own
  section two blocks below. Class is a section of its own directly above them.
- **Three lists have no bounds.** Skills, achievements and titles each render
  every row they have, so a player with 45 skills and 110 achievements scrolls
  through 155 rows to reach the bottom of the page.
- **Only one of them can be searched.** Skills has a search box and a funny
  filter; achievements and titles have neither.
- **The worn title is buried.** It is the name everybody else sees on the
  scoreboard (059 §2), and the only place its owner can find it is inside the
  loot section's inventory list.

## 2. The layout

Two columns on a wide screen, and the grid is the spec:

```
┌─ Player info ─────────────────────────────────────────────────┐
│  ◑  Grix  "the Unbothered"        Rogue ▸    Rank 12          │
│                                   Lv 7       The Mimics       │
│     ████████████░░░░░░░  450 / 1,200 XP to level 8            │
├─ Stats ────────────────┬─ Achievements ───────────────────────┤
│  STR 14   DEX 17       │  ★ ★ ★ ★ ★   the five rarest held   │
│  CON 12   INT 15       │  ─────────────────────────────────── │
│  WIS 11   CHA 13       │  Search…              [ Earned ▾ ]   │
│  ───────────────────   │  ▓ First Blood            2.1%       │
│  Search…   [ Kind ▾ ]  │  ▓ Night Owl             14.0%       │
│  ▓ Injection Artistry  │  ▓ ░░░░░░░░░ (not yet)               │
│  ▓ Auth Bypass         ├─ Loot ───────────────────────────────┤
│  ▓ ░░░░░░░ (undisc.)   │  ◀  [box] [box] [box]  ▶   2 to open │
│  ▓ …                   │  ─────────────────────────────────── │
│  ▓                     │  Search…            [ Rarity ▾ ]     │
│  ▓                     │  ▓ the Unbothered   gold    · worn   │
│  ▓                     │  ▓ the Persistent   bronze           │
└────────────────────────┴───────────────────────────────────────┘
```

**Player info spans the full width.** It is the identity block, and a 5e sheet
puts identity across the top for the same reason.

**Stats is the left column**, as on the printed sheet: abilities, then the skills
they are made of. It is one tall panel, so its height is the sum of the two on
the right — which is what keeps the columns level.

**Achievements and Loot stack in the right column.** Both are about what the
player has *collected*, which is the other half of a sheet.

### 2.1 Sizes are fixed

Every panel and every list inside one has a **fixed height**. Nothing reflows as
data loads, nothing moves when a box is opened or a skill is discovered, and the
sheet is the same shape for a level-2 player and a level-15 one. That is the
single change that makes the page read as a printed sheet rather than a feed.

The target is **one screen on a laptop, with a little scroll acceptable** — panels
are sized generously rather than squeezed to guarantee no page scroll at all.
The inner lists show **8–12 rows** each and scroll internally past that.

### 2.2 On a phone

One column, in reading order: **Player info → Stats → Achievements → Loot.** The
left column lands before the right, so the order matches what the eye does on
the desktop layout. Panels keep their fixed heights; the page scrolls.

## 3. The blocks

### Player info

| Item | Source | Note |
| --- | --- | --- |
| Avatar and name | `display_name`, `has_avatar` | |
| Worn title | **new** on the sheet | Beside the name. It is the name plate everybody else sees on the board (059), and today its owner can only find it inside the loot inventory. |
| Class | `character_class` | **Static text**, with its rarity colour. Clicking it opens the class dialog (§4). |
| Level | `level` | |
| XP bar | `xp_into_level`, `xp_to_next`, `total_xp` | **With the numbers**, not just a bar. 059's rule is about *other people's* XP and about boards; a player's own is theirs to see, here and in their own nav chrome (064). |
| Party | **new** on the sheet | Name, linking to the party. |
| Rank | `rank` | |

### Stats (left)

- **Abilities**: the six, condensed, score-in-a-box. No progress toward the next
  point — abilities tick up quietly by design (018).
- **Skills**: a fixed-height scrolling list with a search box and two filters —
  **Kind** (any / useful / funny) and **Discovered** (any / discovered only).
  Undiscovered rows keep their blur: the server sends no name for them, so the
  blur is honest rather than cosmetic, and search only ever matches discovered
  ones because a placeholder has nothing to match.
- Header carries `N of M discovered`.

### Achievements (right, upper)

- **The five rarest held**, across the top as a row of small cards with the
  percentage of players holding each. `rarest_held` already returns exactly
  five, sorted — no backend work.
- **The rest**, as a fixed-height scrolling list with search and an **Earned**
  filter (any / earned / not yet).
- Search matches earned achievements only, and **says so**, because spec 028
  redacts the name and description of anything unearned server-side. There is
  genuinely nothing to search. The count `N of M earned` stays in the header —
  the total is public on purpose, as something to aim at.

### Loot (right, lower)

- **The box shelf**: a horizontally scrolling row of unopened boxes, **ordered
  by rarity, best first**, at a fixed height whether there are none or twelve.
  Empty says so rather than collapsing. Opening a box keeps the existing flow
  (038); the shelf does not resize when one is opened.
- **The title inventory**: one line per title — name, rarity, and whether it is
  worn — with search and a **Rarity** filter, fixed height, scrolling. Equipping
  from here is unchanged.

### Dropped: bosses felled

`StarsSection` leaves the own sheet. A player can see which bosses they have
beaten on the challenge list, and the stars are on both scoreboards (059). The
`/character/stars` endpoint **stays** — it is untouched, and somebody else's
sheet is the next pass.

## 4. Changing class

The class in the player info block is static text. Clicking it opens a **dialog**
holding what `ClassSection` holds today:

- The roster of **unlocked classes only** — the server never sends the rest, so
  the roster stays a mystery until a class is earned (024). Classless is an
  option.
- Below the unlock level, the roster is replaced by *"Reach level N to choose a
  class"*, as now.
- The System AI's suggestion line (013/016), in its own voice.

A dialog rather than a fourth panel because the sheet has to fit a screen and
this is a thing you do rarely; a dialog rather than a route because the roster is
four fields and a sentence, and a page for it would be mostly empty.

## 5. Shared pieces

Three lists want the same chrome: a search box, one or two `<select>` filters, a
fixed-height scroll region, an empty state and a count. Written once, in
`components/sheet/`:

| Piece | What it does |
| --- | --- |
| `SheetPanel` | A titled, bordered, fixed-height block with an optional right-aligned summary in its header. Every block on the page is one. |
| `FilteredList` | Search + declared filters + the scroll region. Owns the query and filter state; the caller supplies a predicate and a row renderer. |

The lesson from spec 058: four near-identical panels written four times is four
places to fix a scroll bug. `FilteredList` is deliberately *not* `ContentPage` —
that one is an admin CRUD shell with selection and bulk actions, and none of that
belongs on a player's sheet.

The box shelf is its own component: it scrolls horizontally, has no search, and
its items are cards rather than rows.

## 6. Backend

Two fields on `CharacterSheetResponse`, both already one join away:

- **`party`**: `{id, name} | null`. Available in the session today, but the sheet
  should describe the character without the caller stitching two payloads
  together — and the public sheet will want it in the next pass.
- **`equipped_title`**: `string | null`. Otherwise the identity block waits on
  the loot query to render a player's name plate.

Neither adds a query the sheet does not already make. Nothing else changes:
`rarest_held` already returns five, skills already carry `kind` and `discovered`,
and loot already exposes boxes and titles.

**No new XP anywhere.** 059's rule stands: this screen is the exception, and it
stays the only one.

## 7. Testing

- The sheet renders all four blocks, and each panel holds what §3 says.
- **Panel heights do not change with content**: the same sheet with zero boxes
  and with twelve renders the loot panel at one height.
- Skills: search matches discovered rows only; Kind and Discovered filters
  narrow; an undiscovered row stays blurred and unsearchable.
- Achievements: the five rarest render with their percentages; the Earned filter
  narrows; search does not match an unearned row even by its id.
- Loot: boxes order by rarity best-first; an empty shelf says so at the same
  height; a title shows as worn.
- The class name opens the dialog; the dialog lists unlocked classes only; below
  the unlock level it shows the gate instead of the roster; choosing one closes
  it and updates the block.
- The worn title, party and rank all appear in the player info block.
- Bosses felled does not appear on the own sheet.
- **XP appears on this page and no assertion elsewhere changes** — the scoreboard
  tests from 059 keep passing untouched.
- At phone width the four blocks stack in the order §2.2 gives.

## 8. What this spec does not do

- **Touch somebody else's sheet.** `PublicSheet` is unchanged and is the next
  pass; that is also where `party` and the dropped stars get decided for a
  viewer who is not the owner.
- **Change any of the underlying systems.** No scoring, no ability curve, no
  achievement triggers, no loot pools. Every number on the page is already
  computed today.
- **Add a class-preview or comparison.** The dialog lists what is unlocked and
  takes a choice, exactly as the current section does.
- **Rework the avatar.** It renders as it does now.

## 9. Decisions

Signed off 2026-09-18.

1. **The XP bar shows both** — progress into the level *and* total XP. Total XP
   is the number a player quotes at somebody, and this is the only screen
   allowed to show it.
2. **Day-one emptiness is the point, not a cost.** Four panels at full height on
   Monday morning show a player everything there is to unlock before they have
   unlocked any of it. The empty state is a glass half full, so it gets real
   copy rather than an apology — and it is the same argument as the fixed
   heights, one step further.
3. **Skills stay display-ordered.** Scrolling past the locked ones is part of
   the point: it shows how much there is that you do not know yet. A player who
   wants the other view filters to discovered, which also answers "what level am
   I really" without a sort that reshuffles the list as they play.

## 10. As built

Built 2026-09-18. Four notes.

### The old sections are gone, not left behind

`LootSection`, `AchievementsSection` and `StarsSection` are deleted — 327 lines
and 18 tests. Their tests still passed after nothing imported them, which is
exactly why they had to go rather than stay: dead code with a green suite behind
it reads as maintained and survives indefinitely. The stars rendering is in
history if the public-sheet pass wants it back.

### Every scroll region is named

Not in §5, and it should have been. A sheet has four scrollable lists on it, and
without an `aria-label` a screen reader meets four anonymous ones. `FilteredList`
takes a `listLabel` for that reason, and it is what lets a test address one list
rather than the whole panel — which mattered immediately, because the
achievements filter deliberately does *not* touch the rarest-five cards above it.

### The unearned label is rendered twice, on purpose

Once blurred and `aria-hidden` so the shape of what is left to find is visible,
once `sr-only` so a reader hears it. That is spec 028's behaviour carried across
unchanged; it is written down here because it surprises anybody counting rows.

### The public sheet's header is byte-for-byte what it was

§8 says somebody else's sheet is untouched, and its test asserts a specific
string (`Level 2 Rogue adventurer`). The rewrite briefly changed that header
while moving code around; it is restored exactly, and that test passes unchanged.
