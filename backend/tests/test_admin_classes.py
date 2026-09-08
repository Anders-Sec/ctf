"""Admin character classes API (spec 016)."""

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.character_class import CharacterClass
from app.models.skill import Skill
from app.models.user import UserRole, UserStatus
from tests.factories import make_user

pytestmark = pytest.mark.usefixtures("running_event")


async def as_role(db_session, client, sign_in, role: UserRole):
    user = await make_user(db_session, role=role, status=UserStatus.ACTIVE)
    await sign_in(client, user)
    return user


async def make_skill(db_session, name: str) -> Skill:
    skill = Skill(name=name)
    db_session.add(skill)
    await db_session.flush()
    return skill


class TestClassCrud:
    async def test_an_admin_creates_and_lists_a_class(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await as_role(db_session, client, sign_in, UserRole.ADMIN)

        created = await client.post("/api/admin/classes", json={"name": "Rogue"})
        assert created.status_code == 201
        assert created.json()["name"] == "Rogue"

        listed = await client.get("/api/admin/classes")
        assert [c["name"] for c in listed.json()] == ["Rogue"]

    async def test_a_class_carries_an_affinity_skill(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await as_role(db_session, client, sign_in, UserRole.ADMIN)
        hacking = await make_skill(db_session, "Hacking")

        created = await client.post(
            "/api/admin/classes",
            json={"name": "Rogue", "affinity_skill_id": str(hacking.id)},
        )

        assert created.json()["affinity_skill_id"] == str(hacking.id)

    async def test_an_unknown_affinity_skill_is_refused(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        import uuid

        await as_role(db_session, client, sign_in, UserRole.ADMIN)

        response = await client.post(
            "/api/admin/classes",
            json={"name": "Rogue", "affinity_skill_id": str(uuid.uuid4())},
        )

        assert response.status_code == 404

    async def test_a_duplicate_name_is_refused(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await as_role(db_session, client, sign_in, UserRole.ADMIN)
        await client.post("/api/admin/classes", json={"name": "Wizard"})

        dup = await client.post("/api/admin/classes", json={"name": "wizard"})

        assert dup.status_code == 409
        assert dup.json()["error"]["code"] == "class_exists"

    async def test_the_affinity_can_be_cleared(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await as_role(db_session, client, sign_in, UserRole.ADMIN)
        hacking = await make_skill(db_session, "Hacking")
        class_id = (
            await client.post(
                "/api/admin/classes",
                json={"name": "Rogue", "affinity_skill_id": str(hacking.id)},
            )
        ).json()["id"]

        cleared = await client.patch(
            f"/api/admin/classes/{class_id}", json={"affinity_skill_id": None}
        )

        assert cleared.json()["affinity_skill_id"] is None

    async def test_a_player_cannot_write_classes(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await as_role(db_session, client, sign_in, UserRole.PLAYER)

        assert (await client.post("/api/admin/classes", json={"name": "Rogue"})).status_code == 403

    async def test_an_organizer_reads_but_cannot_write(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await as_role(db_session, client, sign_in, UserRole.ORGANIZER)

        assert (await client.get("/api/admin/classes")).status_code == 200
        assert (await client.post("/api/admin/classes", json={"name": "Rogue"})).status_code == 403

    async def test_deleting_a_skill_unlinks_it_as_an_affinity(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await as_role(db_session, client, sign_in, UserRole.ADMIN)
        hacking = await make_skill(db_session, "Hacking")
        class_id = (
            await client.post(
                "/api/admin/classes",
                json={"name": "Rogue", "affinity_skill_id": str(hacking.id)},
            )
        ).json()["id"]

        await client.delete(f"/api/admin/skills/{hacking.id}")

        character_class = await db_session.get(CharacterClass, class_id)
        await db_session.refresh(character_class)
        assert character_class is not None
        assert character_class.affinity_skill_id is None
