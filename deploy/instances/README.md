# Challenge instance images (spec 009)

Images for live challenge containers. They are built and pushed to GHCR like the
app images, reviewed like app code, and **never** player-supplied.

- `demo/` — a trivial target that serves the per-instance `$INSTANCE_ANSWER`.
  Its only job is to exercise the launch → reach → solve path end to end. Point a
  `container_template` at `ghcr.io/anders-sec/ctf-demo:v1`, port 8080, and wire a
  challenge to it.

Real challenges are content, added here later against the same machinery.
