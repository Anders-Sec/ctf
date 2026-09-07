"""The narrow interface between the app and the cluster.

Everything the app needs from Kubernetes goes through this handful of methods, so
the real client (spec 009 commit 3) and the in-memory fake (used by every test)
are interchangeable. The rest of spec 009 — the launcher, the cap, the
reconciler — is written against this interface and never imports a Kubernetes
library, which is what keeps CI off a cluster.
"""

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from app.services.instances.manifests import InstanceSpec


@dataclass(frozen=True)
class LaunchResult:
    #: True once the pod passes its readiness probe. Launch returns it False;
    #: the poll loop calls `status` until it flips.
    ready: bool
    #: For a NodePort exposure; None for the ingress path.
    node_port: int | None = None
    error: str | None = None


@dataclass(frozen=True)
class RuntimeState:
    exists: bool
    ready: bool
    #: A short reason when a pod is wedged (ImagePullBackOff, CrashLoopBackOff),
    #: surfaced to the player as a failure rather than an endless "pending".
    phase: str | None = None
    node_port: int | None = None
    error: str | None = None


@runtime_checkable
class InstanceOrchestrator(Protocol):
    async def ensure_default_deny(self, namespace: str) -> None:
        """Assert the standing default-deny policy. Idempotent; safe every startup."""
        ...

    async def launch(
        self,
        spec: InstanceSpec,
        *,
        expose_ingress: bool,
        host: str | None,
        authorise_url: str | None,
    ) -> LaunchResult:
        """Create the pod, service, per-instance policy and (if HTTP-ingress) the
        Ingress. Returns promptly; readiness is polled via `status`."""
        ...

    async def status(self, namespace: str, name: str) -> RuntimeState:
        """Where this instance's pod is right now."""
        ...

    async def destroy(self, namespace: str, name: str) -> None:
        """Delete every object for this instance. Idempotent: a missing object is
        success, because the goal state is 'gone'."""
        ...

    async def list_managed_pods(self, namespace: str) -> list[str]:
        """Instance names of every managed pod, for orphan reconciliation."""
        ...
