# Spec 047 — The `web-registry` challenge container

Status: **done**
Phase: content (Phase 2/3 — challenge images)
Covers: `Challenge/container-web-registry.md` — the other four Web Attacks
challenges, including the area boss
Depends on: 009 (the instance machinery and the pod hardening contract), 046
(shared instances and per-team flags — **built**), 045 (the conventions this
image follows), 031 (boss encounters — `No Route To It` is the province boss)

## Purpose

Build the single container image behind `Promoted` (medium, mass assignment),
`Signed By Me` (hard, JWT forgery), `Fetch It For Me` (very hard, SSRF to
loopback) and `No Route To It` (**nearly impossible, the area boss, no hints**,
deserialization → RCE).

Content, not platform. Nothing in the app changes; 046 already built everything
this needs. The deliverable is an image under `deploy/instances/`, its tests, its
CI entry, and the `container_template` values an operator enters once.

This is the second of the two Web Attacks containers and it follows 045's
conventions exactly: per-team flags materialised at start, the environment
scrubbed before serving, `/tmp` as the only writable path, the same CI shape.
Where it differs from the apothecary, it is because this brief asks for something
different — and the differences are the interesting part of this document.

## What it is

A JSON API for a fictional records service — token authentication, user
profiles, records — **plus a second HTTP service on loopback** that was never
meant to face anybody.

```
player ──HTTP──> :8080  api                 (published, 0.0.0.0)
                          │
                          └──HTTP──> 127.0.0.1:9000  maintenance (loopback only)
                                     [::1]:9000      (when the runtime has IPv6)
```

That asymmetry is the entire basis of challenges 3 and 4: a player's browser
cannot reach the maintenance service, and the API can. It is one image with two
listeners, per the brief's hard constraint.

The clinic fiction does not carry over. This is **Ridgeline Records Bureau**, an
invented records service. No real organisation appears anywhere in the image.

### Ports differ from the brief, for a reason

The brief puts the API on `:80` and maintenance on `127.0.0.1:8080`. Neither
survives contact with the pod:

- **The API cannot bind :80.** The pod drops all capabilities, so there is no
  `CAP_NET_BIND_SERVICE` and no privileged port. The API binds **8080**, matching
  the apothecary and the demo image.
- **Maintenance therefore moves off 8080**, which the API now occupies. It binds
  **9000** — a thoroughly ordinary place for an internal console, and the second
  hint tells the player to "work through the obvious ports", which 9000 is.

Maintenance listens on `127.0.0.1` always, and on `::1` **when the runtime has an
IPv6 loopback address** — probed at start, not assumed. A plain container usually
has no `::1` at all, and binding an address that does not exist takes gunicorn
down with it, which would cost the maintenance service and challenges 3 and 4
with it in exchange for one alternative spelling.

**Corrected during the build.** An earlier version of this spec bound `::1`
unconditionally, which would not have started in a container without IPv6. The
four IPv4 spellings — `127.1`, decimal, hex and `0.0.0.0` — work everywhere and
are enough for the challenge as the hints describe it; `[::1]` works wherever the
pod has IPv6.

## Two processes, one PID 1

`entrypoint.py` is the supervisor, and it is deliberately small — no supervisord,
no second package:

1. Materialise this team's flags (below).
2. **Scrub `INSTANCE_ANSWERS` and re-exec itself**, so no `/proc/<pid>/environ`
   carries it — including its own.
3. Start maintenance (loopback) and the API (published) as child processes.
4. Wait. If either child dies, restart it; if it dies repeatedly and immediately,
   exit so the pod restarts cleanly rather than sitting there half-alive.

**Step 2 re-execs, and that was a correction made during the build.** Unsetting
alone is what the apothecary does, and it works there because that entrypoint
then `exec`s gunicorn. Here the entrypoint stays resident, and `os.environ.pop`
calls `unsetenv`, which updates the process's own copy of the environment but
*not* `/proc/<pid>/environ` — the kernel's record of what was on the stack at
`execve`. Checking a real container caught PID 1 still advertising all four
flags; re-exec is what actually clears it, and a test now pins it.

