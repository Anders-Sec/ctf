# The demo challenge target for spec 009.
#
# Deliberately trivial: it exists to exercise the whole launch -> reach -> solve
# path end to end, not to be a real challenge. It serves the per-instance answer
# that the launcher injects as $INSTANCE_ANSWER, on port 8080, as a non-root
# user with nothing writable — so it also demonstrates that the hardening in
# spec 008 does not get in the way of a normal image.
FROM python:3.12-slim

# A fixed non-root uid, matching runAsNonRoot on the pod.
RUN useradd --uid 10001 --create-home dungeon
USER 10001

WORKDIR /home/dungeon
COPY --chown=10001:10001 serve.py .

EXPOSE 8080
# INSTANCE_ANSWER is provided per instance by the platform at launch.
ENV INSTANCE_ANSWER="flag{demo_unset}"
CMD ["python", "serve.py"]
