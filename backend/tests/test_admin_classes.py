"""Admin character classes API (spec 016)."""

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

    async def test_a_duplicate_name_is_refused(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await as_role(db_session, client, sign_in, UserRole.ADMIN)
        await client.post("/api/admin/classes", json={"name": "Wizard"})

        dup = await client.post("/api/admin/classes", json={"name": "wizard"})

        assert dup.status_code == 409
        assert dup.json()["error"]["code"] == "class_exists"

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
