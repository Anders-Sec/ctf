"""End-to-end behaviour of the authentication endpoints (spec 002)."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.models.auth import MagicLinkToken
from app.models.user import User, UserRole, UserSource, UserStatus
from app.services.cookies import (
    ACCESS_COOKIE,
    CSRF_COOKIE,
    CSRF_HEADER,
    REFRESH_COOKIE,
    REFRESH_COOKIE_PATH,
)
from app.services.magic_link import consume_magic_link, issue_magic_link
from tests.factories import make_team, make_user

pytestmark = pytest.mark.usefixtures("clear_rate_limits")


class TestMagicLinkRequest:
    async def test_an_unknown_address_gets_the_same_answer_as_a_known_one(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Otherwise this endpoint is a directory of who is registered."""
        await make_user(db_session, email="known@example.com")

        known = await client.post("/api/auth/magic-link", json={"email": "known@example.com"})
        unknown = await client.post("/api/auth/magic-link", json={"email": "nobody@example.com"})

        assert known.status_code == 202
        assert unknown.status_code == 202
        assert known.json() == unknown.json()

    async def test_a_corporate_address_is_answered_identically(
        self, client: AsyncClient, app, settings: Settings
    ) -> None:
        """Employees are steered to Entra without revealing that they exist."""
        app.state.settings = settings.model_copy(
            update={"entra_enforced_email_domains": ["corp.example"]}
        )

        response = await client.post(
            "/api/auth/magic-link", json={"email": "employee@corp.example"}
        )

        assert response.status_code == 202

    async def test_no_token_is_issued_for_an_enforced_domain(
        self, client: AsyncClient, app, settings: Settings, db_session: AsyncSession
    ) -> None:
        app.state.settings = settings.model_copy(
            update={
                "entra_enforced_email_domains": ["corp.example"],
                "smtp_host": "smtp.example",
                "smtp_from": "ctf@example",
            }
        )

        await client.post("/api/auth/magic-link", json={"email": "employee@corp.example"})

        tokens = (
            (
                await db_session.execute(
                    select(MagicLinkToken).where(MagicLinkToken.email == "employee@corp.example")
                )
            )
            .scalars()
            .all()
        )
        assert tokens == []

    async def test_a_malformed_address_is_rejected(self, client: AsyncClient) -> None:
        response = await client.post("/api/auth/magic-link", json={"email": "not-an-email"})

        assert response.status_code == 422
        assert response.json()["error"]["code"] == "validation_error"

    async def test_repeated_requests_are_rate_limited_but_still_answer_202(
        self, client: AsyncClient
    ) -> None:
        """A limited address must not be distinguishable from an accepted one."""
        responses = [
            await client.post("/api/auth/magic-link", json={"email": "spam@example.com"})
            for _ in range(8)
        ]

        assert {r.status_code for r in responses} == {202}


