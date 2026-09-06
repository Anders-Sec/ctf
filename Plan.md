# Project Plan — D&D-Themed CTF Platform

## Vision

A custom-built, self-hosted Capture The Flag platform for a 200+ player, multi-day
work security event. Replaces CTFd with a fully controllable platform. Themed as a
D&D-style dungeon crawl, narrated by a sassy on-screen AI assistant in the spirit of
*Dungeon Crawler Carl*. Players are employees (Entra ID) and outside guests
(passwordless email login), competing solo or in teams by solving security
challenges across categories, earning points, and (in later phases) leveling up
character-style stat blocks.

This project is built using **Spec-Driven Development (SDD)** — see `CLAUDE.md` for
process. This file is the phase roadmap and Phase 1 scope; feature-level specs are
written per-feature before implementation.

## Phase Roadmap

- **Phase 1 — Technical Foundation (this phase).** Core platform, auth, challenges,
  scoring, admin tooling, live isolated challenge infra, and the AI assistant
  integration. No D&D-specific mechanics yet beyond basic team/player identity.
- **Phase 2 — D&D Mechanics.** Character sheets, stat blocks tied to challenge
  categories, leveling/XP, classes, dungeon-map challenge board, boss
  encounters, loot drops.
- **Phase 3 — Art & Creative Pass.** Visual identity, art assets, environment
  theming, lore/narrative writing, AI assistant personality polish, sound design.

Phase 2 and 3 are out of scope for now and should not be designed into Phase 1
beyond leaving reasonable extension points (e.g., a `player` and `team` model that
can later carry stat-block fields without a breaking migration).

---

## Phase 1 Scope

### Tech Stack

- Frontend: React + Vite
- Backend: FastAPI
- Database: PostgreSQL (source of truth)
- Cache / real-time: Redis (scoreboard, pub/sub for live updates, rate limiting)
- Orchestration: Kubernetes on AKS — **cluster is on-prem/hybrid**, not a
  cloud-hosted AKS reaching out over VPN. This matters for how the AI assistant
  and any other on-prem-network services are reached (direct cluster networking,
  not ExpressRoute/VPN tunneling).
- Auth: Entra ID (employees) + passwordless email magic-link (outside guests)

### Identity & Auth

- Two auth paths issuing the same internal session/JWT format so the rest of the
  app doesn't care which path a user came through:
  - **Employees:** Entra ID OIDC login. Pull profile picture and display name from
    Entra profile.
  - **Guests:** Email magic-link (passwordless). User enters email, receives a
    time-limited single-use link, no password ever stored.
- Unified `user` model with a `source` field (`entra` | `guest`), optional
  `avatar_url` (Entra photo or a default placeholder for guests).
- Team model: users belong to a team for the event (team creation/join-by-code).
  Design the schema so solo-play is possible later without a rework, but Phase 1
  UX can assume teams.
- Role-based access: `player`, `admin` at minimum; consider `organizer` if helpful
  for staff who need read-only visibility without full admin CRUD.

### Challenge & Flag System

- Challenge model: title, category, description/body, points, flag (stored
  hashed, never plaintext), difficulty, release time, visibility toggle, links to
  downloadable artifacts if static, and an optional reference to a container
  template if it's a live/instanced challenge.
- Dynamic scoring: points decay as more teams solve a challenge (standard CTF
  dynamic scoring curve) — should be tunable per challenge or globally.
- Flag submission: rate-limited per team/challenge in Redis to block brute force;
  log all attempts (correct and incorrect) for anti-cheat review.
- Hint system: hints cost points or a per-team hint-currency; unlockable and
  logged.
- Scheduled release: challenges/challenge tiers can be set to unlock at a future
  timestamp, supporting the multi-day format.

### Live Isolated Challenge Containers

- Per-team (or per-request) ephemeral container instances in the on-prem
  Kubernetes cluster for challenges that need a live target (web exploitation,
  network-based challenges, etc.).
- Player-facing "Deploy Instance" action that spins up an instance from a
  challenge's container template, assigns it network isolation from other
  teams' instances, and exposes connection info (URL/port) to that team only.
- Auto-teardown after a configurable TTL or on explicit "Destroy Instance";
  reconciler/cleanup job to catch orphaned instances.
