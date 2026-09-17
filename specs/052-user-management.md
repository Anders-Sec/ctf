# Spec 052 — User Management

Status: **approved** (2026-09-17)
Phase: 3 (Polish & Operability)
Depends on: 049 (sidebar placement), 051 (the audit log this links into)
Supersedes: the approvals-only page from spec 002

A real roster: find a person, see their state, and act on it. The approval queue
becomes one filtered view of it rather than the whole page.

## 1. What exists already — this is mostly a frontend spec

The backend is further along than the UI suggests.
[`admin.py`](../backend/app/api/routes/admin.py) already has:

| Endpoint | Does |
| --- | --- |
| `GET /admin/users` | Filter by status, source and role; free-text `search`; `limit`/`offset`; returns `total`. |
| `POST /admin/users/approve` | Bulk, up to 200 ids, with an optional reason and a `notify` flag that emails the approved guest. |
| `POST /admin/users/{id}/disable` | Requires a reason, revokes sessions, records audit. |
| `POST /admin/users/{id}/role` | Sets `player` / `organizer` / `admin`, with a reason. |

[`AdminUsersPage.tsx`](../frontend/src/routes/AdminUsersPage.tsx) calls exactly
one of them — `listUsers({ status: "pending_approval" })` — and its own comment
says so: *"Minimal by design — spec 006 owns the real admin tooling; this exists
because guests are dead in the water without someone to let them in."* Spec 006
never came back for it.

So most of this spec is building the page that the API has been waiting for. The
backend gaps are small and listed in §5.

## 2. The page — `/admin/users`

A roster table with the approval queue as a filter chip, not a separate page.

```
┌────────────────────────────────────────────────────────────┐
│ Users                                    [+ Invite guest?] │
│ Search…    (All) (Pending ⑦) (Active) (Disabled) (Staff)   │
│            Source: [Any ▾]                                 │
├────────────────────────────────────────────────────────────┤
│ ☐ Name            Email           Src  Status   Party  Last│
│ ☐ Rin Vance       rin@…           entra active  Kobolds 4m │
│ ☐ guest@…         guest@…         guest pending —      —   │
└────────────────────────────────────────────────────────────┘
```

| Column | Notes |
| --- | --- |
| ☐ | Selection, for bulk approve. The one bulk action that matters — 200 guests do not get approved one at a time, and the endpoint already takes a list. |
| Display name | Links to the detail panel. |
| Source | `entra` / `guest`. Decides which login problems are even possible for this person. |
| Status | pending / active / disabled. |
| Role | Shown only when not `player`, so staff accounts stand out without a column of "player" repeated 200 times. |
| Party | Current active membership, or an em dash. |
| Solves · XP | Enough to recognise a real player from a dormant account. |
| Last seen | `last_login_at`, relative. |

**Filter chips** across the top: All, Pending (with a count), Active, Disabled,
Staff. Plus a source select and the existing free-text search. All server-side —
the endpoint already supports every one of them.

**Approvals keeps its route.** `/admin/users/approvals` redirects to
`/admin/users?status=pending_approval`, and the sidebar's Approvals item points
at that. The queue is how the page is most often entered during the event; it
just is not a different page.

## 3. The detail panel

Clicking a row opens a drawer over the right-hand side — the same pattern spec
041 chose for challenges, for the same reason: the list does not move, so working
through a queue does not mean re-finding your place after every action.

**Identity** — name, email, source, Entra object id where present, account
created, approved by and when, last login.

**Play state** — solves, XP, level, class, party (with its history: a kicked
membership is a fact worth seeing), achievements, hints used, loot titles.

**Activity** — recent submissions with correct/incorrect and challenge, recent
solves, and the current wall from spec 050. This is the "what is this person
actually doing" view, and it is what makes a support conversation possible.

**Login troubleshooting** — for a guest, their recent magic-link deliveries from
spec 055, right here. "I never got the link" is answered in the place you are
already standing rather than on a separate page.

