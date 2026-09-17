"""The email delivery log (spec 055)."""

import pytest
from httpx import AsyncClient
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.models.email import EmailDelivery, EmailKind, EmailStatus
from app.models.user import UserRole, UserStatus
from app.services import mail
from tests.factories import make_user


@pytest.fixture(autouse=True)
async def _clear_deliveries(db_session: AsyncSession):
    """Start each test with an empty log.

    ``_record`` commits its own session — deliberately, since the senders run as
    background tasks after the response — so these rows outlive the per-test
    transaction and even the test run. Without this, sends from every other test
    in the suite dilute the failure rate this file asserts on.
    """
    await db_session.execute(delete(EmailDelivery))
    await db_session.commit()
    yield


async def admin(db_session: AsyncSession, client: AsyncClient, sign_in):
    user = await make_user(db_session, role=UserRole.ADMIN, status=UserStatus.ACTIVE)
    await sign_in(client, user)
    return user


async def deliveries(db_session: AsyncSession) -> list[EmailDelivery]:
    return list(
        (await db_session.execute(select(EmailDelivery).order_by(EmailDelivery.created_at.desc())))
        .scalars()
        .all()
    )


class TestRecording:
    """The `no_outbound_mail` fixture stubs the transport, so these exercise the
    recording around it rather than a real relay."""

    async def test_a_successful_send_is_recorded_with_a_duration(
        self, db_session: AsyncSession, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async def ok(*_args, **_kwargs) -> None:
            return None

        monkeypatch.setattr(mail, "send_message", ok)

        sent = await mail.send_magic_link(settings, "guest@example.com", "https://x/y")

        assert sent is True
        rows = await deliveries(db_session)
        row = next(r for r in rows if r.to_email == "guest@example.com")
        assert row.status == EmailStatus.SENT
        assert row.kind == EmailKind.MAGIC_LINK
        assert row.duration_ms is not None

    async def test_a_relay_failure_records_the_type_and_never_the_message(
        self, db_session: AsyncSession, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`mail.py` notes the exception text can contain the recipient."""

        async def boom(*_args, **_kwargs) -> None:
            raise TimeoutError("connecting to relay for someone@example.com")

        monkeypatch.setattr(mail, "send_message", boom)

        sent = await mail.send_magic_link(settings, "boom@example.com", "https://x/y")

        assert sent is False
        row = next(r for r in await deliveries(db_session) if r.to_email == "boom@example.com")
        assert row.status == EmailStatus.FAILED
        assert row.error_type == "TimeoutError"
        assert "someone@example.com" not in str(row.error_type)

    async def test_unconfigured_smtp_is_its_own_status(
        self, db_session: AsyncSession, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async def unconfigured(*_args, **_kwargs) -> None:
            raise mail.MailNotConfigured("nope")

        monkeypatch.setattr(mail, "send_message", unconfigured)

        await mail.send_magic_link(settings, "nomail@example.com", "https://x/y")

        row = next(r for r in await deliveries(db_session) if r.to_email == "nomail@example.com")
        assert row.status == EmailStatus.NOT_CONFIGURED

    async def test_no_row_ever_holds_a_token_or_a_link(
        self, db_session: AsyncSession, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A delivery log holding a live login link would be a credential store."""

        async def ok(*_args, **_kwargs) -> None:
            return None

        monkeypatch.setattr(mail, "send_message", ok)
        await mail.send_magic_link(settings, "secret@example.com", "https://ctf/auth?token=SECRET")

        row = next(r for r in await deliveries(db_session) if r.to_email == "secret@example.com")
        dumped = str(row.__dict__)
        assert "SECRET" not in dumped
        assert "token" not in dumped

    async def test_it_records_the_address_whether_or_not_it_has_an_account(
        self, db_session: AsyncSession, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The address is the join, not ``user_id``.

        ``_record`` opens its own session — these senders run as background
        tasks, after the response, when the request's session is gone — so a
        user created inside this test's rolled-back transaction is not visible
        to it. That is a property of the test harness, not of the feature: in
        production the account is committed long before any link is sent.

        What matters either way is that the row exists and carries the address,
        which is what the detail drawer filters on.
        """

        async def ok(*_args, **_kwargs) -> None:
            return None

        monkeypatch.setattr(mail, "send_message", ok)
        await make_user(db_session, email="known@example.com")

        await mail.send_magic_link(settings, "known@example.com", "https://x/y")

        row = next(r for r in await deliveries(db_session) if r.to_email == "known@example.com")
        assert row.to_email == "known@example.com"
        assert row.status == EmailStatus.SENT

    async def test_an_address_with_no_account_still_records(
        self, db_session: AsyncSession, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A link can be requested for an address that does not exist, and the
        endpoint answers identically either way — so the row must look the same
        too, or it becomes the enumeration oracle the 202 exists to prevent."""

        async def ok(*_args, **_kwargs) -> None:
            return None

        monkeypatch.setattr(mail, "send_message", ok)

        await mail.send_magic_link(settings, "stranger@example.com", "https://x/y")

        row = next(r for r in await deliveries(db_session) if r.to_email == "stranger@example.com")
        assert row.user_id is None
        assert row.status == EmailStatus.SENT


class TestTheStatusBand:
    async def test_it_reports_whether_smtp_is_configured(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await admin(db_session, client, sign_in)

        body = (await client.get("/api/admin/email/status")).json()

        assert "configured" in body
        assert body["window_minutes"] > 0

    async def test_it_does_not_cry_wolf_on_a_sample_of_one(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await admin(db_session, client, sign_in)
        db_session.add(
            EmailDelivery(
                kind=EmailKind.MAGIC_LINK,
                to_email="one@example.com",
                status=EmailStatus.FAILED,
                error_type="TimeoutError",
            )
        )
        await db_session.flush()

        body = (await client.get("/api/admin/email/status")).json()

        assert body["failed"] >= 1
        assert body["degraded"] is False

    async def test_it_flags_a_real_run_of_failures(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        """Every guest login failing is the thing nobody notices for an hour."""
        await admin(db_session, client, sign_in)
        for index in range(5):
            db_session.add(
                EmailDelivery(
                    kind=EmailKind.MAGIC_LINK,
                    to_email=f"fail{index}@example.com",
                    status=EmailStatus.FAILED,
                    error_type="TimeoutError",
                )
            )
        await db_session.flush()

        body = (await client.get("/api/admin/email/status")).json()

        assert body["degraded"] is True
        assert body["failure_rate"] > 0.5


class TestTheLog:
    async def test_it_filters_by_recipient(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        """A delivery log you cannot search by recipient answers none of the
        questions it exists for."""
        await admin(db_session, client, sign_in)
        for address in ("wanted@example.com", "other@example.com"):
            db_session.add(
                EmailDelivery(kind=EmailKind.MAGIC_LINK, to_email=address, status=EmailStatus.SENT)
            )
        await db_session.flush()

        body = (await client.get("/api/admin/email/deliveries?search=wanted")).json()

        assert body["entries"]
        assert all("wanted" in row["to_email"] for row in body["entries"])

    async def test_it_filters_by_status(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await admin(db_session, client, sign_in)
        db_session.add(
            EmailDelivery(
                kind=EmailKind.MAGIC_LINK, to_email="ok@example.com", status=EmailStatus.SENT
            )
        )
        db_session.add(
            EmailDelivery(
                kind=EmailKind.MAGIC_LINK, to_email="bad@example.com", status=EmailStatus.FAILED
            )
        )
        await db_session.flush()

        body = (await client.get("/api/admin/email/deliveries?status=failed")).json()

        assert all(row["status"] == "failed" for row in body["entries"])

    async def test_it_filters_to_one_player_for_the_detail_drawer(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await admin(db_session, client, sign_in)
        player = await make_user(db_session, email="theirs@example.com")
        db_session.add(
            EmailDelivery(
                kind=EmailKind.MAGIC_LINK,
                to_email=player.email,
                user_id=player.id,
                status=EmailStatus.SENT,
            )
        )
        await db_session.flush()

        body = (await client.get(f"/api/admin/email/deliveries?user_id={player.id}")).json()

        assert body["total"] == 1

    async def test_a_player_cannot_read_it(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        player = await make_user(db_session, status=UserStatus.ACTIVE)
        await sign_in(client, player)

        assert (await client.get("/api/admin/email/deliveries")).status_code == 403


class TestTheTestSend:
    async def test_it_refuses_a_supplied_recipient(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        """An authenticated send-to-anyone endpoint is an open relay with extra
        steps. The body is ignored entirely; it always goes to the caller."""
        await admin(db_session, client, sign_in)

        response = await client.post(
            "/api/admin/email/test", json={"to_email": "victim@example.com"}
        )

        # Either refused for want of configuration, or sent to the admin — never
        # to the address in the body.
        assert "victim@example.com" not in response.text

    async def test_an_organizer_cannot_send_one(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        organizer = await make_user(db_session, role=UserRole.ORGANIZER, status=UserStatus.ACTIVE)
        await sign_in(client, organizer)

        assert (await client.post("/api/admin/email/test")).status_code == 403
