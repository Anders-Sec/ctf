# Spec 053 — Party Administration

Status: **draft**
Phase: 3 (Polish & Operability)
Depends on: 049 (sidebar placement), 052 (the roster this links to and from)

Admin control over parties. There is currently none: every team endpoint in
[`teams.py`](../backend/app/api/routes/teams.py) is player-scoped, gated on being
the party's leader or a member, and there is no admin route or page at all.

## 1. Why this is needed on day one

Parties are self-organised (spec 002: create, join by password, request-to-join,
leader kicks). That works until it does not, and the failure modes are all
predictable and all currently unfixable without a database client:

- **A leader goes home.** Leadership transfer exists on removal, but a leader who
  simply stops showing up is not removed — they are just absent, and their party
  cannot accept anyone or change anything.
- **Someone joins the wrong party**, which at a work event happens constantly:
  two parties with similar names, or a person who accepted the first invite they
  saw.
- **A party wants to merge** with another, or split.
- **A party is one person short of the cap** and wants nine. `max_members` is
  per-team and overridable precisely so an admin can widen one party without a
  deploy — and there is no way to do it.
- **A name is a problem.** At a work event, someone will name their party
  something that has to change.

Each of these is a two-minute fix with a page and an unanswerable question
without one.

## 2. The page — `/admin/parties`

A table of every party, including disbanded ones (marked, and filtered out by
default — `disbanded_at` is a soft delete precisely so the record survives).

| Column | Notes |
| --- | --- |
| Name | Links to the detail drawer. |
| Members | Active count against `max_members`, so a full party reads as full. |
| Leader | Resolved name, marked if that account is disabled or has not logged in today — the "leader went home" signal, visible without opening anything. |
| Visibility | public / private. |
| Solves · XP | The party aggregate, computed the same way the scoreboard computes it. |
| Created | And `disbanded_at` where set. |

Search by name or member name. Filters: visibility, has-a-problem (full,
leaderless-in-effect, disbanded, empty).

## 3. The detail drawer

**Roster** — active members with role, joined-at, solves and XP each. Former
members shown below, with `removed_at`, `removal_reason` and who removed them.
The membership table never hard-deletes rows for anti-cheat reasons (spec 002),
and that history is exactly what an admin needs when adjudicating a complaint.

**Pending join requests**, with accept and reject. A leader who has gone home
leaves these stranded, and unsticking them is the single most likely reason to
open this drawer.

**Actions**, each audited with a reason:

| Action | Notes |
| --- | --- |
| Rename | Name is `CITEXT` unique; a collision is refused with a clear message. |
| Set visibility | public / private. |
| Clear join password | Not *view* it — it is an Argon2id hash and cannot be shown. Clearing it turns a private party into request-to-join, which is the actual fix when nobody remembers the password. |
| Set max members | Bounded; see §5.2. Never below the current active count. |
| Transfer leadership | To any active member. The fix for an absent leader. |
| **Move a member to another party** | See §4. |
| Remove a member | `removal_reason = admin`, which the enum already has and nothing currently sets. |
| Add a member | From the roster, subject to the size cap and the one-active-membership rule. |
| Disband | Soft delete. Members become party-less, not deleted. |
| View audit history | Filtered to this party as target (spec 051). |

## 4. Moving a member is the operation to get right

"Move" is a remove and an add, and it has to be **one transaction** or it can
leave a player in neither party or — worse — trip the partial unique index
`uq_team_membership_active_user` and half-fail.

The rules it must respect, all of which already exist in the schema:

- A user holds **at most one active membership**, enforced by that index rather
  than by application code. The move must not violate it even momentarily.
- The destination must have room under its `max_members`.
- Moving the **source party's leader** requires transferring leadership first, or
  the move is refused with that as the reason. Silently promoting someone is a
  change to a social structure the admin did not ask for.
- The old membership row is **closed, not deleted**: `removed_at`,
  `removal_reason = admin`, `removed_by_user_id`.

**Solves do not move.** Per the standing decision in `specs/README.md`, solves
belong to the player and a party's standing is an aggregate over its *current*
members, computed at read time. So moving a player moves their contribution
automatically, and there is nothing to recompute. This is worth stating in the UI
at the point of the move, because it is surprising: moving a strong player
visibly changes both parties' standings immediately.

`Solve.team_id_at_solve` records where they were at the time and is untouched —
it is history, not score.

## 5. API

All new, all `Admin` (not `Staff` — every one of these changes state), all
audited:

- `GET /api/admin/parties` — list with the §2 columns, search and filters,
  `include_disbanded`.
- `GET /api/admin/parties/{id}` — detail: roster, former members, join requests.
- `PATCH /api/admin/parties/{id}` — name, visibility, `max_members`,
  `clear_join_password`.
- `POST /api/admin/parties/{id}/leader` — transfer.
- `POST /api/admin/parties/{id}/members` — add.
- `DELETE /api/admin/parties/{id}/members/{user_id}` — remove.
- `POST /api/admin/parties/members/{user_id}/move` — `{ to_party_id, reason }`.
  Routed off the member rather than a party because the source is derivable and
  naming both invites them disagreeing.
- `POST /api/admin/parties/{id}/disband`.
- `POST /api/admin/parties/{id}/join-requests/{request_id}/{accept|reject}`.

### 5.2 `max_members` bounds

`DEFAULT_MAX_MEMBERS` is 8 and the column is a `SmallInteger`. The admin override
needs a ceiling — an unbounded party is a scoring problem, since party standing
is a union of distinct solves and a party of 40 is just "everyone". Recommend a
hard cap of **16** in the endpoint, refusing anything higher, with the reasoning
recorded here so it is not re-argued.

## 6. Testing

- Move is atomic: a move into a full party leaves the member in their original
  party, with a test asserting both sides.
- Move is refused for a party leader, naming leadership transfer as the fix.
- Move closes the old membership with `removal_reason = admin` rather than
  deleting it.
- The one-active-membership index is never violated, including under a
  concurrent move and join.
- Both parties' scoreboard standings reflect a move immediately, with no
  recompute step.
- `Solve.team_id_at_solve` is unchanged by a move.
- Rename to an existing name (differing only in case, since the column is
  `CITEXT`) is refused with a usable message.
- `max_members` cannot be set below the current active count, nor above 16.
- Transfer leadership refuses a non-member and a removed member.
- Disband leaves members party-less and their solves intact; the party still
  resolves for the audit trail.
- An admin accepting a stranded join request has the same effect as the leader
  accepting it.
- Every action writes an audit entry with actor and reason.
- A player calling any of these endpoints gets 403 — the player-facing team
  endpoints keep their own leader-scoped rules unchanged.

## 7. Open questions

1. **Merge as a first-class action?** Merging is "move every member of A into B,
   then disband A", which the move endpoint already composes. Recommend not
   building a dedicated merge until it is wanted — the composition is honest
   about what it does, including refusing when B lacks room.
2. **Should disbanding notify the members?** The notification substrate exists
   (spec 028). A party vanishing without explanation is confusing. Recommend yes,
   as a `system` notification, with the admin's reason *not* included — reasons are
   admin-facing.
3. **Does the size cap of 16 (§5.2) interact badly with the party ranking
   formula?** Spec 005 chose a union-of-distinct-solves formula specifically so a
   party of 1 and a party of 8 have the same ceiling. That property holds at 16
   too, so this is probably fine — flagging it because the formula's reasoning
   assumed 8.
