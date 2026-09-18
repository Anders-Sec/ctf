# Spec 070 — Settings

Status: **approved** (2026-09-18)
Phase: 3 (Polish & Operability) — quality of life, player-facing
Depends on: 048 (theme and contrast), 065 (the kinds), 066 (the tour)
Fourth of four: 067 the party, 068 the ending, 069 the ticker, **070** settings.

The page is 140 lines of theme and contrast. It is where three things have been
deferred to, and one of them turns out to have a trap in it.

## 1. A note on the first item

Spec 065 §8 said, of notification preferences:

> *Choosing which kinds reach you is a settings feature for an event longer than
> five days.*

That was my recommendation and it was overruled, which is the right way round —
it is a product call, not a technical one. It is recorded here so the reversal
is visible rather than looking like the argument was never made.

The design below keeps it cheap enough that the original objection mostly stops
applying: **muting is a list of kinds on the user**, not a preference system.

## 2. What the page holds

| Section | |
| --- | --- |
| **Appearance** | Light/dark, high contrast, held secret themes. Unchanged (048, 058). |
| **Your name** | §3 — and the trap. |
| **Notifications** | Mute by kind. §4. |
| **Getting started** | Re-run the tour (066 §3.2), which is in the profile menu and belongs here too. |

## 3. Your name, and why it is not simply editable

`PATCH /auth/me` accepts `display_name` today and `FirstRunPage` already uses it.
Putting the same field on the settings page looks like five lines of work.

**It is not, for an SSO account.** `identity.py` does this on *every* sign-in:

```python
# Keep the profile fresh: a changed corporate name or photo catches up on
# the next sign-in.
user.display_name = profile.display_name
```

So an Entra user who renames themselves is silently reverted the next time they
sign in — and the platform will have told them it saved. That is worse than not
offering it.

Three ways out:

| | |
| --- | --- |
| **Guests only** | Offer the field to magic-link accounts; tell SSO users their name comes from the directory. Honest, no schema change, and the smaller feature. |
| **A "chosen name" flag** | A boolean that stops the sync once somebody has set their own. One column, and the directory stops catching up on a genuine rename. |
| **A separate nickname** | `display_name` stays the directory's; a nullable `nickname` overrides it for display. Cleanest, most code — every render site has to pick. |

Recommended: **guests only**, and say so plainly to everybody else (§6.1). It is
the one that ships this week, and for a company event the directory name is
arguably the right answer for the people who have one.

## 4. Muting a notification kind

A muted kind **does not toast and does not count toward the badge.** It still
arrives and still sits in the inbox: this is a volume control, not a filter, and
a notification the server decided to send is part of the record.

That distinction is what keeps it cheap. Nothing about delivery changes; spec
065's tabs and filters already make a muted kind findable.

- `user.muted_notification_kinds`, a string array. One column, one migration.
- The five **Yours** kinds and the four **Event** kinds are all mutable. An
  announcement is an admin talking to the room, and somebody who mutes it has
  made a choice they are allowed to make.
- `unread_count` excludes muted kinds; `backlog` does not.

The settings UI is nine checkboxes grouped by the two tabs — the same grouping
`KIND_META` already carries, so the page is built from it rather than from a
second list that could drift.

## 5. Backend

- `user.muted_notification_kinds`: `ARRAY(String)`, default empty. One migration.
- `GET/PATCH /auth/me` carries it, alongside the theme fields it already carries.
- `notifications.unread_count` filters it out.
- Display name: **no change**, under §3's recommendation. The endpoint exists;
  the page decides who is offered it.

## 6. Testing

- Muting a kind drops it out of the unread count but leaves it in the backlog.
- Unmuting restores the count without the notification having been re-sent.
- A muted kind does not toast.
- The checkbox list is generated from `KIND_META`, so a tenth kind appears
  without touching this page — asserted, not assumed.
- **An SSO account is not offered a name field**, and is told why.
- A guest can rename, and the name reaches the scoreboard.
- Appearance behaves exactly as it does today: every existing settings test
  passes untouched.

## 7. What this does not do

- **Per-challenge or per-party notification rules.** Nine checkboxes is the
  whole feature.
- **Turn off the inbox.** A muted kind is quieter, never absent — the inbox is
  the record, which is spec 028's whole argument for having one.
- **Change how the theme works.** 048 and 058 own appearance and it is untouched.
- **Add account deletion or export.** Not a five-day-event feature, and spec 056
  owns the admin-side export.

## 8. Decisions

Signed off 2026-09-18, both as recommended.

1. **Guests only.** It ships now and tells the truth to everybody else: an SSO
   account's name comes from the directory and would be reverted on the next
   sign-in.
2. **Muting an announcement is allowed.** A mute the platform refuses to honour
   is a worse lie than a message somebody missed, and the inbox still holds
   it.

## 9. As built

Built 2026-09-18. Two notes.

### Clearing marks read; muting does not

Worth stating together, because they look alike and are not. **Clearing** a
notification marks it read, because the row becomes unreachable and a badge
counting unreachable rows is a badge that lies (065 §4). **Muting** a kind does
not touch `read_at` at all — the rows stay unread and stay in the inbox, and the
count simply stops including them.

The difference is that clearing is an action on a row and muting is a standing
preference. Unmuting restores the count exactly, with nothing re-sent, and a test
pins that.

### `can_rename` is on the session, not inferred by the client

The client could have checked `user.source === "guest"` itself. It does not,
because the reason the field exists is a server-side behaviour — `identity.py`
rewriting `display_name` on every sign-in — and the day somebody adds a third
account source, the rule should change in one place rather than in whichever
components happened to guess.
