"""Party creation, joining, leaving and leadership.

Capacity and single-membership are both enforced under a row lock on the party,
because the interesting failures here are concurrent: two players accepting the
last slot at once, or one player double-clicking Join. A read-then-write check
in application code loses both races; taking `SELECT ... FOR UPDATE` on the team
row first serialises them.
"""

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.errors import AppError, ConflictError, NotFoundError
from app.logging import get_logger
from app.models.team import (
    JoinRequestStatus,
    MembershipRole,
    RemovalReason,
    Team,
    TeamJoinRequest,
    TeamMembership,
    TeamVisibility,
)
from app.models.user import User
from app.services.identity import record_audit
from app.services.security import hash_password, verify_password

logger = get_logger(__name__)

MIN_NAME_LENGTH = 3
MAX_NAME_LENGTH = 32
MIN_PASSWORD_LENGTH = 6

#: Names that would let a party impersonate event staff in the scoreboard.
RESERVED_NAME_FRAGMENTS = (
    "admin",
    "administrator",
    "dungeon master",
    "organizer",
    "staff",
    "ctf-staff",
)


class TeamFull(AppError):
    status_code = 409
    code = "team_full"
    message = "That party is already full."


class AlreadyInParty(AppError):
    status_code = 409
    code = "already_in_party"
    message = "Leave your current party before joining another."


class NotInParty(AppError):
    status_code = 409
    code = "not_in_party"
    message = "You are not in that party."


class NotPartyLeader(AppError):
    status_code = 403
    code = "not_party_leader"
    message = "Only the party leader can do that."


class InvalidPartyPassword(AppError):
    status_code = 403
    code = "invalid_party_password"
    message = "That party password is not right."


class RequestRequired(AppError):
    status_code = 403
    code = "join_request_required"
    message = "This party is private. Ask the leader to let you in."


class NameUnavailable(AppError):
    status_code = 409
    code = "team_name_unavailable"
    message = "That party name is taken."


class InvalidName(AppError):
    status_code = 422
    code = "invalid_team_name"
    message = "Party names are 3-32 characters."


def validate_name(name: str) -> str:
    cleaned = " ".join(name.split())
    if not (MIN_NAME_LENGTH <= len(cleaned) <= MAX_NAME_LENGTH):
        raise InvalidName
    if not cleaned.isprintable():
        raise InvalidName("Party names must be printable text.")
    lowered = cleaned.lower()
    if any(fragment in lowered for fragment in RESERVED_NAME_FRAGMENTS):
        raise InvalidName("That name is reserved for event staff.")
    return cleaned


def validate_password(password: str | None) -> str | None:
    if password is None:
        return None
    if len(password) < MIN_PASSWORD_LENGTH:
        raise AppError(
            f"Party passwords must be at least {MIN_PASSWORD_LENGTH} characters.",
            code="weak_party_password",
            status_code=422,
        )
    return hash_password(password)


def _active_members_stmt(team_id: UUID) -> Select:
    return select(TeamMembership).where(
        TeamMembership.team_id == team_id, TeamMembership.removed_at.is_(None)
    )


async def active_membership_for(db: AsyncSession, user_id: UUID) -> TeamMembership | None:
    return (
        await db.execute(
            select(TeamMembership).where(
                TeamMembership.user_id == user_id, TeamMembership.removed_at.is_(None)
            )
        )
    ).scalar_one_or_none()


async def count_active_members(db: AsyncSession, team_id: UUID) -> int:
    return (
        await db.scalar(
            select(func.count())
            .select_from(TeamMembership)
            .where(TeamMembership.team_id == team_id, TeamMembership.removed_at.is_(None))
        )
    ) or 0


async def get_team(db: AsyncSession, team_id: UUID, *, for_update: bool = False) -> Team:
    stmt = select(Team).where(Team.id == team_id, Team.disbanded_at.is_(None))
    if for_update:
        # Serialises concurrent joins so capacity cannot be exceeded.
        stmt = stmt.with_for_update()
    team = (await db.execute(stmt)).scalar_one_or_none()
    if team is None:
        raise NotFoundError("No such party.")
    return team


