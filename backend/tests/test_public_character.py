"""Somebody else's character sheet (spec 061).

The load-bearing test here is the redaction: **a secret achievement the viewer
has not earned themselves arrives with no name and no rarity.** It is spec 028's
rule applied to a second reader, and it is server-side for the same reason —
there must be nothing to un-blur in devtools.
"""

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.models.challenge import BossTier, ScoringMode
from app.models.notification import Achievement, AchievementAward, LootItem, LootRarity
from app.models.user import UserRole, UserStatus
from app.redis import get_redis
from app.services import scoreboard_cache
from tests.factories import make_category, make_challenge, make_team, make_user, record_solve

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


async def viewer(db_session, client, sign_in, **kwargs):
    kwargs.setdefault("status", UserStatus.ACTIVE)
    user = await make_user(db_session, **kwargs)
    await sign_in(client, user)
    return user


async def make_achievement(db_session, *, name: str, secret: bool = False) -> Achievement:
    """Suffixed, because `achievement.name` is unique and the test database
    carries the real seeded roster — "First Blood" is already taken."""
    suffix = uuid.uuid4().hex[:6]
    achievement = Achievement(
        code=f"{name.lower().replace(' ', '_')}_{suffix}",
        name=f"{name} {suffix}",
        description="Flavour text nobody else should read.",
        earned_by="Do the thing",
        secret=secret,
    )
    db_session.add(achievement)
    await db_session.flush()
    return achievement


async def make_zone(db_session, name: str):
    """Same reason: the seeded categories own the obvious names."""
    return await make_category(db_session, name=f"{name} {uuid.uuid4().hex[:6]}")


async def award(db_session, achievement: Achievement, user) -> None:
    db_session.add(AchievementAward(achievement_id=achievement.id, user_id=user.id))
    await db_session.flush()


