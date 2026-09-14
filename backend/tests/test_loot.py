"""Loot boxes: dropping, opening, uniqueness and the generated tier (spec 038)."""

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.challenge import BossTier
from app.models.notification import (
    Achievement,
    LootBox,
    LootBoxType,
    LootItem,
    LootRarity,
)
from app.models.user import UserStatus
from app.services import achievements as engine
from app.services import loot
from tests.factories import make_category, make_challenge, make_user, record_solve

pytestmark = pytest.mark.usefixtures("running_event")


async def player(db_session):
    return await make_user(db_session, status=UserStatus.ACTIVE)


def model_down():
    """Settings with the model unavailable — the state the fallback exists for.

    Without this the local model answers and generation quietly supplies a
    unique title, so the exhaustion path is never reached.
    """
    return get_settings().model_copy(update={"ai_enabled": False})


async def a_box(db_session, user, *, box_type=LootBoxType.ADVENTURER, rarity=LootRarity.BRONZE):
    """A box wired to a throwaway achievement, so the unique constraint is happy.

    The code has to be unique per call, not per player: one player opening five
    boxes needs five distinct achievements behind them.
    """
    tag = uuid.uuid4().hex[:10]
    achievement = Achievement(
        code=f"loot_test_{tag}",
        name=f"Loot Test {tag}",
        description="x",
        earned_by="x",
        loot_box_type=box_type,
        loot_rarity=rarity,
    )
    db_session.add(achievement)
    await db_session.flush()
    box = await loot.award_box(db_session, user.id, achievement)
    await db_session.flush()
    return box


class TestDropping:
    async def test_an_achievement_that_pays_out_drops_a_box(self, db_session: AsyncSession) -> None:
        user = await player(db_session)
        achievement = (
            await db_session.execute(select(Achievement).where(Achievement.code == "first_blood"))
        ).scalar_one()

        box = await loot.award_box(db_session, user.id, achievement)

        assert box is not None
        assert box.box_type is LootBoxType.ADVENTURER
        assert box.rarity is LootRarity.BRONZE

    async def test_a_no_box_achievement_drops_nothing(self, db_session: AsyncSession) -> None:
        """36 of the 117 pay out a line instead, which is most of what keeps
        loot from feeling like a queue."""
        user = await player(db_session)
        achievement = (
            await db_session.execute(select(Achievement).where(Achievement.code == "literally"))
        ).scalar_one()

        assert achievement.loot_box_type is None
        assert achievement.no_loot_line
        assert await loot.award_box(db_session, user.id, achievement) is None

    async def test_a_boss_box_takes_its_tier_from_the_boss(self, db_session: AsyncSession) -> None:
        """031 already decided the tier; it is not configured twice."""
        user = await player(db_session)
        zone = await make_category(db_session, name="Loot Boss Zone")
        boss = await make_challenge(db_session, category=zone, title="Loot Boss")
        boss.boss_tier = BossTier.COUNTRY
        achievement = Achievement(
            code=f"boss_{zone.slug}",
            name="Boss: Loot Boss Zone",
            description="x",
            earned_by="x",
            loot_box_type=LootBoxType.BOSS,
        )
        db_session.add(achievement)
        await db_session.flush()

        box = await loot.award_box(db_session, user.id, achievement)

        assert box is not None
        assert box.rarity is LootRarity.LEGENDARY

    async def test_a_boss_achievement_with_no_boss_drops_nothing(
        self, db_session: AsyncSession
    ) -> None:
        user = await player(db_session)
        zone = await make_category(db_session, name="Loot Bossless Zone")
        achievement = Achievement(
            code=f"boss_{zone.slug}",
            name="Boss: Loot Bossless Zone",
            description="x",
            earned_by="x",
            loot_box_type=LootBoxType.BOSS,
        )
        db_session.add(achievement)
        await db_session.flush()

        assert await loot.award_box(db_session, user.id, achievement) is None

    async def test_earning_an_achievement_drops_a_box_end_to_end(
        self, db_session: AsyncSession
    ) -> None:
        user = await player(db_session)
        challenge = await make_challenge(db_session, title="Loot End To End")
        await record_solve(db_session, user, challenge)

        await engine.evaluate(db_session, user.id, engine.SOLVE)

        boxes = await loot.inventory(db_session, user.id)
        assert boxes


