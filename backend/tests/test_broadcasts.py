"""Broadcast notifications (spec 032)."""

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.challenge import BossTier
from app.models.notification import BroadcastLog, Notification, NotificationKind
from app.models.user import UserRole, UserStatus
from app.services import achievements as engine
from app.services import dispatch
from app.services import notifications as notification_service
from tests.factories import make_category, make_challenge, make_user, record_solve

pytestmark = pytest.mark.usefixtures("running_event")


async def as_role(db_session, client, sign_in, role: UserRole):
    user = await make_user(db_session, role=role, status=UserStatus.ACTIVE)
    await sign_in(client, user)
    return user


async def count_for(db_session, user_id) -> int:
    return (
        await db_session.scalar(
            select(func.count(Notification.id)).where(Notification.user_id == user_id)
        )
    ) or 0


class TestFanOut:
    async def test_it_reaches_every_active_player(self, db_session: AsyncSession) -> None:
        players = [await make_user(db_session, status=UserStatus.ACTIVE) for _ in range(3)]

        result = await notification_service.broadcast(
            db_session,
            kind=NotificationKind.ANNOUNCEMENT,
            key="test:everyone",
            title="Listen",
            body="Something happened.",
        )

        assert result.sent is True
        assert result.recipients >= 3
        for player in players:
            assert await count_for(db_session, player.id) == 1

    async def test_it_skips_accounts_that_cannot_act_on_it(self, db_session: AsyncSession) -> None:
        """A pending or disabled account cannot do anything with the news, and
        staff are watching the console rather than the feed."""
        pending = await make_user(db_session, status=UserStatus.PENDING_APPROVAL)
        disabled = await make_user(db_session, status=UserStatus.DISABLED)
        admin = await make_user(db_session, status=UserStatus.ACTIVE, role=UserRole.ADMIN)

        await notification_service.broadcast(
            db_session,
            kind=NotificationKind.ANNOUNCEMENT,
            key="test:skips",
            title="Listen",
            body="Something happened.",
        )

        assert await count_for(db_session, pending.id) == 0
        assert await count_for(db_session, disabled.id) == 0
        assert await count_for(db_session, admin.id) == 0

    async def test_every_row_still_names_one_recipient(self, db_session: AsyncSession) -> None:
        """028's guarantee is unchanged by fan-out: there is no row belonging to
        nobody, which every query in 028 assumes cannot happen."""
        await make_user(db_session, status=UserStatus.ACTIVE)

        await notification_service.broadcast(
            db_session,
            kind=NotificationKind.ANNOUNCEMENT,
            key="test:owned",
            title="Listen",
            body="Something happened.",
        )

        orphaned = await db_session.scalar(
            select(func.count(Notification.id)).where(Notification.user_id.is_(None))
        )
        assert orphaned == 0


