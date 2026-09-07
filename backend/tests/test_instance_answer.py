"""The per-instance answer, through the real submission path (spec 009).

This is the hole that a shared live target would otherwise open: if every player
attacking a copy of the same challenge got the same flag, one could hand it to
another. The answer is generated per instance, so they cannot.
"""

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.instance import ChallengeInstance
from app.models.play import Solve
from app.models.user import UserStatus
from tests.factories import make_container_challenge, make_template, make_user

pytestmark = pytest.mark.usefixtures("running_event")


def _enable(app: FastAPI) -> None:
    app.state.settings = app.state.settings.model_copy(update={"instances_enabled": True})


async def player(db_session, client, sign_in, **kw):  # noqa: ANN001 - helper
    kw.setdefault("status", UserStatus.ACTIVE)
    user = await make_user(db_session, **kw)
    await sign_in(client, user)
    return user


async def _launch_and_get_answer(client: AsyncClient, db: AsyncSession, challenge_id) -> str:  # noqa: ANN001
    await client.post(f"/api/challenges/{challenge_id}/instance")
    instance = (
        (
            await db.execute(
                select(ChallengeInstance).where(ChallengeInstance.challenge_id == challenge_id)
            )
        )
        .scalars()
        .all()[-1]
    )
    return instance.generated_answer


class TestPerInstanceAnswer:
    async def test_the_instance_answer_solves_it(
        self, app: FastAPI, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        _enable(app)
        await player(db_session, client, sign_in)
        template = await make_template(db_session)
        challenge = await make_container_challenge(db_session, template)
        answer = await _launch_and_get_answer(client, db_session, challenge.id)

        result = await client.post(
            f"/api/challenges/{challenge.id}/submit", json={"answer": answer}
        )

        assert result.status_code == 200
        assert result.json()["correct"] is True

    async def test_another_players_instance_answer_does_not_solve_it(
        self, app: FastAPI, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        """The core guarantee: a flag from someone else's instance is worthless."""
        _enable(app)
        template = await make_template(db_session)
        challenge = await make_container_challenge(db_session, template)

        # One player launches and learns their instance's answer...
        other = await make_user(db_session, status=UserStatus.ACTIVE)
        from app.services.instances import launcher
        from app.services.instances.fake import FakeOrchestrator

        their_instance = await launcher.launch(
            db_session, app.state.settings, FakeOrchestrator(), challenge.id, other
        )
        stolen = their_instance.generated_answer

        # ...and a different player tries to use it.
        await player(db_session, client, sign_in)
        await client.post(f"/api/challenges/{challenge.id}/instance")

        result = await client.post(
            f"/api/challenges/{challenge.id}/submit", json={"answer": stolen}
        )

        assert result.json()["correct"] is False

    async def test_without_an_instance_the_answer_is_simply_wrong(
        self, app: FastAPI, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        _enable(app)
        await player(db_session, client, sign_in)
        template = await make_template(db_session)
        challenge = await make_container_challenge(db_session, template)

        # A plausible-looking flag, but the player has launched nothing.
        result = await client.post(
            f"/api/challenges/{challenge.id}/submit", json={"answer": "flag{guess}"}
        )

        assert result.status_code == 200
        assert result.json()["correct"] is False
        assert (await db_session.execute(select(Solve))).first() is None

    async def test_a_correct_instance_answer_records_a_solve(
        self, app: FastAPI, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        _enable(app)
        user = await player(db_session, client, sign_in)
        template = await make_template(db_session)
        challenge = await make_container_challenge(db_session, template)
        answer = await _launch_and_get_answer(client, db_session, challenge.id)

        await client.post(f"/api/challenges/{challenge.id}/submit", json={"answer": answer})

        solve = (
            await db_session.execute(select(Solve).where(Solve.user_id == user.id))
        ).scalar_one_or_none()
        assert solve is not None
