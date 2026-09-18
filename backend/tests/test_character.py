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
from tests.factories import (
    make_category,
    make_challenge,
    make_team,
    make_user,
    record_solve,
)

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


class TestIdentity:
    """The player info block's two new fields (spec 060 §6)."""

    async def test_the_sheet_names_the_party_it_is_in(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        """On the sheet rather than left to the session, so it describes the
        character on its own."""
        user = await player(db_session, client, sign_in)
        team = await make_team(db_session, user, name="The Mimics")

        sheet = (await client.get("/api/character/me")).json()

        assert sheet["party"] == {"id": str(team.id), "name": "The Mimics"}

    async def test_a_partyless_player_reports_null(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await player(db_session, client, sign_in)

        assert (await client.get("/api/character/me")).json()["party"] is None

    async def test_a_disbanded_party_does_not_count(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        from datetime import UTC, datetime

        user = await player(db_session, client, sign_in)
        team = await make_team(db_session, user, name="Gone")
        team.disbanded_at = datetime.now(UTC).replace(tzinfo=None)
        await db_session.flush()

        assert (await client.get("/api/character/me")).json()["party"] is None

    async def test_the_sheet_carries_the_worn_title(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        """The name plate everybody else sees on the board (059) — its owner
        could only find it inside the loot inventory before 060."""
        from app.models.notification import LootItem, LootRarity

        user = await player(db_session, client, sign_in)
        item = LootItem(pool_key="test", rarity=LootRarity.GOLD, title="the Unbothered")
        db_session.add(item)
        await db_session.flush()
        user.equipped_title_id = item.id
        await db_session.flush()

        assert (await client.get("/api/character/me")).json()["equipped_title"] == "the Unbothered"

    async def test_wearing_nothing_reports_null(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await player(db_session, client, sign_in)

        assert (await client.get("/api/character/me")).json()["equipped_title"] is None

    async def test_both_fields_reach_somebody_else_s_sheet_too(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        """Added for the own sheet by spec 060, and carried to the public one by
        061 — a party and a worn title are what a player shows the room."""
        await player(db_session, client, sign_in)
        other = await make_user(db_session, status=UserStatus.ACTIVE)
        team = await make_team(db_session, other, name="Theirs")

        sheet = (await client.get(f"/api/character/{other.id}")).json()

        assert sheet["party"] == {"id": str(team.id), "name": "Theirs"}
        assert sheet["equipped_title"] is None


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

    async def test_a_public_sheet_omits_every_form_of_xp(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        """Rank arrives with spec 061 — XP never does, on any surface but the
        player's own sheet (spec 059 §2)."""
        await player(db_session, client, sign_in)
        other = await make_user(db_session, status=UserStatus.ACTIVE)

        sheet = (await client.get(f"/api/character/{other.id}")).json()

        assert "rank" in sheet
        assert not any("xp" in key for key in sheet)
        assert "score" not in sheet

    async def test_an_unknown_player_is_a_404(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        import uuid

        await player(db_session, client, sign_in)

        assert (await client.get(f"/api/character/{uuid.uuid4()}")).status_code == 404
