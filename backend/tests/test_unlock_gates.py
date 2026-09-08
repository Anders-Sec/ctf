"""Value-based unlock gates: min_xp, skill_level, solves_in_category (spec 017)."""

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.challenge import RequirementType, ScoringMode
from app.models.skill import Skill
from app.models.user import UserRole, UserStatus
from app.services import unlocks as unlock_service
from tests.factories import make_category, make_challenge, make_user, record_solve

pytestmark = pytest.mark.usefixtures("running_event")


async def player(db_session, client, sign_in, **kwargs):
    kwargs.setdefault("status", UserStatus.ACTIVE)
    user = await make_user(db_session, **kwargs)
    await sign_in(client, user)
    return user


async def make_skill(db_session, name: str) -> Skill:
    skill = Skill(name=name)
    db_session.add(skill)
    await db_session.flush()
    return skill


async def gate(db_session, challenge, **kwargs):
    return await unlock_service.add_requirement(db_session, challenge_id=challenge.id, **kwargs)


async def bank_xp(db_session, user, amount, *, category=None):
    challenge = await make_challenge(
        db_session, category=category, scoring=ScoringMode.STATIC, initial_points=amount
    )
    await record_solve(db_session, user, challenge)
    return challenge


class TestMinXp:
    async def test_it_blocks_below_and_opens_at_the_threshold(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        user = await player(db_session, client, sign_in)
        gated = await make_challenge(db_session, title="Vault")
        await gate(db_session, gated, requirement_type=RequirementType.MIN_XP, threshold=500)

        locked = (await client.get(f"/api/challenges/{gated.id}")).json()
        assert locked["locked"] is True
        req = locked["unlock_requirements"][0]
        assert req["type"] == "min_xp"
        assert req["met"] is False
        assert req["progress"] == 0
        assert req["threshold"] == 500
        assert req["description"] == "Reach 500 XP"

        await bank_xp(db_session, user, 500)

        assert (await client.get(f"/api/challenges/{gated.id}")).json()["locked"] is False


class TestSkillLevel:
    async def test_only_that_skill_opens_it(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        user = await player(db_session, client, sign_in)
        hacking = await make_skill(db_session, "Hacking")
        crypto = await make_skill(db_session, "Crypto")
        hack_cat = await make_category(db_session, name="Web")
        hack_cat.skill_id = hacking.id
        crypto_cat = await make_category(db_session, name="Ciphers")
        crypto_cat.skill_id = crypto.id
        await db_session.flush()

        gated = await make_challenge(db_session, title="Deep Vault")
        await gate(
            db_session,
            gated,
            requirement_type=RequirementType.SKILL_LEVEL,
            required_skill_id=hacking.id,
            threshold=2,
        )

        # 200 XP in the *wrong* skill: level 2 Crypto, still level 1 Hacking.
        await bank_xp(db_session, user, 200, category=crypto_cat)
        assert (await client.get(f"/api/challenges/{gated.id}")).json()["locked"] is True

        await bank_xp(db_session, user, 200, category=hack_cat)
        assert (await client.get(f"/api/challenges/{gated.id}")).json()["locked"] is False

    async def test_deleting_the_skill_drops_the_gate(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await player(db_session, client, sign_in)
        hacking = await make_skill(db_session, "Hacking")
        gated = await make_challenge(db_session)
        await gate(
            db_session,
            gated,
            requirement_type=RequirementType.SKILL_LEVEL,
            required_skill_id=hacking.id,
            threshold=5,
        )
        assert (await client.get(f"/api/challenges/{gated.id}")).json()["locked"] is True

        await db_session.delete(hacking)
        await db_session.flush()

        # The gate cascaded away rather than becoming unsatisfiable.
        assert (await client.get(f"/api/challenges/{gated.id}")).json()["locked"] is False


class TestSolvesInCategory:
    async def test_it_counts_only_that_category(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        user = await player(db_session, client, sign_in)
        starter = await make_category(db_session, name="Warm-Up")
        other = await make_category(db_session, name="Elsewhere")
        gated = await make_challenge(db_session, title="Second Wing")
        await gate(
            db_session,
            gated,
            requirement_type=RequirementType.SOLVES_IN_CATEGORY,
            required_category_id=starter.id,
            threshold=2,
        )

        for _ in range(3):
            solved = await make_challenge(db_session, category=other)
            await record_solve(db_session, user, solved)
        assert (await client.get(f"/api/challenges/{gated.id}")).json()["locked"] is True

        for _ in range(2):
            solved = await make_challenge(db_session, category=starter)
            await record_solve(db_session, user, solved)

        detail = (await client.get(f"/api/challenges/{gated.id}")).json()
        assert detail["locked"] is False


class TestCombining:
    async def test_every_requirement_must_be_met(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        user = await player(db_session, client, sign_in)
        first = await make_challenge(db_session, title="Warm-Up")
        gated = await make_challenge(db_session, title="Both Gates")
        await gate(
            db_session,
            gated,
            requirement_type=RequirementType.CHALLENGE_SOLVED,
            required_challenge_id=first.id,
        )
        await gate(db_session, gated, requirement_type=RequirementType.MIN_XP, threshold=300)

        await record_solve(db_session, user, first, xp=100)
        # Solve gate met, XP gate not.
        assert (await client.get(f"/api/challenges/{gated.id}")).json()["locked"] is True

        await bank_xp(db_session, user, 300)
        assert (await client.get(f"/api/challenges/{gated.id}")).json()["locked"] is False


class TestValidation:
    async def test_a_gate_missing_its_fields_is_refused(self, db_session: AsyncSession) -> None:
        challenge = await make_challenge(db_session)

        with pytest.raises(unlock_service.InvalidRequirement):
            await gate(db_session, challenge, requirement_type=RequirementType.MIN_XP)

        with pytest.raises(unlock_service.InvalidRequirement):
            await gate(
                db_session,
                challenge,
                requirement_type=RequirementType.SKILL_LEVEL,
                threshold=2,
            )

    async def test_fields_foreign_to_the_type_are_refused(self, db_session: AsyncSession) -> None:
        challenge = await make_challenge(db_session)
        other = await make_challenge(db_session)

        with pytest.raises(unlock_service.InvalidRequirement):
            await gate(
                db_session,
                challenge,
                requirement_type=RequirementType.MIN_XP,
                threshold=100,
                required_challenge_id=other.id,
            )

    async def test_a_requirement_targets_exactly_one_thing(self, db_session: AsyncSession) -> None:
        challenge = await make_challenge(db_session)
        category = await make_category(db_session)

        with pytest.raises(unlock_service.InvalidRequirement):
            await unlock_service.add_requirement(
                db_session,
                challenge_id=challenge.id,
                category_id=category.id,
                requirement_type=RequirementType.MIN_XP,
                threshold=100,
            )

        with pytest.raises(unlock_service.InvalidRequirement):
            await unlock_service.add_requirement(
                db_session,
                requirement_type=RequirementType.MIN_XP,
                threshold=100,
            )

    async def test_an_unknown_referenced_row_is_refused(self, db_session: AsyncSession) -> None:
        from app.errors import NotFoundError

        challenge = await make_challenge(db_session)

        with pytest.raises(NotFoundError):
            await gate(
                db_session,
                challenge,
                requirement_type=RequirementType.SKILL_LEVEL,
                required_skill_id=uuid.uuid4(),
                threshold=2,
            )


class TestAdminApi:
    async def test_an_admin_adds_and_removes_a_gate(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await player(db_session, client, sign_in, role=UserRole.ADMIN)
        challenge = await make_challenge(db_session)

        created = await client.post(
            f"/api/admin/challenges/{challenge.id}/requirements",
            json={"requirement_type": "min_xp", "threshold": 250},
        )
        assert created.status_code == 201
        requirement_id = created.json()["id"]

        listed = await client.get(f"/api/admin/challenges/{challenge.id}/requirements")
        assert [r["requirement_type"] for r in listed.json()] == ["min_xp"]

        removed = await client.delete(f"/api/admin/requirements/{requirement_id}")
        assert removed.status_code == 200
        assert (await client.get(f"/api/admin/challenges/{challenge.id}/requirements")).json() == []

    async def test_a_player_cannot_write_gates(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await player(db_session, client, sign_in)
        challenge = await make_challenge(db_session)

        response = await client.post(
            f"/api/admin/challenges/{challenge.id}/requirements",
            json={"requirement_type": "min_xp", "threshold": 250},
        )

        assert response.status_code == 403
