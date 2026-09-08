"""Character sheet endpoints (spec 015)."""

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.models.challenge import ScoringMode
from app.models.skill import Skill
from app.models.user import UserStatus
from app.redis import get_redis
from app.services import scoreboard_cache
from tests.factories import make_category, make_challenge, make_user, record_solve

pytestmark = pytest.mark.usefixtures("running_event")


@pytest.fixture(autouse=True)
async def clear_scoreboard_cache(settings: Settings):
    """Rank is read from the scoreboard cache, which outlives a rolled-back
    transaction — clear it so a stale board from a prior test cannot leak in."""
    redis = get_redis(settings)

    async def flush() -> None:
        await redis.delete(
            scoreboard_cache.CACHE_KEY,
            scoreboard_cache.DIRTY_KEY,
            scoreboard_cache.LOCK_KEY,
        )

    await flush()
    yield
    await flush()


async def player(db_session, client, sign_in, **kwargs):
    kwargs.setdefault("status", UserStatus.ACTIVE)
    user = await make_user(db_session, **kwargs)
    await sign_in(client, user)
    return user


async def make_skill(db_session, name: str, order: int = 0) -> Skill:
    skill = Skill(name=name, display_order=order)
    db_session.add(skill)
    await db_session.flush()
    return skill


class TestMySheet:
    async def test_the_sheet_reports_total_xp_and_level(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        user = await player(db_session, client, sign_in)
        challenge = await make_challenge(db_session, scoring=ScoringMode.STATIC, initial_points=200)
        await record_solve(db_session, user, challenge)  # banks 200 → level 2

        sheet = (await client.get("/api/character/me")).json()

        assert sheet["total_xp"] == 200
        assert sheet["level"] == 2
        # 200 is exactly the L2 threshold; the next level (L3) sits at 600.
        assert sheet["xp_into_level"] == 0
        assert sheet["xp_to_next"] == 400

    async def test_skill_xp_is_grouped_and_partitions_the_total(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        user = await player(db_session, client, sign_in)
        hacking = await make_skill(db_session, "Hacking", order=1)
        # Two categories feeding one skill.
        ai = await make_category(db_session, name="AI Prompt Injection")
        red = await make_category(db_session, name="Red Teaming")
        ai.skill_id = hacking.id
        red.skill_id = hacking.id
        # A category mapped to no skill: counts toward total, under no skill.
        loose = await make_category(db_session, name="Trivia")
        await db_session.flush()

        for cat, pts in ((ai, 300), (red, 300), (loose, 100)):
            ch = await make_challenge(
                db_session, category=cat, scoring=ScoringMode.STATIC, initial_points=pts
            )
            await record_solve(db_session, user, ch)

        sheet = (await client.get("/api/character/me")).json()

        assert sheet["total_xp"] == 700
        hacking_slice = next(s for s in sheet["skills"] if s["name"] == "Hacking")
        assert hacking_slice["xp"] == 600  # 300 + 300, the loose 100 is not here
        assert hacking_slice["level"] == 3  # 600 is the L3 threshold

    async def test_the_sheet_carries_board_rank(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        leader = await make_user(db_session, status=UserStatus.ACTIVE)
        big = await make_challenge(db_session, scoring=ScoringMode.STATIC, initial_points=1000)
        await record_solve(db_session, leader, big)

        me = await player(db_session, client, sign_in)
        small = await make_challenge(db_session, scoring=ScoringMode.STATIC, initial_points=100)
        await record_solve(db_session, me, small)

        sheet = (await client.get("/api/character/me")).json()

        assert sheet["rank"] == 2


class TestPublicSheet:
    async def test_another_players_sheet_shows_level_and_skills(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await player(db_session, client, sign_in)
        hacking = await make_skill(db_session, "Hacking")
        cat = await make_category(db_session, name="Web")
        cat.skill_id = hacking.id
        await db_session.flush()
        other = await make_user(db_session, display_name="Sir Solves", status=UserStatus.ACTIVE)
        ch = await make_challenge(
            db_session, category=cat, scoring=ScoringMode.STATIC, initial_points=200
        )
        await record_solve(db_session, other, ch)

        sheet = (await client.get(f"/api/character/{other.id}")).json()

        assert sheet["display_name"] == "Sir Solves"
        assert sheet["level"] == 2
        skill = next(s for s in sheet["skills"] if s["name"] == "Hacking")
        assert skill["level"] == 2

    async def test_a_public_sheet_omits_rank_and_progress(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await player(db_session, client, sign_in)
        other = await make_user(db_session, status=UserStatus.ACTIVE)

        sheet = (await client.get(f"/api/character/{other.id}")).json()

        assert "rank" not in sheet
        assert "total_xp" not in sheet
        assert all("xp_to_next" not in s for s in sheet["skills"])

    async def test_an_unknown_player_is_a_404(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        import uuid

        await player(db_session, client, sign_in)

        assert (await client.get(f"/api/character/{uuid.uuid4()}")).status_code == 404
