"""Notifications and achievements (spec 028)."""

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.challenge import ChallengeState, ScoringMode
from app.models.notification import (
    Achievement,
    AchievementAward,
    Notification,
    NotificationKind,
)
from app.models.user import UserStatus
from app.services import achievements as achievement_service
from app.services import notifications as notification_service
from tests.factories import make_category, make_challenge, make_user, record_solve

pytestmark = pytest.mark.usefixtures("running_event")


async def player(db_session, client, sign_in, **kwargs):
    kwargs.setdefault("status", UserStatus.ACTIVE)
    user = await make_user(db_session, **kwargs)
    await sign_in(client, user)
    return user


async def achievement(db_session, code: str) -> Achievement:
    return (
        await db_session.execute(select(Achievement).where(Achievement.code == code))
    ).scalar_one()


class TestTheFeed:
    async def test_a_notification_reaches_its_recipient_only(
        self, db_session: AsyncSession
    ) -> None:
        mine = await make_user(db_session, status=UserStatus.ACTIVE)
        theirs = await make_user(db_session, status=UserStatus.ACTIVE)

        await notification_service.notify(
            db_session,
            user_id=mine.id,
            kind=NotificationKind.SYSTEM,
            title="For you",
            body="Only you.",
        )

        assert len(await notification_service.backlog(db_session, mine.id)) == 1
        assert await notification_service.backlog(db_session, theirs.id) == []

    async def test_the_backlog_is_the_record_even_with_no_socket(
        self, db_session: AsyncSession
    ) -> None:
        """Delivery is a nicety; the row is the record. A player who was offline
        when it fired still finds it."""
        user = await make_user(db_session, status=UserStatus.ACTIVE)

        await notification_service.notify(
            db_session,
            user_id=user.id,
            kind=NotificationKind.SYSTEM,
            title="Missed it",
            body="Still here.",
            redis=None,
        )

        assert await notification_service.unread_count(db_session, user.id) == 1

    async def test_marking_read_clears_the_count(self, db_session: AsyncSession) -> None:
        user = await make_user(db_session, status=UserStatus.ACTIVE)
        for index in range(3):
            await notification_service.notify(
                db_session,
                user_id=user.id,
                kind=NotificationKind.SYSTEM,
                title=f"#{index}",
                body="x",
            )

        changed = await notification_service.mark_read(db_session, user.id)

        assert changed == 3
        assert await notification_service.unread_count(db_session, user.id) == 0

    async def test_the_feed_endpoint_returns_the_backlog(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        user = await player(db_session, client, sign_in)
        await notification_service.notify(
            db_session,
            user_id=user.id,
            kind=NotificationKind.SYSTEM,
            title="Hello",
            body="From the System AI.",
        )

        response = await client.get("/api/notifications")

        assert response.status_code == 200
        assert response.json()["unread"] == 1
        assert response.json()["items"][0]["title"] == "Hello"

    async def test_a_player_cannot_read_another_players_feed(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        other = await make_user(db_session, status=UserStatus.ACTIVE)
        await notification_service.notify(
            db_session,
            user_id=other.id,
            kind=NotificationKind.SYSTEM,
            title="Theirs",
            body="Private.",
        )
        await player(db_session, client, sign_in)

        response = await client.get("/api/notifications")

        assert [i["title"] for i in response.json()["items"]] == []


class TestAwarding:
    async def test_a_solve_awards_and_notifies(self, db_session: AsyncSession) -> None:
        user = await make_user(db_session, status=UserStatus.ACTIVE)
        challenge = await make_challenge(db_session, title="Notif First")
        await record_solve(db_session, user, challenge)

        earned = await achievement_service.evaluate(db_session, user.id, achievement_service.SOLVE)

        assert "first_blood" in {a.code for a in earned}
        feed = await notification_service.backlog(db_session, user.id)
        assert any(n.kind == "achievement" for n in feed)

    async def test_it_awards_only_once(self, db_session: AsyncSession) -> None:
        user = await make_user(db_session, status=UserStatus.ACTIVE)
        challenge = await make_challenge(db_session, title="Notif Once")
        await record_solve(db_session, user, challenge)

        await achievement_service.evaluate(db_session, user.id, achievement_service.SOLVE)
        second = await achievement_service.evaluate(db_session, user.id, achievement_service.SOLVE)

        # The constraint is the arbiter, but a re-run must also be a no-op.
        # (The first pass legitimately awards more than one: solving the only
        # published challenge in a category also clears that zone.)
        assert second == []
        first = await achievement(db_session, "first_blood")
        count = await db_session.scalar(
            select(func.count(AchievementAward.id)).where(
                AchievementAward.user_id == user.id,
                AchievementAward.achievement_id == first.id,
            )
        )
        assert count == 1

    async def test_it_does_not_backfill(self, db_session: AsyncSession) -> None:
        """An achievement created after the fact awards nothing for work already
        done. That is the simplification the whole design rests on."""
        user = await make_user(db_session, status=UserStatus.ACTIVE)
        challenge = await make_challenge(db_session, title="Notif Late")
        await record_solve(db_session, user, challenge)
        await achievement_service.evaluate(db_session, user.id, achievement_service.SOLVE)
        before = await db_session.scalar(
            select(func.count(AchievementAward.id)).where(AchievementAward.user_id == user.id)
        )

        # A brand-new achievement whose trigger this player already satisfies.
        db_session.add(Achievement(code="first_blood_copy", name="Late Arrival", description="x"))
        await db_session.flush()
        await achievement_service.evaluate(db_session, user.id, achievement_service.SOLVE)

        after = await db_session.scalar(
            select(func.count(AchievementAward.id)).where(AchievementAward.user_id == user.id)
        )
        # No trigger is registered for that code, so it can never fire.
        assert after == before

    async def test_a_trigger_reads_history_not_the_event(self, db_session: AsyncSession) -> None:
        """Ten solves is a query, not a counter threaded through the call site."""
        user = await make_user(db_session, status=UserStatus.ACTIVE)
        category = await make_category(db_session, name="Notif Bulk")
        for index in range(10):
            challenge = await make_challenge(
                db_session, category=category, title=f"Notif Bulk {index}"
            )
            await record_solve(db_session, user, challenge)

        earned = await achievement_service.evaluate(db_session, user.id, achievement_service.SOLVE)

        assert "getting_comfortable" in {a.code for a in earned}


class TestTheSheet:
    async def test_unearned_achievements_are_redacted_server_side(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await player(db_session, client, sign_in)

        response = await client.get("/api/character/achievements")
        body = response.json()

        # Redacted, not merely blurred in CSS: the name never reaches the
        # browser, so the mystery survives devtools.
        assert body["total"] > 0
        assert body["earned"] == 0
        assert all(item["name"] is None for item in body["items"])
        assert all(item["description"] is None for item in body["items"])

    async def test_an_earned_one_shows_its_name(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        user = await player(db_session, client, sign_in)
        challenge = await make_challenge(db_session, title="Notif Sheet")
        await record_solve(db_session, user, challenge)
        await achievement_service.evaluate(db_session, user.id, achievement_service.SOLVE)

        body = (await client.get("/api/character/achievements")).json()

        named = [i for i in body["items"] if i["name"]]
        assert "First Blood" in {i["name"] for i in named}
        assert body["earned"] >= 1

    async def test_the_rarest_bar_holds_only_earned_ones(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        user = await player(db_session, client, sign_in)
        challenge = await make_challenge(db_session, title="Notif Rare")
        await record_solve(db_session, user, challenge)
        await achievement_service.evaluate(db_session, user.id, achievement_service.SOLVE)

        body = (await client.get("/api/character/achievements")).json()

        assert len(body["rarest"]) <= 5
        assert all(item["earned"] for item in body["rarest"])
        assert all(item["rarity"] is not None for item in body["rarest"])

    async def test_rarity_counts_only_players_who_have_played(
        self, db_session: AsyncSession
    ) -> None:
        """Counting every registered account would make everything look rare in
        proportion to how many people signed up and never played."""
        solver = await make_user(db_session, status=UserStatus.ACTIVE)
        await make_user(db_session, status=UserStatus.ACTIVE)  # never plays
        challenge = await make_challenge(db_session, title="Notif Denominator")
        await record_solve(db_session, solver, challenge)
        await achievement_service.evaluate(db_session, solver.id, achievement_service.SOLVE)

        rarity = await achievement_service.rarity_by_achievement(db_session)
        first = await achievement(db_session, "first_blood")

        # One solver, who holds it: 100%, not 50%.
        assert rarity[first.id] == pytest.approx(1.0)

    async def test_rarity_is_empty_when_nobody_has_played(self, db_session: AsyncSession) -> None:
        assert await achievement_service.rarity_by_achievement(db_session) == {}


class TestProgressAnnouncements:
    async def test_a_solve_that_opens_a_zone_says_so(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        from app.models.challenge import RequirementType
        from app.services import unlocks as unlock_service

        await player(db_session, client, sign_in)
        gateway = await make_category(db_session, name="Notif Gateway")
        wing = await make_category(db_session, name="Notif Wing")
        key = await make_challenge(
            db_session,
            category=gateway,
            title="Notif Key",
            state=ChallengeState.PUBLISHED,
            scoring=ScoringMode.STATIC,
            initial_points=100,
        )
        await unlock_service.add_requirement(
            db_session,
            category_id=wing.id,
            requirement_type=RequirementType.SOLVES_IN_CATEGORY,
            required_category_id=gateway.id,
            threshold=1,
        )
        await db_session.flush()

        response = await client.post(
            f"/api/challenges/{key.id}/submit", json={"answer": "flag{correct}"}
        )
        assert response.status_code == 200
        # Assert the solve actually landed: a wrong answer is also a 200, and
        # would make the rest of this test pass for the wrong reason.
        assert response.json()["correct"] is True

        feed = (await client.get("/api/notifications")).json()
        kinds = {item["kind"] for item in feed["items"]}
        # A wing opening is the most satisfying moment the map has, and it used
        # to happen in silence.
        assert "zone_unlocked" in kinds

    async def test_notifications_survive_a_failed_publish(self, db_session: AsyncSession) -> None:
        """A Redis hiccup must never fail the solve that caused the message."""

        class Broken:
            async def publish(self, *_args, **_kwargs):
                raise RuntimeError("redis is down")

        user = await make_user(db_session, status=UserStatus.ACTIVE)

        view = await notification_service.notify(
            db_session,
            user_id=user.id,
            kind=NotificationKind.SYSTEM,
            title="Undelivered",
            body="But recorded.",
            redis=Broken(),
        )

        assert view.id is not None
        stored = await db_session.scalar(
            select(func.count(Notification.id)).where(Notification.user_id == user.id)
        )
        assert stored == 1


class TestClearing:
    """Soft dismiss, not delete (spec 065 §4)."""

    async def _notify(self, db_session, user, kind, title="Something"):
        from app.services import notifications as notification_service

        return await notification_service.notify(
            db_session, user_id=user.id, kind=kind, title=title, body="Body."
        )

    async def test_a_cleared_row_leaves_the_feed_and_the_count(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        user = await player(db_session, client, sign_in)
        view = await self._notify(db_session, user, NotificationKind.LEVEL_UP)

        before = (await client.get("/api/notifications")).json()
        assert before["unread"] == 1

        await client.post(f"/api/notifications/{view.id}/dismiss")
        after = (await client.get("/api/notifications")).json()

        assert after["items"] == []
        # A badge that counts rows the player can no longer open is worse than
        # no badge, so clearing marks read too.
        assert after["unread"] == 0

    async def test_clearing_an_already_read_row_keeps_its_read_stamp(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        """Dismiss must not rewrite when it was read."""
        from sqlalchemy import select

        from app.models.notification import Notification

        user = await player(db_session, client, sign_in)
        view = await self._notify(db_session, user, NotificationKind.LEVEL_UP)
        await client.post(f"/api/notifications/{view.id}/read")
        read_at = await db_session.scalar(
            select(Notification.read_at).where(Notification.id == view.id)
        )

        await client.post(f"/api/notifications/{view.id}/dismiss")

        assert (
            await db_session.scalar(select(Notification.read_at).where(Notification.id == view.id))
            == read_at
        )

    async def test_it_is_a_stamp_rather_than_a_delete(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        """Somebody who clears an announcement has not destroyed it."""
        from sqlalchemy import select

        from app.models.notification import Notification

        user = await player(db_session, client, sign_in)
        view = await self._notify(db_session, user, NotificationKind.ANNOUNCEMENT)

        await client.post(f"/api/notifications/{view.id}/dismiss")

        row = await db_session.scalar(select(Notification).where(Notification.id == view.id))
        assert row is not None
        assert row.dismissed_at is not None

    async def test_clear_all_takes_everything_when_unscoped(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        user = await player(db_session, client, sign_in)
        await self._notify(db_session, user, NotificationKind.LEVEL_UP)
        await self._notify(db_session, user, NotificationKind.BOSS_KILL)

        await client.post("/api/notifications/dismiss", json={"kinds": []})

        assert (await client.get("/api/notifications")).json()["items"] == []

    async def test_clear_all_scoped_by_kind_spares_the_other_tab(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        """Clearing the event news must not throw away a player's own record."""
        user = await player(db_session, client, sign_in)
        await self._notify(db_session, user, NotificationKind.LEVEL_UP, title="You levelled")
        await self._notify(db_session, user, NotificationKind.BOSS_KILL, title="Rin felled it")
        await self._notify(db_session, user, NotificationKind.DISPATCH, title="Day two")

        await client.post(
            "/api/notifications/dismiss",
            json={"kinds": ["boss_kill", "dispatch", "announcement", "system"]},
        )

        items = (await client.get("/api/notifications")).json()["items"]
        assert [item["title"] for item in items] == ["You levelled"]

    async def test_one_player_cannot_clear_another(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await player(db_session, client, sign_in)
        other = await make_user(db_session, status=UserStatus.ACTIVE)
        view = await self._notify(db_session, other, NotificationKind.LEVEL_UP)

        await client.post(f"/api/notifications/{view.id}/dismiss")

        from sqlalchemy import select

        from app.models.notification import Notification

        row = await db_session.scalar(select(Notification).where(Notification.id == view.id))
        assert row.dismissed_at is None


class TestMuting:
    """A volume control, not a filter (spec 070 §4)."""

    async def _notify(self, db_session, user, kind, title="Something"):
        from app.services import notifications as notification_service

        return await notification_service.notify(
            db_session, user_id=user.id, kind=kind, title=title, body="Body."
        )

    async def test_a_muted_kind_leaves_the_count_but_stays_in_the_backlog(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        """The rows still arrive. A notification the server sent is the record."""
        user = await player(db_session, client, sign_in)
        await self._notify(db_session, user, NotificationKind.BOSS_KILL, title="Rin felled it")
        await self._notify(db_session, user, NotificationKind.LEVEL_UP, title="You levelled")

        assert (await client.get("/api/notifications")).json()["unread"] == 2

        await client.patch("/api/auth/me/notifications", json={"kinds": ["boss_kill"]})
        body = (await client.get("/api/notifications")).json()

        assert body["unread"] == 1
        assert {item["title"] for item in body["items"]} == {"Rin felled it", "You levelled"}

    async def test_unmuting_restores_the_count_without_resending(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        user = await player(db_session, client, sign_in)
        await self._notify(db_session, user, NotificationKind.BOSS_KILL)
        await client.patch("/api/auth/me/notifications", json={"kinds": ["boss_kill"]})
        assert (await client.get("/api/notifications")).json()["unread"] == 0

        await client.patch("/api/auth/me/notifications", json={"kinds": []})

        assert (await client.get("/api/notifications")).json()["unread"] == 1

    async def test_an_announcement_may_be_muted(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        """A mute the platform refuses to honour is a worse lie than a missed
        message, and the inbox still holds it (spec 070 §8.2)."""
        user = await player(db_session, client, sign_in)
        await self._notify(db_session, user, NotificationKind.ANNOUNCEMENT, title="Lunch")

        response = await client.patch(
            "/api/auth/me/notifications", json={"kinds": ["announcement"]}
        )

        assert response.status_code == 200
        body = (await client.get("/api/notifications")).json()
        assert body["unread"] == 0
        assert [item["title"] for item in body["items"]] == ["Lunch"]

    async def test_the_session_reports_what_is_muted(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await player(db_session, client, sign_in)

        await client.patch("/api/auth/me/notifications", json={"kinds": ["dispatch"]})

        assert (await client.get("/api/auth/me")).json()["muted_notification_kinds"] == ["dispatch"]

    async def test_an_unknown_kind_is_refused(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await player(db_session, client, sign_in)

        response = await client.patch("/api/auth/me/notifications", json={"kinds": ["not_a_kind"]})

        assert response.status_code == 422
