# Spec 059 — The Player Scoreboard

Status: **approved** (2026-09-17)
Phase: 3 (Polish & Operability) — quality of life, player-facing
Depends on: 005 (the board), 031 (boss stars), 038 (loot titles), 016/024 (classes)

The most-looked-at screen in the platform, and the one that shows the least. Two
boards, both rebuilt: what they display, how they cope with 200 rows, and where
they lead.

## 1. What is wrong with it now

The page is 209 lines and four columns per board:

> **Parties:** Party · Level · XP  **Players:** Player · Party · Level · XP

- **It shows XP, which it should not.** XP is the player's own business — it
  belongs on their character sheet and nowhere else. Publishing it turns a
  scoreboard into a comparison of numbers rather than of standing.
- **It shows nothing that was earned.** Boss stars (spec 031), loot titles
  (038) and class (016) are the things a player collects and wants seen. None of
  them appear.
- **It is a flat list of 200.** Finding yourself means scrolling; finding
  somebody else means scrolling and reading.
- **There is nowhere to go.** A party name is text. A player name is text.

And one thing that is worse than missing — **stars and titles are already
computed and thrown away.** `_rank_players` builds each row with
`"stars": stars.get(...)` and `"title": titles.get(...)`, then constructs a
`PlayerEntry` that has neither field. Two queries run on every refresh
(`star_counts`, `equipped_titles`) and their results reach nothing.

## 2. What each board shows

**XP appears on neither board, in any column, at any width.** It still *orders*
them — the scoring model is unchanged and rank is derived from XP exactly as
before — the number simply is not published. That distinction matters: this is a
display change, not a scoring one.

### Parties

| Column | Notes |
| --- | --- |
| Rank | |
| Party name | With its stars immediately beside it, not in a separate column — they read as part of the party's identity. |
| Stars | The party's **distinct** boss kills, coloured by tier. See §3. |
| Level | Already on the entry. |

### Players

The board that should carry the most, because rank, class, level and title are
the four things a player actually collects.

