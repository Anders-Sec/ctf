# Spec 045 — The `web-apothecary` challenge container

Status: **done**
Phase: content (Phase 2/3 — challenge images, not platform)
Covers: `Challenge/container-web-apothecary.md` — four of the eight Web Attacks
challenges
Depends on: 009 (the instance machinery, the pod hardening contract, the CI image
job), 040 (the CSV rows), **046** (shared instances and per-team flags)
Blocks play on: **046 — one container, several challenges, a flag each per team**
(see Prerequisite below)

## Purpose

Build the single container image that backs four already-authored Web Attacks
challenges: `Someone Else's Chart` (easy, IDOR), `Quotes Are Load Bearing`
(medium, SQLi auth bypass), `Up And Out` (hard, path traversal) and
`Curly Braces` (very hard, SSTI → RCE).

This spec builds **content, not platform**. No backend, frontend or schema change
in this repo's app. The deliverable is an image under `deploy/instances/`, its
tests, its CI entry, and the exact `container_template` field values an operator
enters once at event setup.

The challenge text, hints and XP are written and imported already. This document
is measured against `Challenge/container-web-apothecary.md`; where it deviates,
the deviation is called out in **Deviations from the brief** so the other session
can correct a row if it disagrees. The flag *values* in that brief have since
been superseded by per-team minting (046) — the authored strings live on as the
stems, and `Challenge/dynamic-flags-note.md` is what was sent to that session.

## Prerequisite (decided, separate spec)

All four challenge rows carry `container_template = web-apothecary`. The platform
keys a `challenge_instance` to a **challenge**, so as built today a team playing
all four would launch four identical pods and hit `INSTANCE_MAX_PER_OWNER` (2) on
the third.

Decision: **one instance serves all four challenges, each with its own per-team
flag.** That is spec 046 — the launcher matches on `template_id`, and each
instance mints a flag per challenge as an authored stem plus a hex tail. It is
signed off before the event, not here. The image is buildable and testable
without it; only play is blocked. The same change is what makes `web-registry`
(also four challenges, one image) work, so it is done once for both.

## What it is

A server-rendered patient portal for a fictional clinic, written to look like an
internal application somebody built in 2011 and nobody has touched since: Flask
with Jinja2 templates, a session cookie, an embedded SQLite database, table
layout, no JavaScript framework, no build step. The dated look is load-bearing —
it is what makes four bugs of this vintage plausible in one application.

One image, one process tree, no compose stack, no external database, per the
brief's hard constraint.

### Fiction and safety

- The clinic is **Hollowmere Family Health**, a wholly invented practice. No
  reference to Northwestern Medicine or to any real organisation appears in the
  image, its templates, its seed data or its comments.
- Every patient name, record number, address and clinical note is invented and
  obviously so. Nothing resembling a real record format is used.
- All four flags are **minted per team** (spec 046): the authored stem with a
  hex tail, e.g. `flag{not_your_chart_a3f9c1d0}`, delivered at launch in
  `INSTANCE_ANSWERS`. A flag one team screenshots is worthless to another.

## Stack and layout

Python 3.12-slim · Flask · Jinja2 (Flask's own, unsandboxed — challenge 4 needs
it) · stdlib `sqlite3` · gunicorn, 2 workers × 4 threads · port **8080**.

```
deploy/instances/web-apothecary/
  Dockerfile
  entrypoint.py           # materialises this team's flags, scrubs the env, execs
  flags.py                # where the four flags live, and how they get there
  app.py                  # routes; the four flaws live here and nowhere else
  db.py                   # built at start under /tmp, then opened read-only
  seed.sql                # the invented patients, users and notes
  templates/              # Jinja2 templates for the portal
  static/portal.css       # one stylesheet, deliberately of its era
  pages/                  # the LFI-reachable content pages (welcome.html, etc.)
  tests/
    conftest.py
    test_solves.py        # the four intended solutions, asserting exact flags
    test_hardening.py     # the unintended routes that must stay shut
  README.md               # operator notes: template values, how to run locally
```

