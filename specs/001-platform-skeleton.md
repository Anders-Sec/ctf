# Spec 001 — Platform Skeleton & Local Dev Environment

Status: **approved** (2026-09-06) — implementing
Phase: 1
Covers: foundational (no `Plan.md` feature section; prerequisite for all of them)

## Purpose

Stand up a runnable, testable, empty-but-real application: a FastAPI backend and a
React/Vite frontend that talk to each other, backed by Postgres and Redis, with
migrations and a test harness wired in. Deliberately contains **no game logic** —
no users, challenges, flags, or scoring. Its job is to make spec 002 onward a
matter of adding features rather than also inventing project structure.

Done when a developer can clone the repo, run one command, and get a browser page
that renders data fetched from the API, with `pytest` and `vitest` both green.

## Non-goals

- Any domain model (`user`, `team`, `challenge`, ...) — those belong to 002+.
- Authentication of any kind. Endpoints in this spec are unauthenticated.
- Kubernetes manifests, Bicep/Terraform, or AKS deployment config — per
  `CLAUDE.md` those live in the separate IaC repo. Application `Dockerfile`s *are*
  in scope here (they describe how to build this app, not where it runs).

## Repo layout

```
/
├── CLAUDE.md
├── Plan.md
├── specs/
├── backend/
│   ├── pyproject.toml
│   ├── alembic.ini
│   ├── migrations/            # Alembic
│   ├── app/
│   │   ├── main.py            # app factory + router registration
│   │   ├── config.py          # pydantic-settings Settings
│   │   ├── db.py              # engine, session dependency
│   │   ├── redis.py           # redis client + lifespan wiring
│   │   ├── models/            # SQLAlchemy models (base only, for now)
│   │   ├── schemas/           # Pydantic request/response models
│   │   ├── api/
│   │   │   ├── deps.py
│   │   │   └── routes/        # one module per feature area
│   │   └── services/          # business logic, framework-free where practical
│   └── tests/
├── frontend/
│   ├── package.json
│   ├── vite.config.ts
│   └── src/
│       ├── main.tsx, App.tsx
│       ├── api/client.ts      # single typed fetch wrapper
│       ├── routes/            # one dir per page
│       └── components/
├── .github/workflows/ci.yml   # ruff + pytest + vitest on PR
├── docker-compose.yml         # local dev: postgres, redis
└── .env.example
```

Monorepo — backend and frontend live together here (confirmed).

Rationale for `services/` sitting beside `api/routes/`: flag submission, scoring,
and container provisioning all get called from more than one entry point
(HTTP route, WebSocket handler, background reconciler), so business logic should
not live inside route functions.

## Stack decisions (proposed — flag any you disagree with)

| Concern | Choice | Why |
| ------- | ------ | --- |
| Python version | 3.12 | Current stable; matches FastAPI/SQLAlchemy 2.x support |
| Python dep mgmt | `uv` + `pyproject.toml` | Fast, lockfile, one tool for venv + deps |
| ORM | SQLAlchemy 2.0 (async, `asyncpg`) | Async end-to-end with FastAPI; mature |
| Migrations | Alembic | Standard companion to SQLAlchemy; Phase 2 needs non-breaking schema growth |
| Config | `pydantic-settings`, env-var driven | No secrets in source (`CLAUDE.md`) |
| Redis client | `redis-py` asyncio | Used later for scoreboard, pub/sub, rate limits |
| Lint/format (py) | `ruff` (lint + format) | One tool |
| Backend tests | `pytest` + `pytest-asyncio` + `httpx.AsyncClient` | |
| Frontend | React 18 + TypeScript + Vite | Per `Plan.md` |
| Frontend routing | React Router | |
| Server state | TanStack Query | Scoreboard/challenge list are cache-and-invalidate shaped |
| Frontend tests | Vitest + Testing Library | |
| Styling | Tailwind CSS, colours/spacing via CSS custom-property tokens | Phase 3's art pass rethemes by swapping tokens, not rewriting components |
| CI | GitHub Actions: `ruff check`, `ruff format --check`, `pytest`, `vitest` on PR | In scope for this repo |

Async throughout is a deliberate call: 200+ concurrent players with WebSocket
scoreboard pushes and slow container-provisioning calls is exactly the workload
that suffers under a sync stack.

## Data model changes

None beyond scaffolding:

- A declarative `Base` in `app/models/__init__.py`.
- A shared mixin providing `id` (UUID v4 primary key), `created_at`, `updated_at`
  (both `timestamptz`, UTC).
- One Alembic migration: the initial empty revision establishing the version table,
  so 002's migration has a parent.

UUID over autoincrement integers because IDs will appear in player-facing URLs and
instance identifiers; sequential integers leak challenge counts and invite
enumeration.

## API surface

Everything under `/api`. This spec adds exactly three endpoints.

