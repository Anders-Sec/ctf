"""The isolation guarantees, asserted as data (spec 009).

Spec 008's hardening is only as real as the fields on the pod. This test is the
thing that makes a dropped control fail CI instead of shipping a live
un-sandboxed container next to the database that holds every answer. Read it as
the machine-checked half of spec 008 Decision 2.
"""

from app.models.instance import EgressPolicy
from app.services.instances import manifests
from app.services.instances.manifests import InstanceSpec


def _spec(**over: object) -> InstanceSpec:
    base = dict(
        name="dm-abc123",
        namespace="ctf-instances",
        image="ghcr.io/anders-sec/ctf-demo:v1",
        container_port=8080,
        owner_kind="team",
        owner_id="team-1",
    )
    base.update(over)
    return InstanceSpec(**base)  # type: ignore[arg-type]


class TestPodHardening:
    def test_every_isolation_control_is_present(self) -> None:
        pod = manifests.pod_manifest(_spec())
        container = pod["spec"]["containers"][0]
        sc = container["securityContext"]

        assert sc["runAsNonRoot"] is True
        assert sc["allowPrivilegeEscalation"] is False
        assert sc["readOnlyRootFilesystem"] is True
        assert sc["capabilities"]["drop"] == ["ALL"]
        assert sc["seccompProfile"]["type"] == "RuntimeDefault"

    def test_the_service_account_token_is_not_mounted(self) -> None:
        """Otherwise a compromised container gets an API token and every other
        control becomes decoration."""
        pod = manifests.pod_manifest(_spec())
        assert pod["spec"]["automountServiceAccountToken"] is False

    def test_it_runs_under_the_sandbox_by_default(self) -> None:
        pod = manifests.pod_manifest(_spec())
        assert pod["spec"]["runtimeClassName"] == "gvisor"

    def test_the_sandbox_opt_out_is_explicit_not_silent(self) -> None:
        """A None runtime_class is the deliberate host-runtime opt-out; nothing
        else can produce a pod without runtimeClassName."""
        pod = manifests.pod_manifest(_spec(runtime_class=None))
        assert "runtimeClassName" not in pod["spec"]

    def test_resource_limits_are_set(self) -> None:
        pod = manifests.pod_manifest(_spec(cpu_limit="500m", memory_limit="512Mi"))
        limits = pod["spec"]["containers"][0]["resources"]["limits"]
        assert limits == {"cpu": "500m", "memory": "512Mi"}

    def test_no_host_volumes_only_scratch_memory(self) -> None:
        pod = manifests.pod_manifest(_spec())
        volumes = pod["spec"]["volumes"]
        assert len(volumes) == 1
        assert "emptyDir" in volumes[0]
        assert all("hostPath" not in v for v in volumes)

    def test_the_generated_answer_rides_in_as_env(self) -> None:
        pod = manifests.pod_manifest(_spec(env={"INSTANCE_ANSWER": "flag{unique}"}))
        env = {e["name"]: e["value"] for e in pod["spec"]["containers"][0]["env"]}
        assert env["INSTANCE_ANSWER"] == "flag{unique}"


class TestNetworkPolicy:
    def test_egress_denies_the_cluster_services_by_default(self) -> None:
        """The core guarantee: an instance cannot reach postgres.ctf.

        Egress is DNS only. There is no rule permitting the cluster's own
        services, so the plaintext answers are unreachable.
        """
        policy = manifests.network_policy_manifest(_spec())["spec"]
        assert set(policy["policyTypes"]) == {"Ingress", "Egress"}

        # The only egress rule is DNS to kube-system on port 53.
        assert len(policy["egress"]) == 1
        dns = policy["egress"][0]
        assert dns["ports"] == [
            {"protocol": "UDP", "port": 53},
            {"protocol": "TCP", "port": 53},
        ]

    def test_ingress_is_only_from_the_ingress_controller(self) -> None:
        policy = manifests.network_policy_manifest(_spec())["spec"]
        source = policy["ingress"][0]["from"][0]["namespaceSelector"]["matchLabels"]
        assert source == {"kubernetes.io/metadata.name": "ingress-nginx"}

    def test_a_template_can_open_a_cidr_and_it_is_recorded(self) -> None:
        policy = manifests.network_policy_manifest(
            _spec(egress_policy=EgressPolicy.CIDR, egress_cidrs=["203.0.113.0/24"])
        )["spec"]
        cidrs = [
            peer["ipBlock"]["cidr"]
            for rule in policy["egress"]
            for peer in rule.get("to", [])
            if "ipBlock" in peer
        ]
        assert "203.0.113.0/24" in cidrs

    def test_the_default_deny_selects_every_pod_and_allows_nothing(self) -> None:
        policy = manifests.default_deny_manifest("ctf-instances")["spec"]
        assert policy["podSelector"] == {}
        assert set(policy["policyTypes"]) == {"Ingress", "Egress"}
        assert "ingress" not in policy
        assert "egress" not in policy


class TestIngress:
    def test_it_authorises_at_the_edge(self) -> None:
        ing = manifests.ingress_manifest(
            _spec(), "dm-abc123.ctf-nm.org", "http://ctf-backend/api/instances/authorise"
        )
        ann = ing["metadata"]["annotations"]
        # The instance name is in the auth-url path, so no snippet annotation is
        # needed (those are commonly disabled on ingress-nginx).
        assert ann["nginx.ingress.kubernetes.io/auth-url"].endswith(
            "/api/instances/authorise/dm-abc123"
        )
        assert "auth-snippet" not in " ".join(ann)

    def test_it_routes_the_subdomain_to_the_service(self) -> None:
        ing = manifests.ingress_manifest(_spec(), "dm-abc123.ctf-nm.org", "http://x/authorise")
        rule = ing["spec"]["rules"][0]
        assert rule["host"] == "dm-abc123.ctf-nm.org"
        assert rule["http"]["paths"][0]["backend"]["service"]["name"] == "dm-abc123"

    def test_it_terminates_tls_with_the_wildcard_cert(self) -> None:
        """cert-manager issues ctf-tls in the namespace; the Ingress references it
        so <name>.ctf-nm.org serves the wildcard cert rather than the default."""
        ing = manifests.ingress_manifest(_spec(), "dm-abc123.ctf-nm.org", "http://x/authorise")
        tls = ing["spec"]["tls"][0]
        assert tls["hosts"] == ["dm-abc123.ctf-nm.org"]
        assert tls["secretName"] == "ctf-tls"
