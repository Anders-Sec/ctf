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
