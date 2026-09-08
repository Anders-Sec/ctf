"""Character classes on the sheet: choosing, the level gate, the suggested-class
nudge, and the guarantee that class never touches scoring (spec 016)."""

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.models.challenge import ScoringMode
from app.models.character_class import CharacterClass
from app.models.skill import Skill
from app.models.user import UserStatus
from app.redis import get_redis
from app.services import scoreboard_cache
from tests.factories import make_category, make_challenge, make_user, record_solve

pytestmark = pytest.mark.usefixtures("running_event")


@pytest.fixture(autouse=True)
async def clear_scoreboard_cache(settings: Settings):
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


async def make_class(db_session, name: str, *, affinity: Skill | None = None) -> CharacterClass:
    character_class = CharacterClass(name=name, affinity_skill_id=affinity.id if affinity else None)
    db_session.add(character_class)
    await db_session.flush()
    return character_class


async def reach_unlock_level(db_session, user) -> None:
    """Bank enough XP to clear the default unlock level (3 = 600 XP)."""
    challenge = await make_challenge(db_session, scoring=ScoringMode.STATIC, initial_points=600)
    await record_solve(db_session, user, challenge)


class TestChoosingAClass:
    async def test_a_player_past_the_gate_sets_and_clears_their_class(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        user = await player(db_session, client, sign_in)
        await reach_unlock_level(db_session, user)
        rogue = await make_class(db_session, "Rogue")

        chosen = await client.put("/api/character/class", json={"class_id": str(rogue.id)})
        assert chosen.status_code == 200
        assert chosen.json()["character_class"]["name"] == "Rogue"

        cleared = await client.put("/api/character/class", json={"class_id": None})
        assert cleared.json()["character_class"] is None

    async def test_below_the_gate_a_first_choice_is_refused(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await player(db_session, client, sign_in)  # level 1, no XP
        rogue = await make_class(db_session, "Rogue")

        blocked = await client.put("/api/character/class", json={"class_id": str(rogue.id)})

        assert blocked.status_code == 403
        assert blocked.json()["error"]["code"] == "class_locked"
        sheet = (await client.get("/api/character/me")).json()
        assert sheet["class_unlocked"] is False
        assert sheet["class_unlock_level"] == 3

    async def test_an_already_earned_class_can_change_even_below_the_gate(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        """A later adjustment might drop a player's level; they keep their class."""
        user = await player(db_session, client, sign_in)  # level 1
        rogue = await make_class(db_session, "Rogue")
        wizard = await make_class(db_session, "Wizard")
        # They already earned Rogue at some earlier, higher level.
        user.character_class_id = rogue.id
        await db_session.flush()

        changed = await client.put("/api/character/class", json={"class_id": str(wizard.id)})

        assert changed.status_code == 200
        assert changed.json()["character_class"]["name"] == "Wizard"

    async def test_an_unknown_class_is_refused(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        user = await player(db_session, client, sign_in)
        await reach_unlock_level(db_session, user)

        response = await client.put("/api/character/class", json={"class_id": str(uuid.uuid4())})

        assert response.status_code == 404


class TestSuggestedClass:
    async def _solve_in_skill(self, db_session, user, skill, points):
        category = await make_category(db_session, name=f"cat-{uuid.uuid4().hex[:8]}")
        category.skill_id = skill.id
        await db_session.flush()
        challenge = await make_challenge(
            db_session, category=category, scoring=ScoringMode.STATIC, initial_points=points
        )
        await record_solve(db_session, user, challenge)

    async def test_the_suggestion_follows_the_top_skill(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        user = await player(db_session, client, sign_in)
        hacking = await make_skill(db_session, "Hacking", order=1)
        crypto = await make_skill(db_session, "Crypto", order=2)
        await make_class(db_session, "Rogue", affinity=hacking)
        await make_class(db_session, "Wizard", affinity=crypto)

        await self._solve_in_skill(db_session, user, hacking, 300)
        await self._solve_in_skill(db_session, user, crypto, 100)

        first = (await client.get("/api/character/me")).json()["suggested_class"]
        assert first["name"] == "Rogue"
        assert first["from_skill"] == "Hacking"
        assert "Rogue" in first["narration"]
        assert "**" not in first["narration"]  # System AI voice: plain text

        # Overtake Hacking with more Crypto; the suggestion follows.
        await self._solve_in_skill(db_session, user, crypto, 500)
        second = (await client.get("/api/character/me")).json()["suggested_class"]
        assert second["name"] == "Wizard"

    async def test_no_skill_xp_means_no_suggestion(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await player(db_session, client, sign_in)
        await make_class(db_session, "Rogue")

        assert (await client.get("/api/character/me")).json()["suggested_class"] is None

    async def test_a_top_skill_with_no_class_yields_no_suggestion(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        user = await player(db_session, client, sign_in)
        hacking = await make_skill(db_session, "Hacking")
        # No class points at Hacking.
        await self._solve_in_skill(db_session, user, hacking, 300)

        assert (await client.get("/api/character/me")).json()["suggested_class"] is None


class TestClassNeverScores:
    async def test_choosing_a_class_does_not_move_xp_or_level(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        user = await player(db_session, client, sign_in)
        await reach_unlock_level(db_session, user)
        rogue = await make_class(db_session, "Rogue")

        before = (await client.get("/api/character/me")).json()

        await client.put("/api/character/class", json={"class_id": str(rogue.id)})
        after_pick = (await client.get("/api/character/me")).json()

        await client.put("/api/character/class", json={"class_id": None})
        after_clear = (await client.get("/api/character/me")).json()

        for snapshot in (after_pick, after_clear):
            assert snapshot["total_xp"] == before["total_xp"]
            assert snapshot["level"] == before["level"]
            assert snapshot["rank"] == before["rank"]