| Column | Notes |
| --- | --- |
| Rank | |
| Player | Name, avatar, and the **loot title** they are wearing — worn titles are cosmetic by design (038) and this is the one place they are seen by anybody else. |
| Party | Plain text, no stars. Clicking it opens the **same party panel** the party board uses (§5), so "who are they with" is answered without leaving the board. |
| Class | Their archetype, with its rarity colour (024's ladder). |
| Level | |
| Stars | **The player's own kills only** — never their party's. A player's decoration is theirs. |

## 3. Boss stars, reworked

Six tiers, six colours, already tokenised as `boss-*` and already theme-invariant
(spec 048). A star is a boss killed; its colour is that boss's tier.

**A star is identified by the boss challenge's slug.** That is the rework: a star
stops being an anonymous increment and becomes a named thing, which is what makes
deduplication possible at all — a party where six members each felled *XYZ*
carries one `xyz` star, not six.

Slug rather than challenge id, for the reason specs 027 and 040 already key on
it: it is unique (`CITEXT`, `unique=True`), it is stable across a re-import that
reassigns ids, and it is legible in a payload somebody is debugging. "Why does
this party have four stars?" becomes answerable by reading the response.

A player's stars need no deduplication of their own — `uq_solve_user_challenge`
means a player cannot solve the same boss twice. The dedup exists for parties,
where the union is across members.

**A party's stars are the distinct boss slugs its current members have felled.**
The same union rule spec 005 chose for party scoring, for the same reason: size
buys speed and coverage, never a higher ceiling. Summing per-member counts would
quietly make an eight-person party look eight times as decorated.

`star_counts` cannot answer any of this. It returns one integer per player, with
no tier and no identity, so it can neither colour a star nor deduplicate one. It
is replaced by a per-entry list of `{slug, tier}`:

- **per player**: their own boss solves, already distinct.
- **per party**: the union across current members, distinct by slug.

Rendered as a run of coloured pips grouped by tier, highest tier first, with **a
text total and a per-tier breakdown in the accessible label** — colour is never
the only carrier, and six colours side by side is exactly where that rule earns
its keep. Hovering a pip names its boss.

## 4. Coping with 200 rows

The same shape on both boards:

```
┌──────────────────────────────────────────────┐
│ Parties                          Search…     │
│  1  The Bold          ★★★  Lv 7              │
│  2  Kobold Union      ★★    Lv 6             │
│  …                                           │
│ 10  Late Starters     ★     Lv 4             │
│ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ │
│ 34  Your Party        ★★   Lv 5     ← you    │
│                                              │
│              [ Show all 47 ]                 │
└──────────────────────────────────────────────┘
```

### 4.1 Ties share a place

Two entries on equal points **share a rank**, so a board can show two third
places. Standard competition ranking, so the next entry takes the place its
position implies: `1, 2, 3, 3, 5`.

Ordering *within* a shared rank is still spec 005's tie-break — earliest to reach
the score comes first — because a list has to be in some order and "who got there
first" is the only defensible one. What changes is the number shown beside them,
not the sequence.

- **Top ten, then a break, then you.** The break is a real visual rule, not a
  gap — it says "the list skips" rather than leaving the reader to infer it from
  a rank jump.
- **Your row is marked**, on both boards: your party on the party board, you on
  the player board.
- **No break when you are already in the top ten.** Your row is simply marked
  where it is, and nothing is repeated — a duplicate row for somebody at rank 4
  would read as two entries.
- **Show all** expands to the full board. Client-side, on data already fetched:
  the payload is both whole boards already, so paging it would mean asking the
  server for something it has already sent.
- **Search** filters by name — party name on one board, player name on the
  other. While searching, the top-ten framing steps aside and matches are shown
  with their real ranks, because "rank 34 of 47" is the useful answer to a
  search and "no results in the top ten" is not.

## 5. Where a row leads

The two boards differ here, deliberately.

- **A party opens a detail panel**, on the same page, reached from either board
  — the party board's rows and the player board's Party column open the same
  panel. A party has no page of its own and does not need one; what a player
  wants is a glance at who is in it.
- **A player links through to their character sheet** at `/character/:userId`,
  which already exists and already renders somebody else's sheet. Duplicating a
  fraction of it in a panel would be a second thing to keep true.

### The party panel

Roster (names, classes, levels), distinct solve count, achievement count,
stars broken out by tier, when the party was founded, and its rank.

**No XP**, per §2 — including no member XP. The panel is a place to see who a
party is, and a per-member XP list would be the scoreboard's worst habit
reintroduced one level down.

## 6. API

`GET /api/scoreboard/players` and `/teams` keep their shape and lose `score`.
Both gain what §2 needs:

- **Player entry**: `+ stars` (slug and tier per star), `+ title`,
  `+ class_name`, `+ class_rarity`. Two of these are the values already being
  computed and discarded.
- **Party entry**: `+ stars` (slug and tier, deduplicated across members).
- Both: `score` **removed from the response**, not merely unread. A field that
  is sent and ignored is a field somebody renders by accident later.

`GET /api/scoreboard/teams/{team_id}` is new: the party panel's payload. Roster
with class and level, solve count, achievement count, stars, founded date.

The admin board (spec 051) **keeps its numbers**. It exists to settle
placements, and that is exactly the context where the arithmetic has to be
visible — `admin_scoreboard.board` reads the same computation and is unaffected
by the public entries dropping a field, because it splits `score` itself.

It also inherits §4.1's shared ranks, which is the right outcome there: the
timestamp that *breaks* a tie is already a column on that page, so an admin sees
both that two entries share a place and which of them reached it first. Spec
051's rank-parity test therefore keeps passing unchanged.

## 7. Testing

- **No response from either public board contains XP or `score`** — its own
  test, and the one that keeps §2 true as fields get added later.
- Rank ordering is unchanged by the field removal: the same fixture produces the
  same order as before.
- A party's stars deduplicate **by slug**: six members who each felled the same
  boss yield one star, carrying that boss's slug and the right tier.
- A party's stars follow its *current* roster — a member who leaves takes their
  unique kills with them, matching the scoring rule.
- A player's stars are tallied by tier, and a player with no kills reports an
  empty breakdown rather than a zero-filled one.
- Title and class reach the player entry — the regression test the dropped
  fields never had.
- The party detail endpoint returns the roster and no XP for anybody in it.
- Frontend: the break appears when you are outside the top ten and does not when
  you are inside it; your row is marked in both cases; search shows real ranks;
  "show all" needs no further request.
- Frontend: a star run carries a text total and a per-tier breakdown in its
  accessible label, and each pip names its boss.
- Ties share a rank on both boards, the next entry skips accordingly
  (`1, 2, 3, 3, 5`), and the order within a shared rank is still earliest-first.
- The player board's Party column opens the same panel the party board does.
- A signed-out or unranked viewer sees the top ten and no break, rather than an
  empty space where their row would be.

## 8. What this spec does not do

- **Touch the scoring model.** Rank is still XP, ordered exactly as spec 005
  computes it. Only what is displayed changes.
- **Rebuild the character sheet.** The player board links into it as it stands;
  that screen is its own pass.
- **Add a party page.** The panel is enough, and a route would need a place in
  the player nav that nothing else asks for.
- **Touch the live socket.** Both boards are pushed whole on every change
  (spec 005) and that is unchanged — the payload simply carries different
  fields.

## 9. Decisions

Signed off 2026-09-17.

1. **Party on the player board: kept**, as plain text linking to the party
   panel. No stars on it — those are the player's own (§2).
2. **"Show all" renders all 200.** Virtualising is machinery for a problem
   nobody has yet.
3. **A tie shares the place**, on both boards — see §4.1.
