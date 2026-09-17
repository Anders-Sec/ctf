# Spec Index & Sequencing

Working index of every feature spec. Each spec is written, signed off, and
implemented one at a time (see `CLAUDE.md`). This file records the intended order
and why — it is a plan, not a commitment; later specs may be resequenced as we
learn things.

Status legend: `draft` (written, awaiting sign-off) · `approved` · `building` ·
`done` · `not written`

## Status: Phase 1 and 2 complete; Phase 3 in progress

**All Phase 1 specs (001–013) are done.** Every Definition-of-Done item in
`Plan.md` is built and covered by tests, with two steps that are deliberately the
operator's to run rather than this session's:

- **Live challenge containers go-live** (009): the code, manifests and cluster
  contract are ready and verified; going live is flipping `INSTANCES_ENABLED` +
  `COOKIE_DOMAIN` in `deploy/backend.yaml` and pushing the demo image.
- **The 200-player load test** (012): the harness, seed, automated NFR tests and
  runbook are done; the real run against the cluster is executed per
  `loadtest/README.md`.

Spec 013 was a polish release on top of Phase 1. Phase 2/3 work (D&D mechanics,
lore, art, a wider tone pass) is intentionally not started.


| #   | Spec | Covers (`Plan.md` section) | Status |
| --- | ---- | -------------------------- | ------ |
| 001 | `001-platform-skeleton.md` | (foundational — not a Plan.md feature) | **done** |
| 002 | `002-identity-and-auth.md` | Identity & Auth | **done** |
| 003 | `003-challenges-and-flags.md` | Challenge & Flag System (models, submission, rate limiting, attempt log, dynamic scoring, scheduled release) | **done** |
| 004 | `004-hints.md` | Challenge & Flag System (hint system) | **done** |
| 005 | `005-scoreboard-realtime.md` | Real-Time Scoreboard | **done** |
| 006 | `006-admin-tooling.md` | Admin Tooling (CRUD, score overrides, audit log, live dashboard) | **done** |
| 007 | `007-anticheat-visibility.md` | Admin Tooling (anti-cheat surfacing) | **done** |
| 008 | `008-container-isolation-design.md` | Live Isolated Challenge Containers — **design/decision spec only**, resolves the Open Item | **done** — unblocked 2026-09-07 (NetworkPolicy on, gVisor installed) |
| 009 | `009-container-instances.md` | Live Isolated Challenge Containers — implementation | **done** — HTTP-only, behind a fake orchestrator in CI |
| 010 | `010-ai-assistant-service.md` | AI Assistant — mediator service + model client | **done** |
| 011 | `011-ai-guardrails.md` | AI Assistant — challenge-integrity + real-world-safety layers | **done** |
| 012 | `012-load-and-nfr-verification.md` | Non-Functional Requirements | **done** — harness + runbook + automated NFR tests |
| 013 | `013-system-ai-and-ui-polish.md` | Polish: System AI persona, admin/player nav split, typed categories | **done** |
| 014 | `014-challenge-editor-and-prerequisites.md` | Editor completion, prerequisite locks, event settings | **done** |
| 015 | `015-character-xp-and-skills.md` | Phase 2 — character sheet, banked XP, levels, skills (deferred-hint economy) | **done** |
| 016 | `016-classes.md` | Phase 2 — character classes, level-gated, with the System AI's suggested-class nudge | **done** |
| 017 | `017-dungeon-map-board.md` | Phase 2 — dungeon map, value-based unlock gates, zone gating + fog of war | **done** — gate-editing UI landed in 022 |
| 018 | `018-abilities-and-skills.md` | Phase 2 — difficulty-driven XP, D&D ability scores, per-challenge skills, real seed content | **done** |
| 019 | `019-zone-map-and-progression.md` | Phase 2 — map of 22 zones, the progression graph, percentage and level gates | **done** |
| 020 | `020-illustrated-map.md` | Phase 2/3 — the art pass over the zone map (prompts in `art.md`) | **done** — all 22 tiles landed |
| 021 | `021-map-editor.md` | Phase 2/3 — authored zone positions, drag-to-place admin editor, organic corridors | **done** |
| 022 | `022-connection-editor.md` | Phase 2/3 — zone gate & connection editor, cycle detection, reachability warnings | **done** |
| 023 | `023-map-atmosphere.md` | Phase 2/3 — non-repeating background, map fit & feathering, progression fog, corridor texture | **done** |
| 024 | `024-class-roster.md` | Phase 2 — the 48-class roster, rarity, preference targets, skill-level gates, recommender | **done** |
| 025 | `025-dungeon-sample-data.md` | Phase 2/3 — sample data that fills the real 22 zones with the real skills | **done** |
| 026 | `026-challenge-csv.md` | Phase 2/3 — challenge import/export as CSV, with a pre-filled 242-row template | **done** |
| 027 | `027-map-layout-portability.md` | Phase 2/3 — export/import the map layout between instances, keyed on slug | **done** |
| 028 | `028-notifications-and-achievements.md` | Phase 2 — System AI notification feed, live socket, achievements and rarity | **done** |
| 029 | `029-achievement-roster.md` | Phase 2 — the achievement roster and its triggers, plus the earned_by column | **done** — 95 in the roster, 92 wired |
| 030 | `030-admin-achievements.md` | Phase 2 — admin CRUD over the roster, with trigger and copy status | **done** |
| 031 | `031-boss-encounters.md` | Phase 2 — one boss per zone, six tiers, derived stars, per-zone achievements | **done** |
| 032 | `032-broadcast-notifications.md` | Phase 2 — fan-out broadcasts: boss first kills, admin announcements, daily dispatch | **done** |
| 033 | `033-system-ai-ladder.md` | Phase 1 — the DCC System AI persona and the six-level prompt-injection ladder; **amends 011 and 013** | **done** — verified against the live model |
| 034 | `034-ai-admin-console.md` | Phase 1 — AI health, guardrail signals and session drill-down; **amends 011** | **done** |
| 035 | `035-system-ai-terms.md` | Phase 1 — terms-of-use gate for the System AI, held in a file | **done** — wording approved |
| 036 | `036-ai-session-retention-and-gate-log.md` | Phase 1 — sessions survive a reset, per-call gate log, conduct rules, chat auto-reset; **amends 011/034** | **done** |
| 037 | `037-ladder-difficulty-tune.md` | Phase 1 — retune the six rungs, new `semi-guarded` posture, measured at N=8 | **done** — curve monotonic, 0 fabricated flags |
| 038 | `038-loot-boxes.md` | Phase 2 — loot boxes from achievements: 10 types, six rarities, authored pools, generated one-of-a-kind titles at platinum and above | **done** — visual treatment deferred to Phase 3 |
| 039 | `039-roster-cleanup-and-platform-events.md` | Phase 2 — drop the seven non-monotone achievements, `player_event` for the last three inert triggers, optional Entra redirect URI; **amends 029, resolves 033 open item 1** | **done** — roster 110, zero inert |
| 040 | `040-challenge-csv-full-fidelity.md` | Tooling — every challenge property in the CSV (flags with match types, hints, prerequisites, boss tiers as JSON cells); XP set per challenge, difficulty demoted to a label; **supersedes 026's columns and 018's XP derivation** | **done** |
| 041 | `041-challenge-manager.md` | Tooling — admin challenge list rebuilt for 242: table grouped by zone with a side drawer, server-side search and problem filters, inline editing; fixes the always-zero `answer_count` | **done** |
| 042 | `042-bulk-challenge-operations.md` | Tooling — bulk selection and operations on top of 041: set state/difficulty/XP/skills, bulk delete with per-item results and the zone-pruning warning | **done** — `move_category` deferred |
| 043 | `043-event-reset-and-zone-preservation.md` | Tooling — per-group reset of play data so scaffolding challenges can be deleted; **stop pruning categories**, which was silently destroying seeded zones and their skill grouping, plus migration 0042 to repair the damage | **done** |
| 044 | `044-daily-puzzle-challenges.md` | Content — Wordle, Connections and a crossword mini played inside the challenge description block; a puzzle is an ordinary challenge, one per game per day, 15 across five days for 1,950 XP; server-held answers and sessions, completion awards the solve, failure is terminal | **done** — content (the 15 puzzles) still to author |
| 045 | `045-web-apothecary-container.md` | Content — the `web-apothecary` challenge image: one hardened Flask/SQLite portal carrying four Web Attacks challenges (IDOR, SQLi auth bypass, single-pass-filtered path traversal, SSTI → RCE), with solve and hardening tests in CI | **draft** |
| 046 | `046-shared-container-instances.md` | Platform — one container serving several challenges, each with a flag minted per team as an authored stem plus a hex tail; the `dynamic` match type 003 reserved; **amends 009, completes 008 Decision 6** | **done** |
| 047 | `047-web-registry-container.md` | Content — the `web-registry` challenge image: a JSON API plus a loopback-only maintenance service in one container, carrying mass assignment, JWT forgery, SSRF to loopback, and the province boss (deserialization → RCE, no hints) | **done** |
| 048 | `048-design-tokens-and-theming.md` | Phase 3 — semantic colour tokens, the migration off `bg-white`/literals, four curated presets, per-user and event-default theme | **done** |
| 049 | `049-admin-navigation.md` | Phase 3 — grouped persistent sidebar replacing the twelve-tab row, practical admin naming, badge counts, Live Instances split from Container Templates | **done** |
| 050 | `050-event-metrics.md` | Phase 3 — event-operations metrics: attempt-to-solve drift, near-miss detection, stalled players, progression and hint economy | **done** |
| 051 | `051-audit-log-and-admin-scoreboard.md` | Phase 3 — two read-only pages over endpoints that already exist and render nowhere; **closes two Phase 1 DoD gaps** | **done** |
| 052 | `052-user-management.md` | Phase 3 — the roster the approvals queue was standing in for; detail panel, enable/disable, roles, assistant block, resend magic link | **done** |
| 053 | `053-party-administration.md` | Phase 3 — admin control over parties: move a member, transfer leadership, rename, size cap, disband, stranded join requests | **done** |
| 054 | `054-announcements.md` | Phase 3 — announcements as a page with history, read counts and scheduling, off the bottom of the dashboard | **done** |
| 055 | `055-email-delivery-log.md` | Phase 3 — persist every outbound send so "the guest never got their link" is answerable; status band and test-send | **done** |
| 056 | `056-event-export.md` | Phase 3 — results out: standings, awards sheet, solves, submissions (redacted by default), full archive | **done** |
| 057 | `057-platform-health.md` | Phase 3 — one staff-facing screen for dependency, connection, build and load state; explicitly not observability | **done** |
| 058 | `058-content-admin-consistency.md` | Phase 3 QoL — one shape for all four Content pages: New button, search and filters, grouped lists with a drawer, full CRUD and bulk actions; achievement rewards become editable, and **secret themes unlock by achievement** (resolves 048 §11.4) | **approved** (2026-09-17) |