## Running under spec 009's hardening

The pod manifest (`backend/app/services/instances/manifests.py`) is not
negotiable and the image is built to fit it as-is:

| Control | Consequence for this image |
| --- | --- |
| `runAsNonRoot` | `USER 10001`, a fixed numeric uid, as the demo image does |
| `readOnlyRootFilesystem: true` | nothing outside `/tmp` is writable at runtime |
| only `/tmp` writable (emptyDir) | **everything minted per team is built under `/tmp` at start** — the database and both flag files |
| `capabilities: drop ALL`, seccomp `RuntimeDefault`, gVisor | the RCE in challenge 4 lands in a sandbox with no capabilities |
| `EgressPolicy.NONE` | no outbound network, satisfying the brief directly |
| `restartPolicy: Always` | a player who kills the app gets a clean one back |
| readiness probe | `/healthz` returns 200 and touches nothing |

Per-team flags mean the database cannot be baked at build time — two of the four
flags live inside it. So the entrypoint builds `/tmp/apothecary.db` from
`seed.sql` at container start, and the app then opens it **read-only**
(`file:/tmp/apothecary.db?mode=ro`, `uri=True`) for the rest of its life. No
journal, no writable handle, nothing a player can corrupt from the app. That is
most of the answer to "survive being hammered": a restart rebuilds from the same
seed and the same injected flags, so it is indistinguishable from a fresh start.

The "send a message" feature of challenge 4 therefore renders and displays the
message rather than persisting it — which is what the challenge needs, and is
honest about a portal that "queues" outbound mail.

## Flags at runtime

The platform hands the container one environment variable, `INSTANCE_ANSWERS`, a
JSON object keyed by challenge slug (046). `entrypoint.py` runs before anything
else and, in order:

1. Parses it, and falls back to the four authored stems with a fixed
   `_local` tail when it is absent — so `docker run` and the test suite work with
   no platform. The fallback logs loudly at warning level; it is a development
   convenience, never a production path.
2. Writes each flag where its challenge needs it:
   - `someone-elses-chart` → the clinical notes of record `1043`, in the database
     it is building.
   - `quotes-are-load-bearing` → a `portal_setting` row in the same database,
     which the admin dashboard renders.
   - `up-and-out` → `/tmp/flag.txt`.
   - `curly-braces` → `/tmp/.flag`, mode `0400`.
3. **Unsets `INSTANCE_ANSWERS` and `exec`s gunicorn**, which inherits the
   scrubbed environment.

Step 3 is the whole reason this is an entrypoint and not application startup
code. The path-traversal challenge can read `/proc/self/environ`. Leave the flags
in the environment and that `hard` challenge hands over the `very_hard`
challenge's flag — the upward leak this spec works to prevent everywhere else.
The pod spec that carried the variable is not readable from inside the container:
the service-account token is not mounted, by 009's hardening.

Two consequences of the read-only root filesystem, both visible to players and
both harmless:

- The two flag **files move from `/opt` to `/tmp`** — `/opt` cannot be written at
  runtime. `/tmp` is still outside the web root, which is all the challenge text
  claims, and it is among the first places anyone with a file read looks. The
  path is also named in `app.py`, which the traversal itself can read.
- Nothing survives a restart except what the entrypoint rebuilds, which is
  exactly the set of things that should.

## The four flaws

Each is the **only** flaw on its route. Everything else in the app uses bound
parameters, checks the session, and normalises paths.

### 1. `Someone Else's Chart` — IDOR — stem `not_your_chart`

`GET /record?id=<n>` looks up the record and renders it with **no comparison
between the record's owner and the session user**. Every other authenticated
route checks the session properly, so the flaw is this one missing check.

- Seeded session user: patient **P. Abernathy**, whose own record is `1042`.
- Records `1035`–`1050` are seeded, so incrementing or decrementing lands on a
  plausible neighbour rather than a 404 wall.
