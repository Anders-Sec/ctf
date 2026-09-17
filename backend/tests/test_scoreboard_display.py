"""What the boards show, and what they refuse to (spec 059).

The scoring model is untouched here — every one of these is about display. The
one that has to keep holding as columns are added later is the first: **no public
board response carries XP**.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.models.challenge import BossTier, ScoringMode
from app.models.character_class import CharacterClass, Rarity
from app.models.notification import LootItem, LootRarity
from app.models.user import UserRole, UserStatus
from app.redis import get_redis
from app.services import scoreboard_cache
from tests.factories import add_member, make_challenge, make_team, make_user, record_solve

pytestmark = pytest.mark.usefixtures("running_event")


@pytest.fixture(autouse=True)
async def clear_scoreboard_cache(settings: Settings):
    """The cache outlives a rolled-back transaction, so it must be cleared."""
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


async def signed_in(db_session, client, sign_in, **kwargs):
    kwargs.setdefault("status", UserStatus.ACTIVE)
    user = await make_user(db_session, **kwargs)
    await sign_in(client, user)
    return user


async def make_boss(
    db_session,
    *,
    slug: str,
    tier: BossTier = BossTier.CITY,
    title: str | None = None,
    points: int = 100,
):
    boss = await make_challenge(
        db_session,
        scoring=ScoringMode.STATIC,
        initial_points=points,
        title=title or slug.replace("-", " ").title(),
    )
    boss.slug = slug
    boss.boss_tier = tier
    await db_session.flush()
    return boss


async def make_class(db_session, *, name: str, rarity: Rarity = Rarity.RARE) -> CharacterClass:
    character_class = CharacterClass(
        name=f"{name} {uuid.uuid4().hex[:6]}", display_order=0, rarity=rarity
    )
    db_session.add(character_class)
    await db_session.flush()
    return character_class


async def wear_title(db_session, user, title: str) -> None:
    item = LootItem(pool_key="test", rarity=LootRarity.GOLD, title=title)
    db_session.add(item)
    await db_session.flush()
    user.equipped_title_id = item.id
    await db_session.flush()


class TestXpIsNotPublished:
    """§2. The rule that has to keep holding as fields get added."""

    async def test_neither_board_carries_score(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        challenge = await make_challenge(db_session, scoring=ScoringMode.STATIC)
        user = await signed_in(db_session, client, sign_in)
        team = await make_team(db_session, user, name="Mine")
        await record_solve(db_session, user, challenge, team=team)

        players = (await client.get("/api/scoreboard/players")).json()["entries"]
        teams = (await client.get("/api/scoreboard/teams")).json()["entries"]

        assert players and teams
        for row in players + teams:
            assert "score" not in row
            assert not any("xp" in key for key in row)

    async def test_the_admin_board_keeps_its_numbers(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        """§6. It exists to settle placements, which is where arithmetic belongs."""
        challenge = await make_challenge(db_session, scoring=ScoringMode.STATIC, initial_points=250)
        solver = await make_user(db_session, display_name="Solver")
        await record_solve(db_session, solver, challenge)
        await signed_in(db_session, client, sign_in, role=UserRole.ADMIN)

        body = (await client.get("/api/admin/scoreboard")).json()
        row = next(r for r in body["players"] if r["display_name"] == "Solver")

        assert row["score"] == 250
        # And the two halves still add back to it.
        assert row["solve_points"] + row["adjustment_points"] == row["score"]

    async def test_ordering_survives_the_field_removal(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        big = await make_challenge(db_session, scoring=ScoringMode.STATIC, initial_points=300)
        small = await make_challenge(db_session, scoring=ScoringMode.STATIC, initial_points=100)
        leader = await make_user(db_session, display_name="Leader")
        trailer = await make_user(db_session, display_name="Trailer")
        await record_solve(db_session, leader, big)
        await record_solve(db_session, trailer, small)
        await signed_in(db_session, client, sign_in, display_name="Viewer")

        entries = (await client.get("/api/scoreboard/players")).json()["entries"]

        assert [row["display_name"] for row in entries[:2]] == ["Leader", "Trailer"]


class TestBossStars:
    """§3. A star is a named thing now, which is what lets it deduplicate."""

    async def test_a_player_carries_their_own_kills_with_slug_and_tier(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        boss = await make_boss(db_session, slug="the-gatekeeper", tier=BossTier.PROVINCE)
        user = await signed_in(db_session, client, sign_in, display_name="Slayer")
        await record_solve(db_session, user, boss)

        entries = (await client.get("/api/scoreboard/players")).json()["entries"]
        row = next(r for r in entries if r["display_name"] == "Slayer")

        assert row["stars"] == [
            {
                "slug": "the-gatekeeper",
                "tier": "province",
                "level": 4,
                "title": "The Gatekeeper",
            }
        ]

    async def test_a_player_with_no_kills_reports_an_empty_list(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        """Empty rather than a zero-filled breakdown: there is nothing to draw."""
        await signed_in(db_session, client, sign_in, display_name="Peaceful")

        entries = (await client.get("/api/scoreboard/players")).json()["entries"]
        row = next(r for r in entries if r["display_name"] == "Peaceful")

        assert row["stars"] == []

    async def test_a_party_deduplicates_by_slug(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        """Six members who each felled XYZ carry one XYZ star, not six."""
        boss = await make_boss(db_session, slug="xyz", tier=BossTier.CITY, title="XYZ")
        leader = await make_user(db_session, display_name="Leader")
        party = await make_team(db_session, leader, name="Six Of Them")
        await record_solve(db_session, leader, boss, team=party)
        for index in range(5):
            member = await make_user(db_session, display_name=f"Member {index}")
            await add_member(db_session, party, member)
            await record_solve(db_session, member, boss, team=party)
        await signed_in(db_session, client, sign_in, display_name="Viewer")

        entries = (await client.get("/api/scoreboard/teams")).json()["entries"]
        row = next(r for r in entries if r["name"] == "Six Of Them")

        assert row["member_count"] == 6
        assert row["stars"] == [{"slug": "xyz", "tier": "city", "level": 3, "title": "XYZ"}]

    async def test_a_party_unions_distinct_bosses_highest_tier_first(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        small = await make_boss(db_session, slug="alley-rat", tier=BossTier.NEIGHBORHOOD)
        large = await make_boss(db_session, slug="the-floor", tier=BossTier.FLOOR)
        leader = await make_user(db_session, display_name="Leader")
        party = await make_team(db_session, leader, name="Pair")
        other = await make_user(db_session, display_name="Other")
        await add_member(db_session, party, other)
        await record_solve(db_session, leader, small, team=party)
        await record_solve(db_session, other, large, team=party)
        await signed_in(db_session, client, sign_in, display_name="Viewer")

        entries = (await client.get("/api/scoreboard/teams")).json()["entries"]
        row = next(r for r in entries if r["name"] == "Pair")

        # Biggest fight first — the thing worth showing off.
        assert [star["slug"] for star in row["stars"]] == ["the-floor", "alley-rat"]

    async def test_a_departed_member_takes_their_unique_kills(
        self, client: AsyncClient, db_session: AsyncSession, sign_in, settings: Settings
    ) -> None:
        """The same rule as scoring: stars follow the *current* roster."""
        shared = await make_boss(db_session, slug="shared-boss")
        theirs = await make_boss(db_session, slug="their-boss")
        leader = await make_user(db_session, display_name="Leader")
        party = await make_team(db_session, leader, name="Shrinking")
        leaver = await make_user(db_session, display_name="Leaver")
        membership = await add_member(db_session, party, leaver)
        await record_solve(db_session, leader, shared, team=party)
        await record_solve(db_session, leaver, theirs, team=party)
        await signed_in(db_session, client, sign_in, display_name="Viewer")

        before = (await client.get("/api/scoreboard/teams")).json()["entries"]
        shrinking = next(r for r in before if r["name"] == "Shrinking")
        assert {star["slug"] for star in shrinking["stars"]} == {"shared-boss", "their-boss"}

        membership.removed_at = datetime.now(UTC).replace(tzinfo=None)
        await db_session.flush()
        # The cache outlives the roster change, so force the recompute the app
        # would have been told to do by a membership event.
        await scoreboard_cache.refresh(db_session, get_redis(settings), force=True)

        after = (await client.get("/api/scoreboard/teams")).json()["entries"]
        shrunk = next(r for r in after if r["name"] == "Shrinking")
        assert [star["slug"] for star in shrunk["stars"]] == ["shared-boss"]


class TestPlayerBoardFields:
    """§2. Title and class reach the entry — the regression they never had."""

    async def test_the_worn_title_and_class_reach_the_entry(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        character_class = await make_class(db_session, name="Rogue", rarity=Rarity.LEGENDARY)
        user = await signed_in(db_session, client, sign_in, display_name="Dressed")
        user.character_class_id = character_class.id
        await wear_title(db_session, user, "the Unbothered")

        entries = (await client.get("/api/scoreboard/players")).json()["entries"]
        row = next(r for r in entries if r["display_name"] == "Dressed")

        assert row["title"] == "the Unbothered"
        assert row["class_name"] == character_class.name
        assert row["class_rarity"] == "legendary"

    async def test_an_undressed_player_reports_nulls_rather_than_blanks(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await signed_in(db_session, client, sign_in, display_name="Plain")

        entries = (await client.get("/api/scoreboard/players")).json()["entries"]
        row = next(r for r in entries if r["display_name"] == "Plain")

        assert row["title"] is None
        assert row["class_name"] is None
        assert row["class_rarity"] is None


class TestSharedRanks:
    """§4.1. Two entries on equal points share a place."""

    async def test_a_tie_shares_the_place_and_the_next_entry_skips(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        big = await make_challenge(db_session, scoring=ScoringMode.STATIC, initial_points=300)
        mid = await make_challenge(db_session, scoring=ScoringMode.STATIC, initial_points=200)
        also_mid = await make_challenge(db_session, scoring=ScoringMode.STATIC, initial_points=200)
        small = await make_challenge(db_session, scoring=ScoringMode.STATIC, initial_points=100)

        first = await make_user(db_session, display_name="First")
        tied_a = await make_user(db_session, display_name="Tied A")
        tied_b = await make_user(db_session, display_name="Tied B")
        last = await make_user(db_session, display_name="Last")
        await record_solve(db_session, first, big)
        await record_solve(db_session, tied_a, mid)
        await record_solve(db_session, tied_b, also_mid)
        await record_solve(db_session, last, small)
        await signed_in(db_session, client, sign_in, display_name="Viewer")

        entries = (await client.get("/api/scoreboard/players")).json()["entries"]
        ranks = {row["display_name"]: row["rank"] for row in entries}

        assert ranks["First"] == 1
        assert ranks["Tied A"] == 2
        assert ranks["Tied B"] == 2
        # Standard competition ranking: the next place is the one the position
        # implies, not the next integer.
        assert ranks["Last"] == 4

    async def test_order_within_a_shared_rank_is_still_earliest_first(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        """§4.1. Only the number beside them changes, never the sequence."""
        early = await make_challenge(db_session, scoring=ScoringMode.STATIC, initial_points=200)
        late = await make_challenge(db_session, scoring=ScoringMode.STATIC, initial_points=200)
        first_there = await make_user(db_session, display_name="Early Bird")
        second_there = await make_user(db_session, display_name="Latecomer")

        now = datetime.now(UTC).replace(tzinfo=None)
        solve_a = await record_solve(db_session, first_there, early)
        solve_b = await record_solve(db_session, second_there, late)
        solve_a.submitted_at = now - timedelta(hours=2)
        solve_b.submitted_at = now
        await db_session.flush()
        await signed_in(db_session, client, sign_in, display_name="Viewer")

        entries = (await client.get("/api/scoreboard/players")).json()["entries"]
        tied = [row["display_name"] for row in entries if row["rank"] == 1]

        assert tied == ["Early Bird", "Latecomer"]

    async def test_the_admin_board_inherits_the_shared_rank(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        """§6. An admin sees both the shared place and who reached it first."""
        mid = await make_challenge(db_session, scoring=ScoringMode.STATIC, initial_points=200)
        also_mid = await make_challenge(db_session, scoring=ScoringMode.STATIC, initial_points=200)
        tied_a = await make_user(db_session, display_name="Tied A")
        tied_b = await make_user(db_session, display_name="Tied B")
        await record_solve(db_session, tied_a, mid)
        await record_solve(db_session, tied_b, also_mid)
        await signed_in(db_session, client, sign_in, role=UserRole.ADMIN)

        body = (await client.get("/api/admin/scoreboard")).json()
        ranks = {row["display_name"]: row["rank"] for row in body["players"]}

        assert ranks["Tied A"] == 1
        assert ranks["Tied B"] == 1


class TestPartyPanel:
    """§5. Who a party is, and nothing about how much XP anybody has."""

    async def test_it_returns_the_roster_with_classes_and_levels(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        character_class = await make_class(db_session, name="Ranger")
        challenge = await make_challenge(db_session, scoring=ScoringMode.STATIC)
        leader = await make_user(db_session, display_name="Leader")
        leader.character_class_id = character_class.id
        party = await make_team(db_session, leader, name="The Bold")
        await record_solve(db_session, leader, challenge, team=party)
        await signed_in(db_session, client, sign_in, display_name="Viewer")

        body = (await client.get(f"/api/scoreboard/teams/{party.id}")).json()

        assert body["name"] == "The Bold"
        assert body["rank"] == 1
        assert body["solve_count"] == 1
        assert body["founded_at"]
        member = next(m for m in body["members"] if m["display_name"] == "Leader")
        assert member["class_name"] == character_class.name
        assert member["level"] >= 1

    async def test_no_xp_for_the_party_or_anybody_in_it(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        """The scoreboard's worst habit, not reintroduced one level down."""
        challenge = await make_challenge(db_session, scoring=ScoringMode.STATIC)
        leader = await make_user(db_session, display_name="Leader")
        party = await make_team(db_session, leader, name="Quiet")
        await record_solve(db_session, leader, challenge, team=party)
        await signed_in(db_session, client, sign_in, display_name="Viewer")

        body = (await client.get(f"/api/scoreboard/teams/{party.id}")).json()

        assert "score" not in body
        for member in body["members"]:
            assert "score" not in member
            assert not any("xp" in key for key in member)

    async def test_it_counts_distinct_achievements_across_the_roster(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        """Two members who both earned one thing earned the party one thing."""
        from app.models.notification import Achievement, AchievementAward

        achievement = Achievement(
            code=f"shared_{uuid.uuid4().hex[:8]}",
            name="Shared",
            description="Both of them did it.",
            earned_by="",
        )
        db_session.add(achievement)
        await db_session.flush()

        leader = await make_user(db_session, display_name="Leader")
        party = await make_team(db_session, leader, name="Decorated")
        other = await make_user(db_session, display_name="Other")
        await add_member(db_session, party, other)
        for holder in (leader, other):
            db_session.add(AchievementAward(achievement_id=achievement.id, user_id=holder.id))
        await db_session.flush()
        await signed_in(db_session, client, sign_in, display_name="Viewer")

        body = (await client.get(f"/api/scoreboard/teams/{party.id}")).json()

        assert body["achievement_count"] == 1

    async def test_it_carries_the_same_stars_the_board_showed(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        """Read off the board payload, so the panel cannot disagree with the list."""
        boss = await make_boss(db_session, slug="panel-boss", tier=BossTier.BOROUGH)
        leader = await make_user(db_session, display_name="Leader")
        party = await make_team(db_session, leader, name="Starred")
        await record_solve(db_session, leader, boss, team=party)
        await signed_in(db_session, client, sign_in, display_name="Viewer")

        panel = (await client.get(f"/api/scoreboard/teams/{party.id}")).json()
        board = (await client.get("/api/scoreboard/teams")).json()["entries"]
        row = next(r for r in board if r["name"] == "Starred")

        assert panel["stars"] == row["stars"]
        assert panel["stars"][0]["slug"] == "panel-boss"

    async def test_an_unknown_party_is_a_404(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await signed_in(db_session, client, sign_in)

        response = await client.get(f"/api/scoreboard/teams/{uuid.uuid4()}")

        assert response.status_code == 404

    async def test_a_disbanded_party_is_a_404(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        """It is not on the board it would have been opened from."""
        leader = await make_user(db_session, display_name="Leader")
        party = await make_team(db_session, leader, name="Gone")
        party.disbanded_at = datetime.now(UTC).replace(tzinfo=None)
        await db_session.flush()
        await signed_in(db_session, client, sign_in, display_name="Viewer")

        response = await client.get(f"/api/scoreboard/teams/{party.id}")

        assert response.status_code == 404
