# Spec 061 — Somebody Else's Character Sheet

Status: **draft**
Phase: 3 (Polish & Operability) — quality of life, player-facing
Depends on: 060 (the own sheet this mirrors), 028/030 (achievement redaction),
031 (boss stars), 059 (rank, the party panel, and the XP rule)

Spec 060's explicit non-goal, now its own pass. The same sheet seen from
outside: what a player shows the room, minus everything that is nobody else's
business.

It matters more than it looks — it is reachable from **two** places already, the
player board's names and the party panel's roster (059), and those are the most
clicked rows on the most looked-at screen.

## 1. What it is today

`PublicSheet` is a header, a stat block and a skill table in a `max-w-2xl`
column — the layout 060 just replaced on the own sheet, still standing here. Two
things it already gets right and keeps:

- **Undiscovered skills are omitted, not blurred.** The server sends only
  discovered rows: *"there is nothing to tease a stranger with."*
- **No XP and no rank**, because `PublicCharacterResponse` carries neither.

## 2. The layout

The same grid as 060, panel for panel, so the two sheets read as the same
artifact rather than two designs:

```
┌─ Player info ─────────────────────────────────────────────────┐
│  ◑  Grix  "the Unbothered"        Rogue      Rank 12          │
│                                   Lv 7       The Mimics ▸     │
├─ Stats ────────────────┬─ Achievements ───────────────────────┤
│  STR 14   DEX 17       │  ★ ★ ★ ★ ★   the five rarest named  │
│  CON 12   INT 15       │  ─────────────────────────────────── │
│  WIS 11   CHA 13       │  Search…              [ Any kind ▾ ] │
│  ───────────────────   │  ▓ First Blood            2.1%       │
│  Search…   [ Kind ▾ ]  │  ▓ ░░░░░░░░░░░              —        │
│  ▓ Injection Artistry  │  ▓ Night Owl             14.0%       │
│  ▓ Auth Bypass         ├─ Feats ──────────────────────────────┤
│  ▓ Frequency Analysis  │  38 solved · 12 awards · 14 skills   │
│  ▓ …                   │  ●●● ●● ●   6 bosses felled          │
│  ▓                     │  ─────────────────────────────────── │
│  ▓                     │  Web 12 · Crypto 8 · Forensics 6 …   │
└────────────────────────┴───────────────────────────────────────┘
```

**No XP bar and no total XP**, which is the one structural difference in the
identity block. Everything else in it stays: name, avatar, worn title, class,
level, rank and party.

**The class is static text**, with its rarity colour and no dialog behind it.
Somebody else's calling is not yours to change.

**The party opens the party panel from 059**, not `/party` — that route is the
viewer's *own* party page and would be the wrong destination entirely.

Panel heights, breakpoints and the phone stacking order are 060's, unchanged:
identity, stats, achievements, feats.

## 3. Stats

Identical to 060's panel with one thing removed: **the Discovered filter is
gone**, because every row is discovered — the server sent nothing else. Search
and the Kind filter stay, and no row is blurred.

The header reads `14 of 45 discovered`, which needs `skills_total` on the
response since the list itself no longer carries the undiscovered ones.

## 4. Achievements

**Only what they have earned.** Not the full roster with theirs marked — this is
a trophy case, not a progress bar, and their progress is not the viewer's
business.

**Descriptions are dropped from the payload entirely.** Not hidden, not
truncated — absent. Worth being precise about why, because the obvious reason is
wrong: the text that says *how* to earn an achievement is `earned_by`, and that
has never reached any player, on any sheet. `description` is the System AI's
flavour line shown once earned. Dropping it costs a little colour and removes a
class of hint nobody has to reason about again.

### 4.1 Secrets are blurred, honestly

An achievement marked `secret` that **the viewer has not earned themselves** is
listed as a **blurred placeholder** — a row, in position, with no name and no
percentage.

- **The blur is server-side.** The row arrives with `name: null` and
  `rarity: null`. There is nothing to un-blur in devtools, which is spec 028's
  rule and the only version of this worth building.
- **A secret the viewer has earned shows normally.** Two people who both found
  the Mimic can see it on each other.
- **It is the same treatment the own sheet already gives an unearned row** —
  blurred name, `—` for rarity — so a player has already learned what it means.

The alternative of hiding them entirely was considered and rejected: a player's
proudest finds should be visibly *there*, just unreadable.

### 4.2 The rarest five

The five rarest the **viewer can see named**. Secrets excluded, even though they
are likely the rarest a player holds — a trophy case of five blurred squares
brags about nothing and looks broken.

