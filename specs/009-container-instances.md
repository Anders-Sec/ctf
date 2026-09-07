# Spec 009 — Live Challenge Containers: Implementation

Status: **approved** (2026-09-07) — decisions recorded below
Phase: 1
Covers: `Plan.md` → Live Isolated Challenge Containers (**implementation**)
Depends on: 008 (the isolation design, now unblocked), 003 (`container_template_id`,
the submission path, the reserved `dynamic` match type), 006 (the console)

## Decisions (sign-off)

1. **Kubernetes client:** `kubernetes-asyncio`, behind our own `InstanceOrchestrator`
   interface. Real dependency, contained; tests use a fake.
2. **First build targets orchestration plus one trivial demo image** — a static
   web target that serves `the flag is $INSTANCE_ANSWER` — so the whole path is
   exercised end to end. Real challenge images are content, added later.
3. **HTTP challenges only for Phase 1.** The raw-TCP / NodePort path is **not
   built** — a NodePort cannot be authorised, and dropping it keeps every
   instance authorised at the edge. `protocol` stays on the template for
   forward-compatibility but only `http` is implemented; a `tcp` template is
   rejected at save time with a clear message.
4. **Full spec, all 8 commits**, behind the fake orchestrator in tests.

The wildcard-DNS question (below) remains genuinely owed by the platform session
and is the one thing that can still change the HTTP exposure path.

## Purpose

Build what spec 008 decided: a player (or their party) can launch a private,
isolated instance of a challenge's container, reach it, submit an answer unique
to that instance, and have it torn down on a timer or on demand — with staff able
to see and kill everything running.

Done when a container-backed challenge can be created by staff, launched by a
player, reached over the network, solved with a per-instance answer, and reliably
cleaned up; when one party cannot reach another's instance or the database; and
when nothing is left running that no live database row owns.

008 settled the *what and why*. This spec is the *how*, and it commits to the
concrete contracts — the Kubernetes objects, the state machine, the reconciler,
and the two integration points with existing code (the submission path and the
console).

## The one hard rule this spec exists to keep

**A running instance must never be un-isolated, even for an instant.** Spec 008's
NetworkPolicy is now enforced, but a per-instance policy created *after* its pod
leaves a window where the pod runs wide open — long enough to reach
`postgres.ctf` and read every answer. So isolation is not per-instance-first:

**A standing `default-deny-all` NetworkPolicy is the baseline of the
`ctf-instances` namespace** (denies all ingress and egress, selects every pod).
A pod is therefore isolated the moment it exists, before the app does anything
else. Per-instance policies only *add* the narrow allowances 008 lists (ingress
from `ingress-nginx`, egress to DNS). There is no ordering in which a pod is ever
reachable-but-unpolicied.

The default-deny policy is created once. Preferably the platform session ships it
with the namespace; if the app's namespaced `Role` covers `networkpolicies`
(it does, per 008), the app also asserts it at startup, idempotently, so the
guarantee does not depend on a manual step being remembered.

## Provisioning is slow, so the API is poll-based

Everything else in this platform answers in milliseconds. This does not: pod
scheduling, image pull, gVisor sandbox start and readiness can take seconds to
tens of seconds. Blocking an HTTP request on that is wrong.

So `POST .../instance` creates the database row and the Kubernetes objects and
**returns immediately with `status: pending`**. The client polls
`GET .../instance` until `status: running` (with `connection_url`) or `failed`
(with a reason). This is the one place in the app that is deliberately
asynchronous, and the frontend shows a "summoning your dungeon…" state while it
waits.

## The Kubernetes client, and how it stays out of CI

The backend talks to the cluster API with its ServiceAccount token and the
namespaced `Role` from 008 — create/get/delete on Pods, Services,
NetworkPolicies and Ingresses in `ctf-instances`, nothing cluster-scoped.

All of it sits behind one narrow interface, `InstanceOrchestrator`, with a
handful of methods (`launch`, `status`, `destroy`, `list_pods`). The real
implementation wraps the Kubernetes client; a **fake** implementing the same
interface backs every test, exactly as `ai_client` is faked for spec 010.
**Nothing in CI touches a cluster**, and the reconciler, the cap logic and the
submission wiring are all testable against the fake.

> **Open question 1 — client library.** `kubernetes-asyncio` (official, async,
> handles auth/TLS/discovery/watch) versus a thin hand-rolled httpx client
> against the API server (fewer dependencies, but we reimplement auth and object
> shapes). Recommendation: `kubernetes-asyncio` behind our own interface, so the
> dependency is real but contained and the tests never see it.

## Data model

