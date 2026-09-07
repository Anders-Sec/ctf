"""Authentication endpoints for both login paths."""

from datetime import UTC, datetime

from fastapi import APIRouter, BackgroundTasks, Request, Response, status
from fastapi.responses import RedirectResponse

from app.api.deps import (
    AppSettings,
    Authenticated,
    DbSession,
    EventCfg,
    RedisClient,
)
from app.config import Settings
from app.errors import AppError
from app.logging import get_logger
from app.models.user import User
from app.schemas.auth import (
    CapabilitiesResponse,
    EventSummary,
    MagicLinkRequest,
    MagicLinkVerify,
    MeResponse,
    MessageResponse,
    TeamSummary,
    UpdateProfileRequest,
    UserResponse,
)
from app.services import entra as entra_service
from app.services import identity, magic_link
from app.services.cookies import (
    ACCESS_COOKIE,
    REFRESH_COOKIE,
    clear_session_cookies,
    set_session_cookies,
)
from app.services.mail import send_magic_link
from app.services.sessions import (
    RefreshTokenReuse,
    issue_session,
    revoke_session,
    rotate_session,
)
from app.services.user_cache import get_cached_membership, invalidate

logger = get_logger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])

ENTRA_STATE_COOKIE = "ctf_entra_state"


class LoginUnavailable(AppError):
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    code = "login_unavailable"
    message = "This sign-in method is not configured."


class InvalidToken(AppError):
    status_code = status.HTTP_400_BAD_REQUEST
    code = "invalid_or_expired_token"
    message = "That link is no longer valid. Request a new one."


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


# --------------------------------------------------------------------------
# Employees — Entra ID
# --------------------------------------------------------------------------


@router.get("/entra/login")
async def entra_login(settings: AppSettings) -> RedirectResponse:
    if not settings.entra_configured:
        raise LoginUnavailable("Work-account sign-in is not configured.")

    url, state_cookie = entra_service.build_authorization_url(settings)
    response = RedirectResponse(url, status_code=status.HTTP_302_FOUND)
    response.set_cookie(
        ENTRA_STATE_COOKIE,
        state_cookie,
        httponly=True,
        secure=settings.cookie_secure,
        # The provider redirects back cross-site, and Strict would drop this.
        samesite="lax",
        max_age=entra_service.STATE_TTL_SECONDS,
        path="/api/auth",
    )
    return response


@router.get("/entra/callback")
async def entra_callback(
    request: Request,
    db: DbSession,
    settings: AppSettings,
    redis: RedisClient,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
) -> RedirectResponse:
    if not settings.entra_configured:
        raise LoginUnavailable("Work-account sign-in is not configured.")

    if error or not code or not state:
        logger.info("entra_callback_rejected", extra={"provider_error": error})
        return _login_failed_redirect(settings, "entra_failed")

    state_cookie = request.cookies.get(ENTRA_STATE_COOKIE)
    if not state_cookie:
        return _login_failed_redirect(settings, "entra_state_missing")

    try:
        stored = entra_service.decode_state_cookie(settings, state_cookie)
        # Comparing the returned state to our signed copy is what stops an
        # attacker feeding a victim's browser a code of their choosing.
        if stored.get("state") != state:
            raise entra_service.EntraError("state mismatch")

        tokens = await entra_service.exchange_code(settings, code, stored["verifier"])
        claims = entra_service.validate_id_token(
            settings, tokens["id_token"], stored.get("nonce", "")
        )
        profile = entra_service.profile_from_claims(claims, tokens.get("access_token", ""))
    except (entra_service.EntraError, KeyError) as exc:
        logger.warning("entra_login_failed", extra={"error_type": type(exc).__name__})
        return _login_failed_redirect(settings, "entra_failed")

    avatar = await entra_service.fetch_avatar(profile.access_token)
    user, created = await identity.upsert_entra_user(db, profile, avatar)
    if created:
        logger.info("employee_account_created", extra={"user_id": str(user.id)})
    await invalidate(redis, user.id)

    session = await issue_session(
        db,
        settings,
        user.id,
        ip=_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )

    response = RedirectResponse(settings.app_public_url, status_code=status.HTTP_302_FOUND)
    set_session_cookies(response, settings, session)
    response.delete_cookie(ENTRA_STATE_COOKIE, path="/api/auth")
    return response


def _login_failed_redirect(settings: Settings, reason: str) -> RedirectResponse:
    """Send the browser back to the SPA with a code it can render."""
    return RedirectResponse(
        f"{settings.app_public_url.rstrip('/')}/login?error={reason}",
        status_code=status.HTTP_302_FOUND,
    )


# --------------------------------------------------------------------------
# Guests — magic link
# --------------------------------------------------------------------------