- The flag sits in the **clinical notes** field of record **1043**, one step up
  from the player's own, rendered in full in the notes block — visible on
  arrival, not buried.
- Credentials are on the login page (below), so the challenge is reachable
  without changing the imported challenge row.

### 2. `Quotes Are Load Bearing` — SQLi auth bypass — stem `quotes_are_load_bearing`

`POST /login` builds its query by string concatenation:

```
SELECT id, username, role FROM portal_user
 WHERE password = '<password>' AND username = '<username>'
 ORDER BY id LIMIT 1
```

- **The clause order is deliberate.** With `username` last, the textbook
  `' OR '1'='1` in the *username* field works directly — which is what the hint
  tells the player to reach for. Written the usual way round, `AND` binds tighter
  than `OR` and the bare payload silently fails; that would make the hint wrong.
  `' OR 1=1 -- ` in the username field works too. The mirror image does *not*:
  the same payload in the **password** field fails, because the true test is
  then ANDed against a username that does not exist. Verified, and covered by a
  test, so the asymmetry is recorded rather than discovered.
- A lone apostrophe surfaces the raw SQLite error (`near "...": syntax error`) on
  the login page, so the player can confirm the bug before exploiting it — the
  brief's "visible error or a clear difference in behaviour".
- `ORDER BY id LIMIT 1` makes the bypass land on the first row in the table,
  which is `h.mercer`, role `admin`.
- `sqlite3.Connection.execute` refuses multiple statements, so stacked queries
  are naturally unavailable. That is a property of the driver, not a filter, and
  it keeps the challenge on the intended path.
- **Only this query is built by concatenation.** Every other query in the app
  uses bound parameters.
- `GET /admin` renders the admin dashboard, gated on `session["role"] ==
  "admin"`. This challenge's minted flag is displayed on it, read from the
  `portal_setting` row the entrypoint wrote.

### 3. `Up And Out` — path traversal — stem `up_and_out`

`GET /page?f=welcome.html` reads a file and renders its contents inside the
portal chrome. Content pages live in `/opt/apothecary/pages/`.

The filter is **exactly one non-recursive pass**:

```python
cleaned = value.replace("../", "")        # one pass, by design
path = os.path.join(PAGES_DIR, cleaned)   # no normalisation, no realpath
```

- `....//....//....//etc/passwd` survives the pass as `../../../etc/passwd` and
  resolves — the confirmation step the second hint describes.
- The flag is at **`/tmp/flag.txt`**, outside the web root, reached the same way.
- No recursive strip, no `realpath` containment check on the traversal itself.
  This is the difficulty of the challenge and it stays.

### 4. `Curly Braces` — SSTI → RCE — stem `the_template_ate_it`

`POST /message` composes an outbound note and renders it through
`render_template_string` — Flask's own unsandboxed Jinja2 environment — before
displaying the "queued" message:

```python
rendered = render_template_string(f"Dear {patient.name},\n\n{body}\n\n— {clinic}")
```

- `{{7*7}}` comes back as `49`, the identification step the first hint describes.
- The context is Flask's default, so the usual walk from a template global to
  `os.popen` reaches command execution. No sandbox, no attribute denylist.
- The flag is at **`/tmp/.flag`**, owned by uid `10001`, mode `0400` —
  restrictive-looking, readable by the app's own uid, requiring an actual command
  to read. **It is not in an environment variable, Flask config, or the
  database**: the entrypoint scrubbed `INSTANCE_ANSWERS` before the server
  started, so `{{ config }}` and a `/proc/self/environ` read both come up empty
  and the player has to reach real execution.

## Keeping the four independent

The brief asks that the bugs be independent. Two of them are not independent for
free, and this is how each is handled:

