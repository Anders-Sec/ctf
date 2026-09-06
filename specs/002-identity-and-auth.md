# Spec 002 — Identity, Auth & Teams

Status: **draft — awaiting sign-off**
Phase: 1
Covers: `Plan.md` → Identity & Auth
Depends on: spec 001 (skeleton, migrations, error envelope, request-id logging)

## Purpose

Establish who a player is, how they prove it, what they are allowed to do yet, and
which party they belong to. Two login paths — Entra ID for employees, email magic
link for guests — converge on one internal session format so nothing downstream
cares which door a user came through.

This spec owns the `user` and `team` schema, which everything else in Phase 1 hangs
off and which Phase 2 will extend with stat blocks. Getting the shape right matters
more here than anywhere else in the phase.

Done when an employee can log in through Entra with their profile photo, a guest
can log in through a magic link and sit in a pending state until an admin approves
them, and an approved player can create or join a party of up to 8 with the
public/private and leader rules below.

## Non-goals

- Challenges, flags, scoring, hints (003/004). No points fields on `team` yet.
- The admin *UI* for approving users and viewing audit logs — endpoints ship here,
  screens ship in 006. A minimal admin approval page is included only because
  guests are unusable without it.
- Solo play. Schema supports a team of one; Phase 1 UX assumes a party.
- Phase 2 character/stat fields.

## Decisions taken (from your answers)

- Guests can **sign in** immediately but are **blocked from acting** until an admin
  approves them.
- All users — employees included — are blocked from gameplay actions before the
  event start time.
- Party size: **maximum 8**.
- Account creation prompts the user to create or join a party.
- Parties are **public** (anyone joins) or **private** (join password, or
  request-to-join approved by the leader).
- The party creator is the **leader** and can kick any member.

## Data model

New tables. All inherit spec 001's `id`/`created_at`/`updated_at` mixin.

### `user`

| Column | Type | Notes |
| ------ | ---- | ----- |
| `email` | `citext`, unique, not null | Case-insensitive; the identity key across both paths |
| `display_name` | text, not null | From Entra profile, or guest-chosen at first login |
| `source` | enum `entra` \| `guest` | |
| `entra_object_id` | uuid, unique, nullable | Entra `oid` claim; null for guests |
| `role` | enum `player` \| `organizer` \| `admin` | Default `player` |
| `status` | enum `pending_approval` \| `active` \| `disabled` | |
| `avatar_blob` | bytea, nullable | See "Avatars" |
| `avatar_updated_at` | timestamptz, nullable | Drives ETag |
| `approved_at`, `approved_by_user_id` | timestamptz, uuid FK | Null until approved |
| `last_login_at` | timestamptz, nullable | |

Employees are created `active`. Guests are created `pending_approval`.

Phase 2 extension point: character/stat columns get added to `user` and `team`
additively — nothing here is a natural key that a stat block would have to break.

### `team`

| Column | Type | Notes |
| ------ | ---- | ----- |
| `name` | `citext`, unique, not null | 3–32 chars; uniqueness is case-insensitive so "Mimics" and "mimics" can't both exist |
| `visibility` | enum `public` \| `private` | |
| `join_password_hash` | text, nullable | Argon2id. Private teams only; null means request-to-join is the only route in |
| `leader_user_id` | uuid FK `user`, not null | |
| `max_members` | smallint, not null, default 8 | Per-team override of the global cap, so an admin can widen one party mid-event without a deploy |
| `disbanded_at` | timestamptz, nullable | Soft delete; a team that ever had solves must not vanish |

### `team_membership`

`team_id`, `user_id`, `role` (`leader` \| `member`), `joined_at`, `removed_at`,
`removed_by_user_id`, `removal_reason` (enum `left` \| `kicked` \| `admin`).

Rows are never hard-deleted — a kicked player's history is needed for anti-cheat
review (007). Enforced by a **partial unique index on `user_id` where
`removed_at IS NULL`**: a user is in at most one active party at a time.

### `team_join_request`

`team_id`, `user_id`, `status` (`pending` \| `accepted` \| `rejected` \|
`cancelled`), `decided_at`, `decided_by_user_id`. Partial unique index on
`(team_id, user_id) where status = 'pending'`.

### `magic_link_token`

`email` (citext), `token_hash` (sha256 of the raw token — the raw value exists only
in the emailed URL), `expires_at`, `consumed_at`, `requested_ip`, `requested_user_agent`.

### `auth_session`

`user_id`, `refresh_token_hash`, `expires_at`, `revoked_at`, `ip`, `user_agent`.
One row per active refresh token; rotation writes a new row and revokes the old.

### `event_config` (singleton)

