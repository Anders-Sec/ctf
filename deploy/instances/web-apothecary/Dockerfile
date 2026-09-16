# The web-apothecary challenge image (spec 045).
#
# A deliberately vulnerable patient portal carrying four Web Attacks challenges.
# It is built to fit spec 009's pod hardening exactly as that manifest builder
# writes it — non-root, read-only root filesystem, all capabilities dropped, no
# egress, gVisor — with nothing loosened. The only writable path at runtime is
# /tmp, which is where everything minted per team is built at container start.
#
# The vulnerabilities in this image are the point. Do not "fix" them: each one
# is a challenge somebody has written hints against. See app.py, where all four
# are marked FLAW, and specs/045-web-apothecary-container.md.
FROM python:3.12-slim

# Flask for the app, gunicorn to serve it. No database server: SQLite is in the
# standard library, which is what makes one image enough.
RUN pip install --no-cache-dir "flask==3.0.3" "gunicorn==23.0.0"

# A fixed non-root uid, matching runAsNonRoot on the pod. Same convention as the
# demo image.
RUN useradd --uid 10001 --create-home apothecary

WORKDIR /opt/apothecary
COPY --chown=10001:10001 flags.py db.py app.py entrypoint.py seed.sql ./
COPY --chown=10001:10001 templates/ ./templates/
COPY --chown=10001:10001 static/ ./static/
COPY --chown=10001:10001 pages/ ./pages/

USER 10001
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1

EXPOSE 8080
# Materialises this instance's flags, scrubs INSTANCE_ANSWERS from the
# environment, then execs gunicorn. The scrub is load-bearing: see entrypoint.py.
CMD ["python", "entrypoint.py"]
