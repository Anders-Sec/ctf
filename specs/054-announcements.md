# Spec 054 — Announcements

Status: **draft**
Phase: 3 (Polish & Operability)
Depends on: 049 (sidebar placement), 032 (the broadcast fan-out this uses)

Announcements become a page with a history, instead of a composer bolted to the
bottom of the dashboard that forgets everything it has said.

## 1. What exists, and what is missing

[`AnnouncementComposer.tsx`](../frontend/src/components/AnnouncementComposer.tsx)
is a good component. It confirms before sending, it states plainly that a message
cannot be recalled, and `POST /api/admin/announcements` fans out through the
spec 032 broadcast path and reports a recipient count.

What is missing is everything after the send:

- **No record of what was sent.** The composer shows "Sent to 184 players" and
  then clears itself. Over five days there is no way to answer "what have I
  already told people?" without asking a player to read their feed back to you.
- **No reach data.** 184 received it. How many read it? The notification rows
  carry a read state that nothing aggregates.
- **It is at the bottom of the dashboard**, under the challenge-health table and
  the sample-data panel — the least likely place to look for it and an easy thing
  to scroll past when you need it in a hurry.
- **No scheduling.** A five-day event has a "doors open at 9" message that wants
  writing the night before.

## 2. The page — `/admin/announcements`

The composer, moved and unchanged in behaviour, above a history table.

```
┌───────────────────────────────────────────────────────────┐
│ Announcements                                             │
│ ┌───────────────────────────────────────────────────────┐ │
│ │ Title  [                                            ] │ │
│ │ Message[                                            ] │ │
│ │                          Send now ▾  ( ) Schedule…    │ │
│ └───────────────────────────────────────────────────────┘ │
│                                                           │
│ HISTORY                                                   │
│ Wed 14:02  Lunch is in the atrium    184 sent · 141 read  │
│ Wed 09:00  Doors are open            179 sent · 176 read  │
│ Tue 16:30  Crypto zone is fixed      160 sent · 118 read  │
└───────────────────────────────────────────────────────────┘
```

**History** shows, per announcement: when, who sent it, title, body (expandable),
recipients, and **read count with a share**. Read count is the one genuinely new
piece of information, and it is what tells you whether the thing you announced
actually landed — a 30% read rate on "the Crypto zone is fixed" explains a lot of
support questions.

**No editing, no deleting.** The composer's existing copy is right: a message
people have already read cannot be taken back, and a correction is another
announcement. The history is a record of what happened, so it offers neither.

**Resend** is offered instead — prefills the composer with the previous title and
body, as a new announcement. That is the honest version of "say it again", and
it is what an admin actually wants when a message under-landed.

## 3. Scheduling

A send-at time, in the admin's local zone, stored UTC. A scheduled announcement
sits in the history as **pending**, and pending is the one state that *can* be
edited or cancelled, because nobody has read it.

Delivery is by the same mechanism that already fires the daily dispatch (spec
032) — this adds a due-announcements check to that existing periodic task rather
than introducing a second scheduler.

If the process is down at the due moment, the announcement fires late rather than
being skipped, with the history showing both the intended and actual times. A
"doors are open" message arriving at 09:03 is fine; one silently never arriving
is not.

## 4. Audience

Today's fan-out is every active player. Two narrowings are worth having, and
both are cheap because the recipient set is already computed server-side:

- **Everyone** (default, today's behaviour).
- **Staff only** — for a note to helpers that should not reach players.

Deliberately **not** offering per-zone or per-party targeting. It sounds useful
and it is a trap: an announcement that only some players receive produces
"nobody told me" conversations that cost more than the targeting saves, and the
notification feed has no way to explain why a player did not get something.

## 5. Data model

A new `announcement` table, rather than reverse-engineering the history out of
`notification` rows:

| Column | Notes |
| --- | --- |
| `id`, `created_at` | |
| `title`, `body` | As sent. |
| `audience` | `everyone` / `staff`. |
| `created_by_user_id` | |
| `scheduled_for` | Null for send-now. |
| `sent_at` | Null while pending. |
| `recipient_count` | Stamped at fan-out. |
| `cancelled_at` | Pending only. |

Notification rows gain `announcement_id` (nullable) so the read count is a count
over them rather than a second number to keep in sync. Read state lives on the
notification, which is where it already is; the announcement never stores a read
count of its own.

## 6. API

- `GET /api/admin/announcements` — history with recipient and read counts,
  newest first, paginated.
- `POST /api/admin/announcements` — **existing endpoint**, gains optional
  `audience` and `scheduled_for`, and now writes an `announcement` row. Its
  current contract (title, body → recipient count) is unchanged for a send-now
  call, so the existing composer keeps working during the migration.
- `PATCH /api/admin/announcements/{id}` — pending only: title, body,
  `scheduled_for`.
- `POST /api/admin/announcements/{id}/cancel` — pending only.

All `Admin` — this already requires `administer`, and speaking to 200 people is
not a read-only action.

## 7. Testing

- A send-now announcement writes an `announcement` row, fans out, and stamps
  `sent_at` and `recipient_count`.
- Read count reflects notifications marked read, and is not stored on the
  announcement.
- A scheduled announcement does not fan out before its time, and does fan out on
  the next periodic pass after it.
- A scheduled announcement whose time passed while the process was down fires on
  the next pass, and the history shows intended and actual times.
- Editing and cancelling work on pending and are refused on sent, with a test for
  each.
- `audience: staff` reaches staff and no players.
- Resend creates a new announcement rather than mutating the old one.
- The dashboard no longer renders the composer, and nothing else regressed with
  its removal.
- A non-admin staff account cannot send.

## 8. Open questions

1. **Should announcements also be visible somewhere player-facing beyond the
   notification feed?** A player who joins on day three has no way to read what
   was announced on day one. Recommend a simple read-only "announcements" list in
   the player notification centre — but that is a player-facing surface, so it
   belongs to the QoL workstream rather than here. Flagging so it is not forgotten.
2. **Does `staff` audience have a real use, or is it speculative?** It is one enum
   value and one branch in the recipient query, so it is nearly free, but if there
   is only ever one staff member it is dead code. Recommend building it only if a
   second staff account is expected.
