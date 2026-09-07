"""Prerequisite locks: per-player gating and the admin surface (spec 014)."""

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.challenge import ChallengeState, MatchType
from app.models.user import UserRole, UserStatus
from tests.factories import make_challenge, make_user, record_solve

pytestmark = pytest.mark.usefixtures("running_event")


async def player(db_session, client, sign_in, **kw):  # noqa: ANN001 - helper
    kw.setdefault("status", UserStatus.ACTIVE)
    user = await make_user(db_session, **kw)
    await sign_in(client, user)
    return user


async def admin(db_session, client, sign_in):  # noqa: ANN001 - helper
    user = await make_user(db_session, role=UserRole.ADMIN, status=UserStatus.ACTIVE)
    await sign_in(client, user)
    return user


async def _require(db_session, gated, prerequisite) -> None:  # noqa: ANN001
    from app.services import challenges as svc

    await svc.add_prerequisite(db_session, gated.id, prerequisite.id)


class TestPerPlayerGating:
    async def test_a_locked_challenge_hides_its_body_and_lists_the_prerequisite(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await player(db_session, client, sign_in)
        prereq = await make_challenge(db_session, title="Recon 1", state=ChallengeState.PUBLISHED)
        gated = await make_challenge(
            db_session, title="The Vault", body="secret task", state=ChallengeState.PUBLISHED
        )
        await _require(db_session, gated, prereq)

        detail = (await client.get(f"/api/challenges/{gated.id}")).json()

        assert detail["locked"] is True
        assert detail["body"] is None  # withheld while locked
        names = [r["title"] for r in detail["unlock_requirements"]]
        assert names == ["Recon 1"]
        assert detail["unlock_requirements"][0]["solved"] is False

    async def test_solving_the_prerequisite_unlocks_it(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        user = await player(db_session, client, sign_in)
        prereq = await make_challenge(db_session, title="Recon 1", state=ChallengeState.PUBLISHED)
        gated = await make_challenge(
            db_session, title="The Vault", body="secret task", state=ChallengeState.PUBLISHED
        )
        await _require(db_session, gated, prereq)
        await record_solve(db_session, user, prereq)

        detail = (await client.get(f"/api/challenges/{gated.id}")).json()

        assert detail["locked"] is False
        assert detail["body"] == "secret task"
        assert detail["unlock_requirements"] == []

    async def test_all_prerequisites_must_be_solved(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        user = await player(db_session, client, sign_in)
        a = await make_challenge(db_session, title="A", state=ChallengeState.PUBLISHED)
        b = await make_challenge(db_session, title="B", state=ChallengeState.PUBLISHED)
        gated = await make_challenge(db_session, title="Gated", state=ChallengeState.PUBLISHED)
        await _require(db_session, gated, a)
        await _require(db_session, gated, b)
        await record_solve(db_session, user, a)  # only one of two

        detail = (await client.get(f"/api/challenges/{gated.id}")).json()

        assert detail["locked"] is True
        by_title = {r["title"]: r["solved"] for r in detail["unlock_requirements"]}
        assert by_title == {"A": True, "B": False}

    async def test_submission_is_refused_server_side_while_locked(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        """The gate is real, not cosmetic: even a direct submit is rejected."""
        await player(db_session, client, sign_in)
        prereq = await make_challenge(db_session, state=ChallengeState.PUBLISHED)
        gated = await make_challenge(
            db_session, state=ChallengeState.PUBLISHED, answers=[(MatchType.EXACT, "flag{x}")]
        )
        await _require(db_session, gated, prereq)

        response = await client.post(
            f"/api/challenges/{gated.id}/submit", json={"answer": "flag{x}"}
        )

        assert response.status_code == 403
        assert response.json()["error"]["code"] == "challenge_locked"

    async def test_a_hidden_prerequisite_is_not_revealed(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await player(db_session, client, sign_in)
        hidden = await make_challenge(db_session, title="Secret", state=ChallengeState.HIDDEN)
        gated = await make_challenge(db_session, state=ChallengeState.PUBLISHED)
        await _require(db_session, gated, hidden)

        detail = (await client.get(f"/api/challenges/{gated.id}")).json()

        # Still locked (the hidden prereq can't be solved), but not named.
        assert detail["locked"] is True
        assert detail["unlock_requirements"] == []


class TestAdminSurface:
    async def test_add_and_remove_a_prerequisite(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await admin(db_session, client, sign_in)
        gated = await make_challenge(db_session, title="Gated")
        prereq = await make_challenge(db_session, title="First")

        added = await client.post(
            f"/api/admin/challenges/{gated.id}/prerequisites",
            json={"required_challenge_id": str(prereq.id)},
        )
        assert added.status_code == 201
        assert [p["title"] for p in added.json()] == ["First"]

        detail = (await client.get(f"/api/admin/challenges/{gated.id}")).json()
        assert len(detail["prerequisites"]) == 1

        removed = await client.delete(f"/api/admin/challenges/{gated.id}/prerequisites/{prereq.id}")
        assert removed.status_code == 204
        detail = (await client.get(f"/api/admin/challenges/{gated.id}")).json()
        assert detail["prerequisites"] == []

    async def test_self_reference_is_rejected(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await admin(db_session, client, sign_in)
        challenge = await make_challenge(db_session)

        response = await client.post(
            f"/api/admin/challenges/{challenge.id}/prerequisites",
            json={"required_challenge_id": str(challenge.id)},
        )

        assert response.status_code == 409
        assert response.json()["error"]["code"] == "self_prerequisite"

    async def test_a_cycle_is_rejected(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        """A requires B; B requiring A would lock both forever."""
        await admin(db_session, client, sign_in)
        a = await make_challenge(db_session, title="A")
        b = await make_challenge(db_session, title="B")
        await client.post(
            f"/api/admin/challenges/{a.id}/prerequisites",
            json={"required_challenge_id": str(b.id)},
        )

        response = await client.post(
            f"/api/admin/challenges/{b.id}/prerequisites",
            json={"required_challenge_id": str(a.id)},
        )

        assert response.status_code == 409
        assert response.json()["error"]["code"] == "prerequisite_cycle"

    async def test_deleting_a_prerequisite_challenge_drops_the_requirement(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await admin(db_session, client, sign_in)
        gated = await make_challenge(db_session, title="Gated")
        prereq = await make_challenge(db_session, title="Doomed")
        await client.post(
            f"/api/admin/challenges/{gated.id}/prerequisites",
            json={"required_challenge_id": str(prereq.id)},
        )

        deleted = await client.delete(f"/api/admin/challenges/{prereq.id}")
        assert deleted.status_code == 200

        detail = (await client.get(f"/api/admin/challenges/{gated.id}")).json()
        assert detail["prerequisites"] == []
