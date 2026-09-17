"""Admin control over parties (spec 053).

Every endpoint in ``app.api.routes.teams`` is player-scoped and gated on being
the party's leader or a member. That works until a leader stops showing up, or
somebody joins the wrong party, or a name has to change — all predictable, all
currently unfixable without a database client.

Nothing here recomputes a score. Per the standing decision in
``specs/README.md`` solves belong to the player and a party's standing is an
aggregate over its *current* members, so moving somebody moves their
contribution automatically and there is nothing to keep in step.
"""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.errors import ConflictError, NotFoundError
from app.models.play import Solve
from app.models.team import (
    JoinRequestStatus,
    MembershipRole,
    RemovalReason,
    Team,
    TeamJoinRequest,
    TeamMembership,
    TeamVisibility,
)
from app.models.user import User, UserRole, UserStatus
from app.services.identity import record_audit
from app.services.teams import count_active_members, validate_name

#: The ceiling on an admin's per-party override.
#:
#: An unbounded party is a scoring problem: party standing is a union of
#: distinct solves, so a party of forty is just "everyone". Sixteen is double
#: the default — headroom for any real request, not enough to break the board.
#: Spec 053 §5.2 records the reasoning so it is not re-argued.
MAX_MEMBERS_CEILING = 16


async def get_team(db: AsyncSession, team_id: UUID, *, for_update: bool = False) -> Team:
    """Load a party, disbanded ones included.

    Deliberately not ``teams.get_team``, which filters ``disbanded_at IS NULL``
    — correct for the player-facing endpoints, wrong here. The admin list offers
    disbanded parties as rows to open, and a party stays resolvable because the
    audit trail refers to it. Each operation below decides for itself whether a
    disbanded party is a legal target.
    """
    stmt = select(Team).where(Team.id == team_id)
    if for_update:
        # Serialises concurrent joins so capacity cannot be exceeded.
        stmt = stmt.with_for_update()
    team = (await db.execute(stmt)).scalar_one_or_none()
    if team is None:
        raise NotFoundError("No such party.")
    return team


async def _member_ids(db: AsyncSession, team_id: UUID) -> list[UUID]:
    rows = await db.execute(
        select(TeamMembership.user_id).where(
            TeamMembership.team_id == team_id, TeamMembership.removed_at.is_(None)
        )
    )
    return list(rows.scalars())


async def list_parties(
    db: AsyncSession, *, search: str | None = None, include_disbanded: bool = False
) -> list[dict[str, Any]]:
    conditions = []
    if not include_disbanded:
        conditions.append(Team.disbanded_at.is_(None))
    if search:
        conditions.append(Team.name.ilike(f"%{search}%"))

    teams = (await db.execute(select(Team).where(*conditions).order_by(Team.name))).scalars().all()
    if not teams:
        return []

    team_ids = [team.id for team in teams]

    counts = dict(
        (
            await db.execute(
                select(TeamMembership.team_id, func.count())
                .where(TeamMembership.team_id.in_(team_ids), TeamMembership.removed_at.is_(None))
                .group_by(TeamMembership.team_id)
            )
        ).all()
    )

    leaders = dict(
        (
            await db.execute(
                select(User.id, User.display_name).where(
                    User.id.in_([team.leader_user_id for team in teams])
                )
            )
        ).all()
    )
    # The "leader went home" signal, visible without opening anything.
    stale = {
        user_id
        for user_id, last_login, status in (
            await db.execute(
                select(User.id, User.last_login_at, User.status).where(
                    User.id.in_([team.leader_user_id for team in teams])
                )
            )
        ).all()
        if status != UserStatus.ACTIVE
        or last_login is None
        or (datetime.now(UTC) - last_login).total_seconds() > 24 * 3600
    }

    return [
        {
            "team_id": team.id,
            "name": team.name,
            "visibility": team.visibility.value,
            "member_count": int(counts.get(team.id, 0)),
            "max_members": team.max_members,
            "leader_user_id": team.leader_user_id,
            "leader_name": leaders.get(team.leader_user_id),
            "leader_absent": team.leader_user_id in stale,
            "has_password": team.join_password_hash is not None,
            "created_at": team.created_at,
            "disbanded_at": team.disbanded_at,
        }
        for team in teams
    ]