@router.post("/magic-link", status_code=status.HTTP_202_ACCEPTED)
async def request_magic_link(
    payload: MagicLinkRequest,
    request: Request,
    background: BackgroundTasks,
    db: DbSession,
    settings: AppSettings,
    redis: RedisClient,
) -> MessageResponse:
    """Always answers 202.

    Known address, unknown address, rate-limited address, corporate address that
    should be using Entra — all produce the same response. Anything else would
    turn this endpoint into a directory of who is registered.
    """
    email = payload.email.strip()
    accepted = MessageResponse(message="If that address can sign in, a link is on its way.")

    if identity.is_enforced_entra_domain(settings, email):
        logger.info("magic_link_refused_corporate_domain")
        return accepted

    limit = await magic_link.check_request_limits(redis, email, _client_ip(request))
    if not limit.allowed:
        logger.info("magic_link_rate_limited", extra={"scope": limit.scope})
        return accepted

    if not settings.smtp_configured:
        logger.error("magic_link_unavailable_smtp_unconfigured")
        return accepted

    link = await magic_link.issue_magic_link(
        db,
        settings,
        email,
        ip=_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    # Sent after the response: a slow relay must not hold up the request.
    background.add_task(send_magic_link, settings, email, link)
    return accepted


@router.post("/magic-link/verify")
async def verify_magic_link(
    payload: MagicLinkVerify,
    request: Request,
    response: Response,
    db: DbSession,
    settings: AppSettings,
    redis: RedisClient,
) -> MessageResponse:
    if not await magic_link.check_verify_limits(redis, _client_ip(request)):
        raise InvalidToken

    email = await magic_link.consume_magic_link(db, payload.token)
    if email is None:
        # Expired, already used, superseded and never-existed all answer the
        # same way, so nothing can be learned by trying.
        raise InvalidToken

    user, created = await identity.get_or_create_guest(db, email)
    if created:
        logger.info("guest_account_created", extra={"user_id": str(user.id)})

    session = await issue_session(
        db,
        settings,
        user.id,
        ip=_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    set_session_cookies(response, settings, session)
    return MessageResponse(message="Signed in.")


# --------------------------------------------------------------------------
# Session lifecycle
# --------------------------------------------------------------------------


@router.post("/refresh")
async def refresh(
    request: Request,
    response: Response,
    db: DbSession,
    settings: AppSettings,
) -> MessageResponse:
    token = request.cookies.get(REFRESH_COOKIE)
    if not token:
        raise AppError(
            "You are not signed in.",
            code="not_authenticated",
            status_code=status.HTTP_401_UNAUTHORIZED,
        )

    try:
        session = await rotate_session(
            db,
            settings,
            token,
            ip=_client_ip(request),
            user_agent=request.headers.get("user-agent"),
        )
    except RefreshTokenReuse:
        # Every session for this user has just been revoked. Clear the cookies
        # so the browser stops presenting a token that is now poison.
        clear_session_cookies(response, settings)
        raise AppError(
            "Your session was ended for security reasons. Please sign in again.",
            code="session_revoked",
            status_code=status.HTTP_401_UNAUTHORIZED,
        ) from None

    if session is None:
        clear_session_cookies(response, settings)
        raise AppError(
            "Your session has expired.",
            code="session_expired",
            status_code=status.HTTP_401_UNAUTHORIZED,
        )

    set_session_cookies(response, settings, session)
    return MessageResponse(message="Session refreshed.")


@router.post("/logout")
async def logout(
    request: Request,
    response: Response,
    db: DbSession,
    settings: AppSettings,
) -> MessageResponse:
    """Signing out is always a success, even without a valid session.

    A player who has already expired should still end up logged out rather than
    stuck on an error.
    """
    token = request.cookies.get(REFRESH_COOKIE)
    if token:
        await revoke_session(db, token)
    clear_session_cookies(response, settings)
    return MessageResponse(message="Signed out.")


@router.get("/me")
async def me(
    current: Authenticated,
    db: DbSession,
    settings: AppSettings,
    redis: RedisClient,
    event: EventCfg,
) -> MeResponse:
    team = await get_cached_membership(redis, db, settings, current.user.id)

    return MeResponse(
        user=_user_response(current.user),
        assistant_available=settings.ai_configured and current.is_staff,
        team=TeamSummary(**team) if team else None,
        capabilities=CapabilitiesResponse(**current.capabilities.to_dict()),
        event=(
            None
            if event is None
            else EventSummary(
                name=event.name,
                starts_at=event.starts_at,
                ends_at=event.ends_at,
                registration_open=event.registration_open,
                # The SPA's countdown is decorative; the server clock decides.
                server_time=datetime.now(UTC),
            )
        ),
    )


def _user_response(user: User) -> UserResponse:
    return UserResponse(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        source=user.source,
        role=user.role,
        status=user.status,
        has_avatar=user.avatar_blob is not None,
        created_at=user.created_at,
    )


@router.patch("/me")
async def update_me(
    payload: UpdateProfileRequest,
    # Authenticated, not ActiveUser: the first-run screen asks a brand-new guest
    # for their display name before an admin has approved them.
    current: Authenticated,
    db: DbSession,
) -> UserResponse:
    current.user.display_name = payload.display_name.strip()
    await db.flush()
    return _user_response(current.user)


__all__ = ["ACCESS_COOKIE", "router"]
