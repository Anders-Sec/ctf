"""Admin CRUD over the achievement roster (spec 030)."""

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.notification import Achievement, AchievementAward
from app.models.user import UserRole, UserStatus
from app.services import achievements as engine
from app.services import admin_achievements as service
from tests.factories import make_user

pytestmark = pytest.mark.usefixtures("running_event")


async def as_role(db_session, client, sign_in, role: UserRole):
    user = await make_user(db_session, role=role, status=UserStatus.ACTIVE)
    await sign_in(client, user)
    return user


async def a_row(db_session, code: str = "test_code", **kwargs) -> Achievement:
    achievement = Achievement(
        code=code,
        name=kwargs.pop("name", f"Test {code}"),
        description=kwargs.pop("description", service.PLACEHOLDER),
        earned_by=kwargs.pop("earned_by", "Doing the thing."),
        **kwargs,
    )
    db_session.add(achievement)
    await db_session.flush()
    return achievement


class TestReading:
    async def test_the_seeded_roster_is_listed(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await as_role(db_session, client, sign_in, UserRole.ADMIN)

        rows = (await client.get("/api/admin/achievements")).json()

        assert len(rows) >= 100
        assert {"code", "name", "earned_by", "has_trigger", "needs_copy"} <= set(rows[0])

    async def test_a_row_without_a_trigger_is_marked_inert(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        """An achievement whose code has no trigger will never fire. That has to
        be visible here rather than discovered after the event."""
        await as_role(db_session, client, sign_in, UserRole.ADMIN)
        await a_row(db_session, code="no_such_trigger")

        rows = (await client.get("/api/admin/achievements")).json()
        row = next(r for r in rows if r["code"] == "no_such_trigger")

        assert row["has_trigger"] is False

    async def test_a_row_with_a_trigger_is_not(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await as_role(db_session, client, sign_in, UserRole.ADMIN)

        rows = (await client.get("/api/admin/achievements")).json()
        row = next(r for r in rows if r["code"] == "first_blood")

        assert row["has_trigger"] is True

    async def test_placeholder_descriptions_are_flagged(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await as_role(db_session, client, sign_in, UserRole.ADMIN)
        await a_row(db_session, code="written_up", description="Real copy, written by hand.")

        rows = (await client.get("/api/admin/achievements")).json()
        by_code = {r["code"]: r for r in rows}

        assert by_code["written_up"]["needs_copy"] is False
        assert by_code["first_blood"]["needs_copy"] is True

    async def test_the_triggers_endpoint_offers_unused_codes(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        """A trigger with no achievement is the mirror image of an achievement
        with no trigger, and just as worth surfacing."""
        await as_role(db_session, client, sign_in, UserRole.ADMIN)

        body = (await client.get("/api/admin/achievements/triggers")).json()

        assert set(body["registered"]) == set(engine.REGISTRY)
        # Every registered trigger is used by the seeded roster.
        assert body["unused"] == []

    async def test_a_player_may_not_read_the_roster(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await as_role(db_session, client, sign_in, UserRole.PLAYER)

        assert (await client.get("/api/admin/achievements")).status_code == 403


class TestWriting:
    async def test_an_admin_creates_one(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await as_role(db_session, client, sign_in, UserRole.ADMIN)

        created = await client.post(
            "/api/admin/achievements",
            json={
                "code": "brand_new",
                "name": "Brand New",
                "earned_by": "Doing something new.",
            },
        )

        assert created.status_code == 201
        body = created.json()
        assert body["earned_by"] == "Doing something new."
        # No trigger written yet — a legitimate work-in-progress state.
        assert body["has_trigger"] is False
        assert body["needs_copy"] is True

    async def test_editing_changes_the_copy(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await as_role(db_session, client, sign_in, UserRole.ADMIN)
        row = await a_row(db_session, code="to_edit")

        updated = await client.patch(
            f"/api/admin/achievements/{row.id}",
            json={"description": "Noted, for whatever that is worth."},
        )

        assert updated.status_code == 200
        assert updated.json()["needs_copy"] is False

    async def test_the_code_cannot_be_changed(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        """A code joins to a trigger and to every award already granted, so
        renaming it would silently orphan both."""
        await as_role(db_session, client, sign_in, UserRole.ADMIN)
        row = await a_row(db_session, code="immutable_code")

        updated = await client.patch(
            f"/api/admin/achievements/{row.id}",
            json={"code": "something_else", "name": "Renamed"},
        )

        assert updated.status_code == 200
        assert updated.json()["code"] == "immutable_code"
        assert updated.json()["name"] == "Renamed"

    async def test_a_duplicate_code_says_which_clashed(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await as_role(db_session, client, sign_in, UserRole.ADMIN)
        await a_row(db_session, code="taken_code", name="Taken Code")

        clash = await client.post(
            "/api/admin/achievements",
            json={"code": "taken_code", "name": "A Different Name"},
        )

        assert clash.status_code == 409
        assert clash.json()["error"]["code"] == "code_taken"

    async def test_a_duplicate_name_says_which_clashed(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await as_role(db_session, client, sign_in, UserRole.ADMIN)
        await a_row(db_session, code="some_code", name="Taken Name")

        clash = await client.post(
            "/api/admin/achievements",
            json={"code": "a_different_code", "name": "Taken Name"},
        )

        assert clash.status_code == 409
        assert clash.json()["error"]["code"] == "name_taken"

    async def test_deleting_an_unheld_one_works(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await as_role(db_session, client, sign_in, UserRole.ADMIN)
        row = await a_row(db_session, code="disposable")

        removed = await client.delete(f"/api/admin/achievements/{row.id}")

        assert removed.status_code == 200
        assert await db_session.get(Achievement, row.id) is None

    async def test_deleting_a_held_one_is_refused(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        """Taking an achievement back from a player who earned it is worse than
        living with a badly-named one, and the FK cascade would do exactly that."""
        await as_role(db_session, client, sign_in, UserRole.ADMIN)
        row = await a_row(db_session, code="already_held")
        holder = await make_user(db_session, status=UserStatus.ACTIVE)
        db_session.add(AchievementAward(achievement_id=row.id, user_id=holder.id))
        await db_session.flush()

        refused = await client.delete(f"/api/admin/achievements/{row.id}")

        assert refused.status_code == 409
        assert refused.json()["error"]["code"] == "achievement_held"
        assert await db_session.get(Achievement, row.id) is not None
        # And crucially the award survives.
        award = await db_session.scalar(
            select(AchievementAward).where(AchievementAward.achievement_id == row.id)
        )
        assert award is not None

    async def test_the_hold_count_is_reported(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await as_role(db_session, client, sign_in, UserRole.ADMIN)
        row = await a_row(db_session, code="counted")
        for _ in range(3):
            holder = await make_user(db_session, status=UserStatus.ACTIVE)
            db_session.add(AchievementAward(achievement_id=row.id, user_id=holder.id))
        await db_session.flush()

        rows = (await client.get("/api/admin/achievements")).json()

        assert next(r for r in rows if r["code"] == "counted")["held_by"] == 3

    async def test_a_player_may_not_write(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await as_role(db_session, client, sign_in, UserRole.PLAYER)

        refused = await client.post(
            "/api/admin/achievements", json={"code": "nope", "name": "Nope"}
        )

        assert refused.status_code == 403


class TestTheSeededRoster:
    async def test_every_registered_trigger_has_a_row(self, db_session: AsyncSession) -> None:
        """The mirror check: a trigger nobody seeded is dead code."""
        codes = set((await db_session.execute(select(Achievement.code))).scalars().all())

        assert set(engine.REGISTRY) <= codes

    async def test_descriptions_are_placeholders_awaiting_copy(
        self, db_session: AsyncSession
    ) -> None:
        """Seeding draft prose would risk placeholder copy reaching a player."""
        rows = list((await db_session.execute(select(Achievement))).scalars().all())

        assert rows
        assert all(r.description.strip() == service.PLACEHOLDER for r in rows)

    async def test_every_row_explains_what_earns_it(self, db_session: AsyncSession) -> None:
        rows = list((await db_session.execute(select(Achievement))).scalars().all())

        assert all(r.earned_by.strip() for r in rows)