Step 4 is why the entrypoint stays PID 1 instead of `exec`ing the way the
apothecary does. The apothecary has one process, so `exec` is right there. Here,
a dead maintenance service would silently take challenges 3 and 4 with it while
`/healthz` on the API kept answering — an instance that looks healthy and is not.
The API's readiness probe therefore **also checks that maintenance is up**, so a
half-alive container fails readiness instead of being handed to a team.

## Flags

Minted per team by the platform, delivered as `INSTANCE_ANSWERS` keyed by slug
(046). The entrypoint puts each where its challenge needs it, then scrubs.

| Challenge | Stem | Lives in |
| --- | --- | --- |
| `promoted` | `i_promoted_myself` | an admin-only API response |
| `signed-by-me` | `signed_by_me` | one specific user's private record |
| `fetch-it-for-me` | `the_server_fetched_it` | served by maintenance, on loopback |
| `no-route-to-it` | `trust_no_object` | **a file, and nothing else** |

The first three are handed to the process that serves them, through a runtime
file at `/tmp/runtime/flags.json` (mode `0400`) that the children read once at
startup. Not an environment variable, and not anything either service serves.

**The boss flag is different, and deliberately so.** It is written to
`/tmp/registry/secrets/.flag` and **is not in `flags.json`, not loaded by either
process, and not held in any process's memory**. Neither service can disclose it
even if something in one of them were made to read its own configuration, because
neither has ever read it. The only thing in the container that can reach it is
code the player is running.

With no `INSTANCE_ANSWERS`, the image falls back to `flag{..._local}` values and
logs loudly, exactly as the apothecary does, so it runs and tests off-platform.

## The four flaws

### 1. `Promoted` — mass assignment — stem `i_promoted_myself`

- `GET /api/profile` returns the **whole** user object, `role` included. The hint
  tells the player to read every field, so the field has to be there.
- `PATCH /api/profile` binds the submitted JSON onto the user record with no
  allowlist, so `{"role": "admin"}` promotes the caller.
- `GET /api/admin/audit` checks for the admin role and returns this flag.

Binding is confined to this one endpoint. Every other write validates its input.

### 2. `Signed By Me` — JWT forgery — stem `signed_by_me`

Authentication is a JWT in `Authorization: Bearer`. The brief says build **one**
of `alg: none` or a weak HS256 secret; the published hint mentions both as
things to try.

**Signed off: the weak secret, `changeme`, and not `alg: none`.** At `hard` and
225 XP, `alg: none` is a thirty-second win that undersells the challenge, while
cracking the secret is a real (if short) piece of work with ordinary tools, and
gives the player something to *do*. The hint offers two things to try, and a
player trying the refused one first and moving on is the ordinary shape of this
challenge. Building both would mean nobody ever cracks anything.

`alg: none` is refused, and a test says so: a later change that started accepting
unsigned tokens would quietly turn a 225 XP challenge into a free one.

The forged token impersonates **`m.calloway`**, whose private record carries the
flag. `GET /api/records/mine` returns the caller's own private records — and
**an admin cannot read another user's**, which is what keeps challenges 1 and 2
independent as the brief requires. Promoting yourself does not get you this flag;
becoming Calloway does.

### 3. `Fetch It For Me` — SSRF to loopback — stem `the_server_fetched_it`

`POST /api/fetch` takes a URL, retrieves it server-side, and returns the response
body. It is framed as a webhook tester, so it also accepts an optional method,
body **and headers** — which is how the boss submits a job, and is why that is
not a bolt-on.

The headers were added during the build, and they are load-bearing: the
maintenance service has no session with the player and sees only what the API
sends it, so an administrator token has to be carried *inward* on the fetch.
Realising that is a step the boss requires and challenge 3 does not.

**The filter is a hostname blocklist**, exactly as the hint describes: the literal
strings `localhost` and `127.0.0.1` are refused. The name is **not** resolved and
the resulting address is **not** checked. So `127.1`, decimal, hex, `0.0.0.0` and
`[::1]` all get through, and all of them connect.

Maintenance identifies itself on `/` and lists its endpoints, including the path
serving this flag. A **plain GET through the SSRF is enough** to read it, so
challenge 3 is complete on its own and the boss is a separate step.

