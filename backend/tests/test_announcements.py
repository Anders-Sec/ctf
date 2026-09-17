"""Announcements with a history and scheduling (spec 054)."""

from datetime import UTC, datetime, timedelta

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.models.announcement import Announcement
from app.models.notification import Notification, NotificationKind
from app.models.user import UserRole, UserStatus
from app.redis import get_redis
from app.services import announcements
from tests.factories import make_user


async def admin(db_session: AsyncSession, client: AsyncClient, sign_in):
    user = await make_user(db_session, role=UserRole.ADMIN, status=UserStatus.ACTIVE)
    await sign_in(client, user)
    return user


def created_id(response) -> str:
    return response.json()["id"]


class TestSendingNow:
    async def test_it_records_what_was_said(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        """The composer reported a recipient count and then forgot. Over five
        days that leaves no way to answer "what have I already told people?"."""
        await admin(db_session, client, sign_in)
        await make_user(db_session, status=UserStatus.ACTIVE)

        response = await client.post(
            "/api/admin/announcements",
            json={"title": "Lunch", "body": "In the atrium."},
        )

        assert response.status_code == 200
        body = response.json()
        assert body["title"] == "Lunch"
        assert body["sent_at"] is not None
        assert body["recipient_count"] >= 1

    async def test_it_appears_in_the_history(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await admin(db_session, client, sign_in)
        await client.post("/api/admin/announcements", json={"title": "Doors", "body": "Are open."})

        rows = (await client.get("/api/admin/announcements")).json()

        assert any(row["title"] == "Doors" for row in rows)

    async def test_the_read_count_is_counted_not_stored(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        """Read state already lives on the notification; a second number on the
        announcement would be one to keep in step by hand."""
        await admin(db_session, client, sign_in)
        player = await make_user(db_session, status=UserStatus.ACTIVE)

        await client.post("/api/admin/announcements", json={"title": "Read me", "body": "Please."})

        notification = (
            await db_session.execute(
                select(Notification).where(
                    Notification.user_id == player.id,
                    Notification.kind == NotificationKind.ANNOUNCEMENT,
                )
            )
        ).scalar_one_or_none()
        assert notification is not None
        assert notification.announcement_id is not None

        notification.read_at = datetime.now(UTC)
        await db_session.flush()

        rows = (await client.get("/api/admin/announcements")).json()
        row = next(r for r in rows if r["title"] == "Read me")
        assert row["read_count"] == 1

    async def test_a_staff_announcement_does_not_reach_players(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await admin(db_session, client, sign_in)
        player = await make_user(db_session, status=UserStatus.ACTIVE)

        await client.post(
            "/api/admin/announcements",
            json={"title": "Staff only", "body": "Helpers, gather.", "audience": "staff"},
        )

        reached = (
            await db_session.execute(
                select(Notification).where(
                    Notification.user_id == player.id, Notification.title == "Staff only"
                )
            )
        ).scalar_one_or_none()
        assert reached is None


class TestScheduling:
    async def test_a_future_announcement_does_not_go_out_yet(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await admin(db_session, client, sign_in)
        await make_user(db_session, status=UserStatus.ACTIVE)
        later = (datetime.now(UTC) + timedelta(hours=3)).isoformat()

        response = await client.post(
            "/api/admin/announcements",
            json={"title": "Later", "body": "Not yet.", "scheduled_for": later},
        )

        assert response.json()["sent_at"] is None
        assert response.json()["scheduled_for"] is not None

    async def test_a_schedule_in_the_past_sends_immediately(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        """A schedule for a time already gone is a send; leaving it pending
        until the next sweep would help nobody."""
        await admin(db_session, client, sign_in)
        await make_user(db_session, status=UserStatus.ACTIVE)
        earlier = (datetime.now(UTC) - timedelta(minutes=5)).isoformat()

        response = await client.post(
            "/api/admin/announcements",
            json={"title": "Overdue", "body": "Going now.", "scheduled_for": earlier},
        )

        assert response.json()["sent_at"] is not None

    async def test_a_due_announcement_goes_on_the_next_sweep(
        self, client: AsyncClient, db_session: AsyncSession, sign_in, settings: Settings
    ) -> None:
        """Late rather than skipped: if the process was down at the due moment it
        still goes, and the history keeps both times."""
        await admin(db_session, client, sign_in)
        await make_user(db_session, status=UserStatus.ACTIVE)
        later = datetime.now(UTC) + timedelta(hours=1)
        created = await client.post(
            "/api/admin/announcements",
            json={"title": "Due", "body": "Soon.", "scheduled_for": later.isoformat()},
        )
        announcement = await db_session.get(Announcement, created_id(created))
        assert announcement is not None

        # The moment arrives.
        announcement.scheduled_for = datetime.now(UTC) - timedelta(seconds=1)
        await db_session.flush()

        sent = await announcements.send_due(db_session, get_redis(settings))

        assert sent == 1
        await db_session.refresh(announcement)
        assert announcement.sent_at is not None
        # Both times survive, so the history can show it went late.
        assert announcement.scheduled_for is not None

    async def test_sending_twice_does_not_duplicate(
        self, client: AsyncClient, db_session: AsyncSession, sign_in, settings: Settings
    ) -> None:
        await admin(db_session, client, sign_in)
        await make_user(db_session, status=UserStatus.ACTIVE)
        await client.post(
            "/api/admin/announcements",
            json={
                "title": "Once",
                "body": "Only.",
                "scheduled_for": (datetime.now(UTC) - timedelta(seconds=1)).isoformat(),
            },
        )

        again = await announcements.send_due(db_session, get_redis(settings))

        assert again == 0


class TestPendingOnly:
    async def test_a_pending_announcement_can_be_edited(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await admin(db_session, client, sign_in)
        later = (datetime.now(UTC) + timedelta(hours=2)).isoformat()
        created = await client.post(
            "/api/admin/announcements",
            json={"title": "Draft", "body": "Rough.", "scheduled_for": later},
        )

        response = await client.patch(
            f"/api/admin/announcements/{created_id(created)}", json={"body": "Polished."}
        )

        assert response.status_code == 200
        assert response.json()["body"] == "Polished."

    async def test_a_sent_announcement_cannot_be_edited(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        """A history that could be rewritten afterwards is worth less than none."""
        await admin(db_session, client, sign_in)
        created = await client.post(
            "/api/admin/announcements", json={"title": "Gone", "body": "Out."}
        )

        response = await client.patch(
            f"/api/admin/announcements/{created_id(created)}", json={"body": "Changed."}
        )

        assert response.status_code >= 400
        assert response.json()["error"]["code"] == "already_sent"

    async def test_a_pending_announcement_can_be_cancelled(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await admin(db_session, client, sign_in)
        later = (datetime.now(UTC) + timedelta(hours=2)).isoformat()
        created = await client.post(
            "/api/admin/announcements",
            json={"title": "Never mind", "body": "Cancelled.", "scheduled_for": later},
        )

        response = await client.post(f"/api/admin/announcements/{created_id(created)}/cancel")

        assert response.status_code == 200
        assert response.json()["cancelled_at"] is not None

    async def test_a_cancelled_announcement_never_goes_out(
        self, client: AsyncClient, db_session: AsyncSession, sign_in, settings: Settings
    ) -> None:
        await admin(db_session, client, sign_in)
        created = await client.post(
            "/api/admin/announcements",
            json={
                "title": "Recalled",
                "body": "No.",
                "scheduled_for": (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
            },
        )
        announcement = await db_session.get(Announcement, created_id(created))
        assert announcement is not None
        await client.post(f"/api/admin/announcements/{announcement.id}/cancel")

        announcement.scheduled_for = datetime.now(UTC) - timedelta(seconds=1)
        await db_session.flush()
        await announcements.send_due(db_session, get_redis(settings))

        await db_session.refresh(announcement)
        assert announcement.sent_at is None

    async def test_a_sent_announcement_cannot_be_cancelled(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await admin(db_session, client, sign_in)
        created = await client.post(
            "/api/admin/announcements", json={"title": "Out", "body": "Already."}
        )

        response = await client.post(f"/api/admin/announcements/{created_id(created)}/cancel")

        assert response.json()["error"]["code"] == "already_sent"


class TestAccess:
    async def test_an_organizer_cannot_announce(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        organizer = await make_user(db_session, role=UserRole.ORGANIZER, status=UserStatus.ACTIVE)
        await sign_in(client, organizer)

        response = await client.post(
            "/api/admin/announcements", json={"title": "Nope", "body": "Not allowed."}
        )

        assert response.status_code == 403
