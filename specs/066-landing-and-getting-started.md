# Spec 066 — The Landing Page and Getting Started

Status: **approved** (2026-09-18)
Phase: 3 (Polish & Operability) — quality of life, player-facing
Depends on: 017 (capabilities and gates), 059 (`/scoreboard/me`), 062 (board
ordering), 064 (the nav this points at)
Third of three: 064 the bar, 065 the inbox, **066** the landing page.

The first screen of the event, currently a gate card and a party card. It should
answer the two questions somebody actually arrives with — *how am I doing* and
*what do I do next* — and, for the first hour, teach the furniture.

## 1. What it is today

A capability-driven gate (pending approval, disabled, not started, ended, open)
and a "you march with X" card. The gate states are **load-bearing and stay**:
which one shows is decided by `capabilities.blocked_reason` from the server,
*"never by a client-side clock — 200 browsers with 200 slightly wrong clocks
would otherwise disagree about whether the dungeon is open."*

That sentence is also the design constraint for the countdown below.

## 2. The page

```
┌─────────────────────────────────────────────────────────┐
│  Vault of the Forgotten Flag                            │
│  2 days, 4 hours left                                   │
├──────────────────────────┬──────────────────────────────┤
│ Where you left off       │ Your standing                │
│  Web Attacks   8/12      │  Rank      12 of 87          │
│  Next: Auth Bypass  200  │  Level      7                │
│                          │  The Mimics   4 of 21        │
├──────────────────────────┴──────────────────────────────┤
│ First steps                                    2 of 5   │
│  ✓ Sign in    ✓ Join a party                            │
│  ○ Solve your first challenge   → start in Networking   │
│  ○ Discover a skill    ○ Choose a class  (level 5)      │
└─────────────────────────────────────────────────────────┘
```

### 2.1 The countdown

To `event.ends_at`, and **offset against the server's clock**, not the browser's.
`EventSummary` already carries `server_time` with the comment *"the clock that
actually decides; the client's own is decorative"* — so the offset is taken once
on load and the countdown ticks from there.

`AdminLayout` already has an `EventClock` doing exactly this. It moves to
`components/` and both use it; a second countdown would be a second thing to get
wrong.

Before the event, it counts to the start instead. After, it says so — and the
gate card already covers that case, so the countdown simply stops.

### 2.2 Where you left off

The zone of your most recent solve, its progress, and the next unsolved
challenge in it.

Both facts are already on the client: `/challenges` carries every row with
`solved` and, since spec 062, in the order the author intended — so "the next
one" is the first unsolved row of that zone, which is the same thing the board
would show. `/me/score` carries the solves with their timestamps.

No new endpoint, and deliberately no new notion of "current zone" on the server:
a stored pointer would be a second source of truth that could disagree with the
board.

If nothing is solved yet, this becomes the first step's pointer instead — the
first zone with an unlocked challenge in it.

### 2.3 Your standing

Rank, level and party rank, from `/scoreboard/me` — the endpoint spec 059 kept,
trimmed of XP, and which nothing renders yet. The nav's profile menu (064 §2.2)
shows the same thing; this is the fuller version with the counts beside it.

**No XP**, per 059. Level is the public shape of the same fact.

The party card as it stands is replaced by the party's rank here. Somebody with
no party gets a link to find one, which is what the card was for.

## 3. Getting started

Two pieces, doing genuinely different jobs.

### 3.1 First steps — a checklist

Persistent on this page until complete, then gone for good.

| Step | Done when |
| --- | --- |
| Sign in | Always, on arrival — one tick for free, which is how a checklist earns a first glance |
| Join a party | `me.team` is set |
| Solve your first challenge | Any solve |
| Discover a skill | Any skill at level 1 or better |
| Choose a class | A class is set, and it is only *offered* from the unlock level |

Every incomplete step carries **a link to the place it happens**, and the solve
step names a specific zone rather than the board in general. "Go and solve
something" is not guidance.

**Derived, never stored.** Every one of these is already answerable from data
the client holds, and a `completed_steps` column would be a second source of
truth that could disagree with reality — a player who left a party would still
show the step ticked.

The class step is **shown greyed with its unlock level** rather than hidden, so
the ladder is visible from the first hour. That is the same argument 066's
sibling specs make for sealed zones: knowing there is more is the point.

### 3.2 The tour — once

On first sign-in, numbered callouts on the nav: the inbox, the challenge board,
your character, the assistant. Four, not ten.

- **Skippable at every step**, and skipping is remembered.
- **Re-openable from the profile menu** (064 §2.1), so dismissing it is not a
  one-way door.
- **Remembered per browser**, in `localStorage`. Not on the server: it is a
  convenience, and the cost of a second showing on a second device is that
  somebody presses Skip. A column and a migration to save one press is a bad
  trade.

The tour explains furniture once. The checklist keeps pointing at the next
useful thing all week. That is why the brief wanted both, and why neither
replaces the other.

## 4. Backend

**None.** Every number on this page comes from an endpoint that already exists:
`/auth/me`, `/scoreboard/me`, `/challenges`, `/me/score`, `/character/me`.

The only server-side thing this spec touches is the promise it inherits: the
gates stay capability-driven, and the countdown is offset against `server_time`
rather than trusted to the browser.

## 5. Testing

- Each `blocked_reason` still renders its gate, unchanged.
- The countdown uses the server offset: a browser clock an hour fast shows the
  same remaining time as one that is correct.
- Before the start it counts to the start; after the end it stops rather than
  counting negatives.
- "Where you left off" names the zone of the most recent solve and the first
  unsolved challenge in it, in board order.
- With no solves, it points at the first zone holding something unlocked.
- Standing renders rank, level and party rank, and reads gracefully when
  unranked or partyless — and carries **no XP**.
- The checklist ticks each step from live data: joining a party ticks it,
  leaving one unticks it.
- The class step is visible and greyed below the unlock level.
- The checklist disappears entirely once all five are done.
- The tour shows once, remembers a skip, and can be reopened from the profile
  menu.

## 6. What this does not do

- **Change the gates.** They are correct and server-driven.
- **Store progress.** §3.1, deliberately.
- **Add a dashboard.** Two cards and a checklist; a third column of statistics
  is the character sheet's job and it exists.
- **Show the latest announcement here.** It was considered and left out: the
  inbox (065) is where event news lives, and duplicating the newest one on the
  landing page gives it two homes and two read states.

## 7. Decisions

Signed off 2026-09-18, both as recommended.

1. **The checklist does not come back.** Once all five are done it is gone for
   good, remembered per browser. A checklist that reappears because somebody
   left a party reads as an accusation.
2. **Four tour steps.** The party is left to the checklist, which already links
   there and does it better.