async def party_detail(db: AsyncSession, team_id: UUID) -> dict[str, Any]:
    team = await get_team(db, team_id)

    memberships = (
        (
            await db.execute(
                select(TeamMembership)
                .where(TeamMembership.team_id == team_id)
                .order_by(TeamMembership.joined_at)
            )
        )
        .scalars()
        .all()
    )
    user_ids = {m.user_id for m in memberships} | {
        m.removed_by_user_id for m in memberships if m.removed_by_user_id
    }
    names = dict(
        (await db.execute(select(User.id, User.display_name).where(User.id.in_(user_ids)))).all()
    )

    solve_totals = dict(
        (
            await db.execute(
                select(Solve.user_id, func.count(), func.coalesce(func.sum(Solve.xp_awarded), 0))
                .where(Solve.user_id.in_([m.user_id for m in memberships] or [None]))
                .group_by(Solve.user_id)
            )
        ).all()
    )

    requests = (
        (
            await db.execute(
                select(TeamJoinRequest)
                .where(
                    TeamJoinRequest.team_id == team_id,
                    TeamJoinRequest.status == JoinRequestStatus.PENDING,
                )
                .order_by(TeamJoinRequest.created_at)
            )
        )
        .scalars()
        .all()
    )
    requester_names = dict(
        (
            await db.execute(
                select(User.id, User.display_name).where(
                    User.id.in_([r.user_id for r in requests] or [None])
                )
            )
        ).all()
    )

    return {
        "team_id": team.id,
        "name": team.name,
        "visibility": team.visibility.value,
        "max_members": team.max_members,
        "leader_user_id": team.leader_user_id,
        "has_password": team.join_password_hash is not None,
        "disbanded_at": team.disbanded_at,
        "members": [
            {
                "user_id": m.user_id,
                "display_name": names.get(m.user_id, "unknown"),
                "role": m.role.value,
                "joined_at": m.joined_at,
                "removed_at": m.removed_at,
                "removed_by_name": (
                    names.get(m.removed_by_user_id) if m.removed_by_user_id else None
                ),
                "removal_reason": m.removal_reason.value if m.removal_reason else None,
                "solve_count": int(solve_totals.get(m.user_id, (0, 0))[0])
                if m.user_id in solve_totals
                else 0,
                "xp": int(solve_totals[m.user_id][1]) if m.user_id in solve_totals else 0,
            }
            for m in memberships
        ],
        "join_requests": [
            {
                "id": request.id,
                "user_id": request.user_id,
                "display_name": requester_names.get(request.user_id, "unknown"),
                "message": request.message,
                "created_at": request.created_at,
            }
            for request in requests
        ],
    }


async def update_party(
    db: AsyncSession,
    actor: User,
    team_id: UUID,
    *,
    name: str | None = None,
    visibility: str | None = None,
    max_members: int | None = None,
    clear_join_password: bool = False,
    reason: str | None = None,
    request_id: str | None = None,
) -> None:
    team = await get_team(db, team_id, for_update=True)
    changes: dict[str, Any] = {}

    if name is not None and name != team.name:
        cleaned = validate_name(name)
        existing = await db.scalar(select(Team.id).where(Team.name == cleaned, Team.id != team_id))
        if existing is not None:
            # CITEXT, so this catches a collision that differs only in case.
            raise ConflictError("A party already has that name.", code="name_taken")
        changes["name"] = {"from": team.name, "to": cleaned}
        team.name = cleaned

    if visibility is not None and visibility != team.visibility.value:
        changes["visibility"] = {"from": team.visibility.value, "to": visibility}
        team.visibility = TeamVisibility(visibility)

    if max_members is not None and max_members != team.max_members:
        if max_members > MAX_MEMBERS_CEILING:
            raise ConflictError(
                f"A party cannot exceed {MAX_MEMBERS_CEILING} members.",
                code="max_members_too_high",
            )
        active = await count_active_members(db, team_id)
        if max_members < active:
            raise ConflictError(
                f"That party already has {active} members.", code="max_members_below_current"
            )
        changes["max_members"] = {"from": team.max_members, "to": max_members}
        team.max_members = max_members

    if clear_join_password and team.join_password_hash is not None:
        # Cleared, never shown: it is an Argon2id hash. Clearing turns a private
        # party into request-to-join, which is the actual fix when nobody
        # remembers the password.
        team.join_password_hash = None
        changes["join_password"] = "cleared"

    if changes:
        await record_audit(
            db,
            action="team.admin_update",
            target_type="team",
            target_id=team_id,
            actor_user_id=actor.id,
            reason=reason,
            meta=changes,
            request_id=request_id,
        )
    await db.flush()