## Phase 3 sequencing

Phase 3's admin specs (048–057) were **written as a batch before any of them was
implemented**, so the information architecture could be settled once rather than
renegotiated per page. They are still implemented one at a time, in the order
below; `CLAUDE.md` carries the amended rule.

- **048 first, and it blocks everything.** The app cannot currently be themed —
  ~100 raw `bg-white/xx` uses across 41 component files, plus colour literals and
  a `torch` token doing duty as both brand accent and alert colour. Any page built
  before that migration is a page built twice.
- **049 second** because 050–057 all add sidebar entries, and adding eight items
  to a twelve-tab row that is already overflowing would be building on the thing
  being replaced.
- **051 early among the rest** — it is the cheapest (two tables over finished
  endpoints) and it closes two Phase 1 Definition-of-Done gaps, so it is the one
  that pays back soonest.
- **052 before 053**, since party administration links into the player detail
  panel and reuses its drawer pattern.
- **055 alongside or after 052**, because its most valuable placement is inside
  the player detail panel rather than on its own page.
- **050, 054, 056, 057 are independent** of each other and can be taken in any
  order once 049 lands.

**All ten are built (048–057).** Every missing admin surface in `Plan.md`'s
table now exists and is reachable from the sidebar, and the three that were gaps
against Phase 1's own Definition of Done — the audit log, the admin scoreboard
and real user management — are closed.

