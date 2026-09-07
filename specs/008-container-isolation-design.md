# Spec 008 — Live Challenge Containers: Isolation Design

Status: **unblocked** (2026-09-07) — design complete, cleared to implement in spec 009

> **Both blockers are now cleared.** The platform session has since enabled
> **NetworkPolicy enforcement** on the k3s and **verified that `ctf-instances`
> cannot reach `postgres.ctf`** — the exact test that mattered, since Postgres
> holds every answer in plaintext. **gVisor is installed** as a sandboxed
> `RuntimeClass`, so a container escape is contained to the sandbox rather than
> the node's shared kernel.
>
> These were questions 1 and 2 below, and both came back favourable, which is the
> condition the spec set for building. The design stands unchanged apart from one
> addition folded in below: instances now run under the sandboxed runtime
> (Decision 2), because it exists.
>
> The project owner's standing guidance on the residual single-node risk:
> *"It doesn't have to be perfect as no one will be burning a zero-day on a work
> CTF."* That is the right posture and it matches this spec's own framing — depth
> and honesty rather than a claim of perfection. NetworkPolicy closes the cheap
> path, gVisor makes the expensive one expensive, and the rest is stated plainly
> rather than hidden. Spec 009 implements what follows.

Phase: 1
Covers: `Plan.md` → Live Isolated Challenge Containers (**design only**)
Depends on: 002 (parties), 003 (challenges, `container_template_id`), 006 (console)
Implemented by: spec 009

## Purpose

`Plan.md` asks for this write-up before any container code:

> the isolation/networking approach should be written up as its own spec before
> implementation (namespace-per-team vs. network-policy-per-instance, resource
> quotas per team, how many concurrent instances a team may hold)

This spec answers those three questions, plus the ones that turned out to matter
more once the real cluster was known. **It ships no code.** Spec 009 builds what
this decides.

## What the cluster actually is

`Deployment.md` changes several answers that would have gone differently on a
generic cluster:

- **Single-node k3s v1.35.** Every challenge container shares one kernel with
  Postgres, Redis and the backend.
- **We are not cluster-admin.** The platform session owns the namespace, RBAC and
  secrets; we deploy manifests through ArgoCD and cannot create cluster-scoped
  objects at runtime.
- **ingress-nginx** on NodePorts 30080/30443, with a wildcard certificate
  covering `ctf-nm.org` **and `*.ctf-nm.org`**.

The first two are the load-bearing constraints below.

---

## Decision 1 — One instance namespace, isolated per instance

**Rejected: namespace-per-team.** Creating a namespace is a cluster-scoped
operation. We would need `create namespace` at runtime, which is close to
cluster-admin and is exactly what the deployment contract says we do not get. It
also leaves a namespace per party to garbage-collect, and quota is then per
party rather than per event — the wrong unit for protecting a single node.

**Chosen: one pre-created namespace, `ctf-instances`, with a NetworkPolicy per
instance.** The platform session creates the namespace, a `ResourceQuota` and a
`LimitRange` on it once, and grants us a namespaced `Role` to manage Pods,
Services, NetworkPolicies and Ingresses inside it. Nothing cluster-scoped, no
runtime namespace churn, and quota sits on the whole instance pool where it
belongs.

Every instance gets, on creation:

- A **Pod**, labelled `ctf/instance-id`, `ctf/owner-kind`, `ctf/owner-id`.
- A **Service** in front of it.
- A **NetworkPolicy** selecting exactly that pod.

### The NetworkPolicy

Default-deny both directions, then the narrowest possible holes:

| Direction | Allowed | Why |
| --------- | ------- | --- |
| Ingress | From the `ingress-nginx` namespace only | Players reach it through the ingress, never pod-to-pod |
| Egress | DNS to `kube-dns` | Otherwise most images fail to start |
| Egress | Nothing else | See below |

**Egress is denied by default, and that is the important half.** Instances must
not reach:

- **Other instances** — a player who owns a container could otherwise attack
  another party's, or read its flag.
- **`postgres.ctf`** — which holds every answer in plaintext, per spec 003. A
  challenge container that can reach Postgres makes the entire scoring model
  fiction.
- **`minio.ctf`, `redis.ctf`, the backend** — same argument.
- **The LAN**, including the AI host and anything else on the node's subnet.

A template may declare `egress_dns: true` or a specific allowed CIDR where a
challenge genuinely needs outbound access, and doing so is recorded on the
template so it is visible in review rather than discovered later.

**This depends on k3s enforcing NetworkPolicy.** k3s ships kube-router's policy
controller by default, but it can be disabled with `--disable-network-policy`,
in which case every policy above is a no-op that *looks* like it works. **The
platform session must confirm enforcement is on** — this is question 1 below,
and if the answer is no, the honest position is that instances are not isolated
and container-backed challenges should not run.

## Decision 2 — The single-node problem, stated plainly

A challenge that hands a player remote code execution inside a container is the
whole point of a web-exploitation category. On this cluster, that container
shares a kernel with Postgres, which holds every answer in plaintext.

