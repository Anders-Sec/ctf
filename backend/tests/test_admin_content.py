"""Content-page counts, bulk operations and the reward fields (spec 058)."""

import uuid

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.character_class import CharacterClass, Rarity
from app.models.notification import Achievement
from app.models.skill import ChallengeSkill, Skill
from app.models.theme_unlock import UnlockSource, UserThemeUnlock
from app.models.user import UserRole, UserStatus
from app.services import theme_unlocks
from tests.factories import make_challenge, make_user


async def admin(db_session: AsyncSession, client: AsyncClient, sign_in):
    user = await make_user(db_session, role=UserRole.ADMIN, status=UserStatus.ACTIVE)
    await sign_in(client, user)
    return user


def unique(label: str) -> str:
    """Seeded content is present in the test database — spec 025 fills the real
    zones with the real skills — so a fixed name collides with a real one."""
    return f"{label} {uuid.uuid4().hex[:8]}"


async def make_skill(db_session: AsyncSession, *, name: str, **kwargs) -> Skill:
    row = Skill(name=unique(name), **kwargs)
    db_session.add(row)
    await db_session.flush()
    return row


async def make_class(db_session: AsyncSession, name: str, **kwargs) -> CharacterClass:
    row = CharacterClass(name=unique(name), **kwargs)
    db_session.add(row)
    await db_session.flush()
    return row


async def make_achievement(db_session: AsyncSession, code: str, **kwargs) -> Achievement:
    row = Achievement(
        code=unique(code).replace(" ", "_").lower(),
        name=kwargs.pop("name", unique(code.replace("_", " ").title())),
        description=kwargs.pop("description", "Something happened."),
        earned_by=kwargs.pop("earned_by", ""),
        **kwargs,
    )
    db_session.add(row)
    await db_session.flush()
    return row