async def load_members(db: AsyncSession, team_id: UUID) -> list[TeamMembership]:
    return list(
        (
            await db.execute(
                _active_members_stmt(team_id)
                .options(selectinload(TeamMembership.user))
                .order_by(TeamMembership.joined_at)
            )
        )
        .scalars()
        .all()
    )


async def create_team(
    db: AsyncSession,
    user: User,
    *,
    name: str,
    visibility: TeamVisibility,
    join_password: str | None,
    request_id: str | None = None,
) -> Team:
    if await active_membership_for(db, user.id) is not None:
        raise AlreadyInParty

    clean_name = validate_name(name)
    if await _name_taken(db, clean_name):
        raise NameUnavailable

    team = Team(
        name=clean_name,
        visibility=visibility,
        join_password_hash=validate_password(join_password),
        leader_user_id=user.id,
    )
    db.add(team)
    await db.flush()

    db.add(
        TeamMembership(
            team_id=team.id,
            user_id=user.id,
            role=MembershipRole.LEADER,
            joined_at=datetime.now(UTC),
        )
    )
    await record_audit(
        db,
        action="team.create",
        target_type="team",
        target_id=team.id,
        actor_user_id=user.id,
        meta={"name": clean_name, "visibility": visibility.value},
        request_id=request_id,
    )
    await db.flush()
    return team


async def _name_taken(db: AsyncSession, name: str, *, excluding: UUID | None = None) -> bool:
    stmt = select(Team.id).where(Team.name == name)
    if excluding is not None:
        stmt = stmt.where(Team.id != excluding)
    return (await db.execute(stmt)).first() is not None


async def join_team(
    db: AsyncSession,
    user: User,
    team_id: UUID,
    *,
    password: str | None = None,
    request_id: str | None = None,
) -> TeamMembership:
    """Join a public party, or a private one with the right password."""
    if await active_membership_for(db, user.id) is not None:
        raise AlreadyInParty

    team = await get_team(db, team_id, for_update=True)

    if team.visibility == TeamVisibility.PRIVATE:
        if team.join_password_hash is None:
            raise RequestRequired
        if password is None or not verify_password(password, team.join_password_hash):
            raise InvalidPartyPassword

    return await _add_member(db, team, user, request_id=request_id)


async def _add_member(
    db: AsyncSession,
    team: Team,
    user: User,
    *,
    request_id: str | None = None,
    actor_user_id: UUID | None = None,
) -> TeamMembership:
    """Add a member to an already-locked party row."""
    if await count_active_members(db, team.id) >= team.max_members:
        raise TeamFull(f"That party is full ({team.max_members} adventurers).")

    membership = TeamMembership(
        team_id=team.id,
        user_id=user.id,
        role=MembershipRole.MEMBER,
        joined_at=datetime.now(UTC),
    )
    db.add(membership)
    await record_audit(
        db,
        action="team.join",
        target_type="team",
        target_id=team.id,
        actor_user_id=actor_user_id or user.id,
        meta={"user_id": str(user.id)},
        request_id=request_id,
    )
    await db.flush()
    return membership


async def leave_team(
    db: AsyncSession,
    user: User,
    team_id: UUID,
    *,
    removed_by: User | None = None,
    reason: RemovalReason = RemovalReason.LEFT,
    request_id: str | None = None,
) -> None:
    """Remove a member, handing on leadership or disbanding as needed.

    The player's score is theirs and goes with them; the party's standing simply
    recomputes over whoever is left. Nothing is transferred or clawed back.
    """
    team = await get_team(db, team_id, for_update=True)
    membership = (
        await db.execute(_active_members_stmt(team_id).where(TeamMembership.user_id == user.id))
    ).scalar_one_or_none()
    if membership is None:
        raise NotInParty

    now = datetime.now(UTC)
    membership.removed_at = now
    membership.removal_reason = reason
    membership.removed_by_user_id = removed_by.id if removed_by else user.id
    await db.flush()

    await record_audit(
        db,
        action="team.kick" if reason == RemovalReason.KICKED else "team.leave",
        target_type="team",
        target_id=team.id,
        actor_user_id=removed_by.id if removed_by else user.id,
        meta={"user_id": str(user.id), "reason": reason.value},
        request_id=request_id,
    )

    if team.leader_user_id == user.id:
        await _hand_on_leadership(db, team, request_id=request_id)


