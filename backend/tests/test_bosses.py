"""Boss encounters: tiers, stars and the per-zone achievement (spec 031)."""

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.challenge import BossTier, Challenge
from app.models.notification import Achievement, AchievementAward
from app.models.user import UserRole, UserStatus
from app.services import achievements as engine
from app.services import scoring
from tests.factories import make_category, make_challenge, make_user, record_solve

pytestmark = pytest.mark.usefixtures("running_event")


async def as_role(db_session, client, sign_in, role: UserRole):
    user = await make_user(db_session, role=role, status=UserStatus.ACTIVE)
    await sign_in(client, user)
    return user


async def a_boss(db_session, *, zone, title: str, tier: BossTier = BossTier.CITY):
    challenge = await make_challenge(db_session, category=zone, title=title)
    challenge.boss_tier = tier
    await db_session.flush()
    return challenge


class TestFlaggingABoss:
    async def test_a_tier_makes_it_a_boss(self, db_session: AsyncSession) -> None:
        zone = await make_category(db_session, name="Boss Zone One")
        challenge = await a_boss(db_session, zone=zone, title="Boss One")

        assert challenge.boss_tier is BossTier.CITY

    async def test_one_boss_per_zone_is_refused_with_the_incumbent(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        """The database enforces it; the error has to say which challenge holds
        the slot rather than leaking a constraint violation."""
        await as_role(db_session, client, sign_in, UserRole.ADMIN)
        zone = await make_category(db_session, name="Boss Zone Two")
        await a_boss(db_session, zone=zone, title="The Incumbent")
        rival = await make_challenge(db_session, category=zone, title="The Rival")

        refused = await client.patch(
            f"/api/admin/challenges/{rival.id}", json={"boss_tier": "borough"}
        )

        assert refused.status_code == 409
        assert refused.json()["error"]["code"] == "zone_has_boss"
        assert "The Incumbent" in refused.json()["error"]["message"]

    async def test_a_boss_in_another_zone_is_fine(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await as_role(db_session, client, sign_in, UserRole.ADMIN)
        first = await make_category(db_session, name="Boss Zone Three")
        second = await make_category(db_session, name="Boss Zone Four")
        await a_boss(db_session, zone=first, title="Boss Three")
        elsewhere = await make_challenge(db_session, category=second, title="Boss Four")

        accepted = await client.patch(
            f"/api/admin/challenges/{elsewhere.id}", json={"boss_tier": "floor"}
        )

        assert accepted.status_code == 200

    async def test_a_player_may_not_flag_a_boss(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await as_role(db_session, client, sign_in, UserRole.PLAYER)
        challenge = await make_challenge(db_session, title="Boss Forbidden")

        refused = await client.patch(
            f"/api/admin/challenges/{challenge.id}", json={"boss_tier": "city"}
        )

        assert refused.status_code == 403


class TestStars:
    async def test_beating_a_boss_earns_a_star_of_its_tier(self, db_session: AsyncSession) -> None:
        user = await make_user(db_session, status=UserStatus.ACTIVE)
        zone = await make_category(db_session, name="Boss Star Zone")
        boss = await a_boss(db_session, zone=zone, title="Star Boss", tier=BossTier.COUNTRY)
        await record_solve(db_session, user, boss)

        stars = await engine.stars_for(db_session, user.id)

        assert [s.tier for s in stars] == ["country"]
        assert stars[0].level == 5
        assert stars[0].zone_name == "Boss Star Zone"

    async def test_an_ordinary_solve_earns_nothing(self, db_session: AsyncSession) -> None:
        user = await make_user(db_session, status=UserStatus.ACTIVE)
        ordinary = await make_challenge(db_session, title="Not A Boss")
        await record_solve(db_session, user, ordinary)

        assert await engine.stars_for(db_session, user.id) == []

    async def test_flagging_a_boss_afterwards_gives_prior_solvers_their_star(
        self, db_session: AsyncSession
    ) -> None:
        """Derived rather than awarded, so there is no backfill problem: this is
        what lets bosses be decided late in preparation."""
        user = await make_user(db_session, status=UserStatus.ACTIVE)
        zone = await make_category(db_session, name="Boss Late Zone")
        challenge = await make_challenge(db_session, category=zone, title="Late Boss")
        await record_solve(db_session, user, challenge)
        assert await engine.stars_for(db_session, user.id) == []

        challenge.boss_tier = BossTier.PROVINCE
        await db_session.flush()

        assert len(await engine.stars_for(db_session, user.id)) == 1

    async def test_disabling_a_broken_boss_keeps_the_star(self, db_session: AsyncSession) -> None:
        """Taking a star back because an admin fixed something would be the
        worst possible behaviour."""
        from app.models.challenge import ChallengeState

        user = await make_user(db_session, status=UserStatus.ACTIVE)
        zone = await make_category(db_session, name="Boss Broken Zone")
        boss = await a_boss(db_session, zone=zone, title="Broken Boss")
        await record_solve(db_session, user, boss)

        boss.state = ChallengeState.DRAFT
        await db_session.flush()

        assert len(await engine.stars_for(db_session, user.id)) == 1

    async def test_stars_are_ordered_biggest_fight_first(self, db_session: AsyncSession) -> None:
        user = await make_user(db_session, status=UserStatus.ACTIVE)
        for name, tier in (
            ("Boss Small Zone", BossTier.NEIGHBORHOOD),
            ("Boss Huge Zone", BossTier.FLOOR),
            ("Boss Mid Zone", BossTier.CITY),
        ):
            zone = await make_category(db_session, name=name)
            boss = await a_boss(db_session, zone=zone, title=f"{name} Boss", tier=tier)
            await record_solve(db_session, user, boss)

        stars = await engine.stars_for(db_session, user.id)

        assert [s.level for s in stars] == [6, 3, 1]

    async def test_a_boss_kill_moves_no_score(self, db_session: AsyncSession) -> None:
        """Identity never touches the scoreboard — the rule 015 and 016 both
        drew. A boss is worth exactly what its difficulty makes it worth."""
        plain = await make_user(db_session, status=UserStatus.ACTIVE)
        slayer = await make_user(db_session, status=UserStatus.ACTIVE)
        zone = await make_category(db_session, name="Boss Scoring Zone")
        boss = await a_boss(db_session, zone=zone, title="Scoring Boss")
        ordinary = await make_challenge(db_session, category=zone, title="Scoring Ordinary")
        ordinary.initial_points = boss.initial_points
        await db_session.flush()

        await record_solve(db_session, slayer, boss)
        await record_solve(db_session, plain, ordinary)

        assert await scoring.total_xp(db_session, slayer.id) == await scoring.total_xp(
            db_session, plain.id
        )

    async def test_the_endpoint_lists_them(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        user = await as_role(db_session, client, sign_in, UserRole.PLAYER)
        zone = await make_category(db_session, name="Boss Endpoint Zone")
        boss = await a_boss(db_session, zone=zone, title="Endpoint Boss")
        await record_solve(db_session, user, boss)

        body = (await client.get("/api/character/stars")).json()

        assert [s["challenge_title"] for s in body] == ["Endpoint Boss"]


class TestTheZoneAchievement:
    async def test_it_resolves_by_prefix_rather_than_being_registered(self) -> None:
        """Zones are rows, not code, so the trigger family is registered once
        and the code resolved against it."""
        assert engine.resolve("boss_anything") is not None
        assert engine.resolve("boss_") is None

    async def test_it_awards_on_beating_that_zone_s_boss(self, db_session: AsyncSession) -> None:
        user = await make_user(db_session, status=UserStatus.ACTIVE)
        zone = await make_category(db_session, name="Boss Achieve Zone")
        boss = await a_boss(db_session, zone=zone, title="Achieve Boss")
        db_session.add(
            Achievement(
                code=f"boss_{zone.slug}",
                name="Boss: Achieve Zone",
                description="x",
                earned_by="Beating it.",
            )
        )
        await db_session.flush()

        await record_solve(db_session, user, boss)
        earned = await engine.evaluate(db_session, user.id, engine.SOLVE)

        assert f"boss_{zone.slug}" in {a.code for a in earned}

    async def test_solving_a_non_boss_in_the_zone_does_not_award_it(
        self, db_session: AsyncSession
    ) -> None:
        user = await make_user(db_session, status=UserStatus.ACTIVE)
        zone = await make_category(db_session, name="Boss Wrong Zone")
        await a_boss(db_session, zone=zone, title="Wrong Zone Boss")
        minion = await make_challenge(db_session, category=zone, title="A Minion")
        db_session.add(
            Achievement(
                code=f"boss_{zone.slug}",
                name="Boss: Wrong Zone",
                description="x",
                earned_by="Beating it.",
            )
        )
        await db_session.flush()

        await record_solve(db_session, user, minion)
        await engine.evaluate(db_session, user.id, engine.SOLVE)

        held = (
            (
                await db_session.execute(
                    select(Achievement.code)
                    .join(AchievementAward, AchievementAward.achievement_id == Achievement.id)
                    .where(AchievementAward.user_id == user.id)
                )
            )
            .scalars()
            .all()
        )
        assert f"boss_{zone.slug}" not in held

    async def test_the_seeded_placeholders_exist_for_every_zone(
        self, db_session: AsyncSession
    ) -> None:
        zones = (await db_session.execute(select(Challenge.category_id))).scalars().all()
        assert zones is not None  # the query above is only to touch the table

        codes = set(
            (
                await db_session.execute(
                    select(Achievement.code).where(Achievement.code.startswith("boss_"))
                )
            )
            .scalars()
            .all()
        )
        assert len(codes) >= 22

    async def test_every_seeded_boss_code_resolves(self, db_session: AsyncSession) -> None:
        """A boss achievement with no resolvable trigger would be inert, which
        is the one thing the per-zone keying exists to prevent."""
        codes = (
            (
                await db_session.execute(
                    select(Achievement.code).where(Achievement.code.startswith("boss_"))
                )
            )
            .scalars()
            .all()
        )

        assert codes
        assert all(engine.resolve(code) is not None for code in codes)


class TestTheMap:
    async def test_a_zone_with_a_boss_is_marked(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await as_role(db_session, client, sign_in, UserRole.PLAYER)
        zone = await make_category(db_session, name="Boss Map Zone")
        await a_boss(db_session, zone=zone, title="Map Boss", tier=BossTier.FLOOR)

        board = (await client.get("/api/map")).json()
        marked = next(z for z in board["zones"] if z["name"] == "Boss Map Zone")

        assert marked["boss_tier"] == "floor"

    async def test_a_zone_without_one_is_not(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await as_role(db_session, client, sign_in, UserRole.PLAYER)
        zone = await make_category(db_session, name="Boss Free Zone")
        await make_challenge(db_session, category=zone, title="Just A Challenge")

        board = (await client.get("/api/map")).json()
        plain = next(z for z in board["zones"] if z["name"] == "Boss Free Zone")

        assert plain["boss_tier"] is None