class TestMagicLinkVerify:
    async def test_a_valid_token_signs_a_new_guest_in_as_pending(
        self, client: AsyncClient, db_session: AsyncSession, settings: Settings
    ) -> None:
        link = await issue_magic_link(db_session, settings, "newguest@example.com")
        token = link.split("token=")[1]

        response = await client.post("/api/auth/magic-link/verify", json={"token": token})

        assert response.status_code == 200
        user = (
            await db_session.execute(select(User).where(User.email == "newguest@example.com"))
        ).scalar_one()
        assert user.status == UserStatus.PENDING_APPROVAL
        assert user.source == UserSource.GUEST

    async def test_signing_in_sets_httponly_session_cookies(
        self, client: AsyncClient, db_session: AsyncSession, settings: Settings
    ) -> None:
        link = await issue_magic_link(db_session, settings, "cookies@example.com")

        response = await client.post(
            "/api/auth/magic-link/verify", json={"token": link.split("token=")[1]}
        )

        cookies = response.headers.get_list("set-cookie")
        access = next(c for c in cookies if c.startswith(ACCESS_COOKIE))
        refresh = next(c for c in cookies if c.startswith(REFRESH_COOKIE))
        csrf = next(c for c in cookies if c.startswith(CSRF_COOKIE))

        assert "HttpOnly" in access
        assert "HttpOnly" in refresh
        # The CSRF cookie is the one the SPA must be able to read.
        assert "HttpOnly" not in csrf

    async def test_a_token_cannot_be_used_twice(
        self, client: AsyncClient, db_session: AsyncSession, settings: Settings
    ) -> None:
        """A forwarded or double-clicked link must not mint two sessions."""
        link = await issue_magic_link(db_session, settings, "once@example.com")
        token = link.split("token=")[1]

        first = await client.post("/api/auth/magic-link/verify", json={"token": token})
        second = await client.post("/api/auth/magic-link/verify", json={"token": token})

        assert first.status_code == 200
        assert second.status_code == 400
        assert second.json()["error"]["code"] == "invalid_or_expired_token"

    async def test_an_expired_token_is_refused(
        self, client: AsyncClient, db_session: AsyncSession, settings: Settings
    ) -> None:
        link = await issue_magic_link(db_session, settings, "stale@example.com")
        token = link.split("token=")[1]
        row = (
            await db_session.execute(
                select(MagicLinkToken).where(MagicLinkToken.email == "stale@example.com")
            )
        ).scalar_one()
        row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        await db_session.flush()

        response = await client.post("/api/auth/magic-link/verify", json={"token": token})

        assert response.status_code == 400

    async def test_a_new_request_retires_the_previous_token(
        self, db_session: AsyncSession, settings: Settings
    ) -> None:
        """So a forwarded old email stops working once a fresh one is asked for."""
        first = await issue_magic_link(db_session, settings, "reissue@example.com")
        await issue_magic_link(db_session, settings, "reissue@example.com")

        assert await consume_magic_link(db_session, first.split("token=")[1]) is None

    async def test_a_forged_token_is_refused(self, client: AsyncClient) -> None:
        response = await client.post("/api/auth/magic-link/verify", json={"token": "a" * 43})

        assert response.status_code == 400
        assert response.json()["error"]["code"] == "invalid_or_expired_token"

    async def test_an_existing_guest_keeps_their_status_and_party(
        self, client: AsyncClient, db_session: AsyncSession, settings: Settings
    ) -> None:
        user = await make_user(db_session, email="returning@example.com", status=UserStatus.ACTIVE)
        team = await make_team(db_session, user)
        link = await issue_magic_link(db_session, settings, "returning@example.com")

        response = await client.post(
            "/api/auth/magic-link/verify", json={"token": link.split("token=")[1]}
        )

        assert response.status_code == 200
        await db_session.refresh(user)
        assert user.status == UserStatus.ACTIVE
        assert team.leader_user_id == user.id


