"""Zone gating: a gated category locks its challenges everywhere (spec 017)."""

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.challenge import MatchType, RequirementType, ScoringMode
from app.models.user import UserRole, UserStatus
from app.services import unlocks as unlock_service
from tests.factories import make_category, make_challenge, make_user, record_solve

pytestmark = pytest.mark.usefixtures("running_event")


async def player(db_session, client, sign_in, **kwargs):
    kwargs.setdefault("status", UserStatus.ACTIVE)
    user = await make_user(db_session, **kwargs)
    await sign_in(client, user)
    return user


async def gate_zone(db_session, category, **kwargs):
    return await unlock_service.add_requirement(db_session, category_id=category.id, **kwargs)


async def bank_xp(db_session, user, amount):
    challenge = await make_challenge(db_session, scoring=ScoringMode.STATIC, initial_points=amount)
    await record_solve(db_session, user, challenge)


class TestZoneLocks:
    async def test_a_gated_zone_locks_its_challenges(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        user = await player(db_session, client, sign_in)
        wing = await make_category(db_session, name="Deep Wing")
        room = await make_challenge(db_session, category=wing, title="Inner Sanctum")
        await gate_zone(db_session, wing, requirement_type=RequirementType.MIN_XP, threshold=600)

        detail = (await client.get(f"/api/challenges/{room.id}")).json()

        assert detail["locked"] is True
        assert detail["body"] is None
        req = detail["unlock_requirements"][0]
        assert req["type"] == "min_xp"
        assert req["description"] == "Reach 600 XP"

        await bank_xp(db_session, user, 600)

        assert (await client.get(f"/api/challenges/{room.id}")).json()["locked"] is False

    async def test_the_zone_gate_holds_even_when_the_challenge_is_open(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        """Own requirements met, zone's not — still shut."""
        user = await player(db_session, client, sign_in)
        wing = await make_category(db_session, name="Deep Wing")
        warmup = await make_challenge(db_session, title="Warm-Up")
        room = await make_challenge(db_session, category=wing, title="Inner Sanctum")
        await unlock_service.add_requirement(
            db_session,
            challenge_id=room.id,
            requirement_type=RequirementType.CHALLENGE_SOLVED,
            required_challenge_id=warmup.id,
        )
        await gate_zone(db_session, wing, requirement_type=RequirementType.MIN_XP, threshold=10_000)

        await record_solve(db_session, user, warmup)

        assert (await client.get(f"/api/challenges/{room.id}")).json()["locked"] is True

    async def test_an_ungated_zone_is_open_to_everyone(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        """How the starting area is authored: no requirements at all."""
        await player(db_session, client, sign_in)
        starter = await make_category(db_session, name="Warm-Up")
        room = await make_challenge(db_session, category=starter)

        assert (await client.get(f"/api/challenges/{room.id}")).json()["locked"] is False


class TestNoBypass:
    async def test_a_locked_zone_refuses_a_direct_submission(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        """Fog that is only visual would be walked past by posting a flag."""
        await player(db_session, client, sign_in)
        wing = await make_category(db_session, name="Deep Wing")
        room = await make_challenge(
            db_session,
            category=wing,
            answers=[(MatchType.EXACT, "flag{correct}")],
        )
        await gate_zone(db_session, wing, requirement_type=RequirementType.MIN_XP, threshold=9_000)

        response = await client.post(
            f"/api/challenges/{room.id}/submit", json={"answer": "flag{correct}"}
        )

        assert response.status_code == 403
        assert response.json()["error"]["code"] == "challenge_locked"

    async def test_the_list_view_agrees_with_the_detail_view(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await player(db_session, client, sign_in)
        wing = await make_category(db_session, name="Deep Wing")
        room = await make_challenge(db_session, category=wing, title="Inner Sanctum")
        await gate_zone(db_session, wing, requirement_type=RequirementType.MIN_XP, threshold=9_000)

        rows = (await client.get("/api/challenges")).json()
        listed = next(r for r in rows if r["id"] == str(room.id))

        assert listed["locked"] is True


class TestAdminZoneGates:
    async def test_an_admin_gates_and_ungates_a_zone(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await player(db_session, client, sign_in, role=UserRole.ADMIN)
        wing = await make_category(db_session, name="Deep Wing")

        created = await client.post(
            f"/api/admin/categories/{wing.id}/requirements",
            json={"requirement_type": "min_xp", "threshold": 600},
        )
        assert created.status_code == 201
        assert created.json()["category_id"] == str(wing.id)

        listed = await client.get(f"/api/admin/categories/{wing.id}/requirements")
        assert len(listed.json()) == 1

        await client.delete(f"/api/admin/requirements/{created.json()['id']}")
        assert (await client.get(f"/api/admin/categories/{wing.id}/requirements")).json() == []
