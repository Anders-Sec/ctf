"""The dungeon map: visibility, layout, state and zones (spec 017)."""

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.challenge import ChallengeState, RequirementType, ScoringMode
from app.models.user import UserRole, UserStatus
from app.services import unlocks as unlock_service
from tests.factories import make_category, make_challenge, make_user, record_solve

pytestmark = pytest.mark.usefixtures("running_event")


async def player(db_session, client, sign_in, **kwargs):
    kwargs.setdefault("status", UserStatus.ACTIVE)
    user = await make_user(db_session, **kwargs)
    await sign_in(client, user)
    return user


async def require(db_session, gated, required):
    await unlock_service.add_requirement(
        db_session,
        challenge_id=gated.id,
        requirement_type=RequirementType.CHALLENGE_SOLVED,
        required_challenge_id=required.id,
    )


async def fetch(client) -> dict:
    response = await client.get("/api/map")
    assert response.status_code == 200
    return response.json()


class TestVisibility:
    async def test_invisible_challenges_yield_no_room_and_no_edge(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        """The leak test: hidden and draft challenges are absent entirely."""
        await player(db_session, client, sign_in)
        zone = await make_category(db_session, name="Web")
        open_room = await make_challenge(db_session, category=zone, title="Warm-Up")
        secret = await make_challenge(
            db_session, category=zone, title="Secret", state=ChallengeState.HIDDEN
        )
        draft = await make_challenge(
            db_session, category=zone, title="Draft", state=ChallengeState.DRAFT
        )
        # A corridor from the hidden room to the visible one must not surface.
        await require(db_session, open_room, secret)

        board = await fetch(client)

        titles = {room["title"] for room in board["rooms"]}
        assert titles == {"Warm-Up"}
        assert board["edges"] == []
        assert "Secret" not in str(board)
        assert str(draft.id) not in str(board)

    async def test_an_edge_needs_both_ends_visible(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await player(db_session, client, sign_in)
        zone = await make_category(db_session, name="Web")
        first = await make_challenge(db_session, category=zone, title="First")
        second = await make_challenge(db_session, category=zone, title="Second")
        await require(db_session, second, first)

        board = await fetch(client)

        assert len(board["edges"]) == 1
        assert board["edges"][0]["from_challenge_id"] == str(first.id)
        assert board["edges"][0]["to_challenge_id"] == str(second.id)


class TestRoomState:
    async def test_states_match_the_list(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        user = await player(db_session, client, sign_in)
        zone = await make_category(db_session, name="Web")
        done = await make_challenge(db_session, category=zone, title="Done")
        available = await make_challenge(db_session, category=zone, title="Available")
        gated = await make_challenge(db_session, category=zone, title="Gated")
        await require(db_session, gated, available)
        await record_solve(db_session, user, done)

        by_title = {r["title"]: r for r in (await fetch(client))["rooms"]}

        assert by_title["Done"]["state"] == "cleared"
        assert by_title["Available"]["state"] == "open"
        assert by_title["Gated"]["state"] == "shut"
        assert by_title["Gated"]["unlock_requirements"][0]["description"] == "Solve Available"


class TestLayout:
    async def test_depth_layers_by_prerequisite(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await player(db_session, client, sign_in)
        zone = await make_category(db_session, name="Web")
        first = await make_challenge(db_session, category=zone, title="First")
        second = await make_challenge(db_session, category=zone, title="Second")
        third = await make_challenge(db_session, category=zone, title="Third")
        await require(db_session, second, first)
        await require(db_session, third, second)
        # Also gate third on first: it must still sit past its *deepest* parent.
        await require(db_session, third, first)

        by_title = {r["title"]: r for r in (await fetch(client))["rooms"]}

        assert by_title["First"]["y"] == 0
        assert by_title["Second"]["y"] == 1
        assert by_title["Third"]["y"] == 2

    async def test_layout_is_deterministic_across_calls_and_players(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        zone = await make_category(db_session, name="Web")
        for title in ("Alpha", "Bravo", "Charlie", "Delta"):
            await make_challenge(db_session, category=zone, title=title)

        await player(db_session, client, sign_in)
        first = {r["title"]: (r["x"], r["y"]) for r in (await fetch(client))["rooms"]}
        second = {r["title"]: (r["x"], r["y"]) for r in (await fetch(client))["rooms"]}
        assert first == second

        # A different player sees the same dungeon.
        await player(db_session, client, sign_in)
        other = {r["title"]: (r["x"], r["y"]) for r in (await fetch(client))["rooms"]}
        assert other == first

    async def test_a_pinned_room_wins_and_can_be_cleared(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await player(db_session, client, sign_in, role=UserRole.ADMIN)
        zone = await make_category(db_session, name="Web")
        room = await make_challenge(db_session, category=zone, title="Pinned")

        await client.patch(f"/api/admin/challenges/{room.id}/map-position", json={"x": 7, "y": 9})
        pinned = (await fetch(client))["rooms"][0]
        assert (pinned["x"], pinned["y"]) == (7, 9)

        await client.patch(
            f"/api/admin/challenges/{room.id}/map-position", json={"x": None, "y": None}
        )
        derived = (await fetch(client))["rooms"][0]
        assert (derived["x"], derived["y"]) == (0, 0)

    async def test_a_challenge_with_no_prerequisites_still_appears(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        """Nothing falls off the map."""
        await player(db_session, client, sign_in)
        await make_challenge(db_session, title="Lonely")

        assert [r["title"] for r in (await fetch(client))["rooms"]] == ["Lonely"]


class TestZones:
    async def test_zones_are_categories_with_progress(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        user = await player(db_session, client, sign_in)
        web = await make_category(db_session, name="Web", display_order=1)
        crypto = await make_category(db_session, name="Crypto", display_order=2)
        done = await make_challenge(db_session, category=web, title="Done")
        await make_challenge(db_session, category=web, title="Todo")
        await make_challenge(db_session, category=crypto, title="Cipher")
        await record_solve(db_session, user, done)

        zones = (await fetch(client))["zones"]

        assert [z["name"] for z in zones] == ["Web", "Crypto"]
        assert (zones[0]["cleared"], zones[0]["total"]) == (1, 2)
        assert (zones[1]["cleared"], zones[1]["total"]) == (0, 1)

    async def test_a_gated_zone_reports_locked_with_its_condition(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await player(db_session, client, sign_in)
        wing = await make_category(db_session, name="Deep Wing")
        await make_challenge(db_session, category=wing, title="Inner")
        await unlock_service.add_requirement(
            db_session,
            category_id=wing.id,
            requirement_type=RequirementType.MIN_XP,
            threshold=600,
        )

        board = await fetch(client)
        zone = board["zones"][0]

        assert zone["locked"] is True
        assert zone["unlock_requirements"][0]["description"] == "Reach 600 XP"
        # Greyed, not hidden: the room is still returned, and readable.
        assert [r["title"] for r in board["rooms"]] == ["Inner"]
        assert board["rooms"][0]["state"] == "shut"


class TestFog:
    async def test_fog_is_presentation_only(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        """The same rooms come back either way — fog adds no leak surface."""
        from sqlalchemy import select

        from app.models.event import EventConfig

        await player(db_session, client, sign_in)
        wing = await make_category(db_session, name="Deep Wing")
        await make_challenge(db_session, category=wing, title="Inner", scoring=ScoringMode.STATIC)
        await unlock_service.add_requirement(
            db_session,
            category_id=wing.id,
            requirement_type=RequirementType.MIN_XP,
            threshold=600,
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
        assert with_fog["rooms"] == without_fog["rooms"]
        assert with_fog["zones"] == without_fog["zones"]
