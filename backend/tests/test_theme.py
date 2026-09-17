"""Theme preference, per user and per event (spec 048)."""

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.event import EVENT_CONFIG_ID, EventConfig
from app.models.user import UserRole, UserStatus
from app.theme import FALLBACK_THEME, THEME_IDS, is_theme, resolve_theme
from tests.factories import make_user


async def set_event_default(db_session: AsyncSession, theme: str | None) -> None:
    config = await db_session.get(EventConfig, EVENT_CONFIG_ID)
    assert config is not None
    config.default_theme = theme
    await db_session.flush()


class TestResolution:
    """The precedence rule, unit-level. The endpoint tests exercise it in place."""

    def test_a_users_choice_wins(self) -> None:
        assert resolve_theme("torchlight", "dark-dungeon") == "torchlight"

    def test_the_event_default_applies_when_the_user_has_not_chosen(self) -> None:
        assert resolve_theme(None, "dark-dungeon") == "dark-dungeon"

    def test_the_platform_default_applies_when_neither_is_set(self) -> None:
        assert resolve_theme(None, None) == FALLBACK_THEME

    @pytest.mark.parametrize("stored", ["midnight-gala", "", "PARCHMENT"])
    def test_an_unrecognised_name_falls_back_rather_than_raising(self, stored: str) -> None:
        """A preset removed after somebody selected it must not break their login.

        This is read on every session load, so degrading is the only acceptable
        behaviour — there is no request this could usefully fail.
        """
        assert resolve_theme(stored, None) == FALLBACK_THEME
        assert resolve_theme(stored, "torchlight") == "torchlight"
        assert is_theme(stored) is False


class TestReadingTheTheme:
    async def test_me_reports_the_platform_default_for_a_fresh_user(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        user = await make_user(db_session, status=UserStatus.ACTIVE)
        await sign_in(client, user)

        body = (await client.get("/api/auth/me")).json()

        assert body["theme"] == FALLBACK_THEME
        assert body["theme_source"] == "event"

    async def test_me_reports_the_event_default_when_the_user_has_not_chosen(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        user = await make_user(db_session, status=UserStatus.ACTIVE)
        await sign_in(client, user)
        await set_event_default(db_session, "dark-dungeon")

        body = (await client.get("/api/auth/me")).json()

        assert body["theme"] == "dark-dungeon"
        # Not "user": the picker has to be able to say they are following the
        # default rather than implying they picked it.
        assert body["theme_source"] == "event"

    async def test_a_users_choice_outranks_the_event_default(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        user = await make_user(db_session, status=UserStatus.ACTIVE, theme="torchlight")
        await sign_in(client, user)
        await set_event_default(db_session, "dark-dungeon")

        body = (await client.get("/api/auth/me")).json()

        assert body["theme"] == "torchlight"
        assert body["theme_source"] == "user"

    async def test_a_stored_theme_that_no_longer_exists_does_not_break_the_session(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        user = await make_user(db_session, status=UserStatus.ACTIVE, theme="midnight-gala")
        await sign_in(client, user)

        response = await client.get("/api/auth/me")

        assert response.status_code == 200
        assert response.json()["theme"] == FALLBACK_THEME
        assert response.json()["theme_source"] == "event"


class TestSettingTheTheme:
    @pytest.mark.parametrize("theme", THEME_IDS)
    async def test_every_preset_in_the_roster_can_be_selected(
        self, client: AsyncClient, db_session: AsyncSession, sign_in, theme: str
    ) -> None:
        user = await make_user(db_session, status=UserStatus.ACTIVE)
        await sign_in(client, user)

        response = await client.patch("/api/auth/me/theme", json={"theme": theme})

        assert response.status_code == 200
        await db_session.refresh(user)
        assert user.theme == theme

    async def test_null_clears_the_choice_back_to_the_event_default(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        user = await make_user(db_session, status=UserStatus.ACTIVE, theme="torchlight")
        await sign_in(client, user)
        await set_event_default(db_session, "dark-dungeon")

        await client.patch("/api/auth/me/theme", json={"theme": None})

        body = (await client.get("/api/auth/me")).json()
        assert body["theme"] == "dark-dungeon"
        assert body["theme_source"] == "event"

    async def test_an_unknown_theme_is_refused_rather_than_stored(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        """The read path falls back safely, but storing a value that will never
        render would be recording something the user did not ask for."""
        user = await make_user(db_session, status=UserStatus.ACTIVE)
        await sign_in(client, user)

        response = await client.patch("/api/auth/me/theme", json={"theme": "midnight-gala"})

        assert response.status_code >= 400
        await db_session.refresh(user)
        assert user.theme is None

    async def test_a_guest_awaiting_approval_may_still_pick_one(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        """They are looking at the site while they wait; they can turn the
        lights down. The endpoint is Authenticated, not ActiveUser."""
        user = await make_user(db_session, status=UserStatus.PENDING_APPROVAL)
        await sign_in(client, user)

        response = await client.patch("/api/auth/me/theme", json={"theme": "dark-dungeon"})

        assert response.status_code == 200

    async def test_signing_out_is_not_required_for_the_change_to_show(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        user = await make_user(db_session, status=UserStatus.ACTIVE)
        await sign_in(client, user)

        await client.patch("/api/auth/me/theme", json={"theme": "torchlight"})

        assert (await client.get("/api/auth/me")).json()["theme"] == "torchlight"


class TestTheEventDefault:
    async def test_an_admin_can_set_it(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        admin = await make_user(db_session, role=UserRole.ADMIN, status=UserStatus.ACTIVE)
        await sign_in(client, admin)

        response = await client.patch(
            "/api/admin/event-config", json={"default_theme": "dark-dungeon"}
        )

        assert response.status_code == 200
        assert response.json()["default_theme"] == "dark-dungeon"

    async def test_it_moves_everyone_who_has_not_chosen(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        player = await make_user(db_session, status=UserStatus.ACTIVE)
        await set_event_default(db_session, "dark-dungeon")
        await sign_in(client, player)

        assert (await client.get("/api/auth/me")).json()["theme"] == "dark-dungeon"

    async def test_it_leaves_alone_anyone_who_has_chosen(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        player = await make_user(db_session, status=UserStatus.ACTIVE, theme="torchlight")
        await set_event_default(db_session, "dark-dungeon")
        await sign_in(client, player)

        assert (await client.get("/api/auth/me")).json()["theme"] == "torchlight"

    async def test_an_unknown_theme_is_refused(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        admin = await make_user(db_session, role=UserRole.ADMIN, status=UserStatus.ACTIVE)
        await sign_in(client, admin)

        response = await client.patch(
            "/api/admin/event-config", json={"default_theme": "midnight-gala"}
        )

        assert response.status_code >= 400

    async def test_the_response_carries_the_roster_for_the_picker(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        """So the settings page renders from the server's list rather than its
        own copy, which is the drift this roster is split across two files to
        avoid."""
        admin = await make_user(db_session, role=UserRole.ADMIN, status=UserStatus.ACTIVE)
        await sign_in(client, admin)

        body = (await client.get("/api/admin/event-config")).json()

        assert body["themes"] == list(THEME_IDS)

    async def test_an_organizer_cannot_set_it(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        organizer = await make_user(db_session, role=UserRole.ORGANIZER, status=UserStatus.ACTIVE)
        await sign_in(client, organizer)

        response = await client.patch(
            "/api/admin/event-config", json={"default_theme": "dark-dungeon"}
        )

        assert response.status_code == 403