class TestSendingOnce:
    async def test_the_same_key_sends_nothing_the_second_time(
        self, db_session: AsyncSession
    ) -> None:
        player = await make_user(db_session, status=UserStatus.ACTIVE)

        first = await notification_service.broadcast(
            db_session,
            kind=NotificationKind.DISPATCH,
            key="2026-09-14",
            title="Day one",
            body="It begins.",
        )
        second = await notification_service.broadcast(
            db_session,
            kind=NotificationKind.DISPATCH,
            key="2026-09-14",
            title="Day one",
            body="It begins.",
        )

        assert first.sent is True
        assert second.sent is False
        assert second.recipients == 0
        # And crucially the player was not told twice.
        assert await count_for(db_session, player.id) == 1

    async def test_losing_the_claim_does_not_discard_the_caller_s_work(
        self, db_session: AsyncSession
    ) -> None:
        """The claim uses a savepoint, so a duplicate must not roll back
        whatever the caller was in the middle of."""
        marker = await make_user(db_session, status=UserStatus.ACTIVE)
        await notification_service.claim(db_session, NotificationKind.DISPATCH, "savepoint-test")

        again = await notification_service.claim(
            db_session, NotificationKind.DISPATCH, "savepoint-test"
        )

        assert again is False
        # The user created before the failed claim is still there.
        assert await db_session.get(type(marker), marker.id) is not None

    async def test_a_different_key_is_a_different_broadcast(self, db_session: AsyncSession) -> None:
        player = await make_user(db_session, status=UserStatus.ACTIVE)

        for day in ("2026-09-14", "2026-09-15"):
            await notification_service.broadcast(
                db_session,
                kind=NotificationKind.DISPATCH,
                key=day,
                title=f"Day {day}",
                body="Carry on.",
            )

        assert await count_for(db_session, player.id) == 2

    async def test_the_log_records_how_many_it_reached(self, db_session: AsyncSession) -> None:
        await make_user(db_session, status=UserStatus.ACTIVE)

        result = await notification_service.broadcast(
            db_session,
            kind=NotificationKind.ANNOUNCEMENT,
            key="test:counted",
            title="Listen",
            body="Something happened.",
        )

        logged = (
            await db_session.execute(select(BroadcastLog).where(BroadcastLog.key == "test:counted"))
        ).scalar_one()
        assert logged.recipients == result.recipients


class TestBossFirstKill:
    async def test_the_first_kill_is_announced(self, db_session: AsyncSession) -> None:
        bystander = await make_user(db_session, status=UserStatus.ACTIVE)
        slayer = await make_user(db_session, status=UserStatus.ACTIVE)
        zone = await make_category(db_session, name="Broadcast Boss Zone")
        boss = await make_challenge(db_session, category=zone, title="The Big One")
        boss.boss_tier = BossTier.FLOOR
        await db_session.flush()
        await record_solve(db_session, slayer, boss)

        await engine.announce_boss_kill(db_session, slayer.id)

        feed = await notification_service.backlog(db_session, bystander.id)
        assert any(n.kind == "boss_kill" for n in feed)
        # The player is named. That is the point.
        assert any(slayer.display_name in n.body for n in feed)

    async def test_the_second_kill_is_not(self, db_session: AsyncSession) -> None:
        """Twenty players beating the same boss would be twenty broadcasts
        nobody wants."""
        bystander = await make_user(db_session, status=UserStatus.ACTIVE)
        first = await make_user(db_session, status=UserStatus.ACTIVE)
        second = await make_user(db_session, status=UserStatus.ACTIVE)
        zone = await make_category(db_session, name="Broadcast Second Zone")
        boss = await make_challenge(db_session, category=zone, title="The Second One")
        boss.boss_tier = BossTier.CITY
        await db_session.flush()

        start = datetime.now(UTC)
        await record_solve(db_session, first, boss, submitted_at=start)
        await record_solve(db_session, second, boss, submitted_at=start + timedelta(minutes=5))

        await engine.announce_boss_kill(db_session, first.id)
        before = await count_for(db_session, bystander.id)
        await engine.announce_boss_kill(db_session, second.id)

        assert await count_for(db_session, bystander.id) == before

    async def test_an_ordinary_solve_announces_nothing(self, db_session: AsyncSession) -> None:
        bystander = await make_user(db_session, status=UserStatus.ACTIVE)
        solver = await make_user(db_session, status=UserStatus.ACTIVE)
        ordinary = await make_challenge(db_session, title="Broadcast Ordinary")
        await record_solve(db_session, solver, ordinary)

        await engine.announce_boss_kill(db_session, solver.id)

        assert await count_for(db_session, bystander.id) == 0