class TestTheSheet:
    async def test_it_carries_what_a_player_shows_the_room(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        challenge = await make_challenge(db_session, scoring=ScoringMode.STATIC)
        subject = await make_user(db_session, display_name="Grix")
        team = await make_team(db_session, subject, name="The Mimics")
        await record_solve(db_session, subject, challenge, team=team)

        item = LootItem(pool_key="test", rarity=LootRarity.GOLD, title="the Unbothered")
        db_session.add(item)
        await db_session.flush()
        subject.equipped_title_id = item.id
        await db_session.flush()

        await viewer(db_session, client, sign_in, display_name="Viewer")
        sheet = (await client.get(f"/api/character/{subject.id}")).json()

        assert sheet["display_name"] == "Grix"
        assert sheet["party"] == {"id": str(team.id), "name": "The Mimics"}
        assert sheet["equipped_title"] == "the Unbothered"
        assert sheet["rank"] == 1
        assert sheet["solve_count"] == 1

    async def test_no_xp_in_any_form(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        """Including none implied — the zone breakdown is counts, not points."""
        challenge = await make_challenge(db_session, scoring=ScoringMode.STATIC)
        subject = await make_user(db_session, display_name="Grix")
        await record_solve(db_session, subject, challenge)
        await viewer(db_session, client, sign_in, display_name="Viewer")

        sheet = (await client.get(f"/api/character/{subject.id}")).json()

        assert not any("xp" in key for key in sheet)
        assert "score" not in sheet
        for zone in sheet["zones"]:
            assert set(zone) == {"zone_name", "solves"}

    async def test_only_discovered_skills_are_sent_with_a_total_beside_them(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        """There is nothing to tease a stranger with — but `N of M` still needs M."""
        subject = await make_user(db_session, display_name="Grix")
        await viewer(db_session, client, sign_in, display_name="Viewer")

        sheet = (await client.get(f"/api/character/{subject.id}")).json()

        assert all(row["discovered"] for row in sheet["skills"])
        assert sheet["skills_total"] >= len(sheet["skills"])

    async def test_a_staff_account_has_no_rank_rather_than_failing(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        """The board holds active player-role accounts only, by design."""
        staff = await make_user(db_session, display_name="Dungeon Master", role=UserRole.ADMIN)
        await viewer(db_session, client, sign_in, display_name="Viewer")

        response = await client.get(f"/api/character/{staff.id}")

        assert response.status_code == 200
        assert response.json()["rank"] is None

    async def test_an_unknown_player_is_a_404(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await viewer(db_session, client, sign_in)

        assert (await client.get(f"/api/character/{uuid.uuid4()}")).status_code == 404


class TestFeats:
    async def test_stars_carry_their_slug_and_tier(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        """One shape for a sheet's stars and a scoreboard's (spec 061 §6)."""
        boss = await make_challenge(db_session, scoring=ScoringMode.STATIC, title="The Gatekeeper")
        boss.slug = "the-gatekeeper"
        boss.boss_tier = BossTier.CITY
        await db_session.flush()

        subject = await make_user(db_session, display_name="Slayer")
        await record_solve(db_session, subject, boss)
        await viewer(db_session, client, sign_in, display_name="Viewer")

        sheet = (await client.get(f"/api/character/{subject.id}")).json()

        assert len(sheet["stars"]) == 1
        assert sheet["stars"][0]["slug"] == "the-gatekeeper"
        assert sheet["stars"][0]["tier"] == "city"

    async def test_the_zone_breakdown_sums_to_the_solve_count(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        web = await make_zone(db_session, "Web")
        crypto = await make_zone(db_session, "Crypto")
        subject = await make_user(db_session, display_name="Hunter")
        for _ in range(3):
            await record_solve(
                db_session,
                subject,
                await make_challenge(db_session, category=web, scoring=ScoringMode.STATIC),
            )
        await record_solve(
            db_session,
            subject,
            await make_challenge(db_session, category=crypto, scoring=ScoringMode.STATIC),
        )
        await viewer(db_session, client, sign_in, display_name="Viewer")

        sheet = (await client.get(f"/api/character/{subject.id}")).json()

        assert sheet["solve_count"] == 4
        assert sum(zone["solves"] for zone in sheet["zones"]) == 4
        # Biggest first: a player's shape at a glance.
        assert sheet["zones"][0] == {"zone_name": web.name, "solves": 3}

    async def test_a_zone_with_no_solves_is_omitted(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        """A portrait, not an audit (spec 061 §9.1)."""
        web = await make_zone(db_session, "Web")
        await make_zone(db_session, "Never Touched")
        subject = await make_user(db_session, display_name="Hunter")
        await record_solve(
            db_session,
            subject,
            await make_challenge(db_session, category=web, scoring=ScoringMode.STATIC),
        )
        await viewer(db_session, client, sign_in, display_name="Viewer")

        sheet = (await client.get(f"/api/character/{subject.id}")).json()

        assert [zone["zone_name"] for zone in sheet["zones"]] == [web.name]

    async def test_hints_and_attempts_appear_nowhere(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        """Real numbers, and not ones that belong on a page colleagues open
        about each other (spec 061 §5)."""
        subject = await make_user(db_session, display_name="Grix")
        await viewer(db_session, client, sign_in, display_name="Viewer")

        sheet = (await client.get(f"/api/character/{subject.id}")).json()

        for term in ("hint", "attempt", "fail"):
            assert not any(term in key for key in sheet)


class TestTheTrophyCase:
    async def test_it_lists_only_what_they_earned(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        """A trophy case, not a progress bar."""
        earned = await make_achievement(db_session, name="First Blood")
        await make_achievement(db_session, name="Never Got It")
        subject = await make_user(db_session, display_name="Grix")
        await award(db_session, earned, subject)
        await viewer(db_session, client, sign_in, display_name="Viewer")

        body = (await client.get(f"/api/character/{subject.id}/achievements")).json()

        assert body["earned"] == 1
        assert [row["name"] for row in body["items"]] == [earned.name]

    async def test_no_row_carries_a_description(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        earned = await make_achievement(db_session, name="First Blood")
        subject = await make_user(db_session, display_name="Grix")
        await award(db_session, earned, subject)
        await viewer(db_session, client, sign_in, display_name="Viewer")

        body = (await client.get(f"/api/character/{subject.id}/achievements")).json()

        for row in body["items"] + body["rarest"]:
            assert "description" not in row

    async def test_a_secret_the_viewer_lacks_is_redacted_server_side(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        """The one that keeps spec 028 true for a second reader.

        The row is present — a player's proudest finds should be visibly there —
        but it carries nothing to read.
        """
        secret = await make_achievement(db_session, name="The Konami Solve", secret=True)
        subject = await make_user(db_session, display_name="Grix")
        await award(db_session, secret, subject)
        await viewer(db_session, client, sign_in, display_name="Viewer")

        body = (await client.get(f"/api/character/{subject.id}/achievements")).json()

        assert body["secret_count"] == 1
        assert len(body["items"]) == 1
        assert body["items"][0]["name"] is None
        assert body["items"][0]["rarity"] is None
        # Nothing to un-blur in devtools.
        assert "Konami" not in str(body)

    async def test_a_secret_the_viewer_holds_too_is_named(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        """Two people who both found the Mimic can see it on each other."""
        secret = await make_achievement(db_session, name="The Konami Solve", secret=True)
        subject = await make_user(db_session, display_name="Grix")
        await award(db_session, secret, subject)
        looker = await viewer(db_session, client, sign_in, display_name="Viewer")
        await award(db_session, secret, looker)

        body = (await client.get(f"/api/character/{subject.id}/achievements")).json()

        assert body["secret_count"] == 0
        assert body["items"][0]["name"] == secret.name

    async def test_a_non_secret_is_always_named(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        """Only the secret flag redacts. Everything else is the brag."""
        ordinary = await make_achievement(db_session, name="Night Owl")
        subject = await make_user(db_session, display_name="Grix")
        await award(db_session, ordinary, subject)
        await viewer(db_session, client, sign_in, display_name="Viewer")

        body = (await client.get(f"/api/character/{subject.id}/achievements")).json()

        assert body["items"][0]["name"] == ordinary.name
        assert body["secret_count"] == 0

    async def test_the_rarest_five_never_contain_a_redacted_row(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        """A trophy case of blurred squares brags about nothing (spec 061 §4.2).

        The secret here is rarer than the ordinary one — held by one player
        against two — so it would lead the list if it were eligible.
        """
        secret = await make_achievement(db_session, name="The Konami Solve", secret=True)
        ordinary = await make_achievement(db_session, name="Night Owl")
        subject = await make_user(db_session, display_name="Grix")
        await award(db_session, secret, subject)
        await award(db_session, ordinary, subject)

        # A second holder for the ordinary one, and a solve each so both count as
        # playing players in the rarity denominator.
        other = await make_user(db_session, display_name="Other")
        await award(db_session, ordinary, other)
        for who in (subject, other):
            await record_solve(
                db_session, who, await make_challenge(db_session, scoring=ScoringMode.STATIC)
            )

        await viewer(db_session, client, sign_in, display_name="Viewer")
        body = (await client.get(f"/api/character/{subject.id}/achievements")).json()

        assert [row["name"] for row in body["rarest"]] == [ordinary.name]
        assert all(row["name"] is not None for row in body["rarest"])

    async def test_an_unknown_player_is_a_404(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await viewer(db_session, client, sign_in)

        response = await client.get(f"/api/character/{uuid.uuid4()}/achievements")

        assert response.status_code == 404
