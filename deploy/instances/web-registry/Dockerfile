# The web-registry challenge image (spec 047).
#
# A JSON API on the published port plus a maintenance console bound to loopback,
# in one image, carrying four Web Attacks challenges including the area boss. It
# fits spec 009's pod hardening exactly as that manifest builder writes it —
# non-root, read-only root filesystem, all capabilities dropped, no egress,
# gVisor — with nothing loosened. /tmp is the only writable path at runtime.
#
# The vulnerabilities in this image are the point. Do not "fix" them: each is a
# challenge, and three of them have hints written against the exact mechanics.
# See api.py and maintenance.py, where all four are marked FLAW, and
# specs/047-web-registry-container.md.
#
# The one thing that must never be added here or to maintenance.py is a way to
# run a command without building a gadget. That collapses the area boss.
FROM python:3.12-slim

RUN pip install --no-cache-dir "flask==3.0.3" "gunicorn==23.0.0" "pyjwt==2.9.0"

# A fixed non-root uid, matching runAsNonRoot on the pod.
RUN useradd --uid 10001 --create-home registry

WORKDIR /opt/registry
COPY --chown=10001:10001 flags.py store.py api.py maintenance.py entrypoint.py ./

USER 10001
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1

# Only the API's port is published. The maintenance service binds loopback and
# is never exposed — that asymmetry is what challenges 3 and 4 are built on.
EXPOSE 8080
CMD ["python", "entrypoint.py"]