`name`, `starts_at`, `ends_at`, `registration_open` (bool), `updated_by_user_id`.
A single row guarded by a `CHECK` on a fixed id. Included here — not deferred to
006 — because the "blocked before start time" rule needs somewhere to read the
start time from. Admin editing UI lands in 006.

### `audit_log`

`actor_user_id`, `action` (text, e.g. `user.approve`, `team.kick`), `target_type`,
`target_id`, `reason` (free text, nullable), `metadata` (jsonb), `request_id`,
`created_at`.

**Deliberate cross-spec call:** `Plan.md` lists audit logging under Admin Tooling,
but approvals and kicks happen in this spec, so the table is introduced here and
006 adds actions and read views on top of it rather than inventing a second one.

## Auth flows

### Employees — Entra ID OIDC

Authorization Code + PKCE, confidential client, backend-handled callback. The SPA
never sees an Entra token.

1. `GET /api/auth/entra/login` → 302 to Entra. `state` and PKCE verifier are stored
   in a short-lived signed httpOnly cookie, not in server memory (survives a pod
   restart mid-login).
2. `GET /api/auth/entra/callback` → validate `state`, exchange code, validate the
   `id_token` (issuer, audience, `nonce`, expiry, signature against JWKS with
   cached keys), then upsert the user on `entra_object_id`.
3. Fetch the profile photo from Microsoft Graph (`/me/photo/$value`) with the
   access token, store it (see Avatars), then redirect to the SPA.

Entra users are `active` on creation — no approval step.

### Guests — email magic link

1. `POST /api/auth/magic-link` `{email}` → **always** `202`, regardless of whether
   the address is known. No account enumeration.
2. A 32-byte random token, base64url-encoded, is emailed as a link. Stored hashed.
   **TTL 15 minutes, single use.** Issuing a new token invalidates that email's
   prior unconsumed tokens.