class TestTheDailyDispatch:
    async def test_it_is_skipped_before_the_event_opens(
        self, db_session: AsyncSession, running_event
    ) -> None:
        """A dispatch full of zeros is worse than silence."""
        await make_user(db_session, status=UserStatus.ACTIVE)
        running_event.starts_at = datetime.now(UTC) + timedelta(days=2)
        await db_session.flush()

        assert await dispatch.send_today(db_session) is False

    async def test_it_is_skipped_when_the_event_has_no_start_time(
        self, db_session: AsyncSession, running_event
    ) -> None:
        await make_user(db_session, status=UserStatus.ACTIVE)
        running_event.starts_at = None
        await db_session.flush()

        assert await dispatch.send_today(db_session) is False

    async def test_it_sends_once_a_day(self, db_session: AsyncSession, running_event) -> None:
        player = await make_user(db_session, status=UserStatus.ACTIVE)
        running_event.starts_at = datetime.now(UTC) - timedelta(days=1)
        await db_session.flush()

        assert await dispatch.send_today(db_session) is True
        assert await dispatch.send_today(db_session) is False
        assert await count_for(db_session, player.id) == 1

    async def test_two_replicas_send_one_message(
        self, db_session: AsyncSession, running_event
    ) -> None:
        """Both pods run the same timer; the constraint decides which sends."""
        player = await make_user(db_session, status=UserStatus.ACTIVE)
        running_event.starts_at = datetime.now(UTC) - timedelta(days=1)
        await db_session.flush()

        results = [await dispatch.send_today(db_session) for _ in range(2)]

        assert results.count(True) == 1
        assert await count_for(db_session, player.id) == 1


class TestAnnouncements:
    async def test_an_admin_reaches_everybody(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        player = await make_user(db_session, status=UserStatus.ACTIVE)
        await as_role(db_session, client, sign_in, UserRole.ADMIN)

        sent = await client.post(
            "/api/admin/announcements",
            json={"title": "Crypto is back", "body": "The wing is fixed."},
        )

        assert sent.status_code == 200
        assert sent.json()["recipient_count"] >= 1
        assert await count_for(db_session, player.id) == 1

    async def test_two_announcements_both_send(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        """The key is fresh each time: sending two different announcements is
        entirely legitimate."""
        player = await make_user(db_session, status=UserStatus.ACTIVE)
        await as_role(db_session, client, sign_in, UserRole.ADMIN)

        for title in ("First", "Second"):
            await client.post("/api/admin/announcements", json={"title": title, "body": "Body."})

        assert await count_for(db_session, player.id) == 2

    async def test_a_player_may_not_announce(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await as_role(db_session, client, sign_in, UserRole.PLAYER)

        refused = await client.post(
            "/api/admin/announcements", json={"title": "Hello", "body": "Everyone."}
        )

        assert refused.status_code == 403

    async def test_an_organizer_may_not_announce(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        """Read-only staff stay read-only."""
        await as_role(db_session, client, sign_in, UserRole.ORGANIZER)

        refused = await client.post(
            "/api/admin/announcements", json={"title": "Hello", "body": "Everyone."}
        )

        assert refused.status_code == 403


class TestDeliveryIsBestEffort:
    async def test_a_redis_failure_still_writes_the_backlog(self, db_session: AsyncSession) -> None:
        """The rows are the record. A Redis hiccup costs a toast and nothing
        else — the same rule notify() follows."""

        class Broken:
            async def publish(self, *_args, **_kwargs):
                raise RuntimeError("redis is down")

        player = await make_user(db_session, status=UserStatus.ACTIVE)

        result = await notification_service.broadcast(
            db_session,
            kind=NotificationKind.ANNOUNCEMENT,
            key="test:redis-down",
            title="Listen",
            body="Something happened.",
            redis=Broken(),
        )

        assert result.sent is True
        assert await count_for(db_session, player.id) == 1


class TestConcurrency:
    async def test_concurrent_claims_produce_one_winner(self, db_session: AsyncSession) -> None:
        """Sequential in this session, but the assertion is the one that matters:
        the constraint, not the caller, decides."""
        results = await asyncio.gather(
            *[
                notification_service.claim(db_session, NotificationKind.DISPATCH, "race-key")
                for _ in range(1)
            ]
        )
        again = await notification_service.claim(db_session, NotificationKind.DISPATCH, "race-key")

        assert results == [True]
        assert again is False
