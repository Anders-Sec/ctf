# `web-registry` — the Ridgeline Records Bureau

A deliberately vulnerable JSON API plus an internal maintenance console on
loopback, in one image, carrying four Web Attacks challenges — including the
area boss. Specified in `specs/047-web-registry-container.md`; the challenge
text, hints and stems are in `Challenge/container-web-registry.md`.

**The vulnerabilities are the point.** Four flaws, each marked `FLAW` in
[`api.py`](api.py) or [`maintenance.py`](maintenance.py). Do not fix them. Do fix
anything *else* you find.

| Challenge | Difficulty | Flaw | Where |
| --- | --- | --- | --- |
| Promoted | medium | mass assignment | `PATCH /api/profile` |
| Signed By Me | hard | JWT forgery (weak HS256 secret) | the token |
| Fetch It For Me | very hard | SSRF to loopback | `POST /api/fetch` |
| No Route To It | **nearly impossible, boss, no hints** | pickle deserialization → RCE | `POST /jobs`, maintenance |

## Two listeners, one image

```
player ──HTTP──> :8080  api            (published)
                          └──HTTP──> 127.0.0.1:9000  maintenance (loopback only)
```

The maintenance service is never published. A player's browser cannot reach it;
the API can. That asymmetry is what challenges 3 and 4 are built on.

`entrypoint.py` is the supervisor. It materialises the flags, scrubs
`INSTANCE_ANSWERS`, **re-execs itself**, then starts and watches both services.
The re-exec is not decoration: `unsetenv` does not clear `/proc/<pid>/environ`,
so without it PID 1 would advertise all four flags for the life of the container.

The API's `/healthz` also checks that maintenance is alive, so a container with
one dead service fails readiness instead of being handed to a team with two
broken challenges.

### IPv6

Maintenance listens on `[::1]` **when the runtime has an IPv6 loopback address**,
and on `127.0.0.1` always. A plain container usually has no `::1`, and binding an
address that does not exist takes gunicorn down with it — so it is probed, not
assumed. The four IPv4 spellings (`127.1`, decimal, hex, `0.0.0.0`) work
everywhere and are enough for the challenge as written.

## Flags

Minted per team and delivered as `INSTANCE_ANSWERS`, keyed by challenge slug
(spec 046). Three go into `/tmp/runtime/flags.json` for the services to serve.

**The boss flag is deliberately different.** It is written to
`/tmp/registry/secrets/.flag` and left out of that runtime file, so neither
process ever loads it and neither can disclose it. The only thing in the
container that can reach it is code the player is running.

With no `INSTANCE_ANSWERS` the image falls back to `flag{..._local}` values and
says so in the log.

## The container template

Create once through the admin template form. The four imported challenge rows
reference it **by the name `web-registry`** — it must match exactly.

| Field | Value |
| --- | --- |
| Name | `web-registry` |
| Image | `ghcr.io/anders-sec/ctf-web-registry` |
| Tag | the `sha-<gitsha>` CI published — never a moving tag |
| Container port | `8080` |
| Lifetime | `7200` seconds |
| One container for every challenge | **yes** |
| Mint a flag per team | **yes** |
| Readiness path | `/healthz` |
| CPU / memory limit | `500m` / `384Mi` — two processes want more room than one |

Egress (`none`) and runtime class (`gvisor`) take their defaults.

## Running it locally

```sh
docker build -t web-registry .
docker run --rm -p 8080:8080 \
  --read-only --tmpfs /tmp:rw,size=64m --user 10001 --cap-drop ALL \
  web-registry
```

Those flags are how the pod actually runs it (spec 009). Sign in as
`t.brennan` / `bureau2019`.

## Checking a deployed instance

Browsing the API by hand cannot work: every endpoint but `/` and `/healthz`
needs a bearer token, so a browser gets `{"error": "A bearer token is
required."}` — which is the API behaving correctly, not a fault.

A deployed instance also sits behind the **ingress auth check** (spec 009):
every request to an instance subdomain is validated against the player's
platform session before it reaches the container at all, so a script with no
cookie gets a 401 *from nginx* and never touches the challenge.

```sh
python verify.py https://dm-xxxx.ctf-nm.org <ctf_access>
```

Copy `ctf_access` from devtools → Application → Cookies. It is a 15-minute
token, so use a fresh one. Omit it only when testing a container directly.

It signs in, solves all four challenges in order, and prints which step failed
and what came back. It also reports whether the maintenance service is up, since
challenges 3 and 4 are unreachable without it. Exit code 0 means the instance is
good, which separates an image fault from a platform one.

## Tests

```sh
pip install flask pyjwt pytest
python -m pytest        # from this directory
```

`test_solves.py` performs all four intended solutions. `test_hardening.py` covers
what must stay shut — above all **that reaching the maintenance service is not by
itself enough to get the boss flag or a shell**, which is what makes challenge 4
a boss rather than challenge 3 with extra steps.

Which loopback spellings work is a property of the machine, not the image:
Windows will not resolve `127.1` or connect to `0.0.0.0`, and a container without
IPv6 will not accept `[::1]`. The tests pick a spelling that works where they are
running and skip the ones that cannot, saying so. To run them as the container
does:

```sh
docker run --rm -v "$PWD/tests:/opt/registry/tests:ro" --entrypoint sh \
  web-registry -c "pip install -q pytest && cd /opt/registry && python -m pytest -q"
```