3. `POST /api/auth/magic-link/verify` `{token}` → consumes the token inside a
   transaction (`UPDATE ... WHERE consumed_at IS NULL RETURNING` so a double-click
   can't produce two sessions), creates the user `pending_approval` if new, and
   issues a session.
4. First-time guests are prompted for a display name before anything else.

Rate limited in Redis: per email address and per source IP, on both request and
verify. Verify failures are counted separately — that is the brute-force surface.

### Sessions (both paths)

- **Access token**: JWT, 15-minute TTL, in an httpOnly `Secure` `SameSite=Lax`
  cookie. Claims are deliberately minimal: `sub`, `jti`, `iat`, `exp`.
- **Refresh token**: opaque 32-byte random value, httpOnly cookie, 7-day TTL,
  rotated on every use, stored hashed in `auth_session`. Reuse of an already-rotated
  refresh token revokes the whole chain for that user (token-theft detection).
- **CSRF**: double-submit token in a readable cookie, echoed in an `X-CSRF-Token`
  header on every non-GET request.
- WebSockets (005) authenticate off the same cookie at handshake.

**Role, status, and team are *not* in the JWT.** They are loaded per request from
Postgres through a Redis-cached user record (60s TTL, explicitly invalidated on
approve/disable/role-change/kick). This costs a cache read per request and buys
correctness: a kicked or disabled player loses access immediately rather than up to
15 minutes later. That mattered enough to pay for — a player kicked mid-event
should not keep submitting flags for the party that removed them.

Signing key comes from config as a secret; `kid` in the JWT header so keys can be
rotated without invalidating every session at once.

## Authorization model

Three FastAPI dependencies, composed per route:

| Dependency | Rejects with |
| ---------- | ------------ |
| `require_authenticated` | `401 not_authenticated` |
| `require_active_user` | `403 account_pending_approval` / `403 account_disabled` |
| `require_event_started` | `403 event_not_started` (bypassed by `organizer`/`admin`) |

Capability matrix — what each state can do:

| Action | Pending guest | Active, before start | Active, after start | Organizer | Admin |
| ------ | ------------- | -------------------- | ------------------- | --------- | ----- |
| Log in, view own profile, set display name | yes | yes | yes | yes | yes |
| Create / join / leave a party | no | yes | see roster lock | read | yes |
| View scoreboard | no | no | yes | yes | yes |
| Submit flags, use hints, deploy instances, chat with the DM AI | no | no | yes | no | yes |
| Approve users, adjust scores, edit challenges | no | no | no | **read-only** | yes |

`organizer` is included (`Plan.md` offers it as optional) because event staff
watching for broken challenges should not need an account that can silently rewrite
scores. Read-only staff visibility is cheap now and awkward to retrofit.

Every gate failure returns the spec 001 error envelope with a stable `code`, so the
frontend can render "your account is awaiting a dungeon master's approval" versus
"the dungeon doors open at 09:00" without string-matching messages.

## Team rules

- A user is in **at most one active party**, enforced by the partial unique index.
  Joining a second requires leaving the first.
- **Capacity is 8**, enforced under a row lock: the join transaction takes
  `SELECT ... FOR UPDATE` on the `team` row before counting active members, so two
  simultaneous joins cannot produce a party of 9.
- **Public** party: any active user with a free slot may join, no approval.
- **Private** party: join by password (Argon2id-verified, rate limited per user and
  per team to blunt guessing), or by request-to-join that the leader accepts.
  A private party with no password set accepts requests only.
- **Leader** may: kick any member, accept/reject join requests, rename the party,
  flip visibility, set/clear the join password, and transfer leadership.
- **Leader departure**: if the leader leaves or is removed by an admin, leadership
  auto-transfers to the longest-tenured remaining member. If the last member
  leaves, the party is `disbanded_at`-stamped rather than deleted.
- **Kicks and leaves are audit-logged**, including who and when.
- Party name is validated (3–32 chars, printable, no impersonation of admin/staff
  names via a small blocklist) and unique case-insensitively.

## API surface

All under `/api`, all following spec 001's conventions.

### Auth

| Method | Path | Gate | Notes |
| ------ | ---- | ---- | ----- |
| GET | `/api/auth/entra/login` | none | 302 to Entra |
| GET | `/api/auth/entra/callback` | none | Sets cookies, redirects to SPA |
| POST | `/api/auth/magic-link` | none | Always 202 |
| POST | `/api/auth/magic-link/verify` | none | Consumes token, issues session |
| POST | `/api/auth/refresh` | refresh cookie | Rotates |
| POST | `/api/auth/logout` | authenticated | Revokes refresh chain, clears cookies |
| GET | `/api/auth/me` | authenticated | User, team summary, `status`, and a resolved `capabilities` object so the SPA renders the right gates without reimplementing the matrix |
| PATCH | `/api/users/me` | authenticated | Display name only |
| GET | `/api/users/{id}/avatar` | authenticated | Serves `avatar_blob` with ETag / long cache |

### Teams

| Method | Path | Gate | Notes |
| ------ | ---- | ---- | ----- |
| GET | `/api/teams` | active | Public parties + own party. Name, visibility, member count, has-space |
| POST | `/api/teams` | active | Creator becomes leader |
| GET | `/api/teams/{id}` | active | Members visible; join password never returned |
| PATCH | `/api/teams/{id}` | leader | Name, visibility, join password |
| POST | `/api/teams/{id}/join` | active | Public, or private + correct password |
| DELETE | `/api/teams/{id}/members/{user_id}` | leader (any) or self (own) | Kick or leave |
| POST | `/api/teams/{id}/leader` | leader | Transfer |
| POST | `/api/teams/{id}/join-requests` | active | Private parties |
| GET | `/api/teams/{id}/join-requests` | leader | Pending list |
| POST | `/api/teams/{id}/join-requests/{rid}/accept` | leader | Capacity re-checked at accept time |
| POST | `/api/teams/{id}/join-requests/{rid}/reject` | leader | |
| DELETE | `/api/teams/{id}/join-requests/{rid}` | requester | Cancel own request |

### Admin

| Method | Path | Gate | Notes |
| ------ | ---- | ---- | ----- |
| GET | `/api/admin/users` | organizer (read) / admin | Filter by `status`, `source`, `role`; the approval queue |
| POST | `/api/admin/users/{id}/approve` | admin | Bulk variant accepts an id list — 200 guests approved one click at a time is not a plan |
| POST | `/api/admin/users/{id}/disable` | admin | Reason required; revokes sessions |
| POST | `/api/admin/users/{id}/role` | admin | |
| GET | `/api/admin/event-config` | organizer / admin | |
| PATCH | `/api/admin/event-config` | admin | Start/end time, registration open |

## Avatars

Entra photos are not publicly fetchable — Graph requires a token — so we cannot
store a Graph URL and let the browser load it. At login we fetch the 96×96 photo
once, cap it at 128 KB, and store the bytes in `user.avatar_blob`, served back
through our own endpoint with an ETag. Refreshed on each login, so a changed
corporate photo catches up within a session.

Guests get a deterministic identicon generated from their user id — enough to tell
players apart in a party list. Phase 3 replaces this with real art.

## Frontend

- Login screen: "Sign in with your work account" (Entra) and "Sign in with email"
  (magic link), plus a "check your inbox" state.
- First-run flow for new users: display name (guests only) → create-or-join-party.
- Pending-approval screen for unapproved guests, and a pre-event "doors open at…"
  screen — both driven by `capabilities` from `/api/auth/me`, not by client-side
  clocks.
- Party screen: roster with avatars, leader controls (kick, transfer, visibility,
  password), pending join requests, invite/join flow.
- Minimal admin approval queue, since guests are dead in the water without it.
- The spec 001 API client gains CSRF header injection and a single 401 → refresh →
  retry interceptor.

## Edge cases

- **A guest signs up with an address that later logs in via Entra.** Matched on
  `email`; the account is upgraded in place (`source` → `entra`, `entra_object_id`
  set, status forced `active`) rather than duplicated. History and party membership
  survive.
- **A corporate address tries the magic-link path.** Rejected with guidance to use
  the work-account button, so employees don't end up in the approval queue.
  *Needs the domain list — see open questions.*
- **Magic link forwarded or opened twice.** Single-use consume; second attempt gets
  a generic `invalid_or_expired_token` — the same response as a bad token, so
  nothing leaks.
- **Email delivery is slow or silently fails.** The "check your inbox" screen offers
  a resend after 60s, and delivery failures are logged with the request id so an
  admin can find them mid-event.
- **Two people race to accept the last join request.** Capacity re-checked under the
  row lock at accept time; the loser gets `team_full`, not a party of 9.
- **Leader kicks themselves.** Rejected; they must transfer leadership or leave
  (which auto-transfers).
- **A player leaves a party after solving challenges.** Solves belong to the team
  (003), so points stay with the party. The departing player carries nothing.
  See the roster-lock question below — this is the team-hopping cheat vector.
- **Disabled mid-event.** Cached user record invalidated immediately and refresh
  chain revoked; the next request fails closed.
- **Clock skew around event start.** The gate compares server time only; the SPA
  countdown is decorative and re-fetches `capabilities` at zero.
- **Entra tenant returns a user with no email claim** (some guest/B2B accounts).
  Fall back to `preferred_username`, then `upn`; if all are absent, fail the login
  with a clear code rather than inventing an identity key.

## Testing

- Both login paths end-to-end against a mocked Entra JWKS/token endpoint and a
  captured outbound mail transport.
- Magic-link token: expiry, reuse, invalidation-on-reissue, rate limits.
- The capability matrix, as a table-driven test — every cell, every role/status/time
  combination. This is the security surface of the whole platform and deserves
  exhaustive rather than representative coverage.
- Concurrency: parallel joins against a 7-member party produce exactly one success;
  parallel accepts of two requests for one slot likewise.
- Refresh-token rotation and stolen-token reuse detection.
- Guest→Entra account upgrade preserves party membership.

## Open questions

1. **Email transport for magic links** — internal SMTP relay, Graph `sendMail`, or a
   third-party service? **This blocks guest login entirely**; everything else in the
   spec can be built without it. Need host/auth details in config (never committed).
2. **Entra app registration** — who creates it, and how do `tenant_id`,
   `client_id`, and the client secret reach the cluster? Also: may any user in the
   tenant sign in, or must they be in a specific security group?
3. **Corporate email domain(s)** to steer away from the magic-link path.
4. **Roster lock at event start?** My recommendation is **yes**: after `starts_at`,
   joining/leaving/kicking requires an admin. Otherwise a party can rotate members
   through and a player who solved for team A can carry knowledge to team B, and
   the scoreboard stops meaning anything. The cost is admin work for genuine
   no-shows. Your call — it changes the team endpoints' gating.
5. **Can pending guests join a party before approval?** Spec currently says no. If
   approval is expected to lag (someone signs up the night before), letting them
   pick a party while pending and gating only gameplay would smooth the first hour.
   Cheap to flip either way now, annoying later.
6. **Guest self-service after rejection** — is there a "rejected" state distinct
   from `disabled`, and does a rejected user see why? Currently they see the same
   pending-style screen.
7. **Approval notification** — should approved guests get an email, or is it
   assumed they'll refresh? An email needs the same transport as (1).

## Commit plan

1. Migration: `user`, `team`, `team_membership`, `team_join_request`,
   `magic_link_token`, `auth_session`, `event_config`, `audit_log`
2. Session layer: JWT issue/verify, refresh rotation, CSRF, cached-user dependency
3. Entra OIDC login + callback + avatar fetch
4. Magic-link request/verify + rate limiting + mail transport
5. Authorization gates + capability matrix + `/api/auth/me`
6. Team endpoints (create/join/leave/kick/transfer, join requests)
7. Admin user-approval and event-config endpoints
8. Frontend: login, first-run, pending/pre-event screens, party screen
9. Frontend: admin approval queue
10. Tests (interleaved with the above rather than saved for last; listed here for completeness)