| Route | Reaches | Decision |
| --- | --- | --- |
| SSTI (very hard) → RCE | everything: all three other flags, the DB, the source | **Accepted.** Leakage from the hardest challenge downward is normal and costs nothing — anyone who lands the RCE could have solved the other three. |
| LFI (hard) → arbitrary file read | app source, the SQLite file, hence flags 1 and 2 | **Accepted.** Same direction: hard reveals easy and medium. The player has already done the harder work. |
| LFI (hard) → `/tmp/.flag` or `/proc/self/environ` | flag 4 (very hard) | **Not accepted** — this leaks *upward* and would hand out the hardest flag in the area for free. Guarded by the dotfile rule below, and by the entrypoint's scrub. |

The guard, in the `/page` handler only:

1. After the single pass, if the **basename begins with a dot**, 404. Framed in
   the code as "only visible pages are servable", which is a plausible thing for
   a 2011 page renderer to do, and is invisible to every intended payload —
   `/etc/passwd` and `/tmp/flag.txt` both pass.
2. A second, explicit check that the normalised path is not the challenge-4 flag
   file. Belt and braces, commented as a challenge-integrity guard rather than a
   puzzle element.

Neither guard touches the traversal filter itself, so the `....//` technique the
hints are written against is unaffected. `cat` from the RCE ignores both, which
is the point.

## Credentials

