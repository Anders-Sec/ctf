"""Account resolution across both login paths (spec 002)."""

import uuid

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.models.team import TeamMembership
from app.models.user import User, UserSource, UserStatus
from app.services.entra import EntraError, EntraProfile, profile_from_claims
from app.services.identity import (
    get_or_create_guest,
    is_enforced_entra_domain,
    upsert_entra_user,
)
from tests.factories import make_team, make_user


def profile(
    *,
    email: str = "employee@corp.example",
    object_id: uuid.UUID | None = None,
    name: str = "Sir Reginald",
) -> EntraProfile:
    return EntraProfile(
        object_id=object_id or uuid.uuid4(),
        email=email,
        display_name=name,
        access_token="graph-token",
    )


class TestEntraClaims:
    def test_email_claim_is_preferred(self) -> None:
        result = profile_from_claims(
            {"oid": str(uuid.uuid4()), "email": "a@corp.example", "name": "A"}, "tok"
        )

        assert result.email == "a@corp.example"

    def test_falls_back_to_preferred_username_then_upn(self) -> None:
        """Some tenants and B2B accounts omit the email claim entirely."""
        oid = str(uuid.uuid4())

        from_username = profile_from_claims(
            {"oid": oid, "preferred_username": "b@corp.example"}, "tok"
        )
        from_upn = profile_from_claims({"oid": oid, "upn": "c@corp.example"}, "tok")

        assert from_username.email == "b@corp.example"
        assert from_upn.email == "c@corp.example"

    def test_no_usable_email_fails_loudly(self) -> None:
        """Better a clear failure than an invented identity key."""
        with pytest.raises(EntraError):
            profile_from_claims({"oid": str(uuid.uuid4())}, "tok")

    def test_a_missing_object_id_is_rejected(self) -> None:
        with pytest.raises(EntraError):
            profile_from_claims({"email": "a@corp.example"}, "tok")

    def test_a_non_uuid_object_id_is_rejected(self) -> None:
        with pytest.raises(EntraError):
            profile_from_claims({"oid": "not-a-uuid", "email": "a@corp.example"}, "tok")

    def test_display_name_falls_back_to_the_local_part(self) -> None:
        result = profile_from_claims(
            {"oid": str(uuid.uuid4()), "email": "quiet@corp.example"}, "tok"
        )

        assert result.display_name == "quiet"


