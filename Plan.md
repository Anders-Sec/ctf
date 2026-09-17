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
process. This file is the phase roadmap and the current phase scope; feature-level
specs are written per-feature before implementation, under `specs/`.

## Phase Roadmap

- **Phase 1 — Technical Foundation.** Complete. Core platform, auth, challenges,
  scoring, admin tooling, live isolated challenge infra, and the AI assistant
  integration. Specs 001–014.
- **Phase 2 — D&D Mechanics.** Complete. Character sheets, ability scores tied to
  challenge categories, XP/levels, classes, the dungeon-map challenge board, boss
  encounters, achievements, loot drops. Specs 015–047.
- **Phase 3 — Polish & Operability (this phase).** Theming, an admin information
  architecture that holds the surfaces the event actually needs, event-operations
  metrics, and a quality-of-life pass over every player-facing surface. Specs 048
  onward. Scope below.

**On the old "Phase 3 — Art & Creative Pass".** Most of it already landed inside
Phase 2: the illustrated zone map (020), the map atmosphere pass (023), the class
roster (024) and the System AI persona (033/037) were all art and voice work done
in place. What is left of it — the deferred loot visual treatment (038) and a
wider tone pass — folds into this phase's UI overhaul rather than waiting for a
separate creative phase that would now be re-touching finished screens.

---

## Phase 3 Scope — Polish & Operability

Phases 1 and 2 built the platform and the game. This phase makes both of them
survivable for five days with 200+ players and exactly one admin. The filter for
anything proposed here is **"what will hurt at 2pm on day one?"** — not general
polish.

Four workstreams, in this order. The ordering is load-bearing: theming before the
UI overhaul, and navigation before the pages that fill it.

### 1. Theming (first — it is a foundation, not a feature)

The Tailwind token layer in `frontend/tailwind.config.js` and `index.css` was
built for this, but components have already routed around it: ~100 uses of raw
`bg-white/xx` across 41 component files, plus hardcoded hex/rgba in both `.tsx`
and `index.css`. A theme switch does nothing until those are migrated, and every
component built *before* the migration is a component that has to be touched
twice.

- A complete semantic token set (surface, raised surface, border, focus ring,
  and so on) so no component names a raw colour again.
- Migration of the existing offenders onto it.
- **Curated preset themes**, not a free colour picker — presets can be
  contrast-tested in CI; arbitrary player-chosen colours cannot.
- Theme selection persisted per user, with an event default the admin sets.
- Theming is a **player-facing** concern. Admin surfaces use practical, neutral
  presentation (see §2).

### 2. Admin information architecture

Twelve flat top-level tabs with no grouping, inconsistent naming, and no home for
the surfaces the event needs. Replaced by a **persistent left sidebar with
grouped sections** — one level of navigation, everything one click away, badge
counts for work waiting.

Groups:

| Group | Holds |
| --- | --- |
| (top, ungrouped) | Dashboard |
| Operations | Score adjustments & reports, Anti-cheat signals, Metrics, System AI, Live instances, Approvals, Audit log, Announcements, Platform health |
| Content | Challenges, Skills, Classes, Achievements, Map |
| Settings | Event settings, Theme, Container templates, Email delivery, Export, Reset & sample data |

Two standing decisions for this area:

- **Admin pages get practical, non-themed names.** "Manage" becomes Challenges,
  "Dungeons" becomes Live Instances, "Console" becomes Dashboard. Dungeon
  flavour is reserved for player-facing surfaces, where it lands harder for not
  being diluted across the tooling.
- **Roles stay as they are.** The `organizer` role exists in the model and is not
  being removed, but no further logic is built to support it. There is one admin.
  Where a page would branch on role, it branches on `administer` as it already
  does and nothing more.

### 3. Event-operations metrics

A metrics surface aimed squarely at **spotting a problem early enough to fix it
mid-event** — not platform observability. Failed-attempt rates, player velocity,
challenge difficulty drift, engagement falloff, the hint economy.

Platform/infra metrics to Prometheus/Grafana are explicitly **out of scope**: for
a five-day single-instance event the setup cost is not repaid. Staff-facing
platform health is a single page (§2, Operations), not a metrics stack.

### 4. Quality-of-life pass

Every surface manually walked, with the friction fixed as it is found. Specs for
this workstream are written *after* the admin work lands, from the findings of
that walkthrough. Two already identified:

- **The System AI chat is rough on mobile** — usability, not styling.
- **Challenge navigation loses its place.** Finishing a challenge returns the
  player to the top of a 242-row list, so getting back to the zone they were
  working means re-filtering or scrolling. The list should preserve position and
  offer next/previous within the current zone.

Also in this workstream: responsive behaviour on player-facing surfaces (a
meaningful share of 200 people will be on phones), and consistent empty, loading
and error states.

### Missing admin surfaces to be built this phase — **all built (specs 050–057)**

Identified by walking the current admin area against what a five-day event
actually asks for. Three of these are gaps against Phase 1's own Definition of
Done, not new features:

| Surface | Status today |
| --- | --- |
| **Audit log viewer** | `GET /api/admin/audit-log` exists and the client function exists; **no page renders it**. Phase 1 DoD requires it. |
| **Admin scoreboard** | `GET /api/admin/scoreboard` exists; **no page renders it**. Phase 1 DoD calls for raw solve timestamps for tie-breaking. |
| **User management** | Only an approval queue. No roster, search, per-player drill-down, role assignment, or disable/enable. |
| **Party administration** | None. No way to move a player between parties, rename, or disband. |
| **Announcements** | Composer is bolted to the bottom of the dashboard; no record of what was sent. |
| **Email delivery log** | Sends are best-effort and logged to stdout only. "The guest never got their link" is unanswerable from the UI. |
| **Event export** | Challenge CSV exists; no export of final standings, solves and timings for awards and the write-up. |
| **Staff platform health** | Only the public status page. No internal view of datastore, model-host or socket health. |

### Definition of Done — Phase 3

- No component references a raw colour; every preset theme passes an automated
  contrast check; a player and the admin can each pick a theme and it persists.
- The admin area navigates by grouped sidebar, with badge counts for reports and
  approvals, and every page named practically.
- Every surface in the table above exists and is reachable from the sidebar.
- The metrics page answers, without leaving it: which challenges are behaving
  unexpectedly, which players have stalled, and whether the hint economy is
  working.
- The QoL findings list from the manual walkthrough is specced and cleared.
- The player-facing app is usable on a phone across the core flows: challenge
  list, challenge detail, flag submission, scoreboard, System AI chat.

---

## Phase 1 Scope (delivered — historical record)

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

## Open Items / Decisions Needed Before or During Build (Phase 1 — resolved)

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