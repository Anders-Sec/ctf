"""The ingress auth-url check (spec 009).

This is what makes 'exposed to that party only' literally true rather than
'unguessable'. It runs on every request to an instance subdomain and answers
only 200 or 401.
"""

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.instance import ChallengeInstance
from app.models.user import UserStatus
from tests.factories import (
    add_member,
    make_container_challenge,
    make_team,
    make_template,
    make_user,
)

pytestmark = pytest.mark.usefixtures("running_event")


def _enable(app: FastAPI) -> None:
    app.state.settings = app.state.settings.model_copy(update={"instances_enabled": True})


async def _signed_in(db_session, client, sign_in, **kw):  # noqa: ANN001 - helper
    kw.setdefault("status", UserStatus.ACTIVE)
    user = await make_user(db_session, **kw)
    await sign_in(client, user)
    return user


async def _launch(client: AsyncClient, db: AsyncSession, challenge_id) -> ChallengeInstance:  # noqa: ANN001
    await client.post(f"/api/challenges/{challenge_id}/instance")
    return (
        (
            await db.execute(
                select(ChallengeInstance).where(ChallengeInstance.challenge_id == challenge_id)
            )
        )
        .scalars()
        .all()[-1]
    )


class TestAuthorise:
    async def test_the_owner_is_allowed(
        self, app: FastAPI, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        _enable(app)
        await _signed_in(db_session, client, sign_in)
        template = await make_template(db_session)
        challenge = await make_container_challenge(db_session, template)
        instance = await _launch(client, db_session, challenge.id)

        resp = await client.get(f"/api/instances/authorise/{instance.k8s_name}")

        assert resp.status_code == 200

    async def test_a_different_player_is_denied(
        self, app: FastAPI, client: AsyncClient, db_session: AsyncSession, sign_in, settings
    ) -> None:
        _enable(app)
        owner = await make_user(db_session, status=UserStatus.ACTIVE)
        template = await make_template(db_session)
        challenge = await make_container_challenge(db_session, template)
        from app.services.instances import launcher
        from app.services.instances.fake import FakeOrchestrator

        instance = await launcher.launch(
            db_session, app.state.settings, FakeOrchestrator(), challenge.id, owner
        )

        # A second, unrelated player, signed in.
        intruder = await _signed_in(db_session, client, sign_in)
        assert intruder.id != owner.id

        resp = await client.get(f"/api/instances/authorise/{instance.k8s_name}")

        assert resp.status_code == 401

    async def test_a_party_member_is_allowed(
        self, app: FastAPI, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        """A team-owned instance is reachable by any current member — sharing the
        target is the point of a party holding it."""
        _enable(app)
        leader = await make_user(db_session, status=UserStatus.ACTIVE)
        team = await make_team(db_session, leader)
        member = await _signed_in(db_session, client, sign_in)
        await add_member(db_session, team, member)

        template = await make_template(db_session)
        challenge = await make_container_challenge(db_session, template)
        from app.services.instances import launcher
        from app.services.instances.fake import FakeOrchestrator

        # The leader launches; it is owned by the team.
        instance = await launcher.launch(
            db_session, app.state.settings, FakeOrchestrator(), challenge.id, leader
        )
        assert instance.owner_team_id == team.id

        resp = await client.get(f"/api/instances/authorise/{instance.k8s_name}")

        assert resp.status_code == 200

    async def test_no_session_is_denied(
        self, app: FastAPI, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        _enable(app)
        resp = await client.get("/api/instances/authorise/dm-whatever")
        assert resp.status_code == 401

    async def test_an_unknown_instance_is_denied(
        self, app: FastAPI, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        _enable(app)
        await _signed_in(db_session, client, sign_in)

        resp = await client.get("/api/instances/authorise/dm-does-not-exist")

        assert resp.status_code == 401
