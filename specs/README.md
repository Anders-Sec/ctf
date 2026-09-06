# Spec Index & Sequencing

Working index of Phase 1 feature specs. Each spec is written, signed off, and
implemented one at a time (see `CLAUDE.md`). This file records the intended order
and why — it is a plan, not a commitment; later specs may be resequenced as we
learn things.

Status legend: `draft` (written, awaiting sign-off) · `approved` · `building` ·
`done` · `not written`

| #   | Spec | Covers (`Plan.md` section) | Status |
| --- | ---- | -------------------------- | ------ |
| 001 | `001-platform-skeleton.md` | (foundational — not a Plan.md feature) | **done** |
| 002 | `002-identity-and-auth.md` | Identity & Auth | **done** |
| 003 | `003-challenges-and-flags.md` | Challenge & Flag System (models, submission, rate limiting, attempt log, dynamic scoring, scheduled release) | **done** |
| 004 | `004-hints.md` | Challenge & Flag System (hint system) | **done** |
| 005 | `005-scoreboard-realtime.md` | Real-Time Scoreboard | **done** |
| 006 | `006-admin-tooling.md` | Admin Tooling (CRUD, score overrides, audit log, live dashboard) | approved |
| 007 | `007-anticheat-visibility.md` | Admin Tooling (anti-cheat surfacing) | not written |
| 008 | `008-container-isolation-design.md` | Live Isolated Challenge Containers — **design/decision spec only**, resolves the Open Item | not written |
| 009 | `009-container-instances.md` | Live Isolated Challenge Containers — implementation | not written |
| 010 | `010-ai-assistant-service.md` | AI Assistant — mediator service + model client | not written |
| 011 | `011-ai-guardrails.md` | AI Assistant — challenge-integrity + real-world-safety layers | not written |
| 012 | `012-load-and-nfr-verification.md` | Non-Functional Requirements | not written |

## Sequencing rationale

- **001 first** because every later spec needs a place to put code, a migration
  tool, and a test harness. It deliberately contains no game logic.
- **002 before 003** — challenges, submissions, and scoring all hang off
  `user`/`team` identity, and getting that schema wrong is the expensive mistake.
- **003 before 005** — the scoreboard is a projection of solve data; it needs
  something to project.
- **004 (hints) after 003** because hint cost is a scoring-side effect.
- **006/007 after 003+005** — admin tooling is mostly CRUD and read views over
  models that must already exist.
- **008 split out from 009** because `Plan.md` explicitly flags the isolation
  model as needing its own design write-up before implementation. 008 produces a
  decision (namespace-per-team vs. network-policy-per-instance, quotas,
  concurrency limits); 009 implements it.
- **010 before 011** so there is a real request path to attach guardrails to, but
  011 is *not* optional polish — Phase 1's Definition of Done requires both
  guardrail layers demonstrably working, so 010 does not ship to players without 011.
- **012 last** — load testing needs the flows it is testing.

The container track (008/009) is the largest unknown and depends on cluster
access. It can be lifted earlier if cluster access lands sooner; it is late here
only because it is not a blocker for anything above it.

## Standing decision: scoring attribution

**Solves belong to the player, not the party.** A party's standing is an aggregate
over its current members, computed at read time — never a stored running total.
Rosters therefore stay open all event. Spec 002 carries the full reasoning; 003,
004, 005, 007 and 009 all inherit it.

Phase 2 layers XP, levels and highest-skill breakdowns onto the same aggregate
shape. Phase 1 builds none of that.

## Open Items still owed a decision

Container work (008/009) is the largest remaining unknown and needs cluster
access; it is late in the order only because nothing above it depends on it.


Tracked from `Plan.md`; each is needed *before* the spec that consumes it.

| Open Item | Blocks | Needed by |
| --------- | ------ | --------- |
| ~~Guest accounts: self-serve or admin approval?~~ | 002 | **Resolved** — sign-in allowed, actions blocked until admin approval |
| ~~Team size limits + create/join UX~~ | 002 | **Resolved** — max 8; public/private parties, leader kicks, password or request-to-join |
| ~~Email transport for magic links~~ | 002 | **Resolved** — Proton Mail SMTP, `smtp.protonmail.ch`, token in env |
| ~~Entra registration scope~~ | 002 | **Resolved** — tenant-wide, all employees, config-supplied credentials |
| ~~Corporate email domains~~ | 002 | **Resolved** — `ENTRA_ENFORCED_EMAIL_DOMAINS` env var, never in source |
| ~~Roster lock at event start~~ | 002 | **Resolved** — no lock; safe because solves are personal |
| ~~Party ranking formula~~ | 005 | **Resolved** — union of distinct solves minus distinct hints; identical ceiling for a party of 1 and of 8 |
| ~~Hint cost model~~ | 004 | **Resolved** — points, per player; no party pool |
| ~~Dynamic scoring decay basis~~ | 003 | **Resolved** — configurable per challenge, players *or* teams |
| ~~Artifact storage~~ | 003 | **Resolved** — MinIO in-cluster, behind a swappable storage interface |
| ~~Scoring defaults~~ | 003 | **Resolved** — floor of 100 for now; the full modifier model is deferred to the user |
| Which local model is hosted, and its API shape (OpenAI-compatible or custom?) | 010 | before 010 sign-off |
| Container isolation model | 009 | resolved *by* spec 008 |