Per the decision: the portal's own login page carries a notice box with the
low-privilege account — `p.abernathy` / `springfield` — styled as an internal
help note ("temporary portal accounts issued 2011; contact the front desk to
change yours"). No imported challenge row changes, and challenge 2 stays honest,
since that one is about getting in as somebody the player has no account for.

## Routes

| Route | Purpose | Flaw |
| --- | --- | --- |
| `GET /` | redirect to `/portal` or `/login` | — |
| `GET/POST /login` | sign in; shows the credentials notice; shows SQL errors | **SQLi** |
| `GET /logout` | clear session | — |
| `GET /portal` | landing; link to the player's own record | — |
| `GET /record?id=<n>` | render a patient record | **IDOR** |
| `GET /admin` | admin dashboard, carries flag 2 | — (the SQLi's target) |
| `GET /page?f=<name>` | render a content page | **Path traversal** |
| `GET/POST /message` | compose a note to a patient | **SSTI** |
| `GET /healthz` | readiness; 200, no DB, no session | — |

## Container template values

Created once by an operator through the admin template UI at event setup (there
is no seeder for `container_template`, by design — it is admin-CRUD data). The
four imported rows already reference it **by the name `web-apothecary`**, so the
name must match exactly or the CSV import fails with "No container template
named".

| Field | Value |
| --- | --- |
| `name` | `web-apothecary` |
| `image` | `ghcr.io/anders-sec/ctf-web-apothecary` |
| `image_tag` | the `sha-<gitsha>` tag CI publishes — never a moving tag |
| `container_port` | `8080` |
| `protocol` | `http` |
| `cpu_request` / `cpu_limit` | `100m` / `500m` |
| `memory_request` / `memory_limit` | `128Mi` / `256Mi` |
| `ttl_seconds` | `7200` — four challenges on one container, so twice the default |
| `env` | `{}` — the platform adds `INSTANCE_ANSWERS` itself; nothing static belongs here |
| `egress_policy` | `none` |
| `shared_instance` | **`true`** — one container for all four challenges (046) |
| `injects_answer` | **`true`** — one minted flag per challenge, per team (046) |
| `readiness_path` | `/healthz` |
| `runtime_class` | `gvisor` |

These values go in the image's `README.md` too, so the operator is not reading a
spec at setup time.

## CI

One matrix entry added to the `images` job in `.github/workflows/ci.yml`:

```yaml
- name: web-apothecary
  context: deploy/instances/web-apothecary
```

publishing `ghcr.io/anders-sec/ctf-web-apothecary` on the same pinned-tag rules
as every other image. Pull requests build but do not push, unchanged.

A second job, `challenge-images`, runs this image's pytest suite (Flask + pytest,
no cluster, no Docker) so a regression that makes a challenge unsolvable fails
the build rather than the event.

## Testing

The point of testing a challenge image is not that the code works — it is that
**the intended solution still works and the unintended ones still don't**.

`test_solves.py` runs the entrypoint with a **known `INSTANCE_ANSWERS`** carrying
four distinguishable test flags, then solves each challenge and asserts it got
that challenge's flag and not a sibling's:

- Log in with the published credentials, `GET /record?id=1043`, find the
  `someone-elses-chart` flag in the response.
- `POST /login` with `' OR '1'='1` as the username and anything as the password,
  land on `/admin` as `h.mercer`, find the `quotes-are-load-bearing` flag.
- `GET /page?f=....//....//....//tmp/flag.txt`, find the `up-and-out` flag; and
  `....//....//....//etc/passwd` returns passwd-shaped content.
- `POST /message` with a Jinja payload that executes `cat /tmp/.flag`, find the
  `curly-braces` flag; and `{{7*7}}` returns `49`.
- Each of the four responses contains **only** its own flag.
- The whole suite runs a second time with `INSTANCE_ANSWERS` unset, proving the
  local fallback keeps the image runnable and testable off-platform.

`test_hardening.py` — the routes that must stay shut:

- `/page` cannot read `/tmp/.flag` by any of: the direct path, a traversal to it,
  a dot-prefixed basename, `/proc/self/root/...`.
- **`/proc/self/environ` read through `/page` contains no flag** — the
  entrypoint's scrub, tested through the route that would exploit its absence.
- `/admin` is 403 for the seeded low-privilege session.
- The apostrophe payload that breaks `/login` does **not** break `/record`,
  `/page` or `/message` — those are parameterised.
- The traversal filter is exactly single-pass: `../` is stripped, `....//`
  survives, and a recursive-strip regression (which would make `....//` fail)
  is caught.
- The `curly-braces` flag appears in no environment variable, no Flask config
  value, and nowhere in the database — it exists only as `/tmp/.flag`.
- `/healthz` answers without a session and without touching the database.
- Malformed input — a non-integer `id`, a missing `f`, an unterminated Jinja
  expression, a 1 MB message body — returns an error page, not a 500 traceback
  and not a crashed worker.

## Deviations from the brief

Flagged per the brief's closing instruction. **No flag value changes and no
technique changes**; the hints remain correct as written.

1. **The `/page` handler refuses dot-prefixed basenames.** The brief gives
   challenge 3 an arbitrary file read and puts challenge 4's flag in a file,
   which would hand a `hard` solver the `very_hard` flag. The guard closes that
   and is invisible to both intended payloads.
2. **The login query has `password` before `username`.** Without it the hint's
   `' OR '1'='1` in the username field does not actually work, because `AND`
   binds tighter than `OR`.
3. **Messages are rendered, not stored.** The read-only database that the
   hardened pod makes the robust choice means "sending" displays the rendered
   note rather than persisting it. Challenge 4 is unaffected — the flaw is in the
   render, not the store.
4. **Both flag files moved from `/opt` to `/tmp`.** Per-team flags are written at
   container start, and `/tmp` is the only writable mount under 009's read-only
   root filesystem. Still outside the web root, so the challenge text stands.
5. **The flag values in the brief are now stems, not flags.** `flag{up_and_out}`
   becomes `flag{up_and_out_<8 hex>}`, minted per team. Nothing about the
   techniques or the hints changes.

## Open questions

1. **TTL of 7200s** — one container for four challenges, one of them `very_hard`,
   argues for longer than the 3600s default. Confirm, or set it at setup time.
2. **Instance ownership** (team vs. user) is platform config, not this image's
   business, but it decides whether four teammates share one apothecary. Worth
   settling before the event; no work here either way.

## Non-goals

- The `web-registry` image — spec 047.
- The platform side of sharing and flag minting — spec 046.
- Any app-side backend, frontend or schema change.
- Persisting anything across a restart. The entrypoint rebuilds what matters.
