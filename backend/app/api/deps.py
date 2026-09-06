"""Shared FastAPI dependencies: database, Redis, identity and authorization gates."""

from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Annotated

from fastapi import Depends, Request, status
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db import get_db_session
from app.errors import AppError
from app.models.event import EVENT_CONFIG_ID, EventConfig
from app.models.user import User, UserRole
from app.redis import get_redis
from app.services.capabilities import (
    REASON_DISABLED,
    REASON_PENDING_APPROVAL,
    Capabilities,
    resolve_capabilities,
)
from app.services.cookies import ACCESS_COOKIE, CSRF_COOKIE, CSRF_HEADER
from app.services.security import TokenError, access_token_subject, csrf_tokens_match
from app.services.user_cache import load_user

DbSession = Annotated[AsyncSession, Depends(get_db_session)]


class AuthError(AppError):
    status_code = status.HTTP_401_UNAUTHORIZED
    code = "not_authenticated"
    message = "You are not signed in."


class ForbiddenError(AppError):
    status_code = status.HTTP_403_FORBIDDEN
    code = "forbidden"
    message = "You do not have access to this."


def get_app_settings(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


AppSettings = Annotated[Settings, Depends(get_app_settings)]


async def get_redis_client(settings: AppSettings) -> AsyncIterator[Redis]:
    yield get_redis(settings)


RedisClient = Annotated[Redis, Depends(get_redis_client)]


async def get_event_config(db: DbSession) -> EventConfig | None:
    return await db.get(EventConfig, EVENT_CONFIG_ID)


EventCfg = Annotated[EventConfig | None, Depends(get_event_config)]


@dataclass(frozen=True)
class CurrentUser:
    """The signed-in user plus their resolved permissions for this instant."""

    user: User
    capabilities: Capabilities

    @property
    def id(self):  # noqa: ANN201 - UUID, but keeping the import surface small
        return self.user.id

    @property
    def is_admin(self) -> bool:
        return self.user.role == UserRole.ADMIN

    @property
    def is_staff(self) -> bool:
        return self.user.role in (UserRole.ORGANIZER, UserRole.ADMIN)


async def require_authenticated(
    request: Request,
    db: DbSession,
    settings: AppSettings,
    event: EventCfg,
) -> CurrentUser:
    """Resolve the access-token cookie to a live user record.

    The user is loaded from Postgres on every request rather than trusted from
    the token, so status and role changes bite immediately.
    """
    token = request.cookies.get(ACCESS_COOKIE)
    if not token:
        raise AuthError

    try:
        user_id = access_token_subject(settings, token)
    except TokenError as exc:
        raise AuthError("Your session has expired.", code="session_expired") from exc

    user = await load_user(db, user_id)
    if user is None:
        # The token is valid but the account is gone. Treat as signed out.
        raise AuthError

    _enforce_csrf(request)

    capabilities = resolve_capabilities(user, event, datetime.now(UTC))
    return CurrentUser(user=user, capabilities=capabilities)


def _enforce_csrf(request: Request) -> None:
    """Double-submit check on every state-changing request.

    Cookie-based sessions are sent automatically by the browser, so without this
    any site could POST on a signed-in player's behalf.
    """
    if request.method in ("GET", "HEAD", "OPTIONS"):
        return
    if not csrf_tokens_match(request.cookies.get(CSRF_COOKIE), request.headers.get(CSRF_HEADER)):
        raise ForbiddenError(
            "Your request could not be verified. Reload and try again.", code="csrf_failed"
        )


Authenticated = Annotated[CurrentUser, Depends(require_authenticated)]


async def require_active_user(current: Authenticated) -> CurrentUser:
    """An account an admin has approved and not disabled."""
    reason = current.capabilities.blocked_reason
    if reason in (REASON_PENDING_APPROVAL, REASON_DISABLED):
        raise ForbiddenError(
            "Your account is awaiting a dungeon master's approval."
            if reason == REASON_PENDING_APPROVAL
            else "Your account has been disabled.",
            code=reason,
        )
    return current


ActiveUser = Annotated[CurrentUser, Depends(require_active_user)]


async def require_party_management(current: Authenticated) -> CurrentUser:
    """Party actions. Open to pending guests — only gameplay waits on approval."""
    if not current.capabilities.manage_party:
        raise ForbiddenError(
            "Your account has been disabled.",
            code=current.capabilities.blocked_reason or "forbidden",
        )
    return current


PartyMember = Annotated[CurrentUser, Depends(require_party_management)]


async def require_play(current: Authenticated) -> CurrentUser:
    """Flag submission, hints, instances, DM chat."""
    if not current.capabilities.play:
        reason = current.capabilities.blocked_reason or "forbidden"
        raise ForbiddenError(_play_message(reason), code=reason)
    return current


Player = Annotated[CurrentUser, Depends(require_play)]


def _play_message(reason: str) -> str:
    return {
        REASON_PENDING_APPROVAL: "Your account is awaiting a dungeon master's approval.",
        REASON_DISABLED: "Your account has been disabled.",
        "event_not_started": "The dungeon doors have not opened yet.",
        "event_ended": "This dungeon crawl has ended.",
    }.get(reason, "You do not have access to this.")


async def require_staff(current: Authenticated) -> CurrentUser:
    """Read-only staff visibility: organizers and admins."""
    if not current.is_staff:
        raise ForbiddenError
    return current


Staff = Annotated[CurrentUser, Depends(require_staff)]


async def require_admin(current: Authenticated) -> CurrentUser:
    """Destructive admin actions. Organizers are deliberately excluded."""
    if not current.is_admin:
        raise ForbiddenError
    return current


Admin = Annotated[CurrentUser, Depends(require_admin)]

__all__ = [
    "ActiveUser",
    "Admin",
    "AppSettings",
    "Authenticated",
    "CurrentUser",
    "DbSession",
    "EventCfg",
    "PartyMember",
    "Player",
    "RedisClient",
    "Staff",
    "get_db_session",
]
