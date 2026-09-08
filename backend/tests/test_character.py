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

    async def test_abilities_partition_the_pool(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        """Every category feeds exactly one ability, so the scores partition the
        player's solve XP (spec 018)."""
        from app.models.challenge import Ability

        user = await player(db_session, client, sign_in)
        # Names the seed migration does not already use (spec 018 seeds 21).
        brawn = await make_category(db_session, name="Test Brawn", ability=Ability.STR)
        brains = await make_category(db_session, name="Test Brains", ability=Ability.INT)

        for cat, pts in ((brawn, 448), (brains, 112)):
            ch = await make_challenge(
                db_session, category=cat, scoring=ScoringMode.STATIC, initial_points=pts
            )
            await record_solve(db_session, user, ch)

        sheet = (await client.get("/api/character/me")).json()
        scores = {a["ability"]: a["score"] for a in sheet["abilities"]}

        assert sheet["total_xp"] == 560
        # 448 -> 12, 112 -> 10, and an untouched ability stays at the floor of 8.
        assert scores["str"] == 12
        assert scores["int"] == 10
        assert scores["cha"] == 8
        # Never an XP number for a skill, anywhere in the payload.
        assert all("xp" not in row for row in sheet["skills"])

    async def test_an_undiscovered_skill_is_redacted(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        """The real name must not reach the browser at all — some skills are meant
        to be rare surprises (spec 018)."""
        await player(db_session, client, sign_in)
        # A real seeded skill, unearned: exactly the case that must not leak.
        secret = "Reckless Double-Clicking"

        response = await client.get("/api/character/me")

        assert secret not in response.text
        row = next(r for r in response.json()["skills"] if not r["discovered"])
        assert row["level"] == 0
        assert row["name"] == "Undiscovered skill"

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
        from app.models.skill import ChallengeSkill

        await player(db_session, client, sign_in)
        hacking = await make_skill(db_session, "Test Lockpicking")
        cat = await make_category(db_session, name="Test Wing")
        other = await make_user(db_session, display_name="Sir Solves", status=UserStatus.ACTIVE)
        ch = await make_challenge(
            db_session, category=cat, scoring=ScoringMode.STATIC, initial_points=200
        )
        db_session.add(ChallengeSkill(challenge_id=ch.id, skill_id=hacking.id))
        await db_session.flush()
        await record_solve(db_session, other, ch)

        sheet = (await client.get(f"/api/character/{other.id}")).json()

        assert sheet["display_name"] == "Sir Solves"
        assert sheet["level"] == 2
        # Everything is fair game on a public sheet except undiscovered skills,
        # which are omitted rather than placeholdered (spec 018).
        assert {a["ability"] for a in sheet["abilities"]} == {
            "str",
            "dex",
            "con",
            "int",
            "wis",
            "cha",
        }
        assert all(row["discovered"] for row in sheet["skills"])

    async def test_a_public_sheet_omits_rank_and_progress(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await player(db_session, client, sign_in)
        other = await make_user(db_session, status=UserStatus.ACTIVE)

        sheet = (await client.get(f"/api/character/{other.id}")).json()

        assert "rank" not in sheet
        assert "total_xp" not in sheet

    async def test_an_unknown_player_is_a_404(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        import uuid

        await player(db_session, client, sign_in)

        assert (await client.get(f"/api/character/{uuid.uuid4()}")).status_code == 404
