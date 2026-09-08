"""Admin skills API and the category→skill map (spec 015)."""

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.challenge import Category
from app.models.skill import Skill
from app.models.user import UserRole, UserStatus
from tests.factories import make_category, make_user

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
        assert [s["name"] for s in listed.json()] == ["Hacking"]

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

        assert (
            await client.post("/api/admin/skills", json={"name": "Hacking"})
        ).status_code == 403

    async def test_an_organizer_reads_but_cannot_write(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await as_role(db_session, client, sign_in, UserRole.ORGANIZER)

        assert (await client.get("/api/admin/skills")).status_code == 200
        assert (
            await client.post("/api/admin/skills", json={"name": "Hacking"})
        ).status_code == 403


class TestCategoryMapping:
    async def test_a_category_is_mapped_to_a_skill(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await as_role(db_session, client, sign_in, UserRole.ADMIN)
        category = await make_category(db_session, name="AI Prompt Injection")
        skill_id = (await client.post("/api/admin/skills", json={"name": "Hacking"})).json()["id"]

        mapped = await client.patch(
            f"/api/admin/categories/{category.id}/skill", json={"skill_id": skill_id}
        )

        assert mapped.status_code == 200
        assert mapped.json()["skill_id"] == skill_id

        await db_session.refresh(category)
        assert str(category.skill_id) == skill_id

    async def test_two_categories_can_feed_one_skill(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await as_role(db_session, client, sign_in, UserRole.ADMIN)
        ai = await make_category(db_session, name="AI Prompt Injection")
        red = await make_category(db_session, name="Red Teaming")
        skill_id = (await client.post("/api/admin/skills", json={"name": "Hacking"})).json()["id"]

        for cat in (ai, red):
            await client.patch(
                f"/api/admin/categories/{cat.id}/skill", json={"skill_id": skill_id}
            )

        rows = (await client.get("/api/admin/categories")).json()
        mapped = {r["name"]: r["skill_id"] for r in rows}
        assert mapped["AI Prompt Injection"] == skill_id
        assert mapped["Red Teaming"] == skill_id

    async def test_a_mapping_can_be_cleared(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await as_role(db_session, client, sign_in, UserRole.ADMIN)
        category = await make_category(db_session)
        skill_id = (await client.post("/api/admin/skills", json={"name": "Hacking"})).json()["id"]
        await client.patch(
            f"/api/admin/categories/{category.id}/skill", json={"skill_id": skill_id}
        )

        cleared = await client.patch(
            f"/api/admin/categories/{category.id}/skill", json={"skill_id": None}
        )

        assert cleared.json()["skill_id"] is None

    async def test_deleting_a_skill_unmaps_its_categories_without_losing_them(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await as_role(db_session, client, sign_in, UserRole.ADMIN)
        category = await make_category(db_session, name="Steganography")
        skill_id = (await client.post("/api/admin/skills", json={"name": "Forensics"})).json()["id"]
        await client.patch(
            f"/api/admin/categories/{category.id}/skill", json={"skill_id": skill_id}
        )

        deleted = await client.delete(f"/api/admin/skills/{skill_id}")
        assert deleted.status_code == 200

        # The category survives, un-mapped.
        await db_session.refresh(category)
        assert category.skill_id is None
        assert await db_session.get(Category, category.id) is not None
        assert await db_session.get(Skill, skill_id) is None
