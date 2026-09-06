# CTF Platform

A self-hosted, D&D-themed Capture The Flag platform. See [`Plan.md`](Plan.md) for
the phase roadmap and [`specs/`](specs/) for the feature specs — this project is
built spec-first, so read the relevant spec before changing code
(see [`CLAUDE.md`](CLAUDE.md)).

## Running locally

Prerequisites: Docker, [uv](https://docs.astral.sh/uv/), Node 20+.

```sh
cp .env.example .env          # fill in as needed; never commit .env
docker compose up -d          # postgres on :15432, redis on :6379
cd backend && uv run alembic upgrade head && uv run uvicorn app.main:app --reload
cd frontend && npm install && npm run dev
```

- API: http://localhost:8000 — docs at http://localhost:8000/api/docs
- App: http://localhost:4173 (proxies `/api` to the backend)

### Ports on Windows

Postgres uses host port `15432` and Vite uses `4173` rather than the usual `5432`
and `5173`. Windows reserves blocks of ports for dynamic allocation (Hyper-V, WSL,
Docker), and both defaults commonly fall inside one — binding them fails with a
permissions error that looks nothing like a port conflict. To see the current
reservations:

```sh
netsh int ipv4 show excludedportrange protocol=tcp
```

## Tests

```sh
cd backend  && uv run pytest        # needs docker compose up
cd frontend && npm test
```

## Layout

| Path | What |
| ---- | ---- |
| `backend/` | FastAPI service, SQLAlchemy models, Alembic migrations |
| `frontend/` | React + Vite single-page app |
| `specs/` | Feature specs — written and signed off before implementation |
