# Spec 032 — Broadcast Notifications

Status: **done** (2026-09-14) — 1030 backend tests, 231 frontend tests
Phase: 2 (D&D Mechanics)
Depends on: 028 (the notification system), 031 (bosses — the motivating case)

028 built notifications as strictly per-player and put broadcast explicitly out
of scope. Bosses are the reason to revisit it: the best part of a boss kill is
that everybody hears about it.

Three producers, one mechanism: **a boss first kill**, **an admin
announcement**, and **a daily dispatch on the state of the dungeon**.

## Broadcast is fan-out, not a new kind of row

A broadcast writes one notification per recipient rather than a single shared
row everybody reads.

The shared-row version looks tidier and is worse. It needs a second table to
track who has read what, a second read path in the client, and a notification
that belongs to nobody — which every query in 028 currently assumes cannot
happen. Fan-out reuses the backlog, the unread count, the read state, the socket
and the toast exactly as they are.

The cost is rows: 200 players × perhaps 50 broadcasts across the event is around
ten thousand, which is nothing. It is written as one bulk insert, then published
per channel.

**028's guarantee is unchanged**: every notification still names exactly one
recipient, and nobody can read anybody else's.

## The three producers

### Boss first kill

The first person to beat each boss is announced to everyone. Subsequent kills
are not — the whole value is in being first, and twenty players beating the same
boss would be twenty broadcasts nobody wants.

"First" is decided the same way `first_through` already decides it: the earliest
solve of that challenge. The broadcast fires from the same evaluation that awards
the boss achievement, and is guarded so a race cannot send it twice.

The player is named. That is the point.

### Admin announcements

A composer in the admin console: title, body, optional link, send. It goes to
every active player in the System AI's voice.

- **Admin only**, and audited like every other admin write.
- **Confirmed before sending.** It reaches 200 people and cannot be recalled, so
  it gets a confirmation step rather than a single click.
- **Not recallable.** Deleting a notification somebody has already read would be
  a lie about what happened; a correction is another announcement.

### The daily dispatch

One message a day on the state of the dungeon — the same text for everyone.
Something like: *"Day two. 340 challenges solved, four bosses down, the Prompt
Injection still standing."*

Facts drawn from what already exists: solves in the last day, zones opened,
bosses killed, the board's shape. The prose is a deterministic template in the
System AI's voice, as every other line is.

## Sending exactly once, across two pods

The deployment runs **two replicas**. A naive daily timer in each pod sends the
dispatch twice, and a restart near the send time could send it twice more.

The database arbitrates, exactly as it does for achievement awards: a
`broadcast_log` row keyed `(kind, key)` with a unique constraint — for the daily
dispatch, the key is the date. Whichever pod inserts first sends; the other's
insert fails and it does nothing. A restart mid-window finds the row already
there.

This is the same pattern as `uq_achievement_award_once`, and it is used for the
same reason: a constraint is the only arbiter that survives concurrency and
restarts without coordination.

An admin announcement uses a fresh key every time, since sending two different
announcements is legitimate.

## Separating notifications from achievements

028's structure is already right — `notifications.py` is its own service and
achievements merely call it. What this spec adds is a second caller and a
`broadcast()` alongside `notify()`, which makes the separation obvious rather
than incidental.

No change to the socket, the backlog, the bell or the toast.

## Edge cases

- **A player who joins mid-event** does not receive broadcasts sent before they
  arrived. Fan-out happens at send time against the players who exist then.
- **Inactive, pending or disabled accounts** are skipped; a broadcast goes to
  players who could act on it.
- **Redis down at send time** loses the live toast, not the message: rows are
  written first, and the backlog is authoritative, exactly as in 028.
- **A boss first kill that races** is settled by the broadcast log's unique
  constraint, so only one announcement goes out.
- **The daily dispatch before the event opens** is skipped rather than sent with
  zeros in it.
- **An announcement sent twice by a double-click** is prevented by the
  confirmation step and the log key, not by trusting the client.

## Testing

- A broadcast reaches every active player and no inactive one.
- Rows are per player; nobody can read anybody else's.
- A second send with the same key writes nothing and sends nothing.
- Two concurrent sends of the same key produce exactly one set of rows.
- A boss first kill broadcasts once; the second kill of that boss does not.
- An admin announcement is audited; a player cannot send one.
- The daily dispatch is skipped before the event starts.
- A Redis failure still writes the backlog.

## Non-goals

- Targeting a broadcast at a subset — one zone, one party, one tier of player.
  Everybody or one person; the middle is a segmentation feature nobody asked for.
- Recalling or editing a sent broadcast.
- Email or push outside the app.
- Per-player daily summaries. Considered and deferred: the shared dispatch ships
  first, and the personalised version is a separate piece of work.
