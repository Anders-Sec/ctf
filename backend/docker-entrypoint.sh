#!/bin/sh
# Migrate, then serve. A failed migration must stop the pod rather than let it
# come up against a schema it does not match — the startupProbe has headroom
# for this on a fresh database.
set -e

echo "running migrations"
python -m app.migrate

exec uvicorn app.main:app \
    --host 0.0.0.0 \
    --port 8000 \
    --proxy-headers \
    --forwarded-allow-ips='*' \
    --no-server-header
