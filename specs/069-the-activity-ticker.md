# Spec 069 — The Activity Ticker

Status: **draft**
Phase: 3 (Polish & Operability) — quality of life, player-facing
Depends on: 005 (the board), 031/032 (boss kills and their broadcast),
059 (the scoreboard this sits on)
Third of four: 067 the party, 068 the ending, **069** the ticker, 070 settings.

An event where 200 people are playing at once currently looks, from any one
screen, like an event where nobody is. This puts the room back on the page.

**It is the one item in this batch with a real cost**, and §3 states it plainly
rather than burying it.

## 1. What exists already

Spec 032 broadcasts the **first** kill of each boss to everybody — *"twenty
players beating the same boss would be twenty broadcasts nobody wants, and the
whole value is in being first."* That is the only ambient signal there is, it
arrives as a notification, and since spec 065 it does not even toast.

Everything else — hundreds of solves a day — is invisible unless you are the one
doing it.

## 2. The ticker

On the scoreboard, above the boards:

```
┌──────────────────────────────────────────────┐
│  ⚡ Rin cleared Port of Call        just now  │
│     Vek felled The Gatekeeper ☠      2m ago  │
│     Grix cleared Frequency Analysis  4m ago  │
└──────────────────────────────────────────────┘
```

- **Ten rows, newest first.** A ticker, not a log: the log is the scoreboard.
- **Boss kills are marked** with their tier colour, because that is the line
  worth reading twice.
- **Live over the socket the scoreboard already holds open** — spec 005 pushes
  the whole board on every change, and this rides the same connection rather
  than opening a second one or polling.
- **Quiet when it is quiet.** An empty ticker says the dungeon is quiet, not
  nothing at all, so the space does not collapse.

## 3. The cost, stated plainly

**This tells everybody which challenges are falling.** A player watching it
learns where the solvable work is without doing any of the looking, which is
information a competitor can use — and at a work event with a scoreboard, some
people will use it.

Three ways to spend that, and the spec has to pick one:

| | What it leaks |
| --- | --- |
| **Name the challenge** | Everything. "Port of Call is solvable" is a tip. |
| **Name the zone only** | *"Rin cleared something in Networking"* — the shape of where work is happening, not the work. |
| **Name nobody's target** | *"Rin scored"* — energy with no information at all. |

Recommended: **name the zone, not the challenge** (§7.1). It keeps the human
half — who is moving, how fast the room is going — and drops the part that is
actually a hint. Boss kills are the exception and are named in full, because
spec 032 already broadcasts those to everybody by name and being first is the
entire point of them.

## 4. API

`GET /activity?limit=20` — recent public events, newest first.

```
{ items: [{ kind: "solve"|"boss", display_name, zone_name,
            challenge_title, tier, at }] }
```

- `challenge_title` and `tier` are **null unless `kind` is `boss`**, which is
  §3's decision enforced on the server rather than trusted to the client. A
  title the client is asked to hide is a title in the payload.
- Staff accounts are excluded, exactly as they are from the board: *"staff
  accounts exist to run the event, not to win it."*
- Gated on `view_scoreboard`, so it opens and closes with the board.

Live delivery reuses the scoreboard channel: the payload gains an `activity`
key alongside `players` and `teams`. One socket, one recompute, no new
infrastructure — and the debounce that already protects the board protects this.

## 5. Backend

- The query: recent `Solve` rows joined to challenge and category, newest first,
  excluding staff. One query, indexed on `submitted_at`.
- Added to `scoreboard_cache.serialise`, so it is computed once per recompute
  and shared by every client rather than per request.
- `public_view` leaves it alone — there is no XP in it.

No model change and no migration.

## 6. Testing

- A solve appears; a staff solve does not.
- **A non-boss row carries no challenge title**, asserted by scanning the
  serialised payload for the title — the §3 test.
- A boss kill carries its title and tier.
- The ticker is capped and ordered newest first.
- It rides the scoreboard socket: no second connection is opened.
- It is refused without `view_scoreboard`, and opens when the board does.
- An empty ticker renders its own line rather than collapsing.

## 7. Open questions

1. **Zone, challenge, or neither?** §3. Recommend **zone**, with boss kills
   named in full. It is the only option that keeps the energy without handing
   out a solvable-work list.
2. **Should a player be able to hide it?** It is decoration on somebody else's
   competition. Recommend **not a setting** — spec 070 is adding preferences and
   this would be the first one that is really "I find this distracting", which
   is what collapsing the ticker is for. Make it collapsible, remembered per
   browser, and add no server-side preference.