async def _hand_on_leadership(db: AsyncSession, team: Team, *, request_id: str | None) -> None:
    """Promote the longest-tenured remaining member, or disband the party.

    A party without a leader would have nobody able to accept join requests or
    remove a disruptive member, so leadership is never left vacant.
    """
    remaining = (
        (await db.execute(_active_members_stmt(team.id).order_by(TeamMembership.joined_at)))
        .scalars()
        .all()
    )

    if not remaining:
        team.disbanded_at = datetime.now(UTC)
        await record_audit(
            db,
            action="team.disband",
            target_type="team",
            target_id=team.id,
            meta={"reason": "last member left"},
            request_id=request_id,
        )
        await db.flush()
        return

    successor = remaining[0]
    successor.role = MembershipRole.LEADER
    team.leader_user_id = successor.user_id
    await record_audit(
        db,
        action="team.leader_auto_transfer",
        target_type="team",
        target_id=team.id,
        meta={"new_leader_id": str(successor.user_id)},
        request_id=request_id,
    )
    await db.flush()


async def transfer_leadership(
    db: AsyncSession,
    team: Team,
    current_leader: User,
    new_leader_id: UUID,
    *,
    request_id: str | None = None,
) -> None:
    if team.leader_user_id != current_leader.id:
        raise NotPartyLeader

    target = (
        await db.execute(
            _active_members_stmt(team.id).where(TeamMembership.user_id == new_leader_id)
        )
    ).scalar_one_or_none()
    if target is None:
        raise NotInParty("That player is not in your party.")

    outgoing = (
        await db.execute(
            _active_members_stmt(team.id).where(TeamMembership.user_id == current_leader.id)
        )
    ).scalar_one_or_none()
    if outgoing is not None:
        outgoing.role = MembershipRole.MEMBER

    target.role = MembershipRole.LEADER
    team.leader_user_id = new_leader_id
    await record_audit(
        db,
        action="team.leader_transfer",
        target_type="team",
        target_id=team.id,
        actor_user_id=current_leader.id,
        meta={"new_leader_id": str(new_leader_id)},
        request_id=request_id,
    )
    await db.flush()


async def kick_member(
    db: AsyncSession,
    team: Team,
    leader: User,
    member_id: UUID,
    *,
    request_id: str | None = None,
) -> None:
    if team.leader_user_id != leader.id:
        raise NotPartyLeader
    if member_id == leader.id:
        # Leaving is the supported route, and it hands leadership on properly.
        raise ConflictError(
            "Leaders cannot remove themselves. Leave the party instead.",
            code="leader_cannot_kick_self",
        )

    member = await db.get(User, member_id)
    if member is None:
        raise NotFoundError("No such player.")

    await leave_team(
        db,
        member,
        team.id,
        removed_by=leader,
        reason=RemovalReason.KICKED,
        request_id=request_id,
    )


# --------------------------------------------------------------------------
# Join requests
# --------------------------------------------------------------------------


