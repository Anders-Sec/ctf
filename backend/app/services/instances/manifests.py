"""Building the Kubernetes objects for one instance.

Pure functions from a spec to plain dicts, for one reason above all: the
isolation guarantees in spec 008 are only as real as the fields on these
objects, and a pure builder can be **tested as data** — every hardening control
asserted on the produced manifest, so a regression that drops one fails a test
rather than shipping a live un-sandboxed container.

Nothing here talks to a cluster. The orchestrator applies what these return.
"""

from dataclasses import dataclass, field

from app.models.instance import EgressPolicy

#: Labels every object carries, so the reconciler and NetworkPolicies can select
#: an instance's objects without guessing at names.
LABEL_INSTANCE = "ctf/instance"
LABEL_OWNER_KIND = "ctf/owner-kind"
LABEL_OWNER_ID = "ctf/owner-id"
LABEL_MANAGED = "ctf/managed"

#: The standing baseline policy's name. Created once; selects every pod.
DEFAULT_DENY_NAME = "ctf-default-deny-all"


@dataclass
class InstanceSpec:
    """Everything the builders need for one instance. Assembled by the launcher."""

    name: str
    namespace: str
    image: str
    container_port: int
    owner_kind: str  # "user" | "team"
    owner_id: str
    env: dict[str, str] = field(default_factory=dict)
    cpu_request: str = "100m"
    cpu_limit: str = "250m"
    memory_request: str = "128Mi"
    memory_limit: str = "256Mi"
    runtime_class: str | None = "gvisor"
    egress_policy: EgressPolicy = EgressPolicy.NONE
    egress_cidrs: list[str] = field(default_factory=list)
    readiness_path: str = "/"
    image_pull_secret: str = "ghcr-pull"
    #: The namespace the ingress controller runs in, so ingress traffic can be
    #: allowed from it and nowhere else.
    ingress_namespace: str = "ingress-nginx"
    #: The wildcard-cert secret in this namespace, so the per-instance Ingress
    #: terminates TLS for <name>.ctf-nm.org. cert-manager keeps it renewed.
    tls_secret: str = "ctf-tls"


def _labels(spec: InstanceSpec) -> dict[str, str]:
    return {
        LABEL_MANAGED: "true",
        LABEL_INSTANCE: spec.name,
        LABEL_OWNER_KIND: spec.owner_kind,
        LABEL_OWNER_ID: spec.owner_id,
    }


def pod_manifest(spec: InstanceSpec) -> dict:
    """The pod, with every hardening control from spec 008 Decision 2.

    If you are editing this, the rule is: nothing here loosens without a matching
    change to the spec and its test. These fields are the isolation.
    """
    container: dict = {
        "name": "challenge",
        "image": spec.image,
        "ports": [{"containerPort": spec.container_port}],
        "env": [{"name": key, "value": value} for key, value in spec.env.items()],
        "resources": {
            "requests": {"cpu": spec.cpu_request, "memory": spec.memory_request},
            "limits": {"cpu": spec.cpu_limit, "memory": spec.memory_limit},
        },
        "securityContext": {
            "runAsNonRoot": True,
            "allowPrivilegeEscalation": False,
            "readOnlyRootFilesystem": True,
            "capabilities": {"drop": ["ALL"]},
            "seccompProfile": {"type": "RuntimeDefault"},
        },
        # Anything the image needs to write goes to memory it cannot use to
        # persist across a restart, and never to the host.
        "volumeMounts": [{"name": "scratch", "mountPath": "/tmp"}],
        "readinessProbe": {
            "httpGet": {"path": spec.readiness_path, "port": spec.container_port},
            "periodSeconds": 3,
            "failureThreshold": 20,
        },
    }

    pod_spec: dict = {
        "automountServiceAccountToken": False,
        "enableServiceLinks": False,
        "restartPolicy": "Always",
        "containers": [container],
        "volumes": [{"name": "scratch", "emptyDir": {}}],
        "imagePullSecrets": [{"name": spec.image_pull_secret}],
        "securityContext": {"runAsNonRoot": True, "seccompProfile": {"type": "RuntimeDefault"}},
    }
    # The sandbox. Omitted only when explicitly set to the host runtime, which is
    # the visible per-template opt-out, never a silent default.
    if spec.runtime_class:
        pod_spec["runtimeClassName"] = spec.runtime_class

    return {
        "apiVersion": "v1",
        "kind": "Pod",
        "metadata": {"name": spec.name, "namespace": spec.namespace, "labels": _labels(spec)},
        "spec": pod_spec,
    }


