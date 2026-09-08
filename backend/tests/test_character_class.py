"""Character classes on the sheet: choosing, the level gate, and the guarantee
that class never touches scoring (spec 016; the suggestion was retired by 018)."""

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.models.challenge import ScoringMode
from app.models.character_class import (
    CharacterClass,
    ClassPreference,
    ClassRequirement,
    Rarity,
)
from app.models.skill import ChallengeSkill, Skill
from app.models.user import UserStatus
from app.redis import get_redis
from app.services import scoreboard_cache
from tests.factories import make_challenge, make_user, record_solve

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


async def make_class(
    db_session,
    name: str,
    *,
    rarity: Rarity = Rarity.COMMON,
    abilities: tuple = (),
    skills: tuple = (),
    requires: tuple = (),
) -> CharacterClass:
    character_class = CharacterClass(name=name, rarity=rarity)
    db_session.add(character_class)
    await db_session.flush()
    for ability in abilities:
        db_session.add(ClassPreference(class_id=character_class.id, ability=ability))
    for skill in skills:
        db_session.add(ClassPreference(class_id=character_class.id, skill_id=skill.id))
    for skill, level in requires:
        db_session.add(
            ClassRequirement(class_id=character_class.id, skill_id=skill.id, min_level=level)
        )
    await db_session.flush()
    await db_session.refresh(character_class)
    return character_class


async def make_skill(db_session, name: str) -> Skill:
    skill = Skill(name=name)
    db_session.add(skill)
    await db_session.flush()
    return skill


async def solve_worth(db_session, user, skill, points: int) -> None:
    """Bank `points` XP through one skill, so its level moves."""
    challenge = await make_challenge(db_session, scoring=ScoringMode.STATIC, initial_points=points)
    db_session.add(ChallengeSkill(challenge_id=challenge.id, skill_id=skill.id))
    await db_session.flush()
    await record_solve(db_session, user, challenge)


async def reach_unlock_level(db_session, user) -> None:
    """Bank enough XP to clear the default unlock level (5 = 2,000 XP)."""
    challenge = await make_challenge(db_session, scoring=ScoringMode.STATIC, initial_points=2000)
    await record_solve(db_session, user, challenge)


