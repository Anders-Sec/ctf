"""Admin endpoints for user approval and event configuration.

Split deliberately by dependency: listing is `Staff` (organizers included, so
event staff can watch the queue), while anything that changes state is `Admin`.
Spec 006 builds the wider admin tooling on the same audit log.
"""

from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Query, Request
from sqlalchemy import func, select

from app.api.deps import Admin, AppSettings, DbSession, RedisClient, Staff
from app.errors import ConflictError, NotFoundError
from app.logging import get_logger
from app.models.event import EVENT_CONFIG_ID, EventConfig
from app.models.user import User, UserRole, UserSource, UserStatus
from app.schemas.admin import (
    ApproveUsersRequest,
    AssistantBlockRequest,
    DisableUserRequest,
    EnableUserRequest,
    EventConfigResponse,
    SetRoleRequest,
    UpdateEventConfigRequest,
    UserDetailResponse,
    UserListResponse,
    UserSummary,
)
from app.schemas.auth import MessageResponse
from app.services import admin_users, magic_link
from app.services.identity import record_audit
from app.services.mail import send_approval_notice, send_magic_link
from app.services.sessions import REVOKED_DISABLED, revoke_all_for_user
from app.services.user_cache import invalidate
from app.theme import is_theme

logger = get_logger(__name__)

router = APIRouter(prefix="/admin", tags=["admin"])


def _request_id(request: Request) -> str | None:
    return getattr(request.state, "request_id", None)