- This is flagged as needing more design work — Phase 1 should ship a working
  version but the isolation/networking approach should be written up as its own
  spec before implementation (namespace-per-team vs. network-policy-per-instance,
  resource quotas per team, how many concurrent instances a team may hold).

### Admin Tooling

- Full CRUD on challenges, categories, hints, container templates, and release
  schedules.
- Live event dashboard: solve rates per challenge, currently-flagged-as-broken
  challenges, error/exception feed from container instances.
- Manual scoring overrides: adjust a team's points directly, issue one-off
  point awards (for broken-challenge compensation, community awards, etc.), with
  an audit log of who made the change, when, and why (free-text reason field).
- Ability to disable/hide a challenge instantly without deleting it (for
  mid-event fixes).
- Basic anti-cheat visibility: flag submissions that are suspiciously fast,
  duplicate flags submitted by unrelated teams, etc. — flagged for admin review,
  not auto-actioned in Phase 1.

### Real-Time Scoreboard

- Redis-backed live scoreboard; push updates to clients via WebSocket rather
  than polling.
- Public scoreboard view + admin view (may show more detail, e.g., raw solve
  timestamps for tie-breaking).

### AI Assistant ("Dungeon Master AI")

- Backed by a **locally-hosted model on the on-prem network** (not a cloud API).
  Since the Kubernetes cluster is itself on-prem/hybrid, the backend service
  reaches the model host directly over the local network — design this as an
  internal service call, not an external egress path.
- A dedicated backend service (`ai-assistant-service`) mediates all calls to the
  local model — the frontend never talks to the model directly. This service is
  the enforcement point for guardrails and the only thing that needs to know the
  model host's address.
- Players get a persistent text-chat UI available from any screen in the app to
  ask the assistant for help/flavor/nudges during the hunt.
- **Guardrails — dual focus, treated as equally important:**
  - **Challenge-integrity guardrails:** the assistant must never be given the
    actual flag values or answer-revealing content in its context/prompt for a
    challenge; system-level instructions must resist prompt-injection attempts
    from players trying to extract flags, and output should be filtered/checked
    before returning to the player.
  - **Real-world safety guardrails:** the assistant must not produce actual
    working exploit code, malware, or real attack instructions beyond what's
    needed for the sandboxed challenge context — this needs its own filtering
    layer independent of the challenge-integrity checks, since a jailbreak could
    target either one.
  - Both checks should be logged (without necessarily blocking gameplay flow)
    so you can review attempted abuse after the event.
- Phase 1 delivers: chat UI, backend mediator service, basic system prompt with
  dungeon-master flavor, and both guardrail layers. Deep personality/lore writing
  is a Phase 3 concern — Phase 1 just needs it working and safe.

### Non-Functional Requirements

- Support 200+ concurrent players across a multi-day event without data loss on
  restart (Postgres as source of truth, Redis as cache/real-time layer only).
- Load-test flag submission and container-provisioning endpoints specifically —
  these are the two most likely bottlenecks at scale.
- Audit logging on all admin actions (scoring changes, challenge edits,
  container force-teardowns).

---

## Open Items / Decisions Needed Before or During Build

- Exact isolation model for live challenge containers (namespace-per-team vs.
  network-policy-per-instance) — needs its own spec.
- Which local model is being hosted, and its API shape (OpenAI-compatible?
  custom?) — affects the `ai-assistant-service` client implementation.
- Team size limits and team creation/join UX details.
- Whether guest (non-employee) accounts need any admin approval step before
  being allowed to join, or if magic-link signup is fully self-serve.

## Definition of Done — Phase 1

- Employees can log in via Entra ID with profile picture; guests can log in via
  email magic link.
- Admin can create/edit/hide challenges (static and container-backed) and see
  live solve activity.
- Players can browse challenges, submit flags, see a live-updating scoreboard,
  request hints, and spin up/tear down live challenge instances scoped to their
  team.
- Admin can manually adjust a team's score and see an audit trail of the change.
- Players can chat with the AI assistant from any screen; both guardrail layers
  are demonstrably working (attempted flag extraction and attempted
  real-exploit generation are both refused/deflected).
- Platform sustains a 200+ player load test across the core flows above without
  data loss or crash.