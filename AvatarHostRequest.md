# Cluster request — avatar generation host (app spec 074)

From the app session to the platform session. One-time, small: **a second port
on the `ai` Service and its Endpoints.** Nothing per-player, no new namespace, no
RBAC.

The app code is built, tested and merged with the feature **inert** — with no
reachable host the backend reports it unavailable and the UI does not offer it,
while the rest of the avatar system (procedural crests, class and loot
accessories, the fit editor) works with no GPU at all.

## What it is, in one paragraph

Spec 074 lets a player have a character portrait painted from a fixed set of
authored traits — ancestry, class, clothing and so on. The prompt is assembled
server-side from those keys; players never type text. The backend sends that
prompt to a small HTTP service (`tools/avatar-service` in the app repo) running
**on the same box as LM Studio**, which returns a PNG. That is the whole
interaction: `POST /generate` in, `image/png` out.

## What we need

`ai.ctf.svc.cluster.local` already resolves to that host for the model on 1235.
The avatar service listens on **8188** on the same machine, so the smallest
change is a second named port on the same Service and Endpoints:

```yaml
apiVersion: v1
kind: Service
metadata:
  name: ai
  namespace: ctf
spec:
  ports:
    - { name: model, port: 1235, targetPort: 1235 }   # existing
    - { name: image, port: 8188, targetPort: 8188 }   # new
---
apiVersion: v1
kind: Endpoints
metadata:
  name: ai
  namespace: ctf
subsets:
  - addresses:
      - { ip: <the host, as you already have it> }
    ports:
      - { name: model, port: 1235 }                   # existing
      - { name: image, port: 8188 }                   # new
```

A separate `avatar` Service/Endpoints is equally fine if you would rather keep
them independently disableable — say which and we will point `IMAGE_BASE_URL` at
it instead. **The address itself stays on your side either way**; the app repo
only ever names the in-cluster alias.

### Egress

If the namespace policy restricts egress by port rather than by destination,
8188 to that host needs the same allowance 1235 has. If it is destination-based,
nothing to do.

## What we have already done

`deploy/backend.yaml` carries the config, pointed at the alias above:

```yaml
- { name: IMAGE_BASE_URL, value: "http://ai.ctf.svc.cluster.local:8188" }
- { name: IMAGE_ENABLED,  value: "true" }
- name: IMAGE_API_KEY          # optional, only if the service is keyed
  valueFrom:
    secretKeyRef: { name: ctf-secrets, key: image-api-key, optional: true }
```

No `/v1` suffix — unlike the model host, this service's contract is a bare
`POST /generate`.

## How to tell it worked

From a backend pod:

```
curl -s http://ai.ctf.svc.cluster.local:8188/health
```

Expect `{"ok": true, "model": "stabilityai/sdxl-turbo", "gpu": {...}}` with
`gpu.usable` **true**. If `usable` is false the service says why in `gpu.why` —
that is a host-side problem (wrong CUDA build for the card), not a cluster one,
and `tools/avatar-service/README.md` covers it.

In the app: Settings → Your likeness → a **"Have one painted"** panel appears
below the accessory editor. Its absence is the feature correctly hiding itself,
not an error.

## What we are not asking for

- No GPU in the cluster. The card stays on your box; the cluster only needs to
  reach a port on it.
- No ingress, no public exposure. Backend pods only.
- No secret unless the service is keyed, and then only `image-api-key` in the
  existing `ctf-secrets`.

## Scale

One GPU. The app caps itself at **one generation in flight** and three portraits
per player (more from loot drops), so this is a handful of requests a minute at
worst, not a sustained load. There is no queue yet — a second simultaneous
request is refused rather than queued — so the ceiling is self-limiting.
