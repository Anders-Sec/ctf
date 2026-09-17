"""Admin template CRUD, the instance list, force-teardown, and lifecycle (spec 009)."""

import contextlib
import logging
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.models.instance import ContainerTemplate, InstanceStatus
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


class TestTemplateDeletion:
    async def test_a_template_with_a_terminal_instance_can_be_deleted(
        self, app: FastAPI, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        """The reported bug: a template used to launch (then tear down) an instance
        must still be deletable. The instance keeps its history; the link nulls."""
        from app.models.instance import InstanceStatus
        from app.services.instances import launcher

        _enable(app)
        template = await make_template(db_session)
        challenge = await make_container_challenge(db_session, template)
        owner = await make_user(db_session, status=UserStatus.ACTIVE)
        instance = await launcher.launch(
            db_session, app.state.settings, FakeOrchestrator(), challenge.id, owner
        )
        instance.status = InstanceStatus.DESTROYED
        await db_session.flush()

        await admin(db_session, client, sign_in)
        response = await client.delete(f"/api/admin/templates/{template.id}")

        assert response.status_code == 204
        await db_session.refresh(instance)
        assert instance.template_id is None  # history kept, link nulled

    async def test_a_template_assigned_to_a_challenge_can_be_deleted(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:

        template = await make_template(db_session)
        challenge = await make_container_challenge(db_session, template)
        challenge.container_template_id = template.id
        await db_session.flush()

        await admin(db_session, client, sign_in)
        response = await client.delete(f"/api/admin/templates/{template.id}")

        assert response.status_code == 204
        await db_session.refresh(challenge)
        assert challenge.container_template_id is None  # challenge detached cleanly

    async def test_a_template_with_a_live_instance_is_refused(
        self, app: FastAPI, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        from app.services.instances import launcher

        _enable(app)
        template = await make_template(db_session)
        challenge = await make_container_challenge(db_session, template)
        owner = await make_user(db_session, status=UserStatus.ACTIVE)
        await launcher.launch(
            db_session, app.state.settings, FakeOrchestrator(), challenge.id, owner
        )  # left pending/running

        await admin(db_session, client, sign_in)
        response = await client.delete(f"/api/admin/templates/{template.id}")

        assert response.status_code == 409
        assert response.json()["error"]["code"] == "template_in_use"


class TestTemplateLifetimeIsBounded:
    """An emptied number field sends 0, and 0 was accepted.

    `expires_at = now + 0` means the expiry reconciler destroys the instance on
    its next 30-second tick, so a team's target vanished about a minute after
    they launched it. Found at a live event; these are what stop it recurring.
    """

    async def test_a_zero_lifetime_is_refused(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await admin(db_session, client, sign_in)

        response = await client.post(
            "/api/admin/templates",
            json={"name": "broken", "image": "ghcr.io/x/y", "ttl_seconds": 0},
        )

        assert response.status_code == 422

    async def test_a_lifetime_under_a_minute_is_refused(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await admin(db_session, client, sign_in)

        response = await client.post(
            "/api/admin/templates",
            json={"name": "brief", "image": "ghcr.io/x/y", "ttl_seconds": 30},
        )

        assert response.status_code == 422

    async def test_an_absurd_lifetime_is_refused_too(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await admin(db_session, client, sign_in)

        response = await client.post(
            "/api/admin/templates",
            json={"name": "forever", "image": "ghcr.io/x/y", "ttl_seconds": 999_999},
        )

        assert response.status_code == 422

    async def test_an_empty_name_or_image_is_refused(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await admin(db_session, client, sign_in)

        for payload in ({"name": "", "image": "ghcr.io/x/y"}, {"name": "x", "image": ""}):
            response = await client.post("/api/admin/templates", json=payload)
            assert response.status_code == 422, payload

    async def test_a_sensible_lifetime_is_accepted_and_reported(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await admin(db_session, client, sign_in)

        created = await client.post(
            "/api/admin/templates",
            json={
                "name": "web-registry",
                "image": "ghcr.io/anders-sec/ctf-web-registry",
                "ttl_seconds": 7200,
                "shared_instance": True,
                "cpu_limit": "500m",
                "memory_limit": "384Mi",
            },
        )

        assert created.status_code == 201
        body = created.json()
        assert body["ttl_seconds"] == 7200
        assert body["shared_instance"] is True
        # Visible in the response, so an operator can see what they actually saved.
        assert body["cpu_limit"] == "500m"
        assert body["memory_limit"] == "384Mi"


class TestTemplateEditing:
    """Fixing a template must not mean unbinding every challenge that uses it.

    A template's lifetime was typed wrong at an event and there was no way to
    correct it: the UI could create and delete, and deleting sets every
    `challenge.container_template_id` to NULL.
    """

    async def _template(self, client: AsyncClient) -> str:
        created = await client.post(
            "/api/admin/templates",
            json={"name": "web-registry", "image": "ghcr.io/x/y", "ttl_seconds": 90},
        )
        assert created.status_code == 201
        return created.json()["id"]

    async def test_a_lifetime_can_be_corrected_in_place(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await admin(db_session, client, sign_in)
        template_id = await self._template(client)

        updated = await client.patch(
            f"/api/admin/templates/{template_id}", json={"ttl_seconds": 7200}
        )

        assert updated.status_code == 200
        assert updated.json()["ttl_seconds"] == 7200

    async def test_the_challenge_binding_survives_the_edit(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        """The whole point: deleting and recreating would not do this."""
        await admin(db_session, client, sign_in)
        template_id = await self._template(client)
        template = await db_session.get(ContainerTemplate, UUID(template_id))
        challenge = await make_container_challenge(db_session, template)

        await client.patch(f"/api/admin/templates/{template_id}", json={"ttl_seconds": 7200})
        await db_session.refresh(challenge)

        assert challenge.container_template_id == UUID(template_id)

    async def test_an_edit_is_still_bounded(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await admin(db_session, client, sign_in)
        template_id = await self._template(client)

        refused = await client.patch(f"/api/admin/templates/{template_id}", json={"ttl_seconds": 0})

        assert refused.status_code == 422

    async def test_untouched_fields_are_left_alone(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await admin(db_session, client, sign_in)
        template_id = await self._template(client)

        updated = await client.patch(
            f"/api/admin/templates/{template_id}", json={"ttl_seconds": 7200}
        )

        assert updated.json()["image"] == "ghcr.io/x/y"
        assert updated.json()["container_port"] == 80

    async def test_a_player_cannot_edit_a_template(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await admin(db_session, client, sign_in)
        template_id = await self._template(client)

        player_user = await make_user(db_session, status=UserStatus.ACTIVE)
        await sign_in(client, player_user)
        refused = await client.patch(
            f"/api/admin/templates/{template_id}", json={"ttl_seconds": 7200}
        )

        assert refused.status_code in (401, 403)


class _Collector(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


@contextlib.contextmanager
def capture(logger_name: str):
    """Collect records from one logger.

    Not `caplog`: `configure_logging` replaces the root handlers, which removes
    pytest's capture handler, so anything hung off root sees nothing.
    """
    collector = _Collector()
    logger = logging.getLogger(logger_name)
    logger.addHandler(collector)
    previous_level, previously_disabled = logger.level, logger.disabled
    logger.setLevel(logging.INFO)
    # Something in the app's logging setup leaves these loggers `disabled`, which
    # makes `logger.info` a silent no-op no matter what handlers are attached.
    # Production is unaffected — the JSON logs plainly work — but a test that
    # asserts on a log line has to clear it or it asserts on nothing.
    logger.disabled = False
    try:
        yield collector
    finally:
        logger.removeHandler(collector)
        logger.setLevel(previous_level)
        logger.disabled = previously_disabled


def only(records: list[logging.LogRecord], message: str) -> logging.LogRecord:
    matching = [r for r in records if r.msg == message]
    assert matching, f"nothing logged {message!r}"
    return matching[0]


class TestExpiryExplainsItself:
    """A bare count says an instance died and nothing about why.

    Chasing one of these took days, cycling through container crashes,
    misconfigured templates and a dead event, because the only evidence was
    `instances_expired count: 1`. Each expiry now names the instance, the clause
    that caught it, and how long it lived.
    """

    async def test_a_past_ttl_expiry_says_so(
        self, db_session: AsyncSession, settings: Settings
    ) -> None:
        settings = settings.model_copy(update={"instances_enabled": True})
        user = await make_user(db_session, status=UserStatus.ACTIVE)
        template = await make_template(db_session)
        challenge = await make_container_challenge(db_session, template)
        orchestrator = FakeOrchestrator()
        instance = await launcher.launch(db_session, settings, orchestrator, challenge.id, user)
        instance.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        await db_session.flush()

        with capture("app.services.instances.reconciler") as logs:
            count = await reconciler.reconcile_expiry(db_session, settings, orchestrator)

        assert count == 1, "the expiry did not pick up the instance at all"
        record = only(logs.records, "instance_expired")
        assert record.reason == "past_ttl"
        assert record.instance == instance.k8s_name
        assert record.lived_seconds >= 0

    async def test_a_disbanded_owner_is_not_reported_as_a_ttl_expiry(
        self, db_session: AsyncSession, settings: Settings
    ) -> None:
        """The three clauses look identical from outside, and are not."""
        settings = settings.model_copy(update={"instances_enabled": True})
        leader = await make_user(db_session, status=UserStatus.ACTIVE)
        team = await make_team(db_session, leader)
        template = await make_template(db_session)
        challenge = await make_container_challenge(db_session, template)
        orchestrator = FakeOrchestrator()
        instance = await launcher.launch(db_session, settings, orchestrator, challenge.id, leader)
        assert instance.owner_team_id == team.id
        # Still inside its TTL: only the disband should catch it.
        team.disbanded_at = datetime.now(UTC)
        await db_session.flush()

        with capture("app.services.instances.reconciler") as logs:
            await reconciler.reconcile_expiry(db_session, settings, orchestrator)

        assert only(logs.records, "instance_expired").reason == "owner_disbanded"

    async def test_a_launch_records_the_lifetime_it_got(
        self, db_session: AsyncSession, settings: Settings
    ) -> None:
        settings = settings.model_copy(update={"instances_enabled": True})
        user = await make_user(db_session, status=UserStatus.ACTIVE)
        template = await make_template(db_session, name="web-registry", ttl_seconds=7200)
        challenge = await make_container_challenge(db_session, template)

        with capture("app.services.instances.launcher") as logs:
            await launcher.launch(db_session, settings, FakeOrchestrator(), challenge.id, user)

        record = only(logs.records, "instance_launched")
        assert record.ttl_seconds == 7200
        assert record.template == "web-registry"
        assert record.expires_at