One guard that is not part of the puzzle: **only `http` and `https` are
fetchable.** Without it `file:///tmp/registry/secrets/.flag` ends the boss from
inside challenge 3, which would be the same upward leak the apothecary's dotfile
rule closes. The blocklist the hints describe is untouched.

### 4. `No Route To It` — deserialization → RCE — stem `trust_no_object`

The area boss. `province` tier, 900 XP, **no hints at all**. The difficulty has
to live here, not in the lead-up.

- Maintenance exposes `POST /jobs` accepting a **base64-encoded Python pickle**
  describing work to do, and unpickles it with no validation.
- It requires a token with the admin role, so the player needs one of challenges
  1 or 2 *and* challenge 3 to even knock on the door.
- **It returns the job's result**, so the player can confirm execution. Fully
  blind RCE on a challenge with no hints would be unfair.
- **There is no command parameter.** No `?cmd=`, no ping-style diagnostic, no
  file-write shortcut. If reaching maintenance were enough to run a command, the
  boss would collapse into challenge 3 with extra steps, which the brief names as
  the one thing that must not happen.

The work the boss actually asks for, once the player is through the door: realise
the blob is a pickle, craft a gadget that executes on unpickling, get it through
the SSRF intact, and read a file whose path nothing tells them — they have to
look around the filesystem with the execution they have earned.

### The prerequisite chain is (1 **or** 2) and 3 — not 2 and 3

The brief says the boss makes "challenges 2 and 3 genuinely prerequisites". As
specified it is 3 **and either of** 1 or 2, because both of those yield an
admin-capable token — that is what each of them is *for*.

Forcing challenge 2 specifically would mean the maintenance service demanded a
token for some user that promotion cannot reach, which makes challenge 1's
promotion pointedly useless and reads as arbitrary. Recorded as a deviation
rather than engineered around; the boss still requires two earlier challenges and
real work of its own.

## Keeping them independent

| Route | Reaches | Decision |
| --- | --- | --- |
| Boss RCE | everything — all three other flags, both processes, the filesystem | **Accepted.** Leakage from the hardest challenge downward is normal, and this one is the last thing in the area. |
| SSRF (very hard) → maintenance | challenge 3's flag, and the `/jobs` door | **Intended.** That is the design. |
| SSRF → the boss flag | — | **Closed** by the scheme restriction above, and by the boss flag living nowhere any service has ever read. |
| Mass assignment (medium) → admin | challenge 1's flag, the `/jobs` door | **Accepted**, and see the chain note above. |
| Mass assignment → challenge 2's flag | — | **Closed**: an admin cannot read another user's private records. |

## Routes

**API — published on 8080**

| Route | Purpose | Flaw |
| --- | --- | --- |
| `GET /` | service banner and endpoint list | — |
| `POST /api/login` | token for a seeded account | — |
| `GET /api/profile` | the whole user object, `role` included | (feeds **mass assignment**) |
| `PATCH /api/profile` | update; binds the whole body | **Mass assignment** |
| `GET /api/records` | the public record list | — |
| `GET /api/records/mine` | the caller's own private records | (target of **JWT forgery**) |
| `GET /api/admin/audit` | admin only; carries flag 1 | — |
| `POST /api/fetch` | webhook tester; URL, method, body, headers | **SSRF** |
| `GET /healthz` | readiness; also checks maintenance is up | — |

**Maintenance — loopback only, 9000**

| Route | Purpose | Flaw |
| --- | --- | --- |
| `GET /` | identifies the service, lists its endpoints | — |
| `GET /status` | service status | — |
| `GET /status/flag` | carries flag 3 | — |
| `GET /healthz` | liveness, for the API's readiness check | — |
| `POST /jobs` | base64 pickle, unpickled unvalidated, returns the result | **Deserialization → RCE** |

## Container template

| Field | Value |
| --- | --- |
| `name` | `web-registry` |
| `image` | `ghcr.io/anders-sec/ctf-web-registry` |
| `image_tag` | the `sha-<gitsha>` CI publishes |
| `container_port` | `8080` |
| `ttl_seconds` | `7200` |
| `shared_instance` | **true** |
| `injects_answer` | **true** |
| `readiness_path` | `/healthz` |
| `egress_policy` / `runtime_class` | `none` / `gvisor` (defaults) |

