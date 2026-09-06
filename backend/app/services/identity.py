"""Turning a verified login into a user record.

Both login paths land here, which is where the two doors become one identity.
"""

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.logging import get_logger
from app.models.audit import AuditLog
from app.models.user import User, UserSource, UserStatus
from app.services.entra import EntraProfile

logger = get_logger(__name__)


async def find_by_email(db: AsyncSession, email: str) -> User | None:
    # `email` is citext, so this comparison is already case-insensitive.
    return (await db.execute(select(User).where(User.email == email))).scalar_one_or_none()


async def upsert_entra_user(
    db: AsyncSession, profile: EntraProfile, avatar: bytes | None
) -> tuple[User, bool]:
    """Find or create the employee behind a validated Entra profile.

    Returns the user and whether they were newly created.

    Three cases, in priority order:

    1. Known by Entra object id — the durable identifier, which survives a
       person changing their name or email address.
    2. Known by email but not object id — a guest account that belongs to
       someone who has now signed in as an employee. Upgraded **in place**, so
       their party membership and history survive rather than being orphaned
       behind a duplicate account.
    3. Unknown — created, active immediately. Employees need no approval.
    """
    now = datetime.now(UTC)

    user = (
        await db.execute(select(User).where(User.entra_object_id == profile.object_id))
    ).scalar_one_or_none()
    created = False

    if user is None:
        existing = await find_by_email(db, profile.email)
        if existing is not None:
            user = existing
            user.entra_object_id = profile.object_id
            user.source = UserSource.ENTRA
            # An employee is trusted by virtue of the tenant, so an upgraded
            # guest account stops waiting in the approval queue.
            if user.status == UserStatus.PENDING_APPROVAL:
                user.status = UserStatus.ACTIVE
                user.approved_at = now
            db.add(
                AuditLog(
                    actor_user_id=user.id,
                    action="user.upgrade_to_entra",
                    target_type="user",
                    target_id=user.id,
                    meta={"email": profile.email},
                )
            )
            logger.info("guest_account_upgraded_to_entra", extra={"user_id": str(user.id)})
        else:
            user = User(
                email=profile.email,
                display_name=profile.display_name,
                source=UserSource.ENTRA,
                entra_object_id=profile.object_id,
                status=UserStatus.ACTIVE,
                approved_at=now,
            )
            db.add(user)
            created = True

    # Keep the profile fresh: a changed corporate name or photo catches up on
    # the next sign-in.
    user.display_name = profile.display_name
    user.email = profile.email
    if avatar is not None:
        user.avatar_blob = avatar
        user.avatar_updated_at = now
    user.last_login_at = now

    await db.flush()
    return user, created


async def get_or_create_guest(db: AsyncSession, email: str) -> tuple[User, bool]:
    """Find or create the guest behind a consumed magic link.

    A new guest starts ``pending_approval``: they may sign in and organise a
    party immediately, but cannot play until an admin approves them.
    """
    now = datetime.now(UTC)
    user = await find_by_email(db, email)

    if user is None:
        user = User(
            email=email,
            # Placeholder until the first-run screen collects a real one.
            display_name=email.split("@")[0][:64],
            source=UserSource.GUEST,
            status=UserStatus.PENDING_APPROVAL,
        )
        db.add(user)
        user.last_login_at = now
        await db.flush()
        return user, True

    user.last_login_at = now
    await db.flush()
    return user, False


def is_enforced_entra_domain(settings: Settings, email: str) -> bool:
    """Should this address be sent to the work-account button instead?

    Employees taking the guest path would land in the approval queue for no
    reason, and would end up with an account that has no Entra profile photo.
    """
    domain = email.rsplit("@", 1)[-1].lower()
    return domain in settings.entra_enforced_email_domains


async def record_audit(
    db: AsyncSession,
    *,
    action: str,
    target_type: str,
    target_id: UUID | None = None,
    actor_user_id: UUID | None = None,
    reason: str | None = None,
    meta: dict[str, object] | None = None,
    request_id: str | None = None,
) -> AuditLog:
    entry = AuditLog(
        actor_user_id=actor_user_id,
        action=action,
        target_type=target_type,
        target_id=target_id,
        reason=reason,
        meta=meta or {},
        request_id=request_id,
    )
    db.add(entry)
    await db.flush()
    return entry