class TestOpening:
    async def test_opening_yields_a_title(self, db_session: AsyncSession) -> None:
        user = await player(db_session)
        box = await a_box(db_session, user)

        opened = await loot.open_box(db_session, user.id, box.id, settings=get_settings())

        assert opened.title
        assert opened.rarity == "bronze"

    async def test_opening_is_idempotent(self, db_session: AsyncSession) -> None:
        """A double-click must not reroll it. Players will absolutely try."""
        user = await player(db_session)
        box = await a_box(db_session, user)

        first = await loot.open_box(db_session, user.id, box.id, settings=get_settings())
        second = await loot.open_box(db_session, user.id, box.id, settings=get_settings())

        assert first.title == second.title

    async def test_somebody_else_s_box_cannot_be_opened(self, db_session: AsyncSession) -> None:
        owner = await player(db_session)
        thief = await player(db_session)
        box = await a_box(db_session, owner)

        from app.errors import NotFoundError

        with pytest.raises(NotFoundError):
            await loot.open_box(db_session, thief.id, box.id, settings=get_settings())

    async def test_a_low_tier_prefers_a_title_you_do_not_hold(
        self, db_session: AsyncSession
    ) -> None:
        user = await player(db_session)
        seen = set()
        for _ in range(5):
            box = await a_box(db_session, user)
            opened = await loot.open_box(db_session, user.id, box.id, settings=get_settings())
            seen.add(opened.title)

        # The bronze pool has twelve; five draws should all differ.
        assert len(seen) == 5


class TestUniqueness:
    async def test_a_high_tier_title_is_never_given_twice(self, db_session: AsyncSession) -> None:
        """Two identical legendary titles side by side on the board would undo
        the point of them."""
        settings = model_down()
        titles = []
        for _ in range(6):
            user = await player(db_session)
            box = await a_box(
                db_session,
                user,
                box_type=LootBoxType.CARTOGRAPHER,
                rarity=LootRarity.CELESTIAL,
            )
            opened = await loot.open_box(db_session, user.id, box.id, settings=settings)
            titles.append(opened.title)

        assert len(set(titles)) == len(titles)

    async def test_a_low_tier_title_may_repeat_across_players(
        self, db_session: AsyncSession
    ) -> None:
        """Bronze is one shared pool by design; duplicates there are expected."""
        settings = model_down()
        pool_size = await db_session.scalar(
            select(func.count(LootItem.id)).where(
                LootItem.pool_key == "common", LootItem.rarity == LootRarity.BRONZE
            )
        )
        titles = []
        for _ in range(pool_size + 2):
            user = await player(db_session)
            box = await a_box(db_session, user)
            opened = await loot.open_box(db_session, user.id, box.id, settings=settings)
            titles.append(opened.title)

        assert len(set(titles)) < len(titles)

    async def test_an_exhausted_unique_pool_refuses_rather_than_repeating(
        self, db_session: AsyncSession
    ) -> None:
        """The one place the feature says "not now". Handing out a duplicate to
        save face would be worse."""
        settings = model_down()
        pool_size = await db_session.scalar(
            select(func.count(LootItem.id)).where(
                LootItem.pool_key == "specialist",
                LootItem.rarity == LootRarity.CELESTIAL,
            )
        )
        for _ in range(pool_size):
            user = await player(db_session)
            box = await a_box(
                db_session,
                user,
                box_type=LootBoxType.SPECIALIST,
                rarity=LootRarity.CELESTIAL,
            )
            await loot.open_box(db_session, user.id, box.id, settings=settings)

        unlucky = await player(db_session)
        box = await a_box(
            db_session,
            unlucky,
            box_type=LootBoxType.SPECIALIST,
            rarity=LootRarity.CELESTIAL,
        )
        with pytest.raises(loot.BoxNotReady):
            await loot.open_box(db_session, unlucky.id, box.id, settings=settings)

        # And the box is still unopened, so it can be tried again later.
        await db_session.refresh(box)
        assert box.item_id is None


class TestGeneratedTitles:
    def test_flag_shaped_output_is_refused(self) -> None:
        """core.md forbids the System inventing loot, meaning flags. This is the
        one place it deliberately generates something called loot."""
        assert loot._clean("flag{free_points}") is None
        assert loot._clean("CTF{something}") is None
        assert loot._clean("Owner Of The Map") == "Owner Of The Map"

    def test_a_paragraph_is_refused(self) -> None:
        assert loot._clean("A" * 200) is None
        assert loot._clean("One Two Three Four Five Six Seven Eight") is None

    def test_surrounding_junk_is_trimmed(self) -> None:
        assert loot._clean('  "Owner Of The Map."  ') == "Owner Of The Map"
        assert loot._clean("Owner Of The Map\nand here is why") == "Owner Of The Map"