The **quality-of-life workstream** (`Plan.md` §4) is next, and is specced from
the findings of a manual walkthrough of every surface rather than up front. Two
findings are already recorded there: System AI chat usability on mobile, and
challenge navigation losing its place after a solve.


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

**The container track (008/009) is unblocked (2026-09-07).** The cluster now
enforces NetworkPolicy — verified that `ctf-instances` cannot reach the database —
and gVisor is installed as a sandboxed runtime. Both were spec 008's blocking
conditions. Spec 008's design needed no rework beyond folding the sandbox runtime
in; spec 009 (implementation) is next.

## Standing decision: scoring attribution

**Solves belong to the player, not the party.** A party's standing is an aggregate
over its current members, computed at read time — never a stored running total.
Rosters therefore stay open all event. Spec 002 carries the full reasoning; 003,
004, 005, 007 and 009 all inherit it.

Phase 2 layers XP, levels and highest-skill breakdowns onto the same aggregate
shape. Phase 1 builds none of that.

## Open Items still owed a decision

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
| ~~Which local model, and its API shape~~ | 010 | **Resolved** — LM Studio, OpenAI-compatible, via the in-cluster `ai` Service |
| LM Studio does not enforce its API key — restrict that port at the host | 010 | Operational, not code. Anyone on the LAN can use the model |
| ~~Container isolation model~~ | 009 | **Resolved by spec 008** — one `ctf-instances` namespace, NetworkPolicy per instance |
| ~~k3s NetworkPolicy enforcement~~ | 009 | **Answered (2026-09-07): on and verified** — `ctf-instances` cannot reach the DB |
| ~~Sandboxed RuntimeClass~~ | 009 | **Answered: gVisor installed.** Instances run under it |
| Wildcard DNS for `*.ctf-nm.org` | 009 | **Still open** — decides HTTP-subdomain vs. NodePort default |