Both tables come straight from 008's "data model that spec 009 will build".

### `container_template`

Everything a challenge author configures once. `name`, `image`, `image_tag`,
`container_port`, `protocol` (`http` | `tcp`), `cpu_request`/`cpu_limit`,
`memory_request`/`memory_limit`, `ttl_seconds`, `env` (jsonb, **non-secret
only**), `egress_policy` (`none` | `dns` | `cidr`), `egress_cidrs`,
`injects_answer` (bool), `readiness_path`, `runtime_class` (default `gvisor`).

`challenge.container_template_id` already exists (spec 003 reserved it) and
becomes live here.

### `challenge_instance`

`challenge_id`, `template_id`, `owner_team_id` / `owner_user_id` (**exactly one**,
`CHECK`-enforced as `(owner_user_id IS NOT NULL) <> (owner_team_id IS NOT NULL)`,
mirroring `score_adjustment`), `k8s_name`, `status`
(`pending` | `running` | `failed` | `expired` | `destroyed`), `connection_url`,
`node_port`, `generated_answer`, `expires_at`, `destroyed_at`, `last_error`,
timestamps.

**The per-owner concurrent cap is serialized by a row lock, not a unique index.**
(Correction to the draft: a plain unique index can enforce *at most one* per
owner, not the configured N, so it is the wrong tool for a cap of two.) A launch
takes `SELECT ... FOR UPDATE` on the owning `user`/`team` row before counting
that owner's live (`pending`/`running`) instances, so two concurrent launches for
the same owner serialize rather than both passing a stale count — the same
mechanism spec 002 uses for the last party seat. The namespace `ResourceQuota` is
the independent hard backstop: even a logic bug cannot exceed the node's pod
budget.

## The per-instance answer

008's Decision 6: each instance bakes a generated answer into its target, and the
submission must be checked against *that player's own instance's* value.

The pure resolver registry in `app/services/answers.py` takes
`(submitted, ChallengeAnswer)` and cannot see an instance, so this does **not**
become another entry there. Instead the submission path in
`app/services/challenges.py` gains a small, explicit step: when a challenge's
template has `injects_answer`, resolve the submitting player's live instance and
compare the submission to its `generated_answer` (constant-time), in addition to
any static answer rules. No instance, no match — a player who has not launched one
cannot solve it, which is correct.

This keeps spec 007's shared-wrong-answer signal working (wrong strings are still
comparable across players) while the *correct* string is necessarily unique per
instance, closing the answer-sharing hole a shared live target would otherwise
open.

## Reaching an instance

**HTTP only** (decision 3). Each instance gets a Service, plus an Ingress at
`<k8s_name>.ctf-nm.org` carrying the `auth-url` annotation pointing at
`GET /api/instances/authorise`. The backend checks the session cookie and
confirms the caller owns that instance, so ownership is enforced at the edge and
does not rely on the subdomain being secret. Every instance is authorised; there
is no un-authorisable path, which is the point of dropping raw TCP.

> **Open question 2 — wildcard DNS (still owed by the platform session).** 008's
> question 3: does `*.ctf-nm.org` resolve and can we create Ingress objects in
> `ctf-instances`? If **yes**, the authorised-subdomain path above is used. If
> **no**, HTTP instances fall back to a NodePort — still HTTP, but reachable only
> by node:port and therefore **not** authorised at the edge, which reintroduces
> the exposure we dropped raw TCP to avoid. A config flag
> (`INSTANCE_HTTP_MODE = ingress | nodeport`) selects; the launcher builds both.
> Recommendation: default `ingress`, and if the answer is no, treat the NodePort
> fallback as the same "stated, not hidden" limitation 008 applied to TCP.

**Deployment caveat for the ingress path.** The `auth-url` subrequest carries the
browser's cookies for the instance *subdomain*, so the check only sees the
session cookie if that cookie is scoped to the parent domain
(`Domain=ctf-nm.org`), not host-only to the apex. If the platform enables the
subdomain path, the session cookies from spec 002 must be widened to the parent
domain — a one-line cookie change, but it belongs with turning the path on, and
until then the endpoint correctly denies (fails closed) because it sees no
cookie. Flagged here so it is a decision, not a surprise.

## Reconciliation