class TestWearingATitle:
    async def test_equipping_shows_it_on_the_board(self, db_session: AsyncSession) -> None:
        user = await player(db_session)
        box = await a_box(db_session, user)
        opened = await loot.open_box(db_session, user.id, box.id, settings=get_settings())
        item_id = (await db_session.get(LootBox, box.id)).item_id

        await loot.equip(db_session, user.id, item_id)

        worn = await loot.equipped_titles(db_session)
        assert worn[user.id] == opened.title

    async def test_a_title_you_do_not_hold_cannot_be_worn(self, db_session: AsyncSession) -> None:
        from app.errors import NotFoundError

        user = await player(db_session)
        someone_elses = await db_session.scalar(select(LootItem).limit(1))

        with pytest.raises(NotFoundError):
            await loot.equip(db_session, user.id, someone_elses.id)

    async def test_it_can_be_taken_off(self, db_session: AsyncSession) -> None:
        user = await player(db_session)
        box = await a_box(db_session, user)
        await loot.open_box(db_session, user.id, box.id, settings=get_settings())
        item_id = (await db_session.get(LootBox, box.id)).item_id
        await loot.equip(db_session, user.id, item_id)

        await loot.equip(db_session, user.id, None)

        assert user.id not in await loot.equipped_titles(db_session)


class TestTheCatalogue:
    async def test_every_live_combination_has_titles(self, db_session: AsyncSession) -> None:
        """An empty pool would mean a box that cannot open."""
        rows = (
            await db_session.execute(
                select(Achievement.loot_box_type, Achievement.loot_rarity).where(
                    Achievement.loot_box_type.is_not(None),
                    Achievement.loot_rarity.is_not(None),
                )
            )
        ).all()

        assert rows
        for box_type, rarity in set(rows):
            key = loot.pool_key(box_type, rarity)
            count = await db_session.scalar(
                select(func.count(LootItem.id)).where(
                    LootItem.pool_key == key, LootItem.rarity == rarity
                )
            )
            assert count, f"no titles for {box_type.value}/{rarity.value} (pool {key})"

    async def test_boss_boxes_have_a_pool_at_every_tier(self, db_session: AsyncSession) -> None:
        for rarity in LootRarity:
            count = await db_session.scalar(
                select(func.count(LootItem.id)).where(
                    LootItem.pool_key == "boss", LootItem.rarity == rarity
                )
            )
            assert count, f"no boss titles at {rarity.value}"


class TestApi:
    async def test_the_inventory_and_open_round_trip(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        user = await make_user(db_session, status=UserStatus.ACTIVE)
        await sign_in(client, user)
        box = await a_box(db_session, user)

        listed = await client.get("/api/loot/boxes")
        assert listed.status_code == 200
        assert any(b["id"] == str(box.id) for b in listed.json())

        opened = await client.post(f"/api/loot/boxes/{box.id}/open")
        assert opened.status_code == 200
        assert opened.json()["title"]

        titles = await client.get("/api/loot/titles")
        assert titles.json()[0]["title"] == opened.json()["title"]


class TestGenerationAbsorbsExhaustion:
    async def test_an_exhausted_pool_still_opens_when_the_model_answers(
        self, db_session: AsyncSession
    ) -> None:
        """Uniqueness creates exhaustion; generation is what absorbs it. This is
        the reason the top tiers are allowed to be one of a kind at all.

        Skipped when no model is reachable — it is the one test here that
        genuinely needs one.
        """
        settings = get_settings()
        if not (settings.ai_enabled and settings.ai_configured):
            pytest.skip("no model configured")

        pool_size = await db_session.scalar(
            select(func.count(LootItem.id)).where(
                LootItem.pool_key == "pathfinder",
                LootItem.rarity == LootRarity.LEGENDARY,
            )
        )
        for _ in range(pool_size):
            user = await player(db_session)
            box = await a_box(
                db_session,
                user,
                box_type=LootBoxType.PATHFINDER,
                rarity=LootRarity.LEGENDARY,
            )
            await loot.open_box(db_session, user.id, box.id, settings=model_down())

        # Authored pool is spent. With the model up, the box still opens.
        lucky = await player(db_session)
        box = await a_box(
            db_session,
            lucky,
            box_type=LootBoxType.PATHFINDER,
            rarity=LootRarity.LEGENDARY,
        )
        opened = await loot.open_box(db_session, lucky.id, box.id, settings=settings)

        assert opened.title
        assert opened.generated is True