async def move_member(
    db: AsyncSession,
    actor: User,
    user_id: UUID,
    to_team_id: UUID,
    *,
    reason: str | None = None,
    request_id: str | None = None,
) -> None:
    """Move a player between parties, in one transaction (spec 053 §4).

    A remove and an add that must not be separable: done in two steps it can
    leave the player in neither party, or trip the partial unique index
    ``uq_team_membership_active_user`` and half-fail.

    Solves do not move. A party's standing is an aggregate over its current
    members, so the contribution follows automatically — which is surprising
    enough that the UI says so at the point of the move.
    """
    destination = await get_team(db, to_team_id, for_update=True)
    if destination.disbanded_at is not None:
        raise ConflictError("That party has been disbanded.", code="party_disbanded")

    current = (
        await db.execute(
            select(TeamMembership).where(
                TeamMembership.user_id == user_id, TeamMembership.removed_at.is_(None)
            )
        )
    ).scalar_one_or_none()

    if current is None:
        raise NotFoundError("That player is not in a party.")
    if current.team_id == to_team_id:
        raise ConflictError("They are already in that party.", code="already_there")

    source = await get_team(db, current.team_id, for_update=True)
    if source.leader_user_id == user_id:
        # Silently promoting somebody else is a change to a social structure
        # nobody asked for, so this refuses and names the fix.
        raise ConflictError("They lead that party. Transfer leadership first.", code="is_leader")

    active = await count_active_members(db, to_team_id)
    if active >= destination.max_members:
        raise ConflictError("That party is full.", code="party_full")

    now = datetime.now(UTC)
    # Closed, not deleted: the history is needed for anti-cheat review and for
    # explaining a decision later (spec 002).
    current.removed_at = now
    current.removed_by_user_id = actor.id
    current.removal_reason = RemovalReason.ADMIN

    db.add(
        TeamMembership(
            team_id=to_team_id,
            user_id=user_id,
            role=MembershipRole.MEMBER,
            joined_at=now,
        )
    )

    await record_audit(
        db,
        action="team.admin_move_member",
        target_type="user",
        target_id=user_id,
        actor_user_id=actor.id,
        reason=reason,
        meta={"from": str(source.id), "to": str(to_team_id)},
        request_id=request_id,
    )

    try:
        await db.flush()
    except IntegrityError as exc:
        # The index is the real guard; this turns a 500 into an explanation.
        raise ConflictError(
            "That player's membership changed while this was in flight.",
            code="membership_conflict",
        ) from exc