**Actions**, each recording an audit entry with a reason:

| Action | Notes |
| --- | --- |
| Approve | Pending accounts only. Offers the notify-by-email flag the endpoint already has. |
| Disable | Reason required (already enforced). Revokes sessions. |
| **Re-enable** | New — see §5. |
| Set role | player / organizer / admin. |
| Block from System AI | Toggles `user.assistant_blocked`, which exists on the model and has no UI. |
| Resend magic link | Guests only. The single most common support action for a guest, and currently impossible without asking them to go back to the login page. |
| View audit history | Opens the audit log filtered to this user as target (spec 051). |

**Deliberately not here: delete.** An account with solves, audit entries and
party history cannot be removed without either destroying the record or leaving
dangling references. Disable is the operation that exists, and it is the one that
is correct.

## 4. On roles

Per the standing Phase 3 decision, **no new role logic is built**. The `organizer`
role stays in the model and the role selector can set it, because the endpoint
already exists and hiding a working control would be stranger than showing it.
Nothing branches on it beyond the `Staff` / `Admin` dependencies already in place.

The practical position: there is one admin. The role selector exists so that if a
second person needs to help triage on day three, the lever is there.

## 5. Backend gaps

Small, and all of them obvious once the page exists:

- **`POST /admin/users/{id}/enable`** — disable has no inverse. Clears
  `disabled_reason`, sets status back to `active`, audits with a reason. Without
  it, a disable made in error is permanent.
- **`GET /admin/users/{id}`** — a detail payload: identity, play aggregates,
  party history, recent activity, and (from 055) recent deliveries. One endpoint
  rather than the panel fanning out to six.
- **`POST /admin/users/{id}/assistant-block`** — toggles the existing
  `assistant_blocked` column, audited. The column was added for exactly this and
  has never been settable.
- **`POST /admin/users/{id}/resend-magic-link`** — guests only; reuses the
  existing magic-link service, audited, and rate-limited the same way the public
  path is so this does not become a way around it.
- **`UserSummary` gains** `party_name`, `solve_count` and `xp` for the list
  columns, as aggregate subqueries — not N+1 across 200 rows.

## 6. Testing

- Each filter chip narrows to the right set; chips and search combine.
- Bulk approve approves every selected pending account, skips one already active
  without failing the batch, and reports per-item results.
- Approving with `notify` sends; approving without it does not.
- Disable revokes sessions; the disabled user's next request is rejected.
- **Enable restores access**, clears the reason, and audits.
- Role change is audited with the actor and reason.
- Assistant block prevents that user's next assistant call and nobody else's.
- Resend magic link is refused for an Entra account, and is rate-limited.
- The detail payload's solve and XP totals match the scoreboard's for the same
  user — one number, two places, and they must not drift.
- The list issues a constant number of queries with 200 users.
- **An admin cannot disable or demote their own account.** There is one admin;
  locking themselves out ends the event. Enforced server-side with its own test.
- Staff may read the roster; only admins may act on it.

## 7. Open questions

Signed off 2026-09-17. Each recommendation below was accepted as written
unless a **Decision** line says otherwise.

1. **Should there be a guest invite flow?** Today a guest self-serves from the
   login page and waits for approval. An admin-initiated "invite this address"
   would be useful for late additions, but it is a new email path and a new token
   path. Recommend deferring — resend-magic-link plus self-serve covers the real
   cases — but it is the one plausibly-missing action, hence the `[+ Invite
   guest?]` in the §2 sketch.
2. **Does the detail panel's activity feed need to be live?** Recommend no: it is
   read during a conversation, and a manual refresh is enough. A socket per opened
   drawer is not worth it.
3. **Should disabling a party leader transfer leadership automatically?** The
   model has automatic leadership transfer for removals. Disabling is not removal,
   and a disabled leader silently blocks their party's admin actions. Recommend
   warning at the point of disable and letting the admin decide, rather than
   transferring behind their back — but this needs a decision, and spec 053 is
   where the transfer itself lives.