class TestEntraUpsert:
    async def test_a_new_employee_is_active_without_approval(
        self, db_session: AsyncSession
    ) -> None:
        user, created = await upsert_entra_user(db_session, profile(), None)

        assert created
        assert user.status == UserStatus.ACTIVE
        assert user.source == UserSource.ENTRA
        assert user.approved_at is not None

    async def test_a_returning_employee_is_matched_on_object_id(
        self, db_session: AsyncSession
    ) -> None:
        """The object id survives a person changing their name or address."""
        oid = uuid.uuid4()
        first, _ = await upsert_entra_user(db_session, profile(object_id=oid), None)

        second, created = await upsert_entra_user(
            db_session,
            profile(object_id=oid, email="renamed@corp.example", name="Dame Reginald"),
            None,
        )

        assert not created
        assert second.id == first.id
        assert second.email == "renamed@corp.example"
        assert second.display_name == "Dame Reginald"

    async def test_a_guest_account_is_upgraded_in_place(self, db_session: AsyncSession) -> None:
        """Their party membership and history must survive the upgrade."""
        guest = await make_user(
            db_session,
            email="dual@corp.example",
            source=UserSource.GUEST,
            status=UserStatus.PENDING_APPROVAL,
        )
        team = await make_team(db_session, guest)

        upgraded, created = await upsert_entra_user(
            db_session, profile(email="dual@corp.example"), None
        )

        assert not created
        assert upgraded.id == guest.id
        assert upgraded.source == UserSource.ENTRA
        # Signing in as an employee clears the approval queue entry.
        assert upgraded.status == UserStatus.ACTIVE

        memberships = (
            (
                await db_session.execute(
                    select(TeamMembership).where(
                        TeamMembership.user_id == guest.id, TeamMembership.removed_at.is_(None)
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(memberships) == 1
        assert memberships[0].team_id == team.id

    async def test_the_upgrade_does_not_duplicate_the_account(
        self, db_session: AsyncSession
    ) -> None:
        await make_user(db_session, email="dual2@corp.example", source=UserSource.GUEST)

        await upsert_entra_user(db_session, profile(email="dual2@corp.example"), None)

        count = await db_session.scalar(
            select(func.count()).select_from(User).where(User.email == "dual2@corp.example")
        )
        assert count == 1

    async def test_matching_is_case_insensitive(self, db_session: AsyncSession) -> None:
        guest = await make_user(db_session, email="Mixed.Case@corp.example")

        upgraded, created = await upsert_entra_user(
            db_session, profile(email="mixed.case@corp.example"), None
        )

        assert not created
        assert upgraded.id == guest.id

    async def test_an_avatar_is_stored_when_present(self, db_session: AsyncSession) -> None:
        user, _ = await upsert_entra_user(db_session, profile(), b"\x89PNG-bytes")

        assert user.avatar_blob == b"\x89PNG-bytes"
        assert user.avatar_updated_at is not None

    async def test_a_missing_avatar_does_not_clear_an_existing_one(
        self, db_session: AsyncSession
    ) -> None:
        """A transient Graph failure must not wipe a photo we already have."""
        oid = uuid.uuid4()
        await upsert_entra_user(db_session, profile(object_id=oid), b"photo")

        user, _ = await upsert_entra_user(db_session, profile(object_id=oid), None)

        assert user.avatar_blob == b"photo"

    async def test_last_login_is_recorded(self, db_session: AsyncSession) -> None:
        user, _ = await upsert_entra_user(db_session, profile(), None)

        assert user.last_login_at is not None


class TestGuestCreation:
    async def test_a_new_guest_starts_pending(self, db_session: AsyncSession) -> None:
        user, created = await get_or_create_guest(db_session, "fresh@example.com")

        assert created
        assert user.status == UserStatus.PENDING_APPROVAL
        assert user.source == UserSource.GUEST

    async def test_the_display_name_defaults_to_the_local_part(
        self, db_session: AsyncSession
    ) -> None:
        user, _ = await get_or_create_guest(db_session, "torchbearer@example.com")

        assert user.display_name == "torchbearer"

    async def test_a_returning_guest_is_not_recreated_or_reset(
        self, db_session: AsyncSession
    ) -> None:
        """An approved guest signing in again must not drop back to pending."""
        existing = await make_user(db_session, email="repeat@example.com", status=UserStatus.ACTIVE)

        user, created = await get_or_create_guest(db_session, "repeat@example.com")

        assert not created
        assert user.id == existing.id
        assert user.status == UserStatus.ACTIVE

    async def test_a_disabled_guest_stays_disabled(self, db_session: AsyncSession) -> None:
        """Signing in again is not a way to escape a ban."""
        await make_user(db_session, email="banned@example.com", status=UserStatus.DISABLED)

        user, _ = await get_or_create_guest(db_session, "banned@example.com")

        assert user.status == UserStatus.DISABLED


class TestEnforcedDomains:
    def test_a_configured_domain_is_steered_to_entra(self, settings: Settings) -> None:
        configured = settings.model_copy(
            update={"entra_enforced_email_domains": ["corp.example", "nm.example"]}
        )

        assert is_enforced_entra_domain(configured, "someone@corp.example")
        assert is_enforced_entra_domain(configured, "SOMEONE@CORP.EXAMPLE")
        assert not is_enforced_entra_domain(configured, "guest@example.com")

    def test_no_configuration_means_nothing_is_enforced(self, settings: Settings) -> None:
        assert not is_enforced_entra_domain(settings, "anyone@corp.example")

    def test_a_subdomain_is_not_the_same_domain(self, settings: Settings) -> None:
        """ "evil-corp.example" must not match a rule for "corp.example"."""
        configured = settings.model_copy(update={"entra_enforced_email_domains": ["corp.example"]})

        assert not is_enforced_entra_domain(configured, "attacker@evil-corp.example")
