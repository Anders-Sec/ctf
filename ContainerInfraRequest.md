# Cluster request — live challenge containers (app spec 009)

From the app session to the platform session. Everything below is one-time setup
for `ctf-instances`; nothing is needed per instance. The app code is built,
tested and merged, with the feature **switched off** (`INSTANCES_ENABLED=false`)
until this is in place. Thanks for the wildcard DNS and the capacity numbers —
those settled the two open design questions, so this is HTTP-subdomain only.

## What the app does, in one paragraph

For a container-backed challenge, the backend creates — in `ctf-instances`, using
its own ServiceAccount — a **Pod**, a **Service**, a per-instance
**NetworkPolicy**, and an **Ingress** at `<name>.ctf-nm.org`. It polls the pod to
readiness, hands the player the subdomain, and tears everything down on a TTL or
on demand. A reconciler garbage-collects expired and orphaned objects. The whole
Kubernetes surface is namespaced; the app never touches anything cluster-scoped
at runtime.

## What we need from you

### 1. Namespace `ctf-instances` with quota and limits

Suggested starting numbers, sized against the 32 GB / 16-core node you reported
(app + infra sitting at ~4 % / <1 %). These are deliberately generous; tune to
taste — they live behind the quota, and the app also caps **2 concurrent
instances per player/party** on its side.

```yaml
apiVersion: v1
kind: ResourceQuota
metadata: { name: ctf-instances-quota, namespace: ctf-instances }
spec:
  hard:
    pods: "80"
    requests.cpu: "8"
    requests.memory: 20Gi
    limits.cpu: "16"
    limits.memory: 24Gi
---
apiVersion: v1
kind: LimitRange
metadata: { name: ctf-instances-limits, namespace: ctf-instances }
spec:
  limits:
    - type: Container
      default: { cpu: 250m, memory: 256Mi }
      defaultRequest: { cpu: 100m, memory: 128Mi }
      max: { cpu: "1", memory: 1Gi }
```

Per-instance defaults in the app are 100m/128Mi requested, 250m/256Mi limit, so
80 pods is ~10 GB / 8 cores of requests — comfortable headroom. Give us whatever
`pods` ceiling you're happy with; the app degrades gracefully to "no capacity,
try again" when the quota is hit.

### 2. A namespaced Role + RoleBinding for our ServiceAccount

The backend now runs as **`system:serviceaccount:ctf:ctf-backend`** (the SA is
created by our `deploy/backend.yaml`). It needs, in `ctf-instances` only:

```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata: { name: ctf-instance-manager, namespace: ctf-instances }
rules:
  - apiGroups: [""]
    resources: [pods, services]
    verbs: [get, list, watch, create, delete]
  - apiGroups: ["networking.k8s.io"]
    resources: [networkpolicies, ingresses]
    verbs: [get, list, watch, create, delete]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata: { name: ctf-instance-manager, namespace: ctf-instances }
roleRef: { apiGroup: rbac.authorization.k8s.io, kind: Role, name: ctf-instance-manager }
subjects:
  - kind: ServiceAccount
    name: ctf-backend
    namespace: ctf
```

**Namespaced only** — no cluster-scoped rights, and deliberately **no** access to
`secrets` or `configmaps`. If you'd rather split `create`/`delete` from the read
verbs, or scope it tighter, that's fine; those four resource types with those
verbs are the whole requirement.

### 3. `ghcr-pull` copied into `ctf-instances`

For pulling the challenge images. Same secret you already put in `ctf`.

### 4. TLS for `*.ctf-nm.org`, usable from `ctf-instances`

The per-instance Ingress terminates TLS on the subdomain. We need the wildcard
cert available as a secret **in `ctf-instances`** — a copy of `ctf-tls`, or a
`Certificate` that issues one there. Tell us the secret name and we'll reference
it (default assumption: `ctf-tls`).

### 5. The standing default-deny NetworkPolicy

The load-bearing isolation object: it selects every pod in `ctf-instances` and
allows nothing, so a pod is isolated the instant it exists, before our per-instance
policy is applied. **Our Role above can create it, and the app asserts it at
startup idempotently** — so you don't have to ship it. But if you'd rather own it,
say so and we'll stop asserting it, to avoid both of us writing it. Either is fine;
just let's not have neither.

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata: { name: ctf-default-deny-all, namespace: ctf-instances }
spec:
  podSelector: {}
  policyTypes: [Ingress, Egress]
```

## Five questions

1. **What is the exact `RuntimeClass` name for gVisor?** We default to `gvisor`
   (handler `runsc`); if you named it differently, tell us and we set one env
   value. A wrong name fails the pod at scheduling, so this is the one that will
   bite first.
2. **What namespace is ingress-nginx in, and does it watch `ctf-instances`?** Our
   per-instance NetworkPolicy allows ingress **only** from the controller's
   namespace, selected by `kubernetes.io/metadata.name`. We've assumed
   `ingress-nginx`. If the controller is elsewhere (e.g. `kube-system`), we
   change the selector. Also confirm the controller picks up `Ingress` objects
   created in `ctf-instances` (it watches all namespaces unless scoped).
3. **Is CoreDNS in `kube-system`?** Our only default egress allowance is DNS to
   `kube-system` on port 53. If DNS lives elsewhere, instances won't resolve and
   most images won't start.
4. **Are ingress-nginx snippet annotations needed for anything on your side?** We
   deliberately **do not** use `auth-snippet`/`configuration-snippet` (the
   instance name rides in the `auth-url` path instead), so you can leave
   `allow-snippet-annotations` off. Flagging only so nobody enables it on our
   account.
5. **Anything you want changed about the per-instance objects?** Shapes are in
   `backend/app/services/instances/manifests.py` and the isolation rationale is in
   `specs/008-container-isolation-design.md`. The pods are non-root, all-caps-
   dropped, read-only-root, no service-account token, gvisor by default.

## Our side, for reference (already done / on go-live)

- **Done:** all objects created via the namespaced SA; the `authorise` endpoint
  at `GET /api/instances/authorise/<name>` that the Ingress `auth-url` calls to
  check session ownership at the edge; the reconciler; a trivial demo image under
  `deploy/instances/demo/` (needs building/pushing to
  `ghcr.io/anders-sec/ctf-demo:v1` — that's on our CI).
- **On go-live**, once the above is confirmed, we flip two env values together in
  `deploy/backend.yaml`: `INSTANCES_ENABLED=true` and `COOKIE_DOMAIN=ctf-nm.org`.
  The cookie widening is required so the ingress `auth-url` subrequest receives
  the player's session cookie on the instance subdomain. We rely on the ownership
  check — only an instance's owner can reach it — so a challenge container only
  ever sees its own owner's cookie, which is not an escalation; still, the
  subdomain is untrusted content, so if you can strip the `Cookie` header at the
  instance ingress on your side as defence-in-depth, we'd take it. Not a blocker.

## Not needed

No wildcard-DNS work (done), no raw-TCP/NodePort (we dropped it — every instance
is authorised at the edge), no per-team namespaces, no cluster-scoped anything.
