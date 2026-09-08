"""The dungeon map: zones, progression edges, layout and gating (specs 017, 019)."""

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.challenge import ChallengeState, RequirementType, ScoringMode
from app.models.user import UserStatus
from app.services import unlocks as unlock_service
from tests.factories import make_category, make_challenge, make_user, record_solve

pytestmark = pytest.mark.usefixtures("running_event")


async def player(db_session, client, sign_in, **kwargs):
    kwargs.setdefault("status", UserStatus.ACTIVE)
    user = await make_user(db_session, **kwargs)
    await sign_in(client, user)
    return user


async def gate_zone(db_session, category, **kwargs):
    return await unlock_service.add_requirement(db_session, category_id=category.id, **kwargs)


async def fetch(client) -> dict:
    response = await client.get("/api/map")
    assert response.status_code == 200
    return response.json()


def zone(board: dict, name: str) -> dict:
    return next(z for z in board["zones"] if z["name"] == name)


class TestZones:
    async def test_the_map_is_zones_not_challenges(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        """231 rooms is unreadable and cannot be illustrated; 22 zones can."""
        user = await player(db_session, client, sign_in)
        wing = await make_category(db_session, name="Test Wing")
        done = await make_challenge(db_session, category=wing, title="Done")
        await make_challenge(db_session, category=wing, title="Todo")
        await record_solve(db_session, user, done)

        board = await fetch(client)

        assert "rooms" not in board
        found = zone(board, "Test Wing")
        assert (found["cleared"], found["total"]) == (1, 2)
        assert found["slug"] == "test-wing"

    async def test_counts_ignore_challenges_the_player_cannot_see(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await player(db_session, client, sign_in)
        wing = await make_category(db_session, name="Test Wing")
        await make_challenge(db_session, category=wing, title="Open")
        await make_challenge(db_session, category=wing, title="Secret", state=ChallengeState.HIDDEN)

        board = await fetch(client)

        assert zone(board, "Test Wing")["total"] == 1
        assert "Secret" not in str(board)


class TestProgression:
    async def test_edges_are_the_progression_graph(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        """A corridor means 'this opens that', so it points source to gated."""
        await player(db_session, client, sign_in)
        first = await make_category(db_session, name="Test First")
        second = await make_category(db_session, name="Test Second")
        await gate_zone(
            db_session,
            second,
            requirement_type=RequirementType.PERCENT_IN_CATEGORY,
            required_category_id=first.id,
            threshold=50,
        )

        board = await fetch(client)

        assert {
            "from_zone_id": str(first.id),
            "to_zone_id": str(second.id),
        } in board["edges"]

    async def test_a_level_gate_is_a_condition_not_a_corridor(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        """It has no source zone, so a corridor from nowhere would be nonsense."""
        await player(db_session, client, sign_in)
        wing = await make_category(db_session, name="Test Deep")
        await gate_zone(
            db_session, wing, requirement_type=RequirementType.PLAYER_LEVEL, threshold=5
        )

        board = await fetch(client)
        found = zone(board, "Test Deep")

        assert found["locked"] is True
        assert found["unlock_requirements"][0]["description"] == "Reach level 5"
        assert all(e["to_zone_id"] != str(wing.id) for e in board["edges"])

    async def test_deeper_zones_layer_further_out(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await player(db_session, client, sign_in)
        first = await make_category(db_session, name="Test Tier1")
        second = await make_category(db_session, name="Test Tier2")
        third = await make_category(db_session, name="Test Tier3")
        for gated, source in ((second, first), (third, second)):
            await gate_zone(
                db_session,
                gated,
                requirement_type=RequirementType.PERCENT_IN_CATEGORY,
                required_category_id=source.id,
                threshold=50,
            )

        board = await fetch(client)

        # Rows are not fixed to tiers — a wide tier wraps onto extra rows — so
        # what matters is that depth always moves you further out.
        first = zone(board, "Test Tier1")["y"]
        second = zone(board, "Test Tier2")["y"]
        third = zone(board, "Test Tier3")["y"]
        assert first < second < third

    async def test_layout_is_deterministic_across_players(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await make_category(db_session, name="Test Alpha")
        await make_category(db_session, name="Test Bravo")

        await player(db_session, client, sign_in)
        first = {z["name"]: (z["x"], z["y"]) for z in (await fetch(client))["zones"]}
        await player(db_session, client, sign_in)
        second = {z["name"]: (z["x"], z["y"]) for z in (await fetch(client))["zones"]}

        assert first == second


class TestPercentGate:
    async def test_it_opens_at_the_threshold(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        user = await player(db_session, client, sign_in)
        source = await make_category(db_session, name="Test Source")
        gated = await make_category(db_session, name="Test Gated")
        await gate_zone(
            db_session,
            gated,
            requirement_type=RequirementType.PERCENT_IN_CATEGORY,
            required_category_id=source.id,
            threshold=50,
        )
        challenges = [
            await make_challenge(db_session, category=source, title=f"C{i}") for i in range(4)
        ]

        board = await fetch(client)
        assert zone(board, "Test Gated")["locked"] is True
        requirement = zone(board, "Test Gated")["unlock_requirements"][0]
        assert requirement["description"] == "Clear 50% of Test Source"
        assert requirement["progress"] == 0

        await record_solve(db_session, user, challenges[0])
        assert zone(await fetch(client), "Test Gated")["locked"] is True  # 25%

        await record_solve(db_session, user, challenges[1])
        assert zone(await fetch(client), "Test Gated")["locked"] is False  # 50%

    async def test_hiding_a_challenge_only_helps(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        """The denominator is visible challenges, so hiding one moves a player
        closer to the threshold and never further away (spec 019)."""
        user = await player(db_session, client, sign_in)
        source = await make_category(db_session, name="Test Source")
        gated = await make_category(db_session, name="Test Gated")
        await gate_zone(
            db_session,
            gated,
            requirement_type=RequirementType.PERCENT_IN_CATEGORY,
            required_category_id=source.id,
            threshold=50,
        )
        challenges = [
            await make_challenge(db_session, category=source, title=f"C{i}") for i in range(4)
        ]
        await record_solve(db_session, user, challenges[0])
        assert zone(await fetch(client), "Test Gated")["locked"] is True  # 1 of 4

        challenges[3].state = ChallengeState.HIDDEN
        await db_session.flush()

        # 2 of 3 clears it where 2 of 4 would not have — the bar came down.
        await record_solve(db_session, user, challenges[1])
        assert zone(await fetch(client), "Test Gated")["locked"] is False

    async def test_a_zone_with_nothing_visible_cannot_be_cleared(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        """Better an unopenable zone than one that opens for free."""
        await player(db_session, client, sign_in)
        source = await make_category(db_session, name="Test Empty")
        gated = await make_category(db_session, name="Test Gated")
        await gate_zone(
            db_session,
            gated,
            requirement_type=RequirementType.PERCENT_IN_CATEGORY,
            required_category_id=source.id,
            threshold=50,
        )

        assert zone(await fetch(client), "Test Gated")["locked"] is True


class TestPlayerLevelGate:
    async def test_it_opens_at_the_level(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        user = await player(db_session, client, sign_in)
        wing = await make_category(db_session, name="Test Deep")
        await gate_zone(
            db_session, wing, requirement_type=RequirementType.PLAYER_LEVEL, threshold=5
        )

        assert zone(await fetch(client), "Test Deep")["locked"] is True

        # Level 5 is 2,000 XP on the 015 curve.
        challenge = await make_challenge(
            db_session, scoring=ScoringMode.STATIC, initial_points=2000
        )
        await record_solve(db_session, user, challenge)

        assert zone(await fetch(client), "Test Deep")["locked"] is False


class TestFog:
    async def test_fog_is_presentation_only(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        from sqlalchemy import select

        from app.models.event import EventConfig

        await player(db_session, client, sign_in)
        wing = await make_category(db_session, name="Test Deep")
        await make_challenge(db_session, category=wing, title="Inner")
        await gate_zone(
            db_session, wing, requirement_type=RequirementType.PLAYER_LEVEL, threshold=8
        )
        config = (await db_session.execute(select(EventConfig))).scalars().first()

        config.fog_of_war = True
        await db_session.flush()
        with_fog = await fetch(client)

        config.fog_of_war = False
        await db_session.flush()
        without_fog = await fetch(client)

        assert with_fog["fog_of_war"] is True
        assert without_fog["fog_of_war"] is False
        assert with_fog["zones"] == without_fog["zones"]


class TestSeededGraph:
    async def test_the_real_progression_is_present(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        """Intro is open from the start and gates the first six (spec 019)."""
        await player(db_session, client, sign_in)

        board = await fetch(client)
        by_name = {z["name"]: z for z in board["zones"]}

        # Intro must actually be clearable: it gates the first six on "100% of
        # Intro", and a zone with nothing visible can never be cleared — an empty
        # Intro would seal the whole dungeon behind an empty room.
        assert by_name["Intro"]["locked"] is False
        assert by_name["Intro"]["total"] >= 1
        for name in (
            "Networking",
            "Governance, Risk & Compliance",
            "Hacker Game Show",
            "CTI",
            "Incident Response",
            "AI/LLM Security",
        ):
            assert by_name[name]["locked"] is True
            assert by_name[name]["unlock_requirements"][0]["description"] == "Clear 100% of Intro"

        assert by_name["Red teaming"]["unlock_requirements"][0]["description"] == "Reach level 5"
        for name in ("Mobile Security", "Reverse Engineering", "Malware Analysis"):
            assert by_name[name]["unlock_requirements"][0]["description"] == "Reach level 8"
