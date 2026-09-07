"""The real Kubernetes orchestrator.

Thin glue behind the `InstanceOrchestrator` interface — the launcher, cap and
reconciler never see this file, and it never runs in CI (there is no cluster).
Its whole job is to apply the dicts `manifests.py` produces and report a pod's
readiness back. Every create/delete is idempotent, because the reconciler relies
on "already exists" and "already gone" both meaning success.
"""

from kubernetes_asyncio import client, config
from kubernetes_asyncio.client.exceptions import ApiException

from app.logging import get_logger
from app.services.instances import manifests
from app.services.instances.manifests import (
    LABEL_MANAGED,
    InstanceSpec,
    default_deny_manifest,
    ingress_manifest,
    network_policy_manifest,
    pod_manifest,
    service_manifest,
)
from app.services.instances.orchestrator import LaunchResult, RuntimeState

logger = get_logger(__name__)


class KubeOrchestrator:
    """Talks to the API server with the pod's mounted ServiceAccount.

    In-cluster config only: no kubeconfig or token is ever read from this repo or
    its settings, the same rule the AI address follows.
    """

    def __init__(self) -> None:
        self._loaded = False

    async def _load(self) -> None:
        if not self._loaded:
            config.load_incluster_config()
            self._loaded = True

    async def ensure_default_deny(self, namespace: str) -> None:
        await self._load()
        async with client.ApiClient() as api:
            net = client.NetworkingV1Api(api)
            body = default_deny_manifest(namespace)
            try:
                await net.create_namespaced_network_policy(namespace, body)
            except ApiException as exc:
                if exc.status != 409:  # already there is the goal
                    raise
            logger.info("instance_default_deny_ensured", extra={"namespace": namespace})

    async def launch(
        self,
        spec: InstanceSpec,
        *,
        expose_ingress: bool,
        host: str | None,
        authorise_url: str | None,
    ) -> LaunchResult:
        await self._load()
        async with client.ApiClient() as api:
            core = client.CoreV1Api(api)
            net = client.NetworkingV1Api(api)

            # Policy first is belt to the namespace default-deny's braces: even
            # before the pod exists it is covered, and this closes any theoretical
            # gap if the standing policy were ever missing.
            await _create(
                net.create_namespaced_network_policy(spec.namespace, network_policy_manifest(spec))
            )
            await _create(core.create_namespaced_pod(spec.namespace, pod_manifest(spec)))
            node_port = None
            if expose_ingress and host and authorise_url:
                await _create(
                    core.create_namespaced_service(spec.namespace, service_manifest(spec))
                )
                await _create(
                    client.NetworkingV1Api(api).create_namespaced_ingress(
                        spec.namespace, ingress_manifest(spec, host, authorise_url)
                    )
                )
            else:
                svc = service_manifest(spec)
                svc["spec"]["type"] = "NodePort"
                created = await core.create_namespaced_service(spec.namespace, svc)
                node_port = created.spec.ports[0].node_port

        return LaunchResult(ready=False, node_port=node_port)

    async def status(self, namespace: str, name: str) -> RuntimeState:
        await self._load()
        async with client.ApiClient() as api:
            core = client.CoreV1Api(api)
            try:
                pod = await core.read_namespaced_pod(name, namespace)
            except ApiException as exc:
                if exc.status == 404:
                    return RuntimeState(exists=False, ready=False)
                raise
        phase = pod.status.phase if pod.status else None
        ready = _pod_ready(pod)
        error = _pod_error(pod)
        return RuntimeState(exists=True, ready=ready, phase=phase, error=error)

    async def destroy(self, namespace: str, name: str) -> None:
        await self._load()
        async with client.ApiClient() as api:
            core = client.CoreV1Api(api)
            net = client.NetworkingV1Api(api)
            await _delete(net.delete_namespaced_network_policy(name, namespace))
            await _delete(net.delete_namespaced_ingress(name, namespace))
            await _delete(core.delete_namespaced_service(name, namespace))
            await _delete(core.delete_namespaced_pod(name, namespace))

    async def list_managed_pods(self, namespace: str) -> list[str]:
        await self._load()
        async with client.ApiClient() as api:
            core = client.CoreV1Api(api)
            pods = await core.list_namespaced_pod(namespace, label_selector=f"{LABEL_MANAGED}=true")
        return [
            pod.metadata.labels.get(manifests.LABEL_INSTANCE, pod.metadata.name)
            for pod in pods.items
        ]


async def _create(awaitable: object) -> None:
    """Await a create, swallowing 409 (already exists) as success."""
    try:
        await awaitable  # type: ignore[misc]
    except ApiException as exc:
        if exc.status != 409:
            raise


async def _delete(awaitable: object) -> None:
    """Await a delete, swallowing 404 (already gone) as success."""
    try:
        await awaitable  # type: ignore[misc]
    except ApiException as exc:
        if exc.status != 404:
            raise


def _pod_ready(pod: object) -> bool:
    status = getattr(pod, "status", None)
    conditions = getattr(status, "conditions", None) or []
    return any(c.type == "Ready" and c.status == "True" for c in conditions)


def _pod_error(pod: object) -> str | None:
    """A short waiting reason (ImagePullBackOff, CrashLoopBackOff) if wedged."""
    status = getattr(pod, "status", None)
    for container in getattr(status, "container_statuses", None) or []:
        waiting = getattr(container.state, "waiting", None)
        if waiting and waiting.reason in ("ImagePullBackOff", "ErrImagePull", "CrashLoopBackOff"):
            return waiting.reason
    return None
