"""An in-memory orchestrator for tests.

It records the manifests it would have applied (so tests can assert the hardening
on real produced objects) and lets a test drive readiness and failure by hand,
the way `ai_client`'s mock transport drives the model. No cluster, ever.
"""

from dataclasses import dataclass

from app.services.instances.manifests import (
    InstanceSpec,
    ingress_manifest,
    network_policy_manifest,
    pod_manifest,
    service_manifest,
)
from app.services.instances.orchestrator import LaunchResult, RuntimeState


@dataclass
class _FakePod:
    spec: InstanceSpec
    manifests: dict
    ready: bool = False
    phase: str = "Pending"
    node_port: int | None = None
    error: str | None = None


class FakeOrchestrator:
    """Implements `InstanceOrchestrator` in a dict.

    Defaults to instances that become ready immediately, which is what most tests
    want; `auto_ready=False` plus `mark_ready`/`mark_failed` drive the pending →
    running/failed transitions for the poll-loop tests.
    """

    def __init__(self, *, auto_ready: bool = True) -> None:
        self.auto_ready = auto_ready
        self.pods: dict[str, _FakePod] = {}
        self.default_deny_namespaces: set[str] = set()
        self.destroyed: list[str] = []

    async def ensure_default_deny(self, namespace: str) -> None:
        self.default_deny_namespaces.add(namespace)

    async def launch(
        self,
        spec: InstanceSpec,
        *,
        expose_ingress: bool,
        host: str | None,
        authorise_url: str | None,
    ) -> LaunchResult:
        manifests = {
            "pod": pod_manifest(spec),
            "service": service_manifest(spec),
            "network_policy": network_policy_manifest(spec),
        }
        if expose_ingress and host and authorise_url:
            manifests["ingress"] = ingress_manifest(spec, host, authorise_url)

        node_port = None if expose_ingress else 31000 + len(self.pods)
        self.pods[spec.name] = _FakePod(
            spec=spec,
            manifests=manifests,
            ready=self.auto_ready,
            phase="Running" if self.auto_ready else "Pending",
            node_port=node_port,
        )
        return LaunchResult(ready=self.auto_ready, node_port=node_port)

    async def status(self, namespace: str, name: str) -> RuntimeState:
        pod = self.pods.get(name)
        if pod is None:
            return RuntimeState(exists=False, ready=False)
        return RuntimeState(
            exists=True,
            ready=pod.ready,
            phase=pod.phase,
            node_port=pod.node_port,
            error=pod.error,
        )

    async def destroy(self, namespace: str, name: str) -> None:
        # Idempotent, like the real one: gone is the goal, not an error.
        self.pods.pop(name, None)
        self.destroyed.append(name)

    async def list_managed_pods(self, namespace: str) -> list[str]:
        return list(self.pods)

    # --- test controls -------------------------------------------------------

    def mark_ready(self, name: str) -> None:
        pod = self.pods[name]
        pod.ready = True
        pod.phase = "Running"

    def mark_failed(self, name: str, error: str = "CrashLoopBackOff") -> None:
        pod = self.pods[name]
        pod.ready = False
        pod.phase = error
        pod.error = error

    def orphan_pod(self, spec: InstanceSpec) -> None:
        """A pod with no database row — the dangerous leak the reconciler catches."""
        self.pods[spec.name] = _FakePod(spec=spec, manifests={}, ready=True, phase="Running")