class TestRowCounts:
    async def test_a_skill_reports_how_many_challenges_feed_it(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        """Zero is the signal worth seeing: XP that lands nowhere."""
        await admin(db_session, client, sign_in)
        used = await make_skill(db_session, name="Injection Artistry")
        orphan = await make_skill(db_session, name="Orphaned Skill")
        challenge = await make_challenge(db_session, initial_points=100)
        db_session.add(ChallengeSkill(challenge_id=challenge.id, skill_id=used.id))
        await db_session.flush()

        rows = (await client.get("/api/admin/skills")).json()

        assert next(r for r in rows if r["id"] == str(used.id))["challenge_count"] == 1
        assert next(r for r in rows if r["id"] == str(orphan.id))["challenge_count"] == 0

    async def test_a_class_reports_its_sets_and_its_wearers(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await admin(db_session, client, sign_in)
        rogue = await make_class(db_session, "Rogue", rarity=Rarity.RARE)
        wearer = await make_user(db_session, status=UserStatus.ACTIVE)
        wearer.character_class_id = rogue.id
        await db_session.flush()

        rows = (await client.get("/api/admin/classes")).json()
        row = next(r for r in rows if r["id"] == str(rogue.id))

        assert row["wearers"] == 1
        assert row["rarity"] == "rare"
        assert row["preference_count"] == 0


class TestAchievementRewards:
    async def test_the_reward_can_be_set_which_it_could_not_before(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        """loot_box_type, loot_rarity and no_loot_line were on the model and in
        no update schema, so a payout was whatever the seed said, permanently."""
        await admin(db_session, client, sign_in)
        achievement = await make_achievement(db_session, "first_blood")

        response = await client.patch(
            f"/api/admin/achievements/{achievement.id}",
            json={"loot_box_type": "adventurer", "loot_rarity": "gold"},
        )

        assert response.status_code == 200
        assert response.json()["loot_box_type"] == "adventurer"
        assert response.json()["loot_rarity"] == "gold"

    async def test_a_reward_is_cleared_by_a_flag_not_by_a_null(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        """PATCH cannot tell "not sent" from "set to null", and null is the
        cleared value — so clearing needs saying out loud."""
        await admin(db_session, client, sign_in)
        achievement = await make_achievement(db_session, "had_a_box")
        await client.patch(
            f"/api/admin/achievements/{achievement.id}",
            json={"loot_box_type": "boss", "loot_rarity": "legendary"},
        )

        response = await client.patch(
            f"/api/admin/achievements/{achievement.id}", json={"clear_loot": True}
        )

        assert response.json()["loot_box_type"] is None
        assert response.json()["loot_rarity"] is None

    async def test_a_secret_theme_can_be_attached(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await admin(db_session, client, sign_in)
        achievement = await make_achievement(db_session, "found_the_squirrel")

        response = await client.patch(
            f"/api/admin/achievements/{achievement.id}",
            json={"unlocks_theme": "purple-squirrel"},
        )

        assert response.status_code == 200
        assert response.json()["unlocks_theme"] == "purple-squirrel"

    async def test_an_everyday_theme_cannot_be_attached(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        """Granting Parchment is not a reward — the player already had it."""
        await admin(db_session, client, sign_in)
        achievement = await make_achievement(db_session, "nothing_special")

        response = await client.patch(
            f"/api/admin/achievements/{achievement.id}", json={"unlocks_theme": "parchment"}
        )

        assert response.status_code >= 400
        assert response.json()["error"]["code"] == "theme_not_grantable"


class TestThemeUnlocks:
    async def test_granting_is_idempotent(self, db_session: AsyncSession) -> None:
        """Earning what an admin already gave you is the same grant, settled by
        the unique constraint rather than a check-then-insert."""
        player = await make_user(db_session, status=UserStatus.ACTIVE)

        first = await theme_unlocks.grant(db_session, player.id, "dnd", source=UnlockSource.ADMIN)
        second = await theme_unlocks.grant(
            db_session, player.id, "dnd", source=UnlockSource.ACHIEVEMENT
        )

        assert first is True
        assert second is False
        rows = (
            (
                await db_session.execute(
                    select(UserThemeUnlock).where(UserThemeUnlock.user_id == player.id)
                )
            )
            .scalars()
            .all()
        )
        assert len(rows) == 1

    async def test_an_unknown_theme_is_not_granted(self, db_session: AsyncSession) -> None:
        player = await make_user(db_session, status=UserStatus.ACTIVE)

        assert (
            await theme_unlocks.grant(
                db_session, player.id, "midnight-gala", source=UnlockSource.ADMIN
            )
            is False
        )

    async def test_only_secret_themes_are_grantable(self) -> None:
        grantable = theme_unlocks.grantable()

        assert set(grantable) == {"purple-squirrel", "dnd", "mr-anderson"}
        assert "parchment" not in grantable

    async def test_an_admin_can_grant_and_revoke(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        """The escape hatch for §5's refusal to grant retroactively."""
        await admin(db_session, client, sign_in)
        player = await make_user(db_session, status=UserStatus.ACTIVE)

        granted = await client.post(
            f"/api/admin/users/{player.id}/theme-grant",
            json={"theme": "mr-anderson", "granted": True, "reason": "Earned it the hard way"},
        )
        assert granted.status_code == 200
        assert await theme_unlocks.holds(db_session, player.id, "mr-anderson")

        revoked = await client.post(
            f"/api/admin/users/{player.id}/theme-grant",
            json={"theme": "mr-anderson", "granted": False},
        )
        assert revoked.status_code == 200
        assert not await theme_unlocks.holds(db_session, player.id, "mr-anderson")

    async def test_an_everyday_theme_cannot_be_granted(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await admin(db_session, client, sign_in)
        player = await make_user(db_session, status=UserStatus.ACTIVE)

        response = await client.post(
            f"/api/admin/users/{player.id}/theme-grant",
            json={"theme": "dark-dungeon", "granted": True},
        )

        assert response.json()["error"]["code"] == "theme_not_grantable"

    async def test_revoking_leaves_the_player_to_the_fallback(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        """No cleanup on `user.theme`: spec 048's unknown-theme fallback moves
        them off it, which is the same path a removed preset takes."""
        admin_user = await admin(db_session, client, sign_in)
        await theme_unlocks.grant(db_session, admin_user.id, "dnd", source=UnlockSource.ADMIN)
        await client.patch("/api/auth/me/theme", json={"theme": "dnd"})

        await client.post(
            f"/api/admin/users/{admin_user.id}/theme-grant",
            json={"theme": "dnd", "granted": False},
        )

        body = (await client.get("/api/auth/me")).json()
        assert body["theme"] != "dnd"
        assert "dnd" not in body["unlocked_themes"]

    async def test_me_reports_what_the_player_holds(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        player = await make_user(db_session, status=UserStatus.ACTIVE)
        await sign_in(client, player)
        await theme_unlocks.grant(db_session, player.id, "dnd", source=UnlockSource.ADMIN)

        body = (await client.get("/api/auth/me")).json()

        assert body["unlocked_themes"] == ["dnd"]


class TestBulk:
    async def test_setting_a_skill_kind_in_bulk(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await admin(db_session, client, sign_in)
        first = await make_skill(db_session, name="One")
        second = await make_skill(db_session, name="Two")

        response = await client.post(
            "/api/admin/skills/bulk",
            json={"ids": [str(first.id), str(second.id)], "action": "set_kind", "value": "funny"},
        )

        assert response.json()["changed"] == 2
        await db_session.refresh(first)
        assert first.kind.value == "funny"

    async def test_an_unknown_action_is_refused(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await admin(db_session, client, sign_in)
        skill = await make_skill(db_session, name="Safe")

        response = await client.post(
            "/api/admin/skills/bulk",
            json={"ids": [str(skill.id)], "action": "drop_database", "value": None},
        )

        assert response.status_code >= 400
        assert response.json()["error"]["code"] == "unknown_action"

    async def test_deleting_a_worn_class_is_refused_and_says_why(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        """The FK is SET NULL, so deleting would silently return players to
        Classless. Refusing reports it instead."""
        await admin(db_session, client, sign_in)
        worn = await make_class(db_session, "Worn")
        spare = await make_class(db_session, "Spare")
        wearer = await make_user(db_session, status=UserStatus.ACTIVE)
        wearer.character_class_id = worn.id
        await db_session.flush()

        response = await client.post(
            "/api/admin/classes/bulk",
            json={"ids": [str(worn.id), str(spare.id)], "action": "delete"},
        )

        body = response.json()
        assert body["changed"] == 1
        assert str(worn.id) in body["refused"]
        assert "wearing" in body["refused"][str(worn.id)]

    async def test_deleting_a_held_achievement_is_refused_in_bulk_too(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        """Spec 030's rule, applied where silently skipping would be worse."""
        from app.models.notification import AchievementAward

        await admin(db_session, client, sign_in)
        held = await make_achievement(db_session, "held_one")
        free = await make_achievement(db_session, "free_one")
        player = await make_user(db_session, status=UserStatus.ACTIVE)
        db_session.add(AchievementAward(achievement_id=held.id, user_id=player.id))
        await db_session.flush()

        response = await client.post(
            "/api/admin/achievements/bulk",
            json={"ids": [str(held.id), str(free.id)], "action": "delete"},
        )

        body = response.json()
        assert body["changed"] == 1
        assert str(held.id) in body["refused"]

    async def test_clearing_a_loot_box_in_bulk_clears_its_rarity_too(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        """A rarity describing no box is a number about nothing."""
        await admin(db_session, client, sign_in)
        achievement = await make_achievement(db_session, "boxed")
        await client.patch(
            f"/api/admin/achievements/{achievement.id}",
            json={"loot_box_type": "purist", "loot_rarity": "silver"},
        )

        await client.post(
            "/api/admin/achievements/bulk",
            json={"ids": [str(achievement.id)], "action": "set_loot_box", "value": None},
        )

        await db_session.refresh(achievement)
        assert achievement.loot_box_type is None
        assert achievement.loot_rarity is None

    async def test_an_organizer_cannot_bulk_anything(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        organizer = await make_user(db_session, role=UserRole.ORGANIZER, status=UserStatus.ACTIVE)
        await sign_in(client, organizer)
        skill = await make_skill(db_session, name="Untouchable")

        response = await client.post(
            "/api/admin/skills/bulk",
            json={"ids": [str(skill.id)], "action": "set_kind", "value": "funny"},
        )

        assert response.status_code == 403


class TestClassSets:
    async def test_preferences_replace_as_a_set(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await admin(db_session, client, sign_in)
        rogue = await make_class(db_session, "Rogue")
        skill = await make_skill(db_session, name="Lockpicking")

        await client.put(
            f"/api/admin/classes/{rogue.id}/preferences",
            json={"preferences": [{"ability": "dex"}, {"skill_id": str(skill.id)}]},
        )
        response = await client.put(
            f"/api/admin/classes/{rogue.id}/preferences",
            json={"preferences": [{"ability": "int"}]},
        )

        assert len(response.json()["preferences"]) == 1
        assert response.json()["preferences"][0]["ability"] == "int"

    async def test_a_preference_naming_both_targets_is_refused(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        """The XOR the model's CHECK enforces, explained rather than surfaced as
        an integrity error."""
        await admin(db_session, client, sign_in)
        rogue = await make_class(db_session, "Confused")
        skill = await make_skill(db_session, name="Both")

        response = await client.put(
            f"/api/admin/classes/{rogue.id}/preferences",
            json={"preferences": [{"ability": "dex", "skill_id": str(skill.id)}]},
        )

        assert response.status_code >= 400
        assert response.json()["error"]["code"] == "preference_not_exclusive"

    async def test_a_preference_naming_neither_is_refused(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await admin(db_session, client, sign_in)
        rogue = await make_class(db_session, "Empty")

        response = await client.put(
            f"/api/admin/classes/{rogue.id}/preferences", json={"preferences": [{}]}
        )

        assert response.json()["error"]["code"] == "preference_not_exclusive"

    async def test_requirements_cannot_name_a_skill_twice(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await admin(db_session, client, sign_in)
        rogue = await make_class(db_session, "Twice")
        skill = await make_skill(db_session, name="Repeated")

        response = await client.put(
            f"/api/admin/classes/{rogue.id}/requirements",
            json={
                "requirements": [
                    {"skill_id": str(skill.id), "min_level": 2},
                    {"skill_id": str(skill.id), "min_level": 3},
                ]
            },
        )

        assert response.json()["error"]["code"] == "duplicate_requirement"

    async def test_rarity_is_settable(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        """On the model since spec 024 and settable from nowhere until now."""
        await admin(db_session, client, sign_in)
        rogue = await make_class(db_session, "Shiny")

        response = await client.patch(f"/api/admin/classes/{rogue.id}", json={"rarity": "mythic"})

        assert response.json()["rarity"] == "mythic"
