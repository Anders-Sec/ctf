"""Admin skills API and the category→skill map (spec 015)."""

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import UserRole, UserStatus
from tests.factories import make_user

pytestmark = pytest.mark.usefixtures("running_event")


async def as_role(db_session, client, sign_in, role: UserRole):
    user = await make_user(db_session, role=role, status=UserStatus.ACTIVE)
    await sign_in(client, user)
    return user


class TestSkillCrud:
    async def test_an_admin_creates_and_lists_a_skill(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await as_role(db_session, client, sign_in, UserRole.ADMIN)

        created = await client.post(
            "/api/admin/skills", json={"name": "Hacking", "display_order": 1}
        )
        assert created.status_code == 201
        assert created.json()["name"] == "Hacking"

        listed = await client.get("/api/admin/skills")
        # Seeded content means the list is never just ours (spec 018).
        assert "Hacking" in [s["name"] for s in listed.json()]

    async def test_a_duplicate_name_is_refused(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await as_role(db_session, client, sign_in, UserRole.ADMIN)
        await client.post("/api/admin/skills", json={"name": "Crypto"})

        # CITEXT: a case variation is still the same name.
        dup = await client.post("/api/admin/skills", json={"name": "crypto"})

        assert dup.status_code == 409
        assert dup.json()["error"]["code"] == "skill_exists"

    async def test_a_skill_can_be_renamed(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await as_role(db_session, client, sign_in, UserRole.ADMIN)
        skill_id = (await client.post("/api/admin/skills", json={"name": "Forensics"})).json()["id"]

        renamed = await client.patch(
            f"/api/admin/skills/{skill_id}", json={"name": "Digital Forensics"}
        )

        assert renamed.status_code == 200
        assert renamed.json()["name"] == "Digital Forensics"

    async def test_a_player_cannot_write_skills(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await as_role(db_session, client, sign_in, UserRole.PLAYER)

        assert (await client.post("/api/admin/skills", json={"name": "Hacking"})).status_code == 403

    async def test_an_organizer_reads_but_cannot_write(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await as_role(db_session, client, sign_in, UserRole.ORGANIZER)

        assert (await client.get("/api/admin/skills")).status_code == 200
        assert (await client.post("/api/admin/skills", json={"name": "Hacking"})).status_code == 403


class TestCategoryAbility:
    async def test_an_admin_points_a_category_at_an_ability(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        from tests.factories import make_category

        await as_role(db_session, client, sign_in, UserRole.ADMIN)
        category = await make_category(db_session, name="Test Wing")

        response = await client.patch(
            f"/api/admin/categories/{category.id}/ability", json={"ability": "str"}
        )

        assert response.status_code == 200
        assert response.json()["ability"] == "str"

    async def test_the_listing_carries_the_ability(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await as_role(db_session, client, sign_in, UserRole.ORGANIZER)

        rows = (await client.get("/api/admin/categories")).json()

        # The seed migration points every real category at an ability.
        assert rows and all(row["ability"] for row in rows)


class TestChallengeSkills:
    async def test_skills_are_replaced_wholesale(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        from app.models.skill import Skill
        from tests.factories import make_challenge

        await as_role(db_session, client, sign_in, UserRole.ADMIN)
        challenge = await make_challenge(db_session)
        first = Skill(name="Test Lockpicking")
        second = Skill(name="Test Bluffing")
        db_session.add_all([first, second])
        await db_session.flush()

        await client.put(
            f"/api/admin/challenges/{challenge.id}/skills",
            json={"skill_ids": [str(first.id), str(second.id)]},
        )
        both = (await client.get(f"/api/admin/challenges/{challenge.id}/skills")).json()
        assert len(both) == 2

        # PUT replaces rather than appends.
        await client.put(
            f"/api/admin/challenges/{challenge.id}/skills",
            json={"skill_ids": [str(second.id)]},
        )
        one = (await client.get(f"/api/admin/challenges/{challenge.id}/skills")).json()
        assert one == [str(second.id)]

    async def test_an_unknown_skill_is_refused(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        import uuid

        from tests.factories import make_challenge

        await as_role(db_session, client, sign_in, UserRole.ADMIN)
        challenge = await make_challenge(db_session)

        response = await client.put(
            f"/api/admin/challenges/{challenge.id}/skills",
            json={"skill_ids": [str(uuid.uuid4())]},
        )

        assert response.status_code == 404