async def add_member(
    db: AsyncSession,
    actor: User,
    team_id: UUID,
    user_id: UUID,
    *,
    reason: str | None = None,
    request_id: str | None = None,
) -> None:
    team = await get_team(db, team_id, for_update=True)
    if team.disbanded_at is not None:
        raise ConflictError("That party has been disbanded.", code="party_disbanded")

    user = await db.get(User, user_id)
    if user is None:
        raise NotFoundError("No such user.")

    existing = (
        await db.execute(
            select(TeamMembership).where(
                TeamMembership.user_id == user_id, TeamMembership.removed_at.is_(None)
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise ConflictError(
            "They are already in a party. Move them instead.", code="already_in_a_party"
        )

    if await count_active_members(db, team_id) >= team.max_members:
        raise ConflictError("That party is full.", code="party_full")

    db.add(
        TeamMembership(
            team_id=team_id,
            user_id=user_id,
            role=MembershipRole.MEMBER,
            joined_at=datetime.now(UTC),
        )
    )
    await record_audit(
        db,
        action="team.admin_add_member",
        target_type="team",
        target_id=team_id,
        actor_user_id=actor.id,
        reason=reason,
        meta={"user_id": str(user_id)},
        request_id=request_id,
    )
    await db.flush()


async def disband(
    db: AsyncSession,
    actor: User,
    team_id: UUID,
    *,
    reason: str | None = None,
    request_id: str | None = None,
) -> int:
    """Soft delete. Members become party-less, never deleted.

    The party stays resolvable afterwards because the audit trail refers to it.
    """
    team = await get_team(db, team_id, for_update=True)
    if team.disbanded_at is not None:
        raise ConflictError("That party is already disbanded.", code="already_disbanded")

    now = datetime.now(UTC)
    members = await _member_ids(db, team_id)

    for membership in (
        (
            await db.execute(
                select(TeamMembership).where(
                    TeamMembership.team_id == team_id, TeamMembership.removed_at.is_(None)
                )
            )
        )
        .scalars()
        .all()
    ):
        membership.removed_at = now
        membership.removed_by_user_id = actor.id
        membership.removal_reason = RemovalReason.DISBANDED

    team.disbanded_at = now

    await record_audit(
        db,
        action="team.admin_disband",
        target_type="team",
        target_id=team_id,
        actor_user_id=actor.id,
        reason=reason,
        meta={"members": len(members)},
        request_id=request_id,
    )
    await db.flush()
    return len(members)


async def eligible_members(db: AsyncSession) -> list[dict[str, Any]]:
    """Players with no active party, for the add-member picker."""
    in_a_party = select(TeamMembership.user_id).where(TeamMembership.removed_at.is_(None))
    rows = (
        (
            await db.execute(
                select(User)
                .where(
                    User.status == UserStatus.ACTIVE,
                    User.role == UserRole.PLAYER,
                    User.id.not_in(in_a_party),
                )
                .order_by(User.display_name)
            )
        )
        .scalars()
        .all()
    )
    return [{"user_id": user.id, "display_name": user.display_name} for user in rows]


async def transfer_leadership(
    db: AsyncSession,
    actor: User,
    team_id: UUID,
    new_leader_id: UUID,
    *,
    reason: str | None = None,
    request_id: str | None = None,
) -> None:
    """The fix for a leader who has gone home.

    An admin variant rather than a reuse: the player-facing transfer requires
    the caller to *be* the leader, which is exactly the person who is not
    available when this is needed.
    """
    team = await get_team(db, team_id, for_update=True)

    target = (
        await db.execute(
            select(TeamMembership).where(
                TeamMembership.team_id == team_id,
                TeamMembership.user_id == new_leader_id,
                TeamMembership.removed_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if target is None:
        raise ConflictError(
            "That player is not a current member of the party.", code="not_a_member"
        )

    previous = team.leader_user_id
    if previous == new_leader_id:
        return

    memberships = (
        (
            await db.execute(
                select(TeamMembership).where(
                    TeamMembership.team_id == team_id,
                    TeamMembership.removed_at.is_(None),
                )
            )
        )
        .scalars()
        .all()
    )
    for membership in memberships:
        membership.role = (
            MembershipRole.LEADER if membership.user_id == new_leader_id else MembershipRole.MEMBER
        )

    team.leader_user_id = new_leader_id
    await record_audit(
        db,
        action="team.admin_leader_transfer",
        target_type="team",
        target_id=team_id,
        actor_user_id=actor.id,
        reason=reason,
        meta={"from": str(previous), "to": str(new_leader_id)},
        request_id=request_id,
    )
    await db.flush()


async def remove_member(
    db: AsyncSession,
    actor: User,
    team_id: UUID,
    member_id: UUID,
    *,
    reason: str | None = None,
    request_id: str | None = None,
) -> None:
    """Remove a member, handing leadership on if it was theirs.

    A party without a leader has nobody able to accept a join request, so
    leadership is never left vacant — the same rule the player-facing kick
    follows.
    """
    team = await get_team(db, team_id, for_update=True)

    membership = (
        await db.execute(
            select(TeamMembership).where(
                TeamMembership.team_id == team_id,
                TeamMembership.user_id == member_id,
                TeamMembership.removed_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if membership is None:
        raise NotFoundError("That player is not in the party.")

    membership.removed_at = datetime.now(UTC)
    membership.removed_by_user_id = actor.id
    # The enum has had this value since spec 002 and nothing ever set it.
    membership.removal_reason = RemovalReason.ADMIN

    await record_audit(
        db,
        action="team.admin_remove_member",
        target_type="team",
        target_id=team_id,
        actor_user_id=actor.id,
        reason=reason,
        meta={"user_id": str(member_id)},
        request_id=request_id,
    )
    await db.flush()

    if team.leader_user_id != member_id:
        return

    remaining = (
        (
            await db.execute(
                select(TeamMembership)
                .where(
                    TeamMembership.team_id == team_id,
                    TeamMembership.removed_at.is_(None),
                )
                .order_by(TeamMembership.joined_at)
            )
        )
        .scalars()
        .all()
    )
    if remaining:
        successor = remaining[0]
        successor.role = MembershipRole.LEADER
        team.leader_user_id = successor.user_id
        await record_audit(
            db,
            action="team.leader_auto_transfer",
            target_type="team",
            target_id=team_id,
            actor_user_id=actor.id,
            meta={"new_leader_id": str(successor.user_id)},
            request_id=request_id,
        )
    else:
        team.disbanded_at = datetime.now(UTC)
    await db.flush()


async def decide_join_request(
    db: AsyncSession,
    actor: User,
    team_id: UUID,
    request_row_id: UUID,
    *,
    accept: bool,
    reason: str | None = None,
    request_id: str | None = None,
) -> None:
    """Unstick a request a departed leader left stranded.

    Same effect as the leader accepting it, capacity check included: an admin
    override should not push a party over its cap, because the player-facing
    code would then refuse to reason about it.
    """
    team = await get_team(db, team_id, for_update=True)

    join_request = (
        await db.execute(
            select(TeamJoinRequest).where(
                TeamJoinRequest.id == request_row_id,
                TeamJoinRequest.team_id == team_id,
                TeamJoinRequest.status == JoinRequestStatus.PENDING,
            )
        )
    ).scalar_one_or_none()
    if join_request is None:
        raise NotFoundError("No such pending request.")

    now = datetime.now(UTC)
    join_request.decided_at = now
    join_request.decided_by_user_id = actor.id

    if not accept:
        join_request.status = JoinRequestStatus.REJECTED
    else:
        already = (
            await db.execute(
                select(TeamMembership).where(
                    TeamMembership.user_id == join_request.user_id,
                    TeamMembership.removed_at.is_(None),
                )
            )
        ).scalar_one_or_none()
        if already is not None:
            raise ConflictError("They have joined a party since asking.", code="already_in_a_party")
        if await count_active_members(db, team_id) >= team.max_members:
            raise ConflictError("That party is full.", code="party_full")

        join_request.status = JoinRequestStatus.ACCEPTED
        db.add(
            TeamMembership(
                team_id=team_id,
                user_id=join_request.user_id,
                role=MembershipRole.MEMBER,
                joined_at=now,
            )
        )

    verb = "accept" if accept else "reject"
    await record_audit(
        db,
        action=f"team.admin_join_request_{verb}",
        target_type="team",
        target_id=team_id,
        actor_user_id=actor.id,
        reason=reason,
        meta={"user_id": str(join_request.user_id)},
        request_id=request_id,
    )
    await db.flush()