class TestChoosingAClass:
    async def test_a_player_past_the_gate_sets_and_clears_their_class(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        user = await player(db_session, client, sign_in)
        await reach_unlock_level(db_session, user)
        rogue = await make_class(db_session, "Test Rogue")

        chosen = await client.put("/api/character/class", json={"class_id": str(rogue.id)})
        assert chosen.status_code == 200
        assert chosen.json()["character_class"]["name"] == "Test Rogue"

        cleared = await client.put("/api/character/class", json={"class_id": None})
        assert cleared.json()["character_class"] is None

    async def test_below_the_gate_a_first_choice_is_refused(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await player(db_session, client, sign_in)  # level 1, no XP
        rogue = await make_class(db_session, "Test Rogue")

        blocked = await client.put("/api/character/class", json={"class_id": str(rogue.id)})

        assert blocked.status_code == 403
        assert blocked.json()["error"]["code"] == "class_locked"
        sheet = (await client.get("/api/character/me")).json()
        assert sheet["class_unlocked"] is False
        assert sheet["class_unlock_level"] == 5

    async def test_an_already_earned_class_can_change_even_below_the_gate(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        """A later adjustment might drop a player's level; they keep their class."""
        user = await player(db_session, client, sign_in)  # level 1
        rogue = await make_class(db_session, "Test Rogue")
        wizard = await make_class(db_session, "Test Wizard")
        # They already earned Test Rogue at some earlier, higher level.
        user.character_class_id = rogue.id
        await db_session.flush()

        changed = await client.put("/api/character/class", json={"class_id": str(wizard.id)})

        assert changed.status_code == 200
        assert changed.json()["character_class"]["name"] == "Test Wizard"

    async def test_an_unknown_class_is_refused(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        user = await player(db_session, client, sign_in)
        await reach_unlock_level(db_session, user)

        response = await client.put("/api/character/class", json={"class_id": str(uuid.uuid4())})

        assert response.status_code == 404

    async def test_the_roster_lists_classes_for_the_picker(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await player(db_session, client, sign_in)
        await make_class(db_session, "Test Rogue")
        await make_class(db_session, "Test Wizard")

        roster = await client.get("/api/character/classes")

        assert roster.status_code == 200
        names = {c["name"] for c in roster.json()}
        assert {"Test Rogue", "Test Wizard"} <= names


class TestClassNeverScores:
    async def test_choosing_a_class_does_not_move_xp_or_level(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        user = await player(db_session, client, sign_in)
        await reach_unlock_level(db_session, user)
        rogue = await make_class(db_session, "Test Rogue")

        before = (await client.get("/api/character/me")).json()

        await client.put("/api/character/class", json={"class_id": str(rogue.id)})
        after_pick = (await client.get("/api/character/me")).json()

        await client.put("/api/character/class", json={"class_id": None})
        after_clear = (await client.get("/api/character/me")).json()

        for snapshot in (after_pick, after_clear):
            assert snapshot["total_xp"] == before["total_xp"]
            assert snapshot["level"] == before["level"]
            assert snapshot["rank"] == before["rank"]


class TestLockedClassesAreInvisible:
    """024 makes the roster a mystery: a class a player has not earned must not
    appear at all - not greyed, not counted."""

    async def test_a_class_whose_requirement_is_unmet_is_absent(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        user = await player(db_session, client, sign_in)
        await reach_unlock_level(db_session, user)
        skill = await make_skill(db_session, "Test Lockpicking")
        await make_class(db_session, "Test Locked", requires=((skill, 9),))
        await make_class(db_session, "Test Open")

        roster = await client.get("/api/character/classes")
        names = {c["name"] for c in roster.json()}

        assert "Test Open" in names
        assert "Test Locked" not in names

    async def test_meeting_the_requirement_reveals_it(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        user = await player(db_session, client, sign_in)
        skill = await make_skill(db_session, "Test Safecracking")
        await make_class(db_session, "Test Gated", requires=((skill, 2),))
        await solve_worth(db_session, user, skill, 200)

        roster = await client.get("/api/character/classes")

        assert "Test Gated" in {c["name"] for c in roster.json()}

    async def test_a_multi_requirement_class_needs_all_of_them(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        user = await player(db_session, client, sign_in)
        one = await make_skill(db_session, "Test Alpha Craft")
        two = await make_skill(db_session, "Test Beta Craft")
        await make_class(
            db_session, "Test Mythic", rarity=Rarity.MYTHIC, requires=((one, 2), (two, 2))
        )
        await solve_worth(db_session, user, one, 200)

        roster = await client.get("/api/character/classes")

        # One of two met is not met.
        assert "Test Mythic" not in {c["name"] for c in roster.json()}


class TestTheRecommender:
    async def test_a_skill_target_class_can_win(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        """Ability XP pools whole categories, so it dwarfs any single skill's.
        Scoring each target against the player's own best in that dimension is
        what keeps a skill-target class able to win at all."""
        user = await player(db_session, client, sign_in)
        skill = await make_skill(db_session, "Test Packet Reading")
        await solve_worth(db_session, user, skill, 2000)
        await make_class(db_session, "Test Skill Class", skills=(skill,))

        sheet = await client.get("/api/character/me")
        suggested = sheet.json()["suggested_class"]

        assert suggested is not None
        assert suggested["name"] == "Test Skill Class"

    async def test_it_never_suggests_a_locked_class(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        user = await player(db_session, client, sign_in)
        skill = await make_skill(db_session, "Test Deep Craft")
        # 200 XP is about skill level 3; the class below wants 15.
        await solve_worth(db_session, user, skill, 200)
        # Perfectly matched, but gated far above what this player has.
        await make_class(db_session, "Test Unreachable", skills=(skill,), requires=((skill, 15),))

        sheet = await client.get("/api/character/me")
        suggested = sheet.json()["suggested_class"]

        assert suggested is None or suggested["name"] != "Test Unreachable"

    async def test_it_speaks_in_the_system_ai_voice(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        user = await player(db_session, client, sign_in)
        skill = await make_skill(db_session, "Test Log Reading")
        await solve_worth(db_session, user, skill, 2000)
        await make_class(db_session, "Test Analyst Class", skills=(skill,))

        sheet = await client.get("/api/character/me")
        line = sheet.json()["suggested_class_line"]

        # Deterministic server-side copy, not a model call: no latency, no token
        # cost, and no path for a challenge answer to reach a prompt.
        assert line is not None
        assert "Test Log Reading" in line
        assert "Test Analyst Class" in line

    async def test_no_xp_means_no_suggestion(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await player(db_session, client, sign_in)
        await make_class(db_session, "Test Idle")

        sheet = await client.get("/api/character/me")

        assert sheet.json()["suggested_class"] is None
        assert sheet.json()["suggested_class_line"] is None


class TestRarityIsPresentationOnly:
    async def test_rarity_rides_along_but_gates_nothing(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        user = await player(db_session, client, sign_in)
        await reach_unlock_level(db_session, user)
        mythic = await make_class(db_session, "Test Shiny", rarity=Rarity.MYTHIC)

        roster = await client.get("/api/character/classes")
        row = next(c for c in roster.json() if c["name"] == "Test Shiny")
        assert row["rarity"] == "mythic"

        # A mythic class with no requirements is pickable by anyone past the
        # level gate: rarity is a colour, never a gate.
        chosen = await client.put("/api/character/class", json={"class_id": str(mythic.id)})
        assert chosen.status_code == 200
        assert chosen.json()["character_class"]["rarity"] == "mythic"
