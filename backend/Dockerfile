# syntax=docker/dockerfile:1

# --- build: resolve dependencies into a virtualenv -------------------------
FROM python:3.12-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy

# Dependencies first, so a source change does not re-resolve the world.
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project

# --- runtime ---------------------------------------------------------------
FROM python:3.12-slim AS runtime

# Runs as a non-root user with no shell. Nothing in this image needs to log in.
RUN groupadd --system --gid 1001 ctf \
    && useradd --system --uid 1001 --gid ctf --no-create-home --shell /usr/sbin/nologin ctf

WORKDIR /app

COPY --from=builder --chown=ctf:ctf /app/.venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

COPY --chown=ctf:ctf app ./app
COPY --chown=ctf:ctf migrations ./migrations
COPY --chown=ctf:ctf alembic.ini ./alembic.ini
COPY --chown=ctf:ctf docker-entrypoint.sh ./docker-entrypoint.sh
RUN chmod +x ./docker-entrypoint.sh

USER ctf
EXPOSE 8000

# Probes hit /health directly on the pod, outside the /api prefix.
ENTRYPOINT ["./docker-entrypoint.sh"]
