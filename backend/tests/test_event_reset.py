"""Resetting an event's play data, and zones that stay put (spec 043)."""

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import AuditLog
from app.models.challenge import Category
from app.models.hint import Hint, HintUnlock
from app.models.notification import (
    Achievement,
    LootBox,
    LootBoxType,
    LootItem,
    LootRarity,
)
from app.models.play import Solve, Submission
from app.models.skill import Skill
from app.models.user import User, UserRole, UserStatus
from app.services import event_reset
from tests.factories import make_category, make_challenge, make_user, record_solve

pytestmark = pytest.mark.usefixtures("running_event")


async def as_admin(db_session, client, sign_in):
    user = await make_user(db_session, role=UserRole.ADMIN, status=UserStatus.ACTIVE)
    await sign_in(client, user)
    return user


async def rows(db: AsyncSession, table) -> int:
    return int(await db.scalar(select(func.count()).select_from(table)) or 0)


class TestZonesStayPut:
    async def test_deleting_the_last_challenge_leaves_the_zone(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        """This is the bug that made the CSV look broken: the zone was being
        destroyed, taking its ability mapping and its skills' grouping with it."""
        await as_admin(db_session, client, sign_in)
        zone = (
            await db_session.execute(select(Category).where(Category.name == "Networking"))
        ).scalar_one()
        ability_before, order_before = zone.ability, zone.display_order
        skills_before = await db_session.scalar(
            select(func.count()).select_from(Skill).where(Skill.category_id == zone.id)
        )
        challenge = await make_challenge(db_session, category=zone, title="Only One")

        response = await client.delete(f"/api/admin/challenges/{challenge.id}")

        assert response.status_code == 200
        still = (
            await db_session.execute(select(Category).where(Category.name == "Networking"))
        ).scalar_one_or_none()
        assert still is not None
        assert (still.ability, still.display_order) == (ability_before, order_before)
        assert (
            await db_session.scalar(
                select(func.count()).select_from(Skill).where(Skill.category_id == zone.id)
            )
            == skills_before
        )

    async def test_the_csv_then_imports_into_the_empty_zone(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        from app.services import challenge_csv

        await as_admin(db_session, client, sign_in)
        zone = (
            await db_session.execute(select(Category).where(Category.name == "Networking"))
        ).scalar_one()
        assert (
            await db_session.scalar(
                select(func.count()).select_from(Category).where(Category.id == zone.id)
            )
            == 1
        )

        report = await challenge_csv.import_csv(
            db_session, "category,title,difficulty\nNetworking,From CSV,easy\n"
        )

        assert report.ok, report.errors
        assert report.created == 1

    async def test_an_unknown_area_names_the_ones_that_exist(
        self, db_session: AsyncSession
    ) -> None:
        """A 242-row file refused over one typo should not leave an admin
        guessing which name was right."""
        from app.services import challenge_csv

        report = await challenge_csv.import_csv(
            db_session, "category,title,difficulty\nNetwroking,Typo,easy\n"
        )

        problem = next(e.problem for e in report.errors if e.column == "category")
        assert "Networking" in problem
        assert "not by import" in problem


class TestCounts:
    async def test_counts_report_every_group_without_writing(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        admin = await as_admin(db_session, client, sign_in)
        category = await make_category(db_session)
        challenge = await make_challenge(db_session, category=category, title="Solved Once")
        await record_solve(db_session, admin, challenge)

        body = (await client.get("/api/admin/event/play-data")).json()

        by_group = {row["group"]: row for row in body}
        assert len(by_group) == len(event_reset.ResetGroup)
        assert by_group["solves"]["rows"] == 1
        assert by_group["solves"]["label"] == "Solves"
        # Reading the counts must not empty anything.
        assert await rows(db_session, Solve) == 1


class TestReset:
    async def test_clearing_solves_unblocks_deleting_a_challenge(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        """The whole point: test play pins a scaffolding challenge, and this is
        how it is taken back."""
        admin = await as_admin(db_session, client, sign_in)
        category = await make_category(db_session)
        challenge = await make_challenge(db_session, category=category, title="Pinned")
        await record_solve(db_session, admin, challenge)

        blocked = await client.delete(f"/api/admin/challenges/{challenge.id}")
        assert blocked.status_code == 409

        await client.post("/api/admin/event/reset-play-data", json={"groups": ["solves"]})

        assert (await client.delete(f"/api/admin/challenges/{challenge.id}")).status_code == 200

    async def test_one_group_leaves_the_others_alone(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        admin = await as_admin(db_session, client, sign_in)
        category = await make_category(db_session)
        challenge = await make_challenge(db_session, category=category, title="Both")
        await record_solve(db_session, admin, challenge)
        db_session.add(
            Submission(
                user_id=admin.id,
                challenge_id=challenge.id,
                is_correct=True,
                submitted_value="x",
            )
        )
        await db_session.flush()

        await client.post("/api/admin/event/reset-play-data", json={"groups": ["solves"]})

        assert await rows(db_session, Solve) == 0
        # Submissions were not chosen, so they are still there.
        assert await rows(db_session, Submission) == 1

    async def test_everything_empties_every_group(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        admin = await as_admin(db_session, client, sign_in)
        category = await make_category(db_session)
        challenge = await make_challenge(db_session, category=category, title="Played")
        await record_solve(db_session, admin, challenge)
        hint = Hint(challenge_id=challenge.id, title="H", body="b", cost=10)
        db_session.add(hint)
        await db_session.flush()
        db_session.add(
            HintUnlock(
                user_id=admin.id,
                hint_id=hint.id,
                cost_charged=10,
                unlocked_at=challenge.created_at,
            )
        )
        await db_session.flush()

        response = await client.post(
            "/api/admin/event/reset-play-data",
            json={"groups": [g.value for g in event_reset.ResetGroup]},
        )

        assert response.status_code == 200
        assert await rows(db_session, Solve) == 0
        assert await rows(db_session, HintUnlock) == 0
        # Authored content and accounts survive — a reset means the event has
        # not happened yet, not that these people do not exist.
        assert await rows(db_session, Category) > 0
        assert await rows(db_session, Hint) == 1
        assert await rows(db_session, User) > 0
        assert await rows(db_session, AuditLog) > 0

    async def test_wiping_loot_unequips_but_keeps_the_catalogue(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        """`loot_item` is the catalogue of titles a box can yield, shared by
        everyone — content, not a drop. Only the awarded boxes go."""
        admin = await as_admin(db_session, client, sign_in)
        achievement = (await db_session.execute(select(Achievement))).scalars().first()
        item = LootItem(
            pool_key="boring",
            rarity=LootRarity.BRONZE,
            title="The Unmentionable",
        )
        db_session.add(item)
        await db_session.flush()
        catalogue_before = await rows(db_session, LootItem)
        db_session.add(
            LootBox(
                user_id=admin.id,
                achievement_id=achievement.id,
                box_type=LootBoxType.ADVENTURER,
                rarity=LootRarity.BRONZE,
                item_id=item.id,
            )
        )
        admin.equipped_title_id = item.id
        await db_session.flush()

        await client.post("/api/admin/event/reset-play-data", json={"groups": ["loot"]})

        await db_session.refresh(admin)
        assert admin.equipped_title_id is None
        assert await rows(db_session, LootBox) == 0
        # 380-odd seeded titles, which a reset has no business touching.
        assert await rows(db_session, LootItem) == catalogue_before

    async def test_ai_ladder_progress_clears_its_columns(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        admin = await as_admin(db_session, client, sign_in)
        admin.ai_ladder_level = 3
        await db_session.flush()

        await client.post("/api/admin/event/reset-play-data", json={"groups": ["ai_ladder"]})

        await db_session.refresh(admin)
        assert admin.ai_ladder_level is None
        assert admin.ai_ladder_leaked_at is None

    async def test_one_audit_entry_naming_the_groups(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await as_admin(db_session, client, sign_in)

        await client.post(
            "/api/admin/event/reset-play-data",
            json={"groups": ["solves", "submissions"]},
        )

        entries = (
            (
                await db_session.execute(
                    select(AuditLog).where(AuditLog.action == "event.reset_play_data")
                )
            )
            .scalars()
            .all()
        )
        assert len(entries) == 1
        assert entries[0].meta["groups"] == ["solves", "submissions"]


class TestGuards:
    async def test_no_groups_is_refused(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        """An empty list must never be read as "everything" — the difference
        between one group and all fourteen cannot come down to a missing field."""
        await as_admin(db_session, client, sign_in)

        response = await client.post("/api/admin/event/reset-play-data", json={"groups": []})

        assert response.status_code == 422

    async def test_an_unknown_group_is_refused_by_name(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await as_admin(db_session, client, sign_in)

        response = await client.post(
            "/api/admin/event/reset-play-data", json={"groups": ["everything"]}
        )

        assert response.status_code == 422
        assert "solves" in response.text

    async def test_a_player_may_not_reset(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        user = await make_user(db_session, role=UserRole.PLAYER, status=UserStatus.ACTIVE)
        await sign_in(client, user)

        assert (await client.get("/api/admin/event/play-data")).status_code == 403
        assert (
            await client.post("/api/admin/event/reset-play-data", json={"groups": ["solves"]})
        ).status_code == 403