class TestMe:
    async def test_requires_a_session(self, client: AsyncClient) -> None:
        response = await client.get("/api/auth/me")

        assert response.status_code == 401
        assert response.json()["error"]["code"] == "not_authenticated"

    async def test_returns_the_user_and_resolved_capabilities(
        self, client: AsyncClient, db_session: AsyncSession, sign_in, running_event
    ) -> None:
        user = await make_user(db_session, display_name="Grix", status=UserStatus.ACTIVE)
        await sign_in(client, user)

        response = await client.get("/api/auth/me")

        assert response.status_code == 200
        body = response.json()
        assert body["user"]["display_name"] == "Grix"
        assert body["capabilities"]["play"] is True
        assert body["team"] is None

    async def test_reports_the_current_party(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        user = await make_user(db_session, status=UserStatus.ACTIVE)
        await make_team(db_session, user, name="The Mimics")
        await sign_in(client, user)

        body = (await client.get("/api/auth/me")).json()

        assert body["team"]["name"] == "The Mimics"
        assert body["team"]["is_leader"] is True

    async def test_a_pending_guest_may_manage_a_party_but_not_play(
        self, client: AsyncClient, db_session: AsyncSession, sign_in, running_event
    ) -> None:
        user = await make_user(db_session, status=UserStatus.PENDING_APPROVAL)
        await sign_in(client, user)

        caps = (await client.get("/api/auth/me")).json()["capabilities"]

        assert caps["manage_party"] is True
        assert caps["play"] is False
        assert caps["blocked_reason"] == "account_pending_approval"

    async def test_the_server_clock_is_reported_for_the_countdown(
        self, client: AsyncClient, db_session: AsyncSession, sign_in, running_event
    ) -> None:
        """The SPA countdown is decorative; this is the clock that decides."""
        user = await make_user(db_session, status=UserStatus.ACTIVE)
        await sign_in(client, user)

        event = (await client.get("/api/auth/me")).json()["event"]

        assert event["server_time"] is not None
        assert event["starts_at"] is not None

    async def test_a_disabled_account_loses_access_immediately(
        self, client: AsyncClient, db_session: AsyncSession, sign_in, running_event
    ) -> None:
        """Not at the next token expiry — status is read per request, not cached."""
        user = await make_user(db_session, status=UserStatus.ACTIVE)
        await sign_in(client, user)
        assert (await client.get("/api/auth/me")).json()["capabilities"]["play"] is True

        user.status = UserStatus.DISABLED
        await db_session.flush()

        caps = (await client.get("/api/auth/me")).json()["capabilities"]
        assert caps["play"] is False
        assert caps["blocked_reason"] == "account_disabled"

    async def test_a_role_change_takes_effect_immediately(
        self, client: AsyncClient, db_session: AsyncSession, sign_in, running_event
    ) -> None:
        user = await make_user(db_session, status=UserStatus.ACTIVE)
        await sign_in(client, user)
        assert (await client.get("/api/auth/me")).json()["capabilities"]["administer"] is False

        user.role = UserRole.ADMIN
        await db_session.flush()

        assert (await client.get("/api/auth/me")).json()["capabilities"]["administer"] is True

    async def test_a_token_for_a_deleted_account_is_not_a_session(
        self, client: AsyncClient, db_session: AsyncSession, settings: Settings
    ) -> None:
        from app.services.security import create_access_token

        client.cookies.set(ACCESS_COOKIE, create_access_token(settings, uuid.uuid4()))

        assert (await client.get("/api/auth/me")).status_code == 401


class TestCsrf:
    async def test_a_state_changing_request_without_the_header_is_refused(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        """Cookies ride along automatically; without this any site could post."""
        user = await make_user(db_session, status=UserStatus.ACTIVE)
        await sign_in(client, user)
        del client.headers[CSRF_HEADER]

        response = await client.patch("/api/auth/me", json={"display_name": "Hijacked"})

        assert response.status_code == 403
        assert response.json()["error"]["code"] == "csrf_failed"

    async def test_a_mismatched_header_is_refused(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        user = await make_user(db_session, status=UserStatus.ACTIVE)
        await sign_in(client, user)
        client.headers[CSRF_HEADER] = "not-the-cookie"

        response = await client.patch("/api/auth/me", json={"display_name": "Hijacked"})

        assert response.status_code == 403

    async def test_reads_do_not_need_the_header(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        user = await make_user(db_session, status=UserStatus.ACTIVE)
        await sign_in(client, user)
        del client.headers[CSRF_HEADER]

        assert (await client.get("/api/auth/me")).status_code == 200


class TestProfile:
    async def test_a_pending_guest_can_set_their_display_name(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        """The first-run screen asks for this before approval has happened."""
        user = await make_user(db_session, status=UserStatus.PENDING_APPROVAL)
        await sign_in(client, user)

        response = await client.patch("/api/auth/me", json={"display_name": "Torch Bearer"})

        assert response.status_code == 200
        assert response.json()["display_name"] == "Torch Bearer"

    async def test_a_display_name_must_be_reasonable(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        user = await make_user(db_session, status=UserStatus.ACTIVE)
        await sign_in(client, user)

        assert (await client.patch("/api/auth/me", json={"display_name": "x"})).status_code == 422
        assert (
            await client.patch("/api/auth/me", json={"display_name": "y" * 100})
        ).status_code == 422


class TestSessionLifecycle:
    async def test_refresh_rotates_the_cookies(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        user = await make_user(db_session, status=UserStatus.ACTIVE)
        original = await sign_in(client, user)

        response = await client.post("/api/auth/refresh")

        assert response.status_code == 200
        # Read the Set-Cookie header rather than the jar: this is the contract
        # the browser actually sees, and the jar holds both old and new.
        issued = [
            c for c in response.headers.get_list("set-cookie") if c.startswith(REFRESH_COOKIE)
        ]
        assert len(issued) == 1
        assert original.refresh_token not in issued[0]

    async def test_replaying_a_rotated_refresh_token_kills_the_session(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        user = await make_user(db_session, status=UserStatus.ACTIVE)
        original = await sign_in(client, user)
        await client.post("/api/auth/refresh")

        client.cookies.delete(REFRESH_COOKIE, path=REFRESH_COOKIE_PATH)
        client.cookies.set(REFRESH_COOKIE, original.refresh_token, path=REFRESH_COOKIE_PATH)
        response = await client.post("/api/auth/refresh")

        assert response.status_code == 401
        assert response.json()["error"]["code"] == "session_revoked"

    async def test_refresh_without_a_cookie_is_unauthenticated(self, client: AsyncClient) -> None:
        assert (await client.post("/api/auth/refresh")).status_code == 401

    async def test_logout_clears_cookies_and_revokes_the_session(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        user = await make_user(db_session, status=UserStatus.ACTIVE)
        await sign_in(client, user)

        response = await client.post("/api/auth/logout")

        assert response.status_code == 200
        assert (await client.post("/api/auth/refresh")).status_code == 401

    async def test_logging_out_twice_still_succeeds(self, client: AsyncClient) -> None:
        """An already-expired player should end up logged out, not on an error."""
        assert (await client.post("/api/auth/logout")).status_code == 200


class TestEntraConfiguration:
    async def test_login_is_unavailable_when_entra_is_not_configured(
        self, client: AsyncClient
    ) -> None:
        response = await client.get("/api/auth/entra/login", follow_redirects=False)

        assert response.status_code == 503
        assert response.json()["error"]["code"] == "login_unavailable"

    async def test_login_redirects_to_the_tenant_when_configured(
        self, client: AsyncClient, app, settings: Settings
    ) -> None:
        app.state.settings = settings.model_copy(
            update={
                "entra_tenant_id": "tenant-123",
                "entra_client_id": "client-abc",
                "entra_client_secret": "shhh",
                "entra_redirect_uri": "http://localhost:8000/api/auth/entra/callback",
            }
        )

        response = await client.get("/api/auth/entra/login", follow_redirects=False)

        assert response.status_code == 302
        location = response.headers["location"]
        assert location.startswith("https://login.microsoftonline.com/tenant-123/")
        # PKCE, so an intercepted code is useless without the verifier.
        assert "code_challenge_method=S256" in location
        assert "client_secret" not in location

    async def test_a_provider_error_returns_the_player_to_the_login_screen(
        self, client: AsyncClient, app, settings: Settings
    ) -> None:
        app.state.settings = settings.model_copy(
            update={
                "entra_tenant_id": "t",
                "entra_client_id": "c",
                "entra_client_secret": "s",
                "entra_redirect_uri": "http://localhost/cb",
            }
        )

        response = await client.get(
            "/api/auth/entra/callback?error=access_denied", follow_redirects=False
        )

        assert response.status_code == 302
        assert "error=entra_failed" in response.headers["location"]