| Method | Path | Auth | Response |
| ------ | ---- | ---- | -------- |
| GET | `/api/health` | none | `200 {"status":"ok"}` — liveness. No dependency checks; must stay cheap. |
| GET | `/api/health/ready` | none | `200 {"status":"ok","postgres":"ok","redis":"ok"}`, or `503` naming whichever dependency failed. Readiness for k8s. |
| GET | `/api/version` | none | `{"version":"<git sha or 'dev'>","environment":"<local\|staging\|prod>"}` |

Conventions established here and expected to hold for all later specs:

- **Errors** are JSON `{"error": {"code": "<machine_code>", "message": "<human>"}}`.
  `code` is a stable snake_case string; the frontend switches on `code`, never on
  `message`. FastAPI's default `{"detail": ...}` shape is overridden by an
  exception handler.
- **Timestamps** are ISO-8601 UTC with `Z`, in and out. The DB stores `timestamptz`.
- **Trailing slashes**: no. `/api/challenges`, not `/api/challenges/`.
- **OpenAPI** is served at `/api/docs` in non-production environments only.
- The frontend talks to the API through `src/api/client.ts` and nowhere else, so
  auth headers (spec 002) get exactly one insertion point.

## Configuration

`.env.example` is committed with placeholder values; `.env` is gitignored. Settings
fail fast at startup — a missing required var raises on boot rather than at first
request.

Variables introduced now: `DATABASE_URL`, `REDIS_URL`, `ENVIRONMENT`,
`APP_VERSION`, `CORS_ALLOWED_ORIGINS`, `LOG_LEVEL`.

Per `CLAUDE.md`, no real connection strings and **no local model network address**
ever land in a committed file — the AI model host var arrives in spec 010 as a
placeholder name in `.env.example` only.

## Local dev

`docker-compose.yml` runs Postgres 16 and Redis 7 with dev-only credentials and
named volumes. Backend and frontend run on the host for fast reload:

- backend: `uv run uvicorn app.main:app --reload` → `:8000`
- frontend: `npm run dev` → `:5173`, proxying `/api` → `:8000` via Vite, so the
  browser sees one origin and CORS is a non-issue locally.

A short root `README.md` documents these three commands. That is the whole of the
README for now.

## Logging

Structured JSON logs to stdout (k8s collects stdout; no file handlers). Every
request gets a `request_id` — accepted from an inbound `X-Request-ID` header or
generated — bound to the log context and echoed in the response header. This goes
in now because the audit-log and anti-cheat specs (006/007) need to correlate a
player action to server-side events after the fact.

## Testing

- Backend tests run against a real Postgres (the compose instance, separate
  database name), not SQLite — we will depend on Postgres-specific behaviour
  (`timestamptz`, `ON CONFLICT`, advisory locks for the container reconciler).
- Fixtures: `app` (ASGI transport client) and `db_session` (transaction rolled
  back per test).
- This spec's tests: health endpoints return the documented shapes; readiness
  returns 503 when Redis is unreachable; the error-envelope handler produces the
  documented shape; the frontend renders version data from a mocked API.

## CI

`.github/workflows/ci.yml`, triggered on PR and on pushes to the default branch:

- **backend job** — `uv sync`, `ruff check`, `ruff format --check`, then `pytest`
  against Postgres and Redis service containers (same versions as compose).
- **frontend job** — `npm ci`, `tsc --noEmit`, `vitest run`, `npm run build`.

Both jobs run in parallel; nothing deploys from this workflow — deployment belongs
to the IaC repo.

## Edge cases / risks

- **Readiness vs. liveness confusion** — if `/api/health` checked Postgres, a brief
  DB blip would restart every pod mid-event. Kept deliberately dependency-free.
- **Alembic + async engine** requires the sync-driver-in-migrations pattern
  (`psycopg` for Alembic, `asyncpg` for the app). Both drivers get installed;
  `DATABASE_URL` is stored driver-neutral and the scheme is adapted per consumer.
- **The Vite proxy hides CORS problems locally** that would appear in the deployed
  split-origin setup, so `CORS_ALLOWED_ORIGINS` is wired and tested from the start
  even though local dev does not exercise it.
- **UUID PKs and index bloat** at 200 players x many submissions: fine at this
  scale, and submission tables will be indexed on
  `(team_id, challenge_id, created_at)` rather than scanned by PK.

## Decisions taken

- Monorepo: backend and frontend in this repo. **Confirmed.**
- Styling: Tailwind with token-driven colours. **Confirmed.**
- CI: GitHub Actions in this repo. **Confirmed.**
- Git: initialised on `main` with `origin` →
  `https://github.com/Anders-Sec/ctf.git`. **Done.** Nothing is pushed without an
  explicit ask, per `CLAUDE.md`.

## Open questions

None outstanding.

## Commit plan

Per `CLAUDE.md`, implemented as separate commits rather than one dump:

1. Repo scaffolding: `.gitignore`, `.env.example`, `docker-compose.yml`, `README.md`
2. Backend skeleton: app factory, config, error envelope, request-id logging
3. Database + Redis wiring, `Base`/mixins, initial Alembic revision
4. Health/version endpoints + backend tests
5. Frontend skeleton: Vite app, Tailwind, API client, version page + tests
6. CI workflow
