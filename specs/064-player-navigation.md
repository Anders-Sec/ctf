# Spec 064 — The Player Navigation Bar

Status: **approved** (2026-09-18)
Phase: 3 (Polish & Operability) — quality of life, player-facing
Depends on: 048 (theme toggle), 049 (the admin shell this is the twin of)
First of three: **064** the bar, 065 the inbox, 066 the landing page.

`AppLayout` has carried a note since spec 049:

> *The player nav is deliberately untouched — its own pass belongs to the
> quality-of-life workstream, and rebuilding it twice would be the only thing
> worse than leaving it.*

This is that pass.

## 1. What is wrong with it

Nine things sit on one row, five of them crowded into the right-hand corner:

> `CTF · Challenges · Scoreboard · Character · Party` … `✉ · ☼ · Admin view ·
> Settings · avatar · Sign out`

- **Sign out is a permanent fixture for a once-an-event action.** It sits beside
  Settings, which is nearly as rare.
- **The notification panel opens on the right**, over the assistant panel and
  the rest of the busy corner.
- **The bell and the theme toggle are bordered boxes**, which makes two
  incidental controls look like primary ones.
- **There is no responsive treatment at all.** Four links plus five controls
  wrap badly the moment the window narrows, and there is no menu behind them.

## 2. The bar

```
┌───────────────────────────────────────────────────────────────────────┐
│  CTF   ✉³   Challenges  Scoreboard  Character  Party      ☼   Lv 7 ◑▾ │
└───────────────────────────────────────────────────────────────────────┘
```

Left to right: the brand, **the inbox**, the four content links. On the right:
the theme toggle, and the profile.

**The inbox moves to the left**, immediately after the brand, so its panel opens
leftward into empty space instead of over the assistant. Its unread count rides
next to it as a small badge.

**The bell and the theme toggle lose their boxes** and become plain icons. They
are chrome, not actions.

### 2.1 The profile menu

The avatar becomes a menu. Behind it:

| | |
| --- | --- |
| A summary | §2.2 |
| Character sheet | The full version of that summary |
| Settings | Off the bar |
| Admin view | For an admin, also off the bar |
| Sign out | Where a once-an-event action belongs |

Closes on Escape, on a click outside, and on choosing anything. All three,
because a menu that only closes on its own button is a menu people leave open.

### 2.2 The summary in the menu

Level, rank, party, and progress toward the next level — enough to answer "how
am I doing" without loading the character sheet.

`/scoreboard/me` already returns rank, level, party rank and the two counts, and
**nothing currently renders it** — spec 059 kept it and trimmed its XP. It is
exactly this panel's payload.

### 2.3 Narrow screens

Below `md` the four content links collapse into a menu button; the inbox, theme
and profile stay on the bar, because those are the things you reach for without
thinking. This is a bar-only fix and not the queued pass across every page.

## 3. The level chip, and a rule it bumps into

The brief asks for "a little XP/level indicator next to the profile".

**Spec 059 §2 said XP "belongs on their character sheet and nowhere else", and
060 §3 called the sheet "the one screen where 059's rule permits XP".** A chip in
the nav is neither, so it was raised rather than assumed.

The rule's *purpose* is clear from 059's own wording: publishing XP "turns a
scoreboard into a comparison of numbers rather than of standing". That is about
**other people's** XP, on a board. A player's own number, in their own chrome,
is not the thing it was written to stop.

**Decided (2026-09-18): XP is only ever visible to yourself.** The rule is about
*whose* XP and *where* — never another player's, never on a board — not about
one screen. A bar in your own nav was the intended feature all along.

059 §2 and 060 §3 are amended to say so, rather than leaving three specs
disagreeing. The chip shows `Lv 7` with a progress bar on the bar itself, and the
menu carries the figures.

## 4. Backend

One field, on `/auth/me`: **`level`**.

`/scoreboard/me` supplies rank and party rank for the menu, and the character
sheet supplies the XP figures once it is opened — but the chip is on screen on
every page, and neither of those should be fetched on every page to render two
characters. `level` is one scalar sum and a curve lookup.

Nothing else. `/scoreboard/me` and `/character/me` already exist and are
already shaped for this.

## 5. Testing

- The bar renders the four content links, the inbox, the theme toggle and the
  profile — and **no Sign out button**.
- The profile menu holds settings, sign out and the character sheet; Admin view
  appears for an admin and not for a player.
- The menu closes on Escape, on an outside click, and on selection.
- Signing out from the menu clears the query cache and lands on `/login`.
- The summary renders rank, level and party from `/scoreboard/me`, and says so
  gracefully when unranked.
- Below `md`, the content links are behind a menu button and the inbox, theme
  and profile are not.
- Every existing `AppLayout` test either passes or changes for a reason named in
  the commit.

## 6. What this does not do

- **Touch the inbox's contents.** The bell moves; what is behind it is spec 065.
- **Touch the admin shell.** Spec 049's sidebar is unchanged, and the way into
  admin view moves into the profile menu without changing the way out.
- **Touch the assistant panel.** It keeps its corner — which is the point of
  moving the inbox away from it.
- **A mobile pass.** §2.3 fixes the bar because we are already inside it.

## 7. Decisions

Signed off 2026-09-18.

1. **A player's own XP belongs in their own chrome.** See §3 — 059 and 060 are
   amended to state the rule as it was always meant: never anybody else's, never
   on a board.
2. **The brand reads the event's name**, which `/auth/me` already carries,
   falling back to "CTF" when it is unset.

## 8. As built

Built 2026-09-18. Two notes.

### Four fields on `/auth/me`, not one

§4 said `level`. A progress bar needs both halves of the fraction and the menu
shows the figures, so it carries `level`, `total_xp`, `xp_into_level` and
`xp_to_next`. Still one scalar sum and a curve lookup — the cost §4 was actually
weighing — and the nav now needs no second request to render.

### An existing assertion caught a regression

Rebuilding the bar dropped the `!showingAdmin` guard on the way into admin view,
so the profile offered it while already inside — the confusing half of a toggle.
Spec 049 put that guard there and its test still held it. Restored.
