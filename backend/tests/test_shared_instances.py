"""One container, several challenges, a flag each per team (spec 046).

Both Web Attacks images are a single image carrying four challenges, so the
instance a team launches from one of them has to be the instance they get from
the other three — and each of those four has to hand back a different flag, or
the first solve gives away the rest.

Everything here runs against the fake orchestrator. No cluster.
"""

import re
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.challenge import ChallengeAnswer, ChallengeState, MatchType
from app.models.instance import ChallengeInstance, ChallengeInstanceAnswer
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


async def _area(db: AsyncSession, *, stems: bool = True, count: int = 4):
    """A shared template with `count` published challenges on it."""
    template = await make_template(db, name="web-apothecary", shared_instance=True)
    challenges = []
    for index in range(count):
        challenge = await make_container_challenge(db, template, title=f"Flaw {index}")
        if stems:
            db.add(
                ChallengeAnswer(
                    challenge_id=challenge.id,
                    match_type=MatchType.DYNAMIC,
                    value=f"stem_{index}",
                    options={},
                )
            )
        challenges.append(challenge)
    await db.flush()
    return template, challenges


async def _minted(db: AsyncSession, instance_id, challenge_id) -> str | None:  # noqa: ANN001
    return await db.scalar(
        select(ChallengeInstanceAnswer.value).where(
            ChallengeInstanceAnswer.instance_id == instance_id,
            ChallengeInstanceAnswer.challenge_id == challenge_id,
        )
    )