@router.get("/users")
async def list_users(
    db: DbSession,
    current: Staff,
    status_filter: UserStatus | None = Query(default=None, alias="status"),
    source: UserSource | None = None,
    role: UserRole | None = None,
    search: str | None = Query(default=None, max_length=100),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> UserListResponse:
    """The approval queue, and user search generally."""
    conditions = []
    if status_filter is not None:
        conditions.append(User.status == status_filter)
    if source is not None:
        conditions.append(User.source == source)
    if role is not None:
        conditions.append(User.role == role)
    if search:
        pattern = f"%{search}%"
        conditions.append(User.email.ilike(pattern) | User.display_name.ilike(pattern))

    total = await db.scalar(select(func.count()).select_from(User).where(*conditions)) or 0
    rows = (
        (
            await db.execute(
                select(User)
                .where(*conditions)
                # Oldest first: the queue is worked front to back, and someone
                # who signed up last night should not be buried by today's.
                .order_by(User.created_at)
                .limit(limit)
                .offset(offset)
            )
        )
        .scalars()
        .all()
    )

    parties, solves, xp = await admin_users.roster_extras(db, [user.id for user in rows])

    return UserListResponse(
        total=total,
        users=[
            _summary(
                user,
                party_name=parties.get(user.id),
                solve_count=solves.get(user.id, 0),
                xp=xp.get(user.id, 0),
            )
            for user in rows
        ],
    )


def _summary(
    user: User,
    *,
    party_name: str | None = None,
    solve_count: int = 0,
    xp: int = 0,
) -> UserSummary:
    return UserSummary(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        source=user.source,
        role=user.role,
        status=user.status,
        created_at=user.created_at,
        approved_at=user.approved_at,
        last_login_at=user.last_login_at,
        party_name=party_name,
        solve_count=solve_count,
        xp=xp,
    )


@router.get("/users/{user_id}")
async def user_detail(user_id: UUID, db: DbSession, current: Staff) -> UserDetailResponse:
    """Everything the detail drawer needs, in one call (spec 052 §3)."""
    user = await db.get(User, user_id)
    if user is None:
        raise NotFoundError("No such user.")

    parties, solves, xp = await admin_users.roster_extras(db, [user.id])
    extras = await admin_users.detail(db, user)

    return UserDetailResponse(
        user=_summary(
            user,
            party_name=parties.get(user.id),
            solve_count=solves.get(user.id, 0),
            xp=xp.get(user.id, 0),
        ),
        **extras,
    )


@router.post("/users/approve")
async def approve_users(
    payload: ApproveUsersRequest,
    request: Request,
    background: BackgroundTasks,
    db: DbSession,
    redis: RedisClient,
    settings: AppSettings,
    current: Admin,
) -> UserListResponse:
    """Approve one or many guests.

    Takes a list because 200 guests approved one click at a time is not a plan.
    """
    rows = (await db.execute(select(User).where(User.id.in_(payload.user_ids)))).scalars().all()
    found = {user.id for user in rows}
    missing = set(payload.user_ids) - found
    if missing:
        raise NotFoundError(f"{len(missing)} of those accounts do not exist.")

    now = datetime.now(UTC)
    approved: list[User] = []

    for user in rows:
        if user.status == UserStatus.ACTIVE:
            continue  # Approving twice is harmless; do not re-notify.
        user.status = UserStatus.ACTIVE
        user.approved_at = now
        user.approved_by_user_id = current.user.id
        user.disabled_reason = None
        approved.append(user)

        await record_audit(
            db,
            action="user.approve",
            target_type="user",
            target_id=user.id,
            actor_user_id=current.user.id,
            reason=payload.reason,
            request_id=_request_id(request),
        )
        await invalidate(redis, user.id)

    await db.flush()

    if payload.notify and settings.smtp_configured:
        for user in approved:
            # A guest who signed up the night before otherwise has no signal to
            # come back. Sent after the response so a slow relay cannot stall it.
            background.add_task(send_approval_notice, settings, user.email)

    logger.info(
        "users_approved",
        extra={"count": len(approved), "actor_id": str(current.user.id)},
    )
    return UserListResponse(total=len(approved), users=[_summary(u) for u in approved])


@router.post("/users/{user_id}/disable")
async def disable_user(
    user_id: UUID,
    payload: DisableUserRequest,
    request: Request,
    db: DbSession,
    redis: RedisClient,
    current: Admin,
) -> UserSummary:
    """Disable an account and end its sessions immediately."""
    if user_id == current.user.id:
        raise ConflictError("You cannot disable your own account.", code="cannot_disable_self")

    user = await db.get(User, user_id)
    if user is None:
        raise NotFoundError("No such user.")

    user.status = UserStatus.DISABLED
    user.disabled_reason = payload.reason

    # Revoking sessions plus invalidating the cache is what makes this take
    # effect on the account's very next request rather than at token expiry.
    await revoke_all_for_user(db, user.id, reason=REVOKED_DISABLED)
    await invalidate(redis, user.id)

    await record_audit(
        db,
        action="user.disable",
        target_type="user",
        target_id=user.id,
        actor_user_id=current.user.id,
        reason=payload.reason,
        request_id=_request_id(request),
    )
    await db.flush()

    logger.warning(
        "user_disabled",
        extra={"user_id": str(user.id), "actor_id": str(current.user.id)},
    )
    return _summary(user)


@router.post("/users/{user_id}/role")
async def set_role(
    user_id: UUID,
    payload: SetRoleRequest,
    request: Request,
    db: DbSession,
    redis: RedisClient,
    current: Admin,
) -> UserSummary:
    if user_id == current.user.id and payload.role != UserRole.ADMIN:
        # Otherwise the last admin can lock everyone out of the admin tooling
        # mid-event, which is unrecoverable without database access.
        raise ConflictError("You cannot remove your own admin role.", code="cannot_demote_self")

    user = await db.get(User, user_id)
    if user is None:
        raise NotFoundError("No such user.")

    previous = user.role
    user.role = payload.role
    await invalidate(redis, user.id)

    await record_audit(
        db,
        action="user.set_role",
        target_type="user",
        target_id=user.id,
        actor_user_id=current.user.id,
        reason=payload.reason,
        meta={"from": previous.value, "to": payload.role.value},
        request_id=_request_id(request),
    )
    await db.flush()
    return _summary(user)


@router.get("/event-config")
async def get_event_config(db: DbSession, current: Staff) -> EventConfigResponse:
    config = await db.get(EventConfig, EVENT_CONFIG_ID)
    if config is None:
        raise NotFoundError("Event configuration is missing.")
    return _event_response(config)


@router.patch("/event-config")
async def update_event_config(
    payload: UpdateEventConfigRequest,
    request: Request,
    db: DbSession,
    current: Admin,
) -> EventConfigResponse:
    config = await db.get(EventConfig, EVENT_CONFIG_ID)
    if config is None:
        raise NotFoundError("Event configuration is missing.")

    changes: dict[str, object] = {}
    fields = payload.model_dump(exclude_unset=True)

    theme = fields.get("default_theme")
    if theme is not None and not is_theme(theme):
        raise ConflictError(f"Unknown theme: {theme}", code="unknown_theme")

    starts_at = fields.get("starts_at", config.starts_at)
    ends_at = fields.get("ends_at", config.ends_at)
    if starts_at and ends_at and ends_at <= starts_at:
        raise ConflictError("The event cannot end before it starts.", code="invalid_event_window")

    for field, value in fields.items():
        if getattr(config, field) != value:
            setattr(config, field, value)
            changes[field] = value.isoformat() if isinstance(value, datetime) else value

    config.updated_by_user_id = current.user.id

    if changes:
        await record_audit(
            db,
            action="event_config.update",
            target_type="event_config",
            target_id=config.id,
            actor_user_id=current.user.id,
            meta=changes,
            request_id=_request_id(request),
        )
    await db.flush()
    return _event_response(config)


def _event_response(config: EventConfig) -> EventConfigResponse:
    return EventConfigResponse(
        name=config.name,
        assistant_enabled=config.assistant_enabled,
        fog_of_war=config.fog_of_war,
        starts_at=config.starts_at,
        ends_at=config.ends_at,
        registration_open=config.registration_open,
        default_theme=config.default_theme,
        server_time=datetime.now(UTC),
    )


__all__ = ["MessageResponse", "router"]


@router.post("/users/{user_id}/enable")
async def enable_user(
    user_id: UUID,
    payload: EnableUserRequest,
    request: Request,
    db: DbSession,
    redis: RedisClient,
    current: Admin,
) -> UserSummary:
    """Undo a disable (spec 052 §5).

    Disabling had no inverse, so a disable made in error was permanent short of
    database access. Returns the account to ``active`` rather than to whatever
    it was before: the only other state is pending approval, and re-enabling is
    itself the approval.
    """
    user = await db.get(User, user_id)
    if user is None:
        raise NotFoundError("No such user.")

    user.status = UserStatus.ACTIVE
    user.disabled_reason = None
    await invalidate(redis, user.id)

    await record_audit(
        db,
        action="user.enable",
        target_type="user",
        target_id=user.id,
        actor_user_id=current.user.id,
        reason=payload.reason,
        request_id=_request_id(request),
    )
    await db.flush()
    logger.info("user_enabled", extra={"user_id": str(user.id)})
    return _summary(user)


@router.post("/users/{user_id}/assistant-block")
async def set_assistant_block(
    user_id: UUID,
    payload: AssistantBlockRequest,
    request: Request,
    db: DbSession,
    redis: RedisClient,
    current: Admin,
) -> UserSummary:
    """Take the dungeon master away from one player, or give it back.

    The column has existed since spec 011 for exactly this and has never been
    settable. One player misbehaving should not cost the other 199 the feature,
    which is what the event-wide switch would do.
    """
    user = await db.get(User, user_id)
    if user is None:
        raise NotFoundError("No such user.")

    user.assistant_blocked = payload.blocked
    await invalidate(redis, user.id)

    await record_audit(
        db,
        action="user.assistant_block" if payload.blocked else "user.assistant_unblock",
        target_type="user",
        target_id=user.id,
        actor_user_id=current.user.id,
        reason=payload.reason,
        request_id=_request_id(request),
    )
    await db.flush()
    return _summary(user)


@router.post("/users/{user_id}/resend-magic-link")
async def resend_magic_link(
    user_id: UUID,
    request: Request,
    background: BackgroundTasks,
    db: DbSession,
    redis: RedisClient,
    settings: AppSettings,
    current: Admin,
) -> MessageResponse:
    """Send a guest another sign-in link.

    The most common support action for a guest, and until now impossible without
    asking them to go back to the login page themselves. Rate-limited on the
    same bucket as the public path so this does not become a way around it.
    """
    user = await db.get(User, user_id)
    if user is None:
        raise NotFoundError("No such user.")
    if user.source != UserSource.GUEST:
        raise ConflictError(
            "That account signs in through Entra; there is no link to send.",
            code="not_a_guest",
        )

    # Same bucket the public path uses, so this cannot become a way around it.
    limit = await magic_link.check_request_limits(redis, user.email, None)
    if not limit.allowed:
        raise ConflictError(
            "A link was sent to that address very recently. Try again shortly.",
            code="rate_limited",
        )
    if not settings.smtp_configured:
        raise ConflictError(
            "Mail is not configured, so no link can be sent.", code="mail_unconfigured"
        )

    link = await magic_link.issue_magic_link(db, settings, user.email)
    # After the response: a slow relay must not hold up the request.
    background.add_task(send_magic_link, settings, user.email, link)

    await record_audit(
        db,
        action="user.resend_magic_link",
        target_type="user",
        target_id=user.id,
        actor_user_id=current.user.id,
        request_id=_request_id(request),
    )
    await db.flush()
    return MessageResponse(message="A new link is on its way.")
