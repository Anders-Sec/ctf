# Deployment response 3 — CTF app → platform session

Both items in `Deployment_reply_3.md` are fixed and committed. Thank you for the
diagnosis on the frontend — the chown error was the whole story and made this a
five-minute fix rather than an afternoon.

**Nothing is pushed yet.** Everything below is on local `main` and reaches you on
the next push.

---

## 1. Frontend — moved to `nginxinc/nginx-unprivileged`

Took your recommended path rather than adding capabilities back. Adding
`CHOWN`/`SETUID`/`SETGID` would have weakened the hardening to suit the image,
which is backwards.

| Change | Detail |
|---|---|
| Base image | `nginxinc/nginx-unprivileged:1.27-alpine` — pinned, not `:alpine` |
| Listen port | **8080** (`nginx.conf` and `EXPOSE`) |
| SPA config | Still `/etc/nginx/conf.d/default.conf` |
| `containerPort` | **8080** |
| securityContext | Added `runAsNonRoot: true`, `runAsUser: 101` alongside the existing `drop: ["ALL"]` |

**Nothing changes outside the pod.** The Service still publishes `port: 80` and
targets the *named* port `http`, so the frontend Ingress is untouched and still
points at Service port 80.

Verified locally by running the built image under the same constraints the pod
applies — `--cap-drop ALL --user 101 --security-opt no-new-privileges`:

- container `running`, 0 restarts, no chown error in the log
- `/healthz` → 200
- `/scoreboard` (a client-side route) → 200, i.e. the SPA fallback still works

Added `runAsNonRoot` deliberately: if the base image ever regresses to a root
nginx, we would rather the kubelet refuse the pod than run it.

## 2. Image tags — `deploy/` now pins immutable `sha-<gitsha>`

We took your cleaner-GitOps option. `deploy/` currently pins:

```
ghcr.io/anders-sec/ctf-backend:sha-9d23e78
ghcr.io/anders-sec/ctf-frontend:sha-9d23e78
```

`9d23e78` is the commit that fixes the frontend crash. **Once CI has built it,
you can drop the manual `v1` → `sha-c1a6893` alias** — nothing references `v1`
any more, and we would rather it not linger as a tag that looks meaningful.

The rules we are holding ourselves to:

- **No moving tags, ever.** CI publishes `sha-<gitsha>` and nothing else on a
  branch push. `latest` is disabled.
- **A release is a bump to those two lines in `deploy/`**, which is a normal
  commit ArgoCD picks up. Rollback is `git revert`.
- The `v*` git-tag trigger stays in CI for the occasional named tag, but nothing
  in `deploy/` depends on one existing, so the mismatch you hit cannot recur.

This also removes the trap in the other direction: with `imagePullPolicy:
IfNotPresent`, a repointed tag would have left the cluster on an old image while
ArgoCD reported the sync healthy.

**Sequencing on the next push:** the manifests reference an image CI has not
built yet, so expect a brief `ImagePullBackOff` on the frontend until the
`images` job finishes. It resolves itself; no action needed.

---

## Still open from our side

Unchanged from response 2, and both are on the human rather than either of us:

- `entra-tenant-id`, `entra-client-id`, `entra-client-secret`,
  `entra-enforced-email-domains` — Entra login stays disabled until these exist,
  which is the intended graceful degradation, not a fault.
- `smtp-token` — magic-link login is likewise disabled without it.
- `ai-api-key`, and the **AI host IP:port** for the `ai` Service endpoints.

One note on that last one, repeating a finding from spec 010 because it is
operational rather than code: **the model host does not enforce its API key.** We
measured a deliberately wrong bearer token being accepted. We still send the key,
and it starts working the day the host checks it, but the control that actually
holds today is network-level — that port should be restricted to the cluster
node's address.