class TestOneContainerServesTheArea:
    async def test_launching_from_each_challenge_yields_one_instance(
        self, app: FastAPI, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        _enable(app)
        await player(db_session, client, sign_in)
        _, challenges = await _area(db_session)

        ids = set()
        for challenge in challenges:
            response = await client.post(f"/api/challenges/{challenge.id}/instance")
            assert response.status_code == 201
            ids.add(response.json()["id"])

        assert len(ids) == 1
        rows = (await db_session.execute(select(ChallengeInstance))).scalars().all()
        assert len(rows) == 1

    async def test_the_area_costs_one_slot_of_the_cap(
        self, app: FastAPI, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        """Four challenges must not eat a cap of two."""
        _enable(app)
        await player(db_session, client, sign_in)
        _, challenges = await _area(db_session)
        for challenge in challenges:
            await client.post(f"/api/challenges/{challenge.id}/instance")

        # A different container still launches alongside it.
        other_template = await make_template(db_session, name="web-registry")
        other = await make_container_challenge(db_session, other_template, title="Elsewhere")
        response = await client.post(f"/api/challenges/{other.id}/instance")

        assert response.status_code == 201

    async def test_get_and_destroy_from_a_sibling_reach_the_same_container(
        self, app: FastAPI, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        _enable(app)
        await player(db_session, client, sign_in)
        _, challenges = await _area(db_session)
        launched = await client.post(f"/api/challenges/{challenges[0].id}/instance")

        found = await client.get(f"/api/challenges/{challenges[2].id}/instance")
        assert found.status_code == 200
        assert found.json()["id"] == launched.json()["id"]

        destroyed = await client.delete(f"/api/challenges/{challenges[3].id}/instance")
        assert destroyed.status_code == 204
        gone = await client.get(f"/api/challenges/{challenges[0].id}/instance")
        assert gone.status_code == 404

    async def test_an_unshared_template_still_gets_one_instance_per_challenge(
        self, app: FastAPI, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        """The regression guard: nothing changes for a template that did not ask."""
        _enable(app)
        await player(db_session, client, sign_in)
        template = await make_template(db_session, shared_instance=False)
        first = await make_container_challenge(db_session, template, title="One")
        second = await make_container_challenge(db_session, template, title="Two")

        a = await client.post(f"/api/challenges/{first.id}/instance")
        b = await client.post(f"/api/challenges/{second.id}/instance")

        assert a.json()["id"] != b.json()["id"]

    async def test_the_shared_count_reports_published_siblings_only(
        self, app: FastAPI, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        _enable(app)
        await player(db_session, client, sign_in)
        _, challenges = await _area(db_session)
        challenges[3].state = ChallengeState.DRAFT
        await db_session.flush()

        response = await client.post(f"/api/challenges/{challenges[0].id}/instance")

        # Four on the template, one now a draft, minus itself.
        assert response.json()["shared_challenge_count"] == 2

    async def test_an_ordinary_target_reports_no_sharing(
        self, app: FastAPI, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        _enable(app)
        await player(db_session, client, sign_in)
        template = await make_template(db_session)
        challenge = await make_container_challenge(db_session, template)

        response = await client.post(f"/api/challenges/{challenge.id}/instance")

        assert response.json()["shared_challenge_count"] == 0


class TestMintedFlags:
    async def test_every_challenge_gets_its_own_flag_from_its_own_stem(
        self, app: FastAPI, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        _enable(app)
        await player(db_session, client, sign_in)
        _, challenges = await _area(db_session)
        launched = await client.post(f"/api/challenges/{challenges[0].id}/instance")
        instance_id = launched.json()["id"]

        values = [await _minted(db_session, instance_id, c.id) for c in challenges]

        assert all(v is not None for v in values)
        for index, value in enumerate(values):
            assert re.fullmatch(rf"flag\{{stem_{index}_[0-9a-f]{{8}}\}}", value), value

    async def test_no_two_challenges_share_a_tail(
        self, app: FastAPI, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        """The one that matters.

        A tail shared across the area would let a team read the easy challenge's
        flag and type the hard one's without exploiting anything — the stems are
        the challenge titles.
        """
        _enable(app)
        await player(db_session, client, sign_in)
        _, challenges = await _area(db_session)
        launched = await client.post(f"/api/challenges/{challenges[0].id}/instance")

        tails = {
            (await _minted(db_session, launched.json()["id"], c.id)).rsplit("_", 1)[1]
            for c in challenges
        }

        assert len(tails) == len(challenges)

    async def test_the_flags_reach_the_container_keyed_by_slug(
        self, app: FastAPI, client: AsyncClient, db_session: AsyncSession, sign_in, orchestrator
    ) -> None:
        import json

        _enable(app)
        await player(db_session, client, sign_in)
        _, challenges = await _area(db_session)
        await client.post(f"/api/challenges/{challenges[0].id}/instance")

        instance = (await db_session.execute(select(ChallengeInstance))).scalar_one()
        pod = orchestrator.pods[instance.k8s_name].manifests["pod"]
        env = {e["name"]: e["value"] for e in pod["spec"]["containers"][0]["env"]}
        delivered = json.loads(env["INSTANCE_ANSWERS"])

        assert set(delivered) == {c.slug for c in challenges}
        for challenge in challenges:
            assert delivered[challenge.slug] == await _minted(db_session, instance.id, challenge.id)
        # Several challenges, so the single-flag variable would be a lie.
        assert "INSTANCE_ANSWER" not in env

    async def test_each_flag_solves_only_its_own_challenge(
        self, app: FastAPI, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        _enable(app)
        await player(db_session, client, sign_in)
        _, challenges = await _area(db_session)
        launched = await client.post(f"/api/challenges/{challenges[0].id}/instance")
        instance_id = launched.json()["id"]

        mine = await _minted(db_session, instance_id, challenges[0].id)
        siblings = await _minted(db_session, instance_id, challenges[1].id)

        right = await client.post(
            f"/api/challenges/{challenges[0].id}/submit", json={"answer": mine}
        )
        wrong = await client.post(
            f"/api/challenges/{challenges[2].id}/submit", json={"answer": siblings}
        )

        assert right.json()["correct"] is True
        assert wrong.json()["correct"] is False

    async def test_another_teams_flag_is_worthless(
        self, app: FastAPI, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        """The whole point of minting per team."""
        from app.services.instances import launcher
        from app.services.instances.fake import FakeOrchestrator

        _enable(app)
        _, challenges = await _area(db_session)

        other = await make_user(db_session, status=UserStatus.ACTIVE)
        theirs = await launcher.launch(
            db_session, app.state.settings, FakeOrchestrator(), challenges[0].id, other
        )
        stolen = await _minted(db_session, theirs.id, challenges[0].id)

        await player(db_session, client, sign_in)
        await client.post(f"/api/challenges/{challenges[0].id}/instance")
        result = await client.post(
            f"/api/challenges/{challenges[0].id}/submit", json={"answer": stolen}
        )

        assert result.json()["correct"] is False

    async def test_the_tail_may_be_typed_in_capitals(
        self, app: FastAPI, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        _enable(app)
        await player(db_session, client, sign_in)
        _, challenges = await _area(db_session)
        launched = await client.post(f"/api/challenges/{challenges[0].id}/instance")
        mine = await _minted(db_session, launched.json()["id"], challenges[0].id)

        result = await client.post(
            f"/api/challenges/{challenges[0].id}/submit", json={"answer": mine.upper()}
        )

        assert result.json()["correct"] is True

    async def test_an_unpublished_sibling_gets_no_flag(
        self, app: FastAPI, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        _enable(app)
        await player(db_session, client, sign_in)
        _, challenges = await _area(db_session)
        challenges[3].state = ChallengeState.DRAFT
        await db_session.flush()

        launched = await client.post(f"/api/challenges/{challenges[0].id}/instance")

        assert await _minted(db_session, launched.json()["id"], challenges[3].id) is None

    async def test_a_dynamic_rule_alone_never_matches(
        self, app: FastAPI, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        """The stem is not the flag, and submitting it must not be a solve."""
        _enable(app)
        await player(db_session, client, sign_in)
        _, challenges = await _area(db_session)
        await client.post(f"/api/challenges/{challenges[0].id}/instance")

        for guess in ("stem_0", "flag{stem_0}"):
            result = await client.post(
                f"/api/challenges/{challenges[0].id}/submit", json={"answer": guess}
            )
            assert result.json()["correct"] is False


class TestWindDown:
    async def test_solving_the_last_challenge_starts_the_wind_down(
        self, app: FastAPI, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        _enable(app)
        await player(db_session, client, sign_in)
        _, challenges = await _area(db_session, count=2)
        launched = await client.post(f"/api/challenges/{challenges[0].id}/instance")
        instance_id = launched.json()["id"]

        first = await _minted(db_session, instance_id, challenges[0].id)
        await client.post(f"/api/challenges/{challenges[0].id}/submit", json={"answer": first})

        instance = await db_session.get(ChallengeInstance, instance_id)
        await db_session.refresh(instance)
        # One of the two still to go, so nothing has changed.
        assert instance.expires_at > datetime.now(UTC) + timedelta(minutes=30)

        second = await _minted(db_session, instance_id, challenges[1].id)
        await client.post(f"/api/challenges/{challenges[1].id}/submit", json={"answer": second})

        await db_session.refresh(instance)
        assert instance.expires_at <= datetime.now(UTC) + timedelta(
            seconds=app.state.settings.instance_completion_grace_seconds + 5
        )

    async def test_it_never_extends_an_instance_expiring_sooner(
        self, app: FastAPI, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        _enable(app)
        await player(db_session, client, sign_in)
        _, challenges = await _area(db_session, count=1)
        launched = await client.post(f"/api/challenges/{challenges[0].id}/instance")
        instance = await db_session.get(ChallengeInstance, launched.json()["id"])

        soon = datetime.now(UTC) + timedelta(seconds=30)
        instance.expires_at = soon
        await db_session.flush()

        mine = await _minted(db_session, instance.id, challenges[0].id)
        await client.post(f"/api/challenges/{challenges[0].id}/submit", json={"answer": mine})

        await db_session.refresh(instance)
        assert instance.expires_at == soon
