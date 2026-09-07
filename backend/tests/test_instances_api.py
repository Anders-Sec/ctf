"""Launching, polling, the cap and teardown, end to end against the fake (spec 009)."""

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.instance import ChallengeInstance, InstanceStatus
from app.models.user import UserStatus
from app.services.instances.fake import FakeOrchestrator
from tests.factories import make_container_challenge, make_template, make_user

pytestmark = pytest.mark.usefixtures("running_event")


def _enable(app: FastAPI) -> None:
    """Turn the feature on for this app without rebuilding the (fake) orchestrator."""
    app.state.settings = app.state.settings.model_copy(update={"instances_enabled": True})


async def player(db_session, client, sign_in, **kw):  # noqa: ANN001 - helper
    kw.setdefault("status", UserStatus.ACTIVE)
    user = await make_user(db_session, **kw)
    await sign_in(client, user)
    return user


class TestLaunch:
    async def test_launch_returns_pending_then_running(
        self,
        app: FastAPI,
        client: AsyncClient,
        db_session: AsyncSession,
        sign_in,
        orchestrator: FakeOrchestrator,
    ) -> None:
        _enable(app)
        orchestrator.auto_ready = False  # make the poll transition observable
        await player(db_session, client, sign_in)
        template = await make_template(db_session)
        challenge = await make_container_challenge(db_session, template)

        launched = await client.post(f"/api/challenges/{challenge.id}/instance")
        assert launched.status_code == 201
        assert launched.json()["status"] == "pending"
        assert launched.json()["connection_url"] is None

        # The cluster reports the pod ready; the next poll advances it.
        name = (await db_session.execute(select(ChallengeInstance.k8s_name))).scalar_one()
        orchestrator.mark_ready(name)
        polled = await client.get(f"/api/challenges/{challenge.id}/instance")

        assert polled.json()["status"] == "running"
        assert polled.json()["connection_url"].endswith(".ctf-nm.org")

    async def test_a_second_launch_returns_the_same_instance(
        self, app: FastAPI, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        _enable(app)
        await player(db_session, client, sign_in)
        template = await make_template(db_session)
        challenge = await make_container_challenge(db_session, template)

        first = await client.post(f"/api/challenges/{challenge.id}/instance")
        second = await client.post(f"/api/challenges/{challenge.id}/instance")

        assert first.json()["id"] == second.json()["id"]
        # Exactly one row: the second launch did not create a duplicate.
        rows = (await db_session.execute(select(ChallengeInstance))).scalars().all()
        assert len(rows) == 1

    async def test_the_generated_answer_reaches_the_container_env(
        self,
        app: FastAPI,
        client: AsyncClient,
        db_session: AsyncSession,
        sign_in,
        orchestrator: FakeOrchestrator,
    ) -> None:
        _enable(app)
        await player(db_session, client, sign_in)
        template = await make_template(db_session)
        challenge = await make_container_challenge(db_session, template)

        await client.post(f"/api/challenges/{challenge.id}/instance")

        instance = (await db_session.execute(select(ChallengeInstance))).scalar_one()
        pod = orchestrator.pods[instance.k8s_name].manifests["pod"]
        env = {e["name"]: e["value"] for e in pod["spec"]["containers"][0]["env"]}
        assert env["INSTANCE_ANSWER"] == instance.generated_answer

    async def test_a_non_container_challenge_is_refused(
        self, app: FastAPI, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        from tests.factories import make_challenge

        _enable(app)
        await player(db_session, client, sign_in)
        challenge = await make_challenge(db_session)  # no template

        response = await client.post(f"/api/challenges/{challenge.id}/instance")

        assert response.status_code == 400
        assert response.json()["error"]["code"] == "not_a_container_challenge"

    async def test_the_feature_can_be_off(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        """Not enabled → 503, not a crash. instances_enabled defaults off."""
        await player(db_session, client, sign_in)
        template = await make_template(db_session)
        challenge = await make_container_challenge(db_session, template)

        response = await client.post(f"/api/challenges/{challenge.id}/instance")

        assert response.status_code == 503


class TestCap:
    async def test_the_per_owner_cap_refuses_the_next(
        self, app: FastAPI, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        _enable(app)
        app.state.settings = app.state.settings.model_copy(update={"instance_max_per_owner": 1})
        await player(db_session, client, sign_in)
        template = await make_template(db_session)
        first = await make_container_challenge(db_session, template, title="One")
        second = await make_container_challenge(db_session, template, title="Two")

        assert (await client.post(f"/api/challenges/{first.id}/instance")).status_code == 201
        blocked = await client.post(f"/api/challenges/{second.id}/instance")

        assert blocked.status_code == 409
        assert blocked.json()["error"]["code"] == "instance_cap_reached"

    async def test_destroying_frees_a_slot(
        self, app: FastAPI, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        _enable(app)
        app.state.settings = app.state.settings.model_copy(update={"instance_max_per_owner": 1})
        await player(db_session, client, sign_in)
        template = await make_template(db_session)
        first = await make_container_challenge(db_session, template, title="One")
        second = await make_container_challenge(db_session, template, title="Two")

        await client.post(f"/api/challenges/{first.id}/instance")
        assert (await client.delete(f"/api/challenges/{first.id}/instance")).status_code == 204
        # The slot is free now.
        assert (await client.post(f"/api/challenges/{second.id}/instance")).status_code == 201


class TestLifecycle:
    async def test_destroy_tears_down_and_marks_the_row(
        self,
        app: FastAPI,
        client: AsyncClient,
        db_session: AsyncSession,
        sign_in,
        orchestrator: FakeOrchestrator,
    ) -> None:
        _enable(app)
        await player(db_session, client, sign_in)
        template = await make_template(db_session)
        challenge = await make_container_challenge(db_session, template)
        await client.post(f"/api/challenges/{challenge.id}/instance")
        instance = (await db_session.execute(select(ChallengeInstance))).scalar_one()

        await client.delete(f"/api/challenges/{challenge.id}/instance")

        assert instance.k8s_name in orchestrator.destroyed
        await db_session.refresh(instance)
        assert instance.status == InstanceStatus.DESTROYED

    async def test_extend_pushes_the_expiry_out(
        self, app: FastAPI, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        _enable(app)
        await player(db_session, client, sign_in)
        template = await make_template(db_session)
        challenge = await make_container_challenge(db_session, template)
        await client.post(f"/api/challenges/{challenge.id}/instance")
        instance = (await db_session.execute(select(ChallengeInstance))).scalar_one()
        before = instance.expires_at

        await client.post(f"/api/challenges/{challenge.id}/instance/extend")

        await db_session.refresh(instance)
        assert instance.expires_at >= before

    async def test_a_failed_pod_surfaces_as_failed(
        self,
        app: FastAPI,
        client: AsyncClient,
        db_session: AsyncSession,
        sign_in,
        orchestrator: FakeOrchestrator,
    ) -> None:
        _enable(app)
        orchestrator.auto_ready = False
        await player(db_session, client, sign_in)
        template = await make_template(db_session)
        challenge = await make_container_challenge(db_session, template)
        await client.post(f"/api/challenges/{challenge.id}/instance")

        name = (await db_session.execute(select(ChallengeInstance.k8s_name))).scalar_one()
        orchestrator.mark_failed(name, "ImagePullBackOff")
        polled = await client.get(f"/api/challenges/{challenge.id}/instance")

        assert polled.json()["status"] == "failed"
        assert polled.json()["error"] == "ImagePullBackOff"
