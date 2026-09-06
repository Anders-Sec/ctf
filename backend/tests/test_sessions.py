"""Session issuing, rotation and revocation (spec 002)."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.models.auth import AuthSession
from app.services.security import (
    TokenError,
    access_token_subject,
    create_access_token,
    csrf_tokens_match,
    decode_access_token,
    generate_token,
    hash_password,
    hash_token,
    verify_password,
)
from app.services.sessions import (
    REVOKED_REUSE,
    RefreshTokenReuse,
    issue_session,
    revoke_all_for_user,
    revoke_session,
    rotate_session,
)
from tests.factories import make_user


class TestPasswords:
    def test_a_password_verifies_against_its_own_hash(self) -> None:
        digest = hash_password("open sesame")

        assert verify_password("open sesame", digest)
        assert not verify_password("open sesamf", digest)

    def test_hashes_are_salted(self) -> None:
        """Identical party passwords must not produce identical hashes."""
        assert hash_password("same") != hash_password("same")

    def test_a_malformed_hash_is_a_failure_not_a_crash(self) -> None:
        assert not verify_password("anything", "not-a-real-hash")


class TestAccessTokens:
    def test_round_trip(self, settings: Settings) -> None:
        user_id = uuid.uuid4()

        token = create_access_token(settings, user_id)

        assert access_token_subject(settings, token) == user_id

    def test_claims_stay_minimal(self, settings: Settings) -> None:
        """Role, status and party are read per request, never carried in the token."""
        payload = decode_access_token(settings, create_access_token(settings, uuid.uuid4()))

        assert set(payload) == {"sub", "jti", "iat", "exp"}

    def test_an_expired_token_is_rejected(self, settings: Settings) -> None:
        past = datetime.now(UTC) - timedelta(hours=2)

        token = create_access_token(settings, uuid.uuid4(), now=past)

        with pytest.raises(TokenError):
            decode_access_token(settings, token)

    def test_a_token_signed_with_another_key_is_rejected(self, settings: Settings) -> None:
        other = settings.model_copy(
            update={"jwt_secret": "a-different-secret-of-sufficient-length"}
        )

        token = create_access_token(other, uuid.uuid4())

        with pytest.raises(TokenError):
            decode_access_token(settings, token)

    def test_an_unsigned_token_is_rejected(self, settings: Settings) -> None:
        """The classic alg=none attack."""
        import jwt

        forged = jwt.encode(
            {"sub": str(uuid.uuid4()), "iat": 0, "exp": 9999999999},
            key="",
            algorithm="none",
        )

        with pytest.raises(TokenError):
            decode_access_token(settings, forged)

    def test_garbage_is_rejected(self, settings: Settings) -> None:
        with pytest.raises(TokenError):
            decode_access_token(settings, "not.a.token")


class TestCsrf:
    def test_matching_values_pass(self) -> None:
        assert csrf_tokens_match("abc", "abc")

    def test_a_missing_header_fails(self) -> None:
        """Otherwise a cross-site post could simply omit it."""
        assert not csrf_tokens_match("abc", None)
        assert not csrf_tokens_match(None, "abc")
        assert not csrf_tokens_match(None, None)

    def test_mismatched_values_fail(self) -> None:
        assert not csrf_tokens_match("abc", "abd")


class TestRefreshRotation:
    async def test_issuing_stores_only_a_digest(
        self, db_session: AsyncSession, settings: Settings
    ) -> None:
        user = await make_user(db_session)

        issued = await issue_session(db_session, settings, user.id)

        row = (
            await db_session.execute(select(AuthSession).where(AuthSession.id == issued.session_id))
        ).scalar_one()
        assert row.refresh_token_hash == hash_token(issued.refresh_token)
        assert issued.refresh_token not in row.refresh_token_hash

    async def test_rotation_returns_a_new_pair_and_revokes_the_old(
        self, db_session: AsyncSession, settings: Settings
    ) -> None:
        user = await make_user(db_session)
        first = await issue_session(db_session, settings, user.id)

        second = await rotate_session(db_session, settings, first.refresh_token)

        assert second is not None
        assert second.refresh_token != first.refresh_token

        old = (
            await db_session.execute(select(AuthSession).where(AuthSession.id == first.session_id))
        ).scalar_one()
        assert old.revoked_at is not None
        assert old.replaced_by_id == second.session_id

    async def test_reusing_a_rotated_token_revokes_the_whole_chain(
        self, db_session: AsyncSession, settings: Settings
    ) -> None:
        """A legitimate client never presents a rotated token twice."""
        user = await make_user(db_session)
        first = await issue_session(db_session, settings, user.id)
        second = await rotate_session(db_session, settings, first.refresh_token)
        assert second is not None

        with pytest.raises(RefreshTokenReuse):
            await rotate_session(db_session, settings, first.refresh_token)

        live = (
            (
                await db_session.execute(
                    select(AuthSession).where(
                        AuthSession.user_id == user.id, AuthSession.revoked_at.is_(None)
                    )
                )
            )
            .scalars()
            .all()
        )
        assert live == []

        successor = (
            await db_session.execute(select(AuthSession).where(AuthSession.id == second.session_id))
        ).scalar_one()
        assert successor.revoked_reason == REVOKED_REUSE

    async def test_an_unknown_token_is_simply_refused(
        self, db_session: AsyncSession, settings: Settings
    ) -> None:
        assert await rotate_session(db_session, settings, generate_token()) is None

    async def test_an_expired_token_cannot_rotate(
        self, db_session: AsyncSession, settings: Settings
    ) -> None:
        user = await make_user(db_session)
        issued = await issue_session(db_session, settings, user.id)
        row = (
            await db_session.execute(select(AuthSession).where(AuthSession.id == issued.session_id))
        ).scalar_one()
        row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        await db_session.flush()

        assert await rotate_session(db_session, settings, issued.refresh_token) is None

    async def test_logout_revokes_only_that_session(
        self, db_session: AsyncSession, settings: Settings
    ) -> None:
        """Signing out on a phone must not sign the player out on their laptop."""
        user = await make_user(db_session)
        phone = await issue_session(db_session, settings, user.id)
        laptop = await issue_session(db_session, settings, user.id)

        await revoke_session(db_session, phone.refresh_token)

        rows = {
            row.id: row
            for row in (
                await db_session.execute(select(AuthSession).where(AuthSession.user_id == user.id))
            ).scalars()
        }
        assert rows[phone.session_id].revoked_at is not None
        assert rows[laptop.session_id].revoked_at is None

    async def test_disabling_an_account_revokes_every_session(
        self, db_session: AsyncSession, settings: Settings
    ) -> None:
        user = await make_user(db_session)
        await issue_session(db_session, settings, user.id)
        await issue_session(db_session, settings, user.id)

        await revoke_all_for_user(db_session, user.id, reason="account_disabled")

        live = (
            (
                await db_session.execute(
                    select(AuthSession).where(
                        AuthSession.user_id == user.id, AuthSession.revoked_at.is_(None)
                    )
                )
            )
            .scalars()
            .all()
        )
        assert live == []
