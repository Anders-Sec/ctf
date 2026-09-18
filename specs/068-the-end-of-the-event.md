# Spec 068 — The End of the Event

Status: **draft**
Phase: 3 (Polish & Operability) — quality of life, player-facing
Depends on: 059 (final standings), 060 (the figures), 066 (the landing page)
Second of four: 067 the party, **068** the ending, 069 the ticker, 070 settings.

Five days of play currently end like this:

> **The crawl is over**
> Thanks for playing. The scoreboard stands as its final record.

That is the entire payoff. This spec gives the event an ending worth looking at,
and it is close to free: every number already exists.

## 1. Why now, and why it is cheap

Two things make this small:

- **The scoreboard stays readable after the end.** `view_scoreboard` is
  `approved and (is_staff or started)` — it turns on when the event starts and
  never turns off. Nothing has to be preserved or frozen.
- **Every figure is already computed**: standings from the board, solves and
  stars from the sheet, the rarest achievement from `rarest_held`, the worn
  title from loot.

There is no new data here at all. It is an arrangement of what five days already
produced.

## 2. What it shows

Replacing the gate card on the landing page when `blocked_reason` is
`event_ended`:

```
┌─ The crawl is over ──────────────────────────┐
│  🥇 The Mimics          Lv 9                 │
│  🥈 Kobold Union        Lv 8                 │
│  🥉 Late Starters       Lv 7                 │
├─ Your five days ─────────────────────────────┤
│  Rank 12 of 87        ·  The Mimics, 4th     │
│  38 challenges        ·  6 bosses felled     │
│  12 achievements      ·  rarest: First Blood │
│  Finished as "the Unbothered"                │
│                       [ Full scoreboard → ]  │
└──────────────────────────────────────────────┘
```

### 2.1 The podium

Top three parties, and top three players, as two short lists. Three, not ten —
the full board is one link away and this is the moment, not the record.

**Ties share a place** exactly as spec 059 §4.1 decided, so a shared third shows
as two thirds and there is no fourth.

### 2.2 Your five days

The personal half, and the more important one: 87 people did not win, and the
screen should still be worth their time.

| Line | Source |
| --- | --- |
| Your rank, and your party's | `/scoreboard/me` |
| Challenges solved | the board's own count |
| Bosses felled | the stars, coloured, from the player entry |
| Achievements earned, and the rarest | `/character/achievements` |
| The title you finished wearing | `equipped_title`, already on the sheet (060) |

**XP is allowed here and shown**: this is the player's own summary, in their own
chrome, which is the rule as 064 §7.1 states it.

## 3. Where it lives

**On the landing page**, in place of the ended gate — not a new route.

A player whose event has ended arrives at `/` and gets the ending. Giving it a
URL of its own would mean somebody has to navigate to their own conclusion, and
the landing page already owns "what state is the event in".

The rest of the landing page's playing cards (066 §2) do not render, because
`capabilities.play` is false. That is already how it behaves.

## 4. Backend

**None.** As §1 says.

The one thing worth stating: the gate is still `blocked_reason` from the server,
never a client clock. A browser an hour fast must not show anybody their ending
early, which is the same rule 066's countdown follows.

## 5. Testing

- The ending renders only for `event_ended`, and the playing cards do not.
- A browser clock past the end shows nothing while the server still says
  running — the gate is the server's.
- The podium shows three parties and three players, and a shared rank shows as
  a shared place.
- The personal summary reads correctly for somebody unranked, partyless,
  achievement-less and untitled — the day-five equivalent of day one, and the
  case most likely to be wrong.
- The full scoreboard is still reachable and still renders after the end.
- **No other gate changes.** Pending, disabled and not-started render exactly as
  they did.

## 6. What this does not do

- **Freeze or archive anything.** The board is live and stays live; nothing is
  snapshotted, because nothing needs to be.
- **Award anything.** No end-of-event achievement, no final loot. Spec 028's
  rule is that achievements fire from triggers, and inventing a ceremonial one
  here would be a scoring change dressed as a screen.
- **Email a summary.** Spec 055 owns mail and it stays about sign-in links.
- **Add an admin "close the event" action.** The event ends by its own clock;
  spec 053 owns the event window.

## 7. Open questions

1. **Should the podium name players at all, or only parties?** Parties are the
   scoring unit spec 005 built the event around, and a player podium quietly
   makes the individual board the real one. Recommend **both**, kept to three
   each — the player board is the one people look at, and pretending otherwise
   on the final screen would be odd.
2. **Should a player who joined on day four see "your five days"?** The heading
   is wrong for them and the numbers are small. Recommend **the same screen,
   with the heading taken from the event rather than the player** — "The crawl
   is over" is true for everybody, and a smaller summary is not an embarrassment
   worth special-casing.
