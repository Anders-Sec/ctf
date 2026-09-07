"""Admin template CRUD, the instance list, force-teardown, and lifecycle (spec 009)."""

from datetime import UTC, datetime, timedelta

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.models.instance import InstanceStatus
from app.models.user import UserRole, UserStatus
from app.services.instances import launcher, reconciler
from app.services.instances.fake import FakeOrchestrator
from tests.factories import (
    make_container_challenge,
    make_team,
    make_template,
    make_user,
)

pytestmark = pytest.mark.usefixtures("running_event")


def _enable(app: FastAPI) -> None:
    app.state.settings = app.state.settings.model_copy(update={"instances_enabled": True})


async def admin(db_session, client, sign_in):  # noqa: ANN001 - helper
    user = await make_user(db_session, role=UserRole.ADMIN, status=UserStatus.ACTIVE)
    await sign_in(client, user)
    return user


class TestTemplateCrud:
    async def test_admin_creates_and_lists_a_template(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await admin(db_session, client, sign_in)

        created = await client.post(
            "/api/admin/templates",
            json={"name": "Web Target", "image": "ghcr.io/anders-sec/ctf-demo"},
        )
        assert created.status_code == 201

        listing = (await client.get("/api/admin/templates")).json()
        assert any(t["name"] == "Web Target" for t in listing)

    async def test_a_tcp_template_is_refused(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        """Decision 3: only HTTP, because a NodePort cannot be authorised."""
        await admin(db_session, client, sign_in)

        response = await client.post(
            "/api/admin/templates",
            json={"name": "Netcat", "image": "ghcr.io/x/nc", "protocol": "tcp"},
        )

        assert response.status_code == 400
        assert response.json()["error"]["code"] == "tcp_not_supported"

    async def test_a_player_cannot_create_a_template(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        player = await make_user(db_session, status=UserStatus.ACTIVE)
        await sign_in(client, player)

        response = await client.post("/api/admin/templates", json={"name": "x", "image": "y"})

        assert response.status_code == 403


class TestInstanceList:
    async def test_staff_see_running_instances_with_owners(
        self, app: FastAPI, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        _enable(app)
        template = await make_template(db_session)
        challenge = await make_container_challenge(db_session, template)
        owner = await make_user(db_session, status=UserStatus.ACTIVE, display_name="Brannor")
        await launcher.launch(
            db_session, app.state.settings, FakeOrchestrator(), challenge.id, owner
        )

        await admin(db_session, client, sign_in)
        listing = (await client.get("/api/admin/instances")).json()

        assert len(listing) == 1
        assert "Brannor" in listing[0]["owner_label"]

    async def test_force_teardown_destroys_and_audits(
        self,
        app: FastAPI,
        client: AsyncClient,
        db_session: AsyncSession,
        sign_in,
        orchestrator: FakeOrchestrator,
    ) -> None:
        _enable(app)
        template = await make_template(db_session)
        challenge = await make_container_challenge(db_session, template)
        owner = await make_user(db_session, status=UserStatus.ACTIVE)
        instance = await launcher.launch(
            db_session, app.state.settings, orchestrator, challenge.id, owner
        )
        await admin(db_session, client, sign_in)

        response = await client.delete(f"/api/admin/instances/{instance.id}")

        assert response.status_code == 204
        assert instance.k8s_name in orchestrator.destroyed
        await db_session.refresh(instance)
        assert instance.status == InstanceStatus.DESTROYED


class TestLifecycleHooks:
    async def test_a_disbanded_partys_instances_are_reaped(
        self, app: FastAPI, db_session: AsyncSession, settings: Settings
    ) -> None:
        settings = settings.model_copy(update={"instances_enabled": True})
        orch = FakeOrchestrator()
        leader = await make_user(db_session, status=UserStatus.ACTIVE)
        team = await make_team(db_session, leader)
        template = await make_template(db_session)
        challenge = await make_container_challenge(db_session, template)
        instance = await launcher.launch(db_session, settings, orch, challenge.id, leader)
        assert instance.owner_team_id == team.id

        # The party disbands; its live target must not outlive it.
        team.disbanded_at = datetime.now(UTC)
        await db_session.flush()

        await reconciler.reconcile_expiry(db_session, settings, orch)

        await db_session.refresh(instance)
        assert instance.status == InstanceStatus.EXPIRED

    async def test_the_event_ending_reaps_everything(
        self, app: FastAPI, db_session: AsyncSession, settings: Settings, running_event
    ) -> None:
        settings = settings.model_copy(update={"instances_enabled": True})
        orch = FakeOrchestrator()
        owner = await make_user(db_session, status=UserStatus.ACTIVE)
        template = await make_template(db_session)
        challenge = await make_container_challenge(db_session, template)
        instance = await launcher.launch(db_session, settings, orch, challenge.id, owner)

        # The crawl ends while the instance still has TTL left.
        running_event.ends_at = datetime.now(UTC) - timedelta(minutes=1)
        await db_session.flush()

        await reconciler.reconcile_expiry(db_session, settings, orch)

        await db_session.refresh(instance)
        assert instance.status == InstanceStatus.EXPIRED