NetworkPolicy stops the easy path. It does not stop a kernel escape. On a
single node there is no topology that makes that safe, so the mitigations are
depth and honesty rather than a claim of safety:

- **Non-root**, `runAsNonRoot: true`, `allowPrivilegeEscalation: false`.
- **All capabilities dropped**, `seccompProfile: RuntimeDefault`.
- **Read-only root filesystem**, with an `emptyDir` for anything writable.
- **`automountServiceAccountToken: false`** — otherwise a compromised container
  gets an API token, and everything above becomes decoration.
- **CPU and memory limits** on every instance, plus the namespace quota.
- **No secrets, no volumes from the host**, ever.

- **`runtimeClassName: gvisor`** — the sandboxed runtime the platform session
  installed. A container escape lands in gVisor's user-space kernel, not the
  host's, which is the difference between "owns a sandbox" and "owns the node
  that holds every answer". Every instance runs under it; if a template ever
  needs the host runtime (a challenge that gVisor's syscall surface cannot run),
  that is a deliberate per-template opt-out recorded on the template, not a
  default. **The exact `RuntimeClass` name must be confirmed with the platform
  session** — `gvisor` is the conventional name (handler `runsc`), but it is
  whatever they named the object, and a wrong name fails the pod at scheduling.

And three rules that are policy, not configuration:

1. **We only run images we build.** No player-supplied images, no arbitrary
   registry pulls.
2. **Instance images live in GHCR alongside the app**, reviewed like app code.
3. **A container-backed challenge is a deliberate decision each time**, not a
   default.

## Decision 3 — How players reach an instance

Two shapes of challenge, two mechanisms.

### HTTP challenges: per-instance subdomain, authorised at the ingress

`<token>.ctf-nm.org`, covered by the wildcard certificate the platform is
already issuing. A subdomain rather than a path because path-hosting breaks any
web app that emits absolute URLs, which is most of them.

The interesting part is that this can be **properly authorised**, not merely
unguessable. ingress-nginx supports `auth-url`, so each instance's Ingress
carries:

```yaml
nginx.ingress.kubernetes.io/auth-url: "http://ctf-backend.ctf.svc.cluster.local:8000/api/instances/authorise"
```

The backend then checks the session cookie on every request and confirms the
caller owns that instance — enforcing the same party scoping as everything else,
at the edge, with no trust in the token being secret. This is what makes
`Plan.md`'s "exposed to that team only" literally true rather than
approximately true.

Requires **wildcard DNS** for `*.ctf-nm.org`. Question 3.

### Raw TCP challenges: NodePort, with the limitation stated

Some challenges are `nc host port`, not HTTP. Those get a NodePort from the
30000–32767 range.

**A NodePort cannot be authorised.** There is no session cookie in a raw TCP
connection, so anyone who can reach the node and guess the port can connect.
Mitigations are real but partial: ports are assigned randomly rather than
sequentially, TTLs are short, and every instance is logged with its owner.

Being direct about it: for raw TCP, "exposed to that team only" is not
achievable with the tools this cluster has. The options are to accept that for
TCP challenges, to prefer HTTP challenges where the shape allows, or to add a
TCP gateway that authenticates first — which is more machinery than Phase 1
warrants. **Recommendation: accept it, prefer HTTP, and say so in the challenge
brief.** Flagged rather than hidden.

## Decision 4 — Ownership, limits and lifetime

**Owned by the party**, or by the player when they have none. `Plan.md`'s
definition of done says instances are "scoped to their team", and sharing a live
target is exactly the kind of division of labour a party is for. It does not
affect scoring: solves stay personal (spec 002), so a shared instance changes
who does the work, not who gets the points.

| Limit | Default | Reasoning |
| ----- | ------- | --------- |
| Concurrent instances per owner | 2 | Enough to work two challenges; not enough for one party to fill a node |
| Instances per event (namespace quota) | 40 pods | The platform session sets the real number against actual node capacity |
| Default TTL | 60 minutes | Long enough to work a challenge, short enough that abandoned ones clear |
| TTL extension | +30 min, while under the cap | A player still working should not lose their target |
| CPU / memory per instance | 250m / 256Mi, template-overridable | Fits ~40 instances on a modest node |

When capacity runs out the player gets a clear "no capacity right now, try in a
few minutes", not a stack trace and not a silent failure.

## Decision 5 — Reconciliation

Two loops, because there are two ways to leak:

- **Expiry**: instances past `expires_at` are deleted. Runs every 30 seconds.
- **Orphans**: pods in `ctf-instances` with no matching live database row, and
  database rows with no matching pod, are reconciled every 5 minutes. A pod that
  outlives its row is the dangerous direction — it is an unowned container
  running on the node.

Both run under a **Postgres advisory lock**, so several backend replicas do not
fight over the same instance. Same mechanism as the migration lock.

Instances are also destroyed when their owner party disbands, when the event
ends, and on admin demand from the console.

## Decision 6 — Per-instance answers

Spec 003 reserved a `dynamic` match type and `challenge.container_template_id`
for exactly this.

Each instance gets a **generated answer** injected as an environment variable
the image bakes into its target. The answer rule of type `instance` compares a
submission against *that player's own instance's* value.

This closes the sharing hole that live targets otherwise open: one player cannot
pass another the answer, because the answer is different for every instance. It
also means the anti-cheat signal in spec 007 for identical wrong strings keeps
working, while the correct string is necessarily unique per instance.

---

## Data model that spec 009 will build

### `container_template`

`name`, `image`, `image_tag`, `container_port`, `protocol` (`http` | `tcp`),
`cpu_request`/`cpu_limit`, `memory_request`/`memory_limit`, `ttl_seconds`,
`env` (jsonb, non-secret only), `egress_policy` (`none` | `dns` | `cidr`),
`egress_cidrs`, `injects_answer` (bool), `readiness_path`,
`runtime_class` (default `gvisor`; the sandbox opt-out is setting this to the
host runtime, which is visible in review rather than silent).

`challenge.container_template_id` already exists and is currently unused.

### `challenge_instance`

`challenge_id`, `template_id`, `owner_team_id` / `owner_user_id` (exactly one,
`CHECK`-enforced, mirroring `score_adjustment` from spec 006), `k8s_name`,
`status` (`pending` | `running` | `failed` | `expired` | `destroyed`),
`connection_url`, `node_port`, `generated_answer`, `expires_at`, `destroyed_at`,
`last_error`.

## API surface for spec 009

| Method | Path | Gate | Notes |
| ------ | ---- | ---- | ----- |
| POST | `/api/challenges/{id}/instance` | play | Deploy. Enforces the per-owner cap |
| GET | `/api/challenges/{id}/instance` | play | Status and connection details |
| DELETE | `/api/challenges/{id}/instance` | play | Destroy early |
| POST | `/api/challenges/{id}/instance/extend` | play | Extend the TTL |
| GET | `/api/instances/authorise` | — | The ingress `auth-url` check. Returns 200 or 401 and nothing else |
| GET | `/api/admin/instances` | staff | Everything running, with owners and ages |
| DELETE | `/api/admin/instances/{id}` | admin | Force-teardown, audit-logged |

The admin list also fills the container panel that spec 006's dashboard left as
an honest placeholder.

---

## What the platform session must provide

Everything here is a one-time setup; nothing is needed per instance.

1. Namespace **`ctf-instances`**, with a `ResourceQuota` and a `LimitRange`.
2. A **`Role` + `RoleBinding`** in that namespace for the backend's
   ServiceAccount, allowing `create`/`delete`/`get`/`list`/`watch` on `pods`,
   `services`, `networkpolicies` and `ingresses`. **Namespaced only** — nothing
   cluster-scoped, and no access to `secrets` or `configmaps`.
3. The **`ghcr-pull`** image-pull secret copied into `ctf-instances`.
4. **Wildcard DNS** for `*.ctf-nm.org`, and the wildcard cert usable from that
   namespace (a copy of `ctf-tls`, or a separate `Certificate`).
5. Confirmation on the three questions below.

## Questions for the platform session

1. ~~**Is NetworkPolicy enforcement enabled on this k3s?**~~ **Resolved
   (2026-09-07): yes, enabled and verified** — `ctf-instances` cannot reach
   `postgres.ctf`. The load-bearing control is real.
2. ~~**Is a sandboxed `RuntimeClass` available?**~~ **Resolved: yes, gVisor is
   installed.** Instances run under it (Decision 2). Spec 009 needs the exact
   `RuntimeClass` name to put in `runtimeClassName`.
3. **Does the ingress controller allow per-instance Ingress objects in a second
   namespace**, and can `*.ctf-nm.org` resolve? Still open. If not, HTTP
   instances fall back to NodePort with the authorisation caveat above. Spec 009
   is written to work either way, but the answer decides which path is the
   default.
4. **What is the real node capacity?** Still open. The 40-pod quota and
   250m/256Mi limits stay placeholders until someone who can see the node picks
   numbers; they live in config, so this is not a code change when it lands.

Items 1–4 of *What the platform session must provide* (the `ctf-instances`
namespace with quota/limits, the namespaced `Role`, the `ghcr-pull` copy, and
wildcard DNS/cert) still need confirmation that they are provisioned. Spec 009
can be built and unit-tested against a fake Kubernetes client without them, but
a live instance cannot launch until they exist.

## Open questions for the project

1. **Accept the raw-TCP exposure limitation?** Recommended: yes, prefer HTTP
   challenges, and state it in the brief for any TCP challenge. Unchanged by the
   unblocking — NetworkPolicy and gVisor protect the node, but neither puts a
   session cookie into a raw TCP connection.
2. ~~**Should container-backed challenges run at all** if there is no policy
   enforcement and no sandbox?~~ **Resolved: yes.** Both came back favourable,
   and the project owner has accepted the residual single-node risk explicitly.

## Non-goals

- Multi-node scheduling, autoscaling, or per-party namespaces.
- Player-supplied images, ever.
- A TCP authentication gateway. Named as the fix for the NodePort limitation, and
  deliberately out of scope for Phase 1.