Two processes in one container want a little more room than the apothecary:
`cpu_limit` **500m**, `memory_limit` **384Mi**.

## Testing

Same shape as 045 — the tests exist to prove the challenges are still solvable
and the unintended routes are still shut.

`test_solves.py`

- Read the profile, see `role`, PATCH `{"role": "admin"}`, read the audit
  endpoint, get flag 1.
- Crack/forge a token for `m.calloway`, read their private records, get flag 2.
- Through `POST /api/fetch`, with each of `127.1`, decimal, hex, `0.0.0.0` and
  `[::1]`: reach maintenance, read `/`, follow it to the flag path, get flag 3 —
  **with a plain GET**.
- Through the SSRF, POST a pickle gadget to `/jobs`, read
  `/tmp/registry/secrets/.flag`, get flag 4, and get output back.
- Each response carries its own flag and no sibling's.
- The whole suite again with no `INSTANCE_ANSWERS`.

`test_hardening.py` — and the first of these is the one that decides whether
this container has a boss at all:

- **Reaching maintenance through the SSRF does not, by itself, yield the boss
  flag or command execution.** `GET /` and every documented endpoint are
  exercised; none returns it, and none runs anything. The brief names this as the
  test to write and it is the reason the boss is a boss.
- **No route anywhere returns the boss flag**: every API route, every maintenance
  route, the fetch endpoint, and a traversal attempt at each.
- `file://`, `gopher://`, `ftp://` and friends are refused by `/api/fetch`; only
  `http`/`https` are fetched.
- The boss flag is in no environment variable, in `flags.json`, or in either
  process's loaded configuration.
- The maintenance service is **not reachable on the published port** — nothing on
  0.0.0.0:9000, and no API route proxies to it except the deliberate SSRF.
- An admin cannot read another user's private records (challenges 1 and 2 stay
  independent).
- `/jobs` refuses a non-admin token.
- The blocklist refuses the literal `localhost` and `127.0.0.1`, so the filter
  the hints describe genuinely exists.
- Only `PATCH /api/profile` mass-assigns; other writes validate.
- Malformed input — a bad pickle, a 1 MB body, a URL that is not a URL, a token
  that is not a token — is an error response, not a traceback and not a dead
  worker.
- If maintenance dies, `/healthz` fails rather than reporting a healthy instance
  with two broken challenges.
- No real organisation is named anywhere in the image.

Two-process tests run the real entrypoint, as 045's do, so what is tested is the
container as it actually starts.

## Commit plan

1. The image skeleton: entrypoint/supervisor, flag materialisation and scrub,
   the runtime file, the Dockerfile.
2. The API: auth, profile, records, the seeded data — with challenges 1 and 2.
3. The maintenance service and the SSRF endpoint — challenge 3.
4. `/jobs`, the deserialization sink — challenge 4, with the negative tests.
5. CI entry, README, and the operator's template values.

## Resolved at sign-off

1. **JWT: the weak secret (`changeme`) alone**, not `alg: none` — which is
   refused, and there is a test saying so, because a later "fix" that started
   accepting unsigned tokens would quietly devalue a 225 XP challenge.
2. **The prerequisite chain is (1 or 2) and 3**, not 2 and 3.
3. **Ports 8080 and 9000** rather than the brief's 80 and 8080.

## Found during the build

Recorded because each is a thing this spec asserted and reality corrected:

1. **The re-exec** — see "Two processes, one PID 1" above. Unsetting is not
   scrubbing when the process stays resident.
2. **Conditional IPv6 binding** — an unconditional `[::1]` bind does not start in
   a container without IPv6.
3. **Configurable headers on `/api/fetch`** — without them there is no way to
   present an admin token to the maintenance service, and the boss is unreachable
   rather than hard.
4. **Which loopback spellings work is a property of the environment**, not of the
   image: Windows resolves none of the IPv4 shorthands and refuses to connect to
   `0.0.0.0`; a container without IPv6 refuses `[::1]`. The tests pick one that
   works where they run and skip the rest, saying which and why.

## Non-goals

- Any change to the platform. 046 built everything this image needs.
- A second container, a real registry protocol, or an external datastore.
- Hints for the boss. It has none, by design, and nothing here should leak into
  the other three challenges' hints to compensate.