Two background loops, started once per process like the scoreboard broadcaster,
both holding a **Postgres advisory lock** so only one replica runs them (the
migration lock's mechanism):

- **Expiry** — every 30 s, instances past `expires_at` move to `expired` and
  their Kubernetes objects are destroyed.
- **Orphans** — every 5 min, reconcile both directions: a pod in `ctf-instances`
  with no live row is deleted (the dangerous leak — an unowned attacker
  container), and a row marked running with no pod is marked `failed`.

Destruction is idempotent: a 404 from the cluster means "already gone", which is
success. Instances are also destroyed when the owning party disbands, when the
event ends, and on staff demand.

## API surface

From 008, unchanged:

| Method | Path | Gate | Notes |
| ------ | ---- | ---- | ----- |
| POST | `/api/challenges/{id}/instance` | play | Launch; enforces the per-owner cap; returns `pending` |
| GET | `/api/challenges/{id}/instance` | play | Status and connection details; the poll target |
| DELETE | `/api/challenges/{id}/instance` | play | Destroy early |
| POST | `/api/challenges/{id}/instance/extend` | play | +TTL while under the cap |
| GET | `/api/instances/authorise` | — | The ingress `auth-url` check; 200 or 401, nothing else |
| GET | `/api/admin/instances` | staff | Everything running, owners and ages |
| DELETE | `/api/admin/instances/{id}` | admin | Force-teardown, audit-logged |

Plus template CRUD under `/api/admin/challenges/...`, alongside the existing
challenge and hint admin from spec 006. The admin list fills the container panel
spec 006's dashboard left as a placeholder.

## Configuration

`KUBE_NAMESPACE` (default `ctf-instances`), `INSTANCE_BASE_DOMAIN`
(e.g. `ctf-nm.org`), `INSTANCE_RUNTIME_CLASS` (default `gvisor`),
`INSTANCE_HTTP_MODE` (`ingress` | `nodeport`), `INSTANCE_MAX_PER_OWNER`
(default 2), `INSTANCE_DEFAULT_TTL_SECONDS` (default 3600),
`INSTANCE_IMAGE_PULL_SECRET` (default `ghcr-pull`). In-cluster API access uses
the standard mounted ServiceAccount; **no kubeconfig or token is ever read from
this repo or its config** — same rule as the AI address.

The node-capacity numbers (008's question 4) live here as config, so setting the
real quota when the platform session provides it is not a code change.

## Testing

Against the fake orchestrator, deterministic, no cluster:

- Launch creates a row and the objects, returns `pending`, then `running` once the
  fake reports readiness.
- The per-owner cap refuses the (n+1)th, and a forced double-launch cannot exceed
  it (the partial unique index holds).
- The generated answer solves the instance; another player's instance value does
  not; a submission with no instance is wrong, not an error.
- `authorise` returns 200 to the owner and 401 to anyone else.
- Expiry destroys past-TTL instances; the orphan loop deletes a pod with no row
  and fails a row with no pod.
- Destruction is idempotent against a 404.
- Party disband and event end tear down instances.
- A player cannot reach the admin endpoints; force-teardown is audit-logged.
- **The manifest the orchestrator builds carries every hardening field from 008**:
  `runtimeClassName`, non-root, all caps dropped, read-only root,
  `automountServiceAccountToken: false`, the resource limits, and a per-instance
  NetworkPolicy that denies egress to the cluster services. This is asserted on
  the generated object, so a regression that drops a control fails a test.

The last one matters most: the isolation guarantees are only as real as the spec
fields on the pod, so they are tested as data, the way the answer-whitelist is in
spec 010.

## Commit plan

1. Schema + config: `container_template`, `challenge_instance`, the settings.
2. The orchestrator interface, the fake, and the manifest builder (with the
   hardening-fields test) — no live client yet.
3. The real Kubernetes client behind the interface; the default-deny baseline.
4. Launch / status / destroy / extend endpoints and the per-owner cap.
5. The per-instance answer, wired into the submission path.
6. `authorise`, and the Ingress/NodePort exposure paths.
7. Reconciliation: expiry and orphan loops under the advisory lock.
8. Template CRUD, the admin instance list + force-teardown, and the console panel.

## Open questions

1. ~~Kubernetes client library~~ — **decided: `kubernetes-asyncio` behind our
   interface.**
2. **Wildcard DNS / Ingress in `ctf-instances`** — still owed by the platform
   session (008 Q3). Build both HTTP paths, default `ingress`; the one open item
   that can still change the exposure design.
3. ~~Real images vs demo~~ — **decided: orchestration plus one trivial demo image.**
4. **Who ships the standing `default-deny-all` policy** — the platform session
   with the namespace, or the app at startup? Recommendation: both — platform
   ships it, app asserts it idempotently, so the guarantee survives a manual miss.

## Non-goals

- Multi-node scheduling, autoscaling, per-party namespaces (008).
- Player-supplied images, ever (008).
- A TCP authentication gateway (008).
- A challenge-image catalogue — this builds the machinery; images are content.
