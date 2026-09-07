"""Choosing an orchestrator.

The real one when instances are configured; a harmless fake otherwise, so the
app boots and the endpoints report "unavailable" rather than importing a cluster
client that has nothing to talk to. Tests replace `app.state.orchestrator`
directly with a fake they control.
"""

from app.config import Settings
from app.services.instances.orchestrator import InstanceOrchestrator


def build_orchestrator(settings: Settings) -> InstanceOrchestrator:
    if settings.instances_configured:
        from app.services.instances.kube import KubeOrchestrator

        return KubeOrchestrator()

    from app.services.instances.fake import FakeOrchestrator

    return FakeOrchestrator()
