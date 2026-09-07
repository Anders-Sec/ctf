"""Reconciliation: expiry and the two-way orphan sweep (spec 009).

The loop itself is just a clock and an advisory lock; the logic under it is these
two pure functions, tested directly against the fake.
"""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.models.instance import InstanceStatus
from app.services.instances import launcher, reconciler
from app.services.instances.fake import FakeOrchestrator
from app.services.instances.manifests import InstanceSpec
from tests.factories import make_container_challenge, make_template, make_user

pytestmark = pytest.mark.anyio


def _settings(settings: Settings) -> Settings:
    return settings.model_copy(update={"instances_enabled": True})


async def _launch(db, settings, orch, challenge, user):  # noqa: ANN001 - helper
    return await launcher.launch(db, settings, orch, challenge.id, user)


class TestExpiry:
    async def test_a_past_ttl_instance_is_destroyed(
        self, db_session: AsyncSession, settings: Settings
    ) -> None:
        settings = _settings(settings)
        orch = FakeOrchestrator()
        user = await make_user(db_session)
        template = await make_template(db_session)
        challenge = await make_container_challenge(db_session, template)
        instance = await _launch(db_session, settings, orch, challenge, user)

        # It expired a minute ago.
        instance.expires_at = datetime.now(UTC) - timedelta(minutes=1)
        await db_session.flush()

        count = await reconciler.reconcile_expiry(db_session, settings, orch)

        assert count == 1
        await db_session.refresh(instance)
        assert instance.status == InstanceStatus.EXPIRED
        assert instance.k8s_name in orch.destroyed

    async def test_a_live_instance_is_left_alone(
        self, db_session: AsyncSession, settings: Settings
    ) -> None:
        settings = _settings(settings)
        orch = FakeOrchestrator()
        user = await make_user(db_session)
        template = await make_template(db_session)
        challenge = await make_container_challenge(db_session, template)
        instance = await _launch(db_session, settings, orch, challenge, user)

        count = await reconciler.reconcile_expiry(db_session, settings, orch)

        assert count == 0
        await db_session.refresh(instance)
        assert instance.status in (InstanceStatus.PENDING, InstanceStatus.RUNNING)


class TestOrphans:
    async def test_a_pod_with_no_row_is_deleted(
        self, db_session: AsyncSession, settings: Settings
    ) -> None:
        """The dangerous direction: an unowned container still running on the node."""
        settings = _settings(settings)
        orch = FakeOrchestrator()
        orch.orphan_pod(
            InstanceSpec(
                name="dm-orphan",
                namespace=settings.kube_namespace,
                image="ghcr.io/x:v1",
                container_port=80,
                owner_kind="user",
                owner_id="ghost",
            )
        )

        deleted, failed = await reconciler.reconcile_orphans(db_session, settings, orch)

        assert deleted == 1
        assert "dm-orphan" in orch.destroyed
        assert failed == 0

    async def test_a_running_row_with_no_pod_is_failed(
        self, db_session: AsyncSession, settings: Settings
    ) -> None:
        settings = _settings(settings)
        orch = FakeOrchestrator()
        user = await make_user(db_session)
        template = await make_template(db_session)
        challenge = await make_container_challenge(db_session, template)
        instance = await _launch(db_session, settings, orch, challenge, user)
        # It was running, but its pod is gone from the cluster.
        instance.status = InstanceStatus.RUNNING
        await db_session.flush()
        orch.pods.clear()

        deleted, failed = await reconciler.reconcile_orphans(db_session, settings, orch)

        assert failed == 1
        await db_session.refresh(instance)
        assert instance.status == InstanceStatus.FAILED

    async def test_a_matched_pair_is_left_alone(
        self, db_session: AsyncSession, settings: Settings
    ) -> None:
        settings = _settings(settings)
        orch = FakeOrchestrator()
        user = await make_user(db_session)
        template = await make_template(db_session)
        challenge = await make_container_challenge(db_session, template)
        instance = await _launch(db_session, settings, orch, challenge, user)

        deleted, failed = await reconciler.reconcile_orphans(db_session, settings, orch)

        assert (deleted, failed) == (0, 0)
        assert instance.k8s_name not in orch.destroyed