The count line carries the rest: `12 earned · 6 secret`.

## 5. Feats

The block where the own sheet has Loot, because a stranger's inventory is not a
thing to browse.

| Item | Note |
| --- | --- |
| **Bosses felled** | Their stars, coloured by tier and named on hover. 060 dropped these from the *own* sheet because a player can look at their own challenge list — you cannot look at somebody else's, so this is the only place their kills appear on their own page. Renders with 059's `BossStars`. |
| **Three counters** | Challenges solved · achievements earned · skills discovered of the total. |
| **Where they hunt** | Solves per zone, biggest first: `Web 12 · Crypto 8 · Forensics 6`. A player's shape at a glance, and the closest thing we have to a 5e sheet's proficiencies. |

**Deliberately not here: hints used and failed attempts.** Both are real numbers
we hold and both are interesting. Neither belongs on a page colleagues will open
about each other at a work event.

**No XP, in any form**, including none implied — no points, no per-zone totals,
only counts.

## 6. Backend

### `PublicCharacterResponse` gains

| Field | Source |
| --- | --- |
| `rank` | The scoreboard projection the route already loads for the own sheet. |
| `party` | `_party_of`, added in 060. |
| `equipped_title` | `_equipped_title`, added in 060. |
| `stars` | `stars_for`, which already exists — **plus `slug`**, see below. |
| `solve_count`, `zones` | One new grouped query: solves joined to category. The count is the sum, so it costs nothing extra. |
| `skills_total` | The roster length, already loaded to build the skill rows. |

`rank` is the only field that can be null for a real reason: the board holds
active player-role accounts only, so a staff account has no row. Null is the
honest answer there — they genuinely have no rank — and every other field is
computed directly and correct for anybody.

**`Star` gains `slug`.** `stars_for` selects the challenge already; adding one
column converges it with 059's `BossStar` shape so one component renders both.
`StarResponse` gains the field too — additive, and the own `/character/stars`
endpoint is otherwise untouched.

### `GET /character/{user_id}/achievements` — new

Mirrors the own `/character/achievements`, which is why it is a second request
rather than a fatter sheet payload: the two sheets then load the same way.

```
{ earned: 12, secret_count: 6, items: [...], rarest: [...] }
```

- `items`: the target's earned achievements. A secret the viewer has not earned
  arrives as `{id, name: null, rarity: null}`.
- `rarest`: the five rarest **nameable** ones (§4.2).
- No `description` on any row, and no `total` — the roster size is a fact about
  the game, not about this player, and it is on the viewer's own sheet already.

Route ordering is safe: `/character/achievements` is one segment and
`/character/{user_id}/achievements` is two, so neither shadows the other. It is
declared above the `/{user_id}` catch-all regardless.

## 7. Testing

- The sheet carries rank, party, worn title, class and level — and **no XP
  field of any kind**, asserted by scanning every key.
- A staff account's sheet renders with a null rank rather than failing.
- Skills: every row is discovered, there is no Discovered filter, and nothing is
  blurred. `N of M discovered` counts correctly from `skills_total`.
- **A secret the viewer has not earned arrives with a null name and null
  rarity** — the redaction test, and the one that keeps 028 true here.
- The same secret, when the viewer *has* earned it, arrives named.
- A non-secret achievement the target earned is always named.
- The rarest five never contain a blurred row.
- No achievement row on this endpoint carries a description.
- Feats: stars carry slug and tier; the zone breakdown sums to the solve count;
  hints and attempts appear nowhere in the response.
- The party opens 059's panel, not `/character`'s own party route.
- Viewing your own id still renders the own sheet (060), unchanged.
- **Every spec 060 test passes untouched.** The own sheet is not in scope.

## 8. What this spec does not do

- **Touch the own sheet.** 060 is done; this mirrors it.
- **Show loot.** A stranger's inventory is not a thing to browse, and the worn
  title — the only part anybody else is meant to see — is already in the
  identity block.
- **Let anybody change anything.** No class dialog, no equipping, no actions at
  all. It is a page you read.
- **Add a follow/compare feature.** Two sheets side by side is a different
  product; the scoreboard is where comparison belongs.

## 9. Open questions

1. **Should the zone breakdown show zones with no solves?** Showing `Crypto 0`
   says where somebody has *not* been, which is arguably as interesting and
   arguably unkind. Recommend **omitting zeroes** — the block is a portrait, not
   an audit.
2. **Should `secret_count` appear when it is zero?** Recommend **no**: a player
   who has found no secrets should not have a line drawing attention to it,
   and the blurred rows already carry the signal when there are any.
