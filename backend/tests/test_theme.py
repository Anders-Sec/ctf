"""Theme preference, per user and per event (spec 048)."""

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.event import EVENT_CONFIG_ID, EventConfig
from app.models.user import UserRole, UserStatus
from app.models.theme_unlock import UnlockSource
from app.services import theme_unlocks
from app.theme import (
    FALLBACK_THEME,
    HIGH_CONTRAST_THEME,
    THEME_IDS,
    is_secret,
    is_theme,
    resolve_theme,
)
from tests.factories import make_user


async def set_event_default(db_session: AsyncSession, theme: str | None) -> None:
    config = await db_session.get(EventConfig, EVENT_CONFIG_ID)
    assert config is not None
    config.default_theme = theme
    await db_session.flush()


class TestResolution:
    """The precedence rule, unit-level. The endpoint tests exercise it in place."""

    def test_a_users_choice_wins(self) -> None:
        assert resolve_theme("mr-anderson", "dark-dungeon") == "mr-anderson"

    def test_the_event_default_applies_when_the_user_has_not_chosen(self) -> None:
        assert resolve_theme(None, "dark-dungeon") == "dark-dungeon"

    def test_the_platform_default_applies_when_neither_is_set(self) -> None:
        assert resolve_theme(None, None) == FALLBACK_THEME

    @pytest.mark.parametrize("stored", ["midnight-gala", "", "PARCHMENT", "torchlight"])
    def test_an_unrecognised_name_falls_back_rather_than_raising(self, stored: str) -> None:
        """A preset removed after somebody selected it must not break their login.

        This is read on every session load, so degrading is the only acceptable
        behaviour — there is no request this could usefully fail. ``torchlight``
        is in the list because it is exactly that case: dropped in spec 048 §10.
        """
        assert resolve_theme(stored, None) == FALLBACK_THEME
        assert resolve_theme(stored, "dark-dungeon") == "dark-dungeon"
        assert is_theme(stored) is False

    def test_high_contrast_overrides_whatever_is_selected(self) -> None:
        assert resolve_theme("dnd", "parchment", True) == HIGH_CONTRAST_THEME
        assert resolve_theme(None, None, True) == HIGH_CONTRAST_THEME

    def test_turning_high_contrast_off_restores_the_underlying_choice(self) -> None:
        """The whole reason it is a separate flag rather than a theme value."""
        assert resolve_theme("dnd", "parchment", False) == "dnd"

    def test_the_secret_themes_are_real_themes(self) -> None:
        for secret in ("purple-squirrel", "dnd", "mr-anderson"):
            assert is_theme(secret)


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
        user = await make_user(db_session, status=UserStatus.ACTIVE, theme="high-contrast")
        await sign_in(client, user)
        await set_event_default(db_session, "dark-dungeon")

        body = (await client.get("/api/auth/me")).json()

        assert body["theme"] == "high-contrast"
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
    @pytest.mark.parametrize("theme", [t for t in THEME_IDS if not is_secret(t)])
    async def test_every_everyday_preset_can_be_selected(
        self, client: AsyncClient, db_session: AsyncSession, sign_in, theme: str
    ) -> None:
        user = await make_user(db_session, status=UserStatus.ACTIVE)
        await sign_in(client, user)

        response = await client.patch("/api/auth/me/theme", json={"theme": theme})

        assert response.status_code == 200
        await db_session.refresh(user)
        assert user.theme == theme

    @pytest.mark.parametrize("theme", [t for t in THEME_IDS if is_secret(t)])
    async def test_a_secret_theme_is_refused_until_it_is_held(
        self, client: AsyncClient, db_session: AsyncSession, sign_in, theme: str
    ) -> None:
        """Spec 058 §5. The read path falls back on a theme somebody does not
        hold; refusing the *write* is the difference between degrading and
        storing a choice they were never given."""
        user = await make_user(db_session, status=UserStatus.ACTIVE)
        await sign_in(client, user)

        response = await client.patch("/api/auth/me/theme", json={"theme": theme})

        assert response.status_code >= 400
        assert response.json()["error"]["code"] == "theme_not_unlocked"

    @pytest.mark.parametrize("theme", [t for t in THEME_IDS if is_secret(t)])
    async def test_a_secret_theme_can_be_selected_once_granted(
        self, client: AsyncClient, db_session: AsyncSession, sign_in, theme: str
    ) -> None:
        user = await make_user(db_session, status=UserStatus.ACTIVE)
        await sign_in(client, user)
        await theme_unlocks.grant(db_session, user.id, theme, source=UnlockSource.ADMIN)

        response = await client.patch("/api/auth/me/theme", json={"theme": theme})

        assert response.status_code == 200
        await db_session.refresh(user)
        assert user.theme == theme

    async def test_null_clears_the_choice_back_to_the_event_default(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        user = await make_user(db_session, status=UserStatus.ACTIVE, theme="mr-anderson")
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

        await client.patch("/api/auth/me/theme", json={"theme": "dark-dungeon"})

        assert (await client.get("/api/auth/me")).json()["theme"] == "dark-dungeon"


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
        player = await make_user(db_session, status=UserStatus.ACTIVE, theme="high-contrast")
        await set_event_default(db_session, "dark-dungeon")
        await sign_in(client, player)

        assert (await client.get("/api/auth/me")).json()["theme"] == "high-contrast"

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


class TestHighContrast:
    """The accessibility switch (spec 048 §10)."""

    async def test_it_overrides_the_selected_theme(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        user = await make_user(db_session, status=UserStatus.ACTIVE, theme="dnd")
        await sign_in(client, user)
        # Held, or the new unheld-secret fallback would move them off it and
        # this test would be measuring that instead (spec 058 §5.1).
        await theme_unlocks.grant(db_session, user.id, "dnd", source=UnlockSource.ADMIN)

        await client.patch("/api/auth/me/high-contrast", json={"high_contrast": True})

        body = (await client.get("/api/auth/me")).json()
        assert body["theme"] == HIGH_CONTRAST_THEME
        assert body["high_contrast"] is True
        # The choice underneath is untouched, which is what makes it reversible.
        assert body["base_theme"] == "dnd"

    async def test_turning_it_off_puts_back_the_selected_theme(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        user = await make_user(
            db_session, status=UserStatus.ACTIVE, theme="dnd", high_contrast=True
        )
        await sign_in(client, user)
        await theme_unlocks.grant(db_session, user.id, "dnd", source=UnlockSource.ADMIN)

        await client.patch("/api/auth/me/high-contrast", json={"high_contrast": False})

        body = (await client.get("/api/auth/me")).json()
        assert body["theme"] == "dnd"
        assert body["high_contrast"] is False

    async def test_it_survives_a_theme_change_underneath_it(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        """Switching light/dark while high contrast is on changes what you go
        back to, not what you are looking at."""
        user = await make_user(db_session, status=UserStatus.ACTIVE, high_contrast=True)
        await sign_in(client, user)

        await client.patch("/api/auth/me/theme", json={"theme": "dark-dungeon"})

        body = (await client.get("/api/auth/me")).json()
        assert body["theme"] == HIGH_CONTRAST_THEME
        assert body["base_theme"] == "dark-dungeon"

    async def test_a_guest_awaiting_approval_may_turn_it_on(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        user = await make_user(db_session, status=UserStatus.PENDING_APPROVAL)
        await sign_in(client, user)

        response = await client.patch("/api/auth/me/high-contrast", json={"high_contrast": True})

        assert response.status_code == 200


class TestSecretThemes:
    """Not offered by the toggle; assignable by an admin (spec 048 §10.1)."""

    @pytest.mark.parametrize("secret", ["purple-squirrel", "dnd", "mr-anderson"])
    async def test_an_admin_may_set_one_as_the_event_default(
        self, client: AsyncClient, db_session: AsyncSession, sign_in, secret: str
    ) -> None:
        admin = await make_user(db_session, role=UserRole.ADMIN, status=UserStatus.ACTIVE)
        await sign_in(client, admin)

        response = await client.patch("/api/admin/event-config", json={"default_theme": secret})

        assert response.status_code == 200
        assert response.json()["default_theme"] == secret

    async def test_torchlight_is_gone(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        # It read as Dark Dungeon two values apart, so it was dropped rather
        # than kept as a near-duplicate.
        assert "torchlight" not in THEME_IDS

        user = await make_user(db_session, status=UserStatus.ACTIVE)
        await sign_in(client, user)
        response = await client.patch("/api/auth/me/theme", json={"theme": "torchlight"})

        assert response.status_code >= 400
