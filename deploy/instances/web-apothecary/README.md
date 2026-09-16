# `web-apothecary` — the Hollowmere Family Health portal

A deliberately vulnerable patient portal, carrying four of the eight Web Attacks
challenges in one image. Specified in `specs/045-web-apothecary-container.md`;
the challenge text, hints and stems are in `Challenge/container-web-apothecary.md`.

**The vulnerabilities are the point.** Four flaws, each marked `FLAW` in
`app.py`, each with published hints written against it. Do not fix them. Do fix
anything *else* you find — a fifth, unintended hole lets a player skip the area.

| Challenge | Difficulty | Flaw | Route |
| --- | --- | --- | --- |
| Someone Else's Chart | easy | IDOR | `/record?id=` |
| Quotes Are Load Bearing | medium | SQL injection | `/login` |
| Up And Out | hard | path traversal, single-pass filter | `/page?f=` |
| Curly Braces | very hard | template injection → RCE | `/message` |

## Flags

Minted per team by the platform and delivered as `INSTANCE_ANSWERS`, a JSON
object keyed by challenge slug (spec 046). `entrypoint.py` writes each one where
its challenge needs it, then **unsets the variable before starting the server** —
without that, the traversal challenge reads `/proc/self/environ` and collects the
template-injection challenge's flag for free.

With no `INSTANCE_ANSWERS` the image falls back to `flag{..._local}` values so it
runs and tests off-platform. It logs a warning when it does.

## The container template

Create this once through the admin template form. The four imported challenge
rows reference it **by the name `web-apothecary`** — the name must match exactly
or the CSV import fails with "No container template named".

| Field | Value |
| --- | --- |
| Name | `web-apothecary` |
| Image | `ghcr.io/anders-sec/ctf-web-apothecary` |
| Tag | the `sha-<gitsha>` CI published — never a moving tag |
| Container port | `8080` |
| Lifetime | `7200` seconds — four challenges on one container |
| One container for every challenge | **yes** |
| Mint a flag per team | **yes** |
| Readiness path | `/healthz` |

Egress (`none`) and runtime class (`gvisor`) take their defaults, which are the
values this image wants.

## Running it locally

```sh
docker build -t web-apothecary .
docker run --rm -p 8080:8080 \
  --read-only --tmpfs /tmp:rw,size=64m --user 10001 --cap-drop ALL \
  web-apothecary
```

Those flags are not decoration — they are how the pod actually runs it (spec
009), and `/tmp` is the only writable path the image gets. Sign in at
`http://localhost:8080` with the account the login page shows you.

## Tests

```sh
pip install flask pytest
python -m pytest        # from this directory
```

`test_solves.py` performs all four intended solutions and asserts each returns
its own flag. `test_hardening.py` covers what must stay shut: the upward leak
from the traversal to the template-injection flag, the single-pass filter's exact
behaviour, the routes that are not injectable, and that the container survives
malformed input.

Two tests are POSIX-only (`/etc/passwd`, `/proc/self/environ`) and skip on
Windows. To run the whole suite as the container does:

```sh
docker run --rm -v "$PWD/tests:/opt/apothecary/tests:ro" --entrypoint sh \
  web-apothecary -c "pip install -q pytest && cd /opt/apothecary && python -m pytest -q"
```
