# Spec 065 — The Inbox

Status: **approved** (2026-09-18)
Phase: 3 (Polish & Operability) — quality of life, player-facing
Depends on: 028 (notifications), 032 (boss broadcasts), 048 (colour rules),
064 (where the bell now lives)
Second of three: 064 the bar, **065** the inbox, 066 the landing page.

The brief's own framing, and the right one:

> *I don't want it to become a meaningless feed of chat no one reads.*

So this is less "add filters" than "decide what deserves to interrupt somebody",
and give the rest a place to be found rather than scrolled past.

## 1. What is wrong with it

- **One undifferentiated stream.** Your level-up and somebody else's boss kill
  are the same kind of row, read for completely different reasons.
- **Nine glyphs that look alike** — `★ ◈ ⌸ ▲ ◆ ☠ ❖ ▤ ▸` — all rendered in the
  same accent colour.
- **Nothing can be removed.** `GET /notifications`, mark-one-read and
  mark-all-read is the whole API. A backlog only grows.
- **Toasts are 7 seconds, bottom-right, and clickable.** Bottom-right is where
  the assistant panel is, and `pointer-events-auto` means a toast *blocks
  clicks* there until it fades.
- **Everything toasts.** At 200 players, boss kills and daily dispatches are the
  loudest things on the platform and the least about you.
- **The client's type is missing three kinds.** `NotificationKind` lists six;
  the backend sends nine. `boss_kill`, `announcement` and `dispatch` are absent,
  so a filter built from that union would silently omit announcements.

## 2. Two tabs, because they are two different things

| Tab | Kinds | Why |
| --- | --- | --- |
| **Yours** | `achievement`, `level_up`, `class_unlocked`, `zone_unlocked`, `ability_milestone` | Things that happened to you. A record of your own event. |
| **Event** | `boss_kill`, `announcement`, `dispatch`, `system` | Things that happened. News. |

Each tab carries its own unread count, and the bell's badge is the sum.

Splitting by **audience** rather than only filtering by kind is what answers the
brief. A player checking "did I level" and a player checking "what did I miss"
are doing different jobs, and one list makes both worse.

Inside a tab, a **kind filter** narrows further — built from the backend's nine,
not the client's stale six.

## 3. Colour, with the kind named

Each kind gets a colour *and a short label* — `Level up`, `Boss kill`,
`Announcement`. Spec 048's standing rule is that colour is never the only
carrier, and nine near-identical glyphs is the case that rule exists for.

No new tokens: the existing role palette covers it (`accent` for your own
progress, `info` for news, `warning` for anything that wants attention,
`success` for an achievement).

## 4. Clearing

**Clear is a soft dismiss**, not a delete: a `dismissed_at` stamp on the row.

- Recoverable. Somebody who clears the announcement with the lunch time in it
  has not destroyed it, and an organiser can see it still exists.
- **Clearing an unread notification marks it read.** Otherwise the badge counts
  things the player can no longer reach, and a badge that lies is worse than no
  badge.
- Per row, and "clear all" scoped to the **visible tab and filter** — clearing
  "Event" must not take your achievements with it.

### API

| | |
| --- | --- |
| `POST /notifications/{id}/dismiss` | One row |
| `POST /notifications/dismiss` | Every row matching an optional `kinds` list |

`GET /notifications` excludes dismissed rows, and `unread_count` already excludes
read ones. The backlog stays capped at 50 newest-first, which is now a cap on
*undismissed* rows and so means something.

## 5. Toasts

**Personal events and announcements toast. Boss kills and dispatches do not** —
they land in the inbox and bump the badge.

That is the single biggest lever against the brief's worry. A boss broadcast is
interesting once and irrelevant the forty-first time; an admin saying "the
network is back" is worth interrupting for.

And the mechanics:

- **Top-left, under the inbox** (064 §2), not bottom-right over the assistant.
- **Four seconds**, not seven.
- **`pointer-events-none`, and no dismiss button.** The brief says *"I'm always
  clicking out of them"* — so make them impossible to click. Nothing to dismiss,
  nothing blocked underneath, and the inbox is the record either way.
- **At most three at once.** A burst of solves should not become a column.
- `aria-live="polite"` stays: a reader is told once, and the inbox holds the rest.

## 6. Backend

- `Notification.dismissed_at`, nullable — one migration.
- The two dismiss endpoints in §4.
- `backlog()` and `unread_count()` filter dismissed rows.

Notification **kinds are unchanged**. The split in §2 is a grouping of the nine
that exist, made on the client, so adding a kind later does not need a migration
— it needs a line in one map, and a test asserts every kind is in exactly one
tab so a new one cannot quietly go missing.

## 7. Testing

- A dismissed notification is absent from the feed and from the unread count.
- Dismissing an unread one drops the count by one.
- "Clear all" with a kind filter clears only those kinds.
- Every `NotificationKind` the backend defines appears in exactly one tab — the
  test that stops a tenth kind vanishing.
- The client's kind union matches the backend's, asserted rather than assumed.
- Frontend: each tab counts its own unread; the badge is the sum.
- Frontend: a boss kill does not toast; an announcement does.
- Frontend: a toast disappears on its own, has no button, and does not intercept
  a click aimed underneath it.
- Frontend: at most three toasts render at once.
- Frontend: every row shows its kind as text, not only as a colour.

## 8. What this does not do

- **Change what produces a notification.** Every trigger, broadcast and dispatch
  is untouched; this is delivery and presentation.
- **Add notification preferences.** Choosing which kinds reach you is a settings
  feature for an event longer than five days.
- **Add email.** Spec 055 owns that, and it stays about sign-in links.
- **Hard delete.** §4, deliberately.

## 9. Decisions

Signed off 2026-09-18, both as recommended.

1. **`system` sits in Event.** Anything not clearly *about your progress*
   belongs with the news, and it keeps "Yours" meaning exactly one thing.
2. **Clearing is offered, per tab, and "Yours" asks first.** Clearing "Event" is
   housekeeping; clearing "Yours" throws away your own record of the event, so
   that one confirms.

## 10. As built

Built 2026-09-18. Two notes.

### Clearing marks read with a `coalesce`, not a blind write

§4 says clearing marks read, because a badge that counts rows the player can no
longer open is worse than no badge. The obvious implementation — set both stamps
— would also *rewrite* `read_at` on a row that had been read an hour earlier,
quietly destroying when it was actually read.

`read_at=coalesce(read_at, now)` sets it only where it was null. A test pins
that an already-read row keeps its original stamp.

### The kind union is now derived, not duplicated

§1 called out three missing kinds. Rather than adding them to a hand-written
union that would drift again, `NOTIFICATION_KINDS` is a const array and the type
is derived from it — so `KIND_META` cannot compile without covering every kind,
and a test asserts the map's keys and the array match exactly.

That is what makes §6's promise real: a tenth kind needs a line in one map, and
if somebody forgets, the build stops rather than the kind vanishing from both
tabs.
