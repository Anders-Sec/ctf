# Spec 028 — Notifications & Achievements

Status: **draft** (2026-09-08) — awaiting sign-off
Phase: 2 (D&D Mechanics)
Depends on: 013 (the System AI persona), 015/018 (XP, levels, skills), 017/019
(zones and gates), 024 (the class roster)

Two things, in this order: a **notification system** that is the System AI's
channel to the player, and **achievements** as its first and largest producer.
The notification system is the substrate — class unlocks, zone unlocks and
level-ups all speak through it too.

## The notification system

A notification is one message from the System AI to one player. It has a kind, a
title, a body in the System AI's voice, an optional link, and a read flag.

- **Per-player, never broadcast.** Every notification names its recipient. An
  event-wide announcement is a different feature and is not in this spec.
- **Persistent backlog.** Nothing is fire-and-forget: a player who was offline
  when it fired sees it later, and a player who dismissed the popup can read it
  again. This is the DCC-style feed.
- **Read state per notification**, with mark-all-read. No expiry — the backlog
  is the record of the player's run.
- **The voice lives server-side**, in one place, as 016's class nudge already
  does. Copy is a deterministic template, never a model call: no latency, no
  token cost, no guardrail surface, and no path for a challenge answer to reach
  a prompt. It is the System AI's *voice*, not its *reasoning*.

### Delivery

A WebSocket at `/api/ws/notifications`, authenticated from the same cookie as
`/ws/scoreboard`, fed by Redis pub/sub — the pattern 007 already established and
proved.

The one difference from the scoreboard: that channel is a broadcast where every
listener wants the same payload, so one channel serves everyone. Notifications
are addressed, so the channel is **per recipient**
(`notifications:v1:user:<id>`). Fanning every notification to every connection
and filtering client-side would put one player's messages on another player's
wire, which is both a leak and a waste.

On connect the socket sends the unread backlog, so a reconnect is self-healing
in the same way the scoreboard is.

### Presentation

- A **toast** in the corner, auto-dismissing after a few seconds, not a modal.
  A modal that interrupts someone mid-challenge to say "you levelled up" is a
  punishment, not a reward.
- **At most three toasts at once**; anything beyond that collapses into "and N
  more" and is read from the backlog. A single solve can award several things at
  once — an achievement, a level, and the zone it opened.
- A **bell with an unread count** in the nav, opening the backlog.

## Achievements

An achievement is a named thing a player did, with a description and a trigger.

### Triggers read history, and fire forward only

**There is no backfill.** An achievement created after the event starts awards
nothing for work already done. That is a deliberate simplification: the roster
is seeded before the event, so the case never arises, and avoiding it removes a
bulk evaluation path, a silent-award distinction, and the toast flood that
seeding would otherwise cause.

A trigger is still a **predicate over the player's stored history**, evaluated
after the events that could plausibly change its answer. Reading history rather
than an event payload is what keeps a trigger writable at all: "three solves
inside five minutes" and "ten wrong flags on one challenge" are one query each,
where threading enough context through every call site to answer them live would
not be.

The history is already there: `Submission` logs every attempt right or wrong
with timestamps, `Solve` is timestamped, and `HintUnlock` records hint use.

**The constraint this imposes**: a trigger that depends on something not stored
cannot be built. If the list contains one of those, the fix is to store the
thing, and that is worth knowing before the list is seeded rather than after.

### Awarding

- An award is **once per player per achievement**, enforced by a unique
  constraint rather than by a check-then-insert that two concurrent solves could
  both pass.
- Awarding writes a notification and pops a toast. Every award is live now, so
  there is only one kind.
- Evaluation runs after the events that could plausibly change the answer —
  solve, hint unlock, class change, zone unlock — not on every request.

### Sample data has to award them

Without backfill, seeding achievements into a database whose solves already
exist awards nothing, and the local dev instance would show an empty list
forever. So the dungeon sample generator (spec 025) runs the evaluator as it
creates its solves. Otherwise the feature looks broken in the one environment it
is built in.

### The sheet

- **A full list, unearned ones blurred**, exactly as skills are. The total is
  therefore public, which is the point: it is something to aim at.
- **A top-five bar** of the player's *rarest earned* achievements, each with the
  percentage of players holding it.
- Rarity's denominator is **players with at least one solve**. Counting every
  registered account would make everything look rare in proportion to how many
  people signed up and never played, which is noise rather than signal.
- The percentage is computed periodically and cached, not per page load — with
  200+ players and a live event it is a scan, and it does not need to be exact
  to the second.

## The other producers

Given the same substrate, these become small calls rather than features:

- **Class unlocked** — the gap 024 explicitly left open.
- **Zone unlocked** — a wing opening is the most narratively satisfying moment
  the map has, and today it happens silently.
- **Level up**, and **ability milestones** at a score crossing 12/16/20.

Each is one line of System AI copy in the same server-side place.

## Edge cases

- **A deleted achievement** takes its awards and notifications with it.
- **An achievement edited after awards exist** keeps them; the criteria are not
  re-evaluated, because taking one back is worse than a slightly stale one.
- **A player with no solves** sees an all-blurred list and an empty top five.
- **Rarity when nobody has played** — no denominator, so the bar is empty rather
  than showing 100% for everything.
- **The socket is down** — the backlog is authoritative and the bell still shows
  the count on next load. Delivery is a nicety; the record is the database.
- **Sample data** should award achievements too, or the feature looks broken in
  the environment it is developed in.

## Testing

- A notification is delivered live to its recipient and to nobody else.
- The backlog survives a reconnect; unread count is correct.
- An achievement awards exactly once under concurrent triggers.
- An achievement created after a qualifying solve awards nothing for it.
- The sample data generator leaves players holding achievements.
- Unearned achievements are blurred in the API, not merely hidden by CSS.
- The top five are the player's rarest, with percentages against players who
  have solved something.
- Rarity is 0 players → empty, not a division by zero.

## Non-goals

- Admin-authored broadcast announcements.
- Team or party achievements — awards are per player.
- Email or push outside the app.
- Achievement icons or art; the Phase 3 pass owns that.

## Decisions

1. **No backfill.** Achievements fire forward only; the roster is seeded before
   the event, so nothing is owed for past work.

## Open question

**The achievement list itself.** The engine ships with a handful of obvious ones
(first solve, first zone cleared, a wrong-flag streak) so the feature is
testable, and your list drops in as seed data. Send it whenever — and if a
trigger on it cannot be answered from stored history, that is the one thing I
need to raise before seeding rather than after.