def service_manifest(spec: InstanceSpec) -> dict:
    return {
        "apiVersion": "v1",
        "kind": "Service",
        "metadata": {"name": spec.name, "namespace": spec.namespace, "labels": _labels(spec)},
        "spec": {
            "selector": {LABEL_INSTANCE: spec.name},
            "ports": [{"port": 80, "targetPort": spec.container_port}],
        },
    }


def network_policy_manifest(spec: InstanceSpec) -> dict:
    """Per-instance allowances on top of the standing default-deny.

    Ingress: only from the ingress controller's namespace — players reach an
    instance through the edge, never pod-to-pod. Egress: DNS always (or nothing
    starts), and nothing else unless the template opts into it, which is recorded
    and visible. Critically absent from egress: the cluster's own services, so an
    instance can never reach postgres.ctf and its plaintext answers.
    """
    egress: list[dict] = [_dns_egress()]
    if spec.egress_policy == EgressPolicy.CIDR and spec.egress_cidrs:
        egress.append({"to": [{"ipBlock": {"cidr": cidr}} for cidr in spec.egress_cidrs]})

    return {
        "apiVersion": "networking.k8s.io/v1",
        "kind": "NetworkPolicy",
        "metadata": {"name": spec.name, "namespace": spec.namespace, "labels": _labels(spec)},
        "spec": {
            "podSelector": {"matchLabels": {LABEL_INSTANCE: spec.name}},
            "policyTypes": ["Ingress", "Egress"],
            "ingress": [
                {
                    "from": [
                        {
                            "namespaceSelector": {
                                "matchLabels": {
                                    "kubernetes.io/metadata.name": spec.ingress_namespace
                                }
                            }
                        }
                    ]
                }
            ],
            "egress": egress,
        },
    }


def _dns_egress() -> dict:
    """UDP/TCP 53 to kube-dns. Without it most images fail to resolve and die."""
    return {
        "to": [
            {"namespaceSelector": {"matchLabels": {"kubernetes.io/metadata.name": "kube-system"}}}
        ],
        "ports": [{"protocol": "UDP", "port": 53}, {"protocol": "TCP", "port": 53}],
    }


def default_deny_manifest(namespace: str) -> dict:
    """The namespace baseline: selects every pod, allows nothing.

    A pod is isolated the instant it exists, before the launcher creates its
    per-instance policy — so there is no window in which a pod is
    reachable-but-unpolicied. This is the load-bearing object in spec 009.
    """
    return {
        "apiVersion": "networking.k8s.io/v1",
        "kind": "NetworkPolicy",
        "metadata": {
            "name": DEFAULT_DENY_NAME,
            "namespace": namespace,
            "labels": {LABEL_MANAGED: "true"},
        },
        "spec": {"podSelector": {}, "policyTypes": ["Ingress", "Egress"]},
    }


def ingress_manifest(spec: InstanceSpec, host: str, authorise_url: str) -> dict:
    """The authorised subdomain. auth-url makes ownership an edge check, so the
    subdomain never has to be secret.

    The instance name is baked into the auth-url path (``.../authorise/<name>``)
    rather than passed via an ``auth-snippet`` header — snippet annotations are
    commonly disabled on ingress-nginx for CVE reasons, and a per-instance Ingress
    already has a per-instance auth-url to carry it. ``auth-url`` itself is a
    first-class annotation and always allowed.
    """
    return {
        "apiVersion": "networking.k8s.io/v1",
        "kind": "Ingress",
        "metadata": {
            "name": spec.name,
            "namespace": spec.namespace,
            "labels": _labels(spec),
            "annotations": {
                "nginx.ingress.kubernetes.io/auth-url": f"{authorise_url.rstrip('/')}/{spec.name}",
            },
        },
        "spec": {
            "ingressClassName": "nginx",
            "tls": [{"hosts": [host], "secretName": spec.tls_secret}],
            "rules": [
                {
                    "host": host,
                    "http": {
                        "paths": [
                            {
                                "path": "/",
                                "pathType": "Prefix",
                                "backend": {"service": {"name": spec.name, "port": {"number": 80}}},
                            }
                        ]
                    },
                }
            ],
        },
    }