async def request_to_join(
    db: AsyncSession,
    user: User,
    team_id: UUID,
    *,
    message: str | None = None,
    request_id: str | None = None,
) -> TeamJoinRequest:
    if await active_membership_for(db, user.id) is not None:
        raise AlreadyInParty

    team = await get_team(db, team_id)
    if team.visibility != TeamVisibility.PRIVATE:
        raise ConflictError("That party is open — just join it.", code="team_is_public")

    existing = (
        await db.execute(
            select(TeamJoinRequest).where(
                TeamJoinRequest.team_id == team_id,
                TeamJoinRequest.user_id == user.id,
                TeamJoinRequest.status == JoinRequestStatus.PENDING,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing

    join_request = TeamJoinRequest(team_id=team_id, user_id=user.id, message=message)
    db.add(join_request)
    await db.flush()
    return join_request


async def decide_join_request(
    db: AsyncSession,
    team: Team,
    leader: User,
    request_row_id: UUID,
    *,
    accept: bool,
    request_id: str | None = None,
) -> TeamJoinRequest:
    if team.leader_user_id != leader.id:
        raise NotPartyLeader

    join_request = (
        await db.execute(
            select(TeamJoinRequest).where(
                TeamJoinRequest.id == request_row_id, TeamJoinRequest.team_id == team.id
            )
        )
    ).scalar_one_or_none()
    if join_request is None:
        raise NotFoundError("No such join request.")
    if join_request.status != JoinRequestStatus.PENDING:
        raise ConflictError("That request has already been decided.", code="request_decided")

    now = datetime.now(UTC)
    join_request.decided_at = now
    join_request.decided_by_user_id = leader.id

    if not accept:
        join_request.status = JoinRequestStatus.REJECTED
        await db.flush()
        return join_request

    applicant = await db.get(User, join_request.user_id)
    if applicant is None:
        raise NotFoundError("That player no longer exists.")

    # They may have joined elsewhere while waiting, and capacity may have gone.
    # Both are re-checked here rather than trusted from when they applied.
    if await active_membership_for(db, applicant.id) is not None:
        join_request.status = JoinRequestStatus.CANCELLED
        await db.flush()
        raise ConflictError(
            "That player has already joined another party.", code="applicant_in_other_party"
        )

    locked = await get_team(db, team.id, for_update=True)
    await _add_member(db, locked, applicant, request_id=request_id, actor_user_id=leader.id)
    join_request.status = JoinRequestStatus.ACCEPTED
    await db.flush()
    return join_request


async def cancel_join_request(
    db: AsyncSession, user: User, request_row_id: UUID
) -> TeamJoinRequest:
    join_request = await db.get(TeamJoinRequest, request_row_id)
    if join_request is None or join_request.user_id != user.id:
        raise NotFoundError("No such join request.")
    if join_request.status != JoinRequestStatus.PENDING:
        raise ConflictError("That request has already been decided.", code="request_decided")

    join_request.status = JoinRequestStatus.CANCELLED
    join_request.decided_at = datetime.now(UTC)
    await db.flush()
    return join_request


async def update_team(
    db: AsyncSession,
    team: Team,
    leader: User,
    *,
    name: str | None = None,
    visibility: TeamVisibility | None = None,
    join_password: str | None = None,
    clear_password: bool = False,
    request_id: str | None = None,
) -> Team:
    if team.leader_user_id != leader.id:
        raise NotPartyLeader

    changes: dict[str, object] = {}

    if name is not None:
        clean = validate_name(name)
        if clean != team.name:
            if await _name_taken(db, clean, excluding=team.id):
                raise NameUnavailable
            team.name = clean
            changes["name"] = clean

    if visibility is not None and visibility != team.visibility:
        team.visibility = visibility
        changes["visibility"] = visibility.value
        if visibility == TeamVisibility.PUBLIC:
            # A public party has no password to check, so leaving a stale hash
            # behind would silently resurrect it on a switch back to private.
            team.join_password_hash = None

    if clear_password:
        team.join_password_hash = None
        changes["password"] = "cleared"
    elif join_password is not None:
        team.join_password_hash = validate_password(join_password)
        changes["password"] = "set"

    if changes:
        await record_audit(
            db,
            action="team.update",
            target_type="team",
            target_id=team.id,
            actor_user_id=leader.id,
            meta=changes,
            request_id=request_id,
        )
    await db.flush()
    return team
