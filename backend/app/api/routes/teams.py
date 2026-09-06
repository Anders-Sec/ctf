"""Party endpoints.

Gated on `PartyMember` rather than `ActiveUser`: an unapproved guest may pick or
form a party the night before the event. Only gameplay waits on approval.
"""

from uuid import UUID

from fastapi import APIRouter, Request, status
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.api.deps import DbSession, PartyMember, RedisClient
from app.models.team import (
    JoinRequestStatus,
    Team,
    TeamJoinRequest,
    TeamMembership,
    TeamVisibility,
)
from app.schemas.auth import MessageResponse
from app.schemas.teams import (
    CreateJoinRequest,
    CreateTeamRequest,
    JoinRequestResponse,
    JoinTeamRequest,
    TeamDetailResponse,
    TeamListItem,
    TeamMemberResponse,
    TransferLeadershipRequest,
    UpdateTeamRequest,
)
from app.services import teams as team_service
from app.services.scoreboard_cache import mark_dirty
from app.services.user_cache import invalidate

router = APIRouter(prefix="/teams", tags=["teams"])


def _request_id(request: Request) -> str | None:
    return getattr(request.state, "request_id", None)


@router.get("")
async def list_teams(db: DbSession, current: PartyMember) -> list[TeamListItem]:
    """Public parties, plus the caller's own if it happens to be private."""
    member_count = (
        select(TeamMembership.team_id, func.count().label("members"))
        .where(TeamMembership.removed_at.is_(None))
        .group_by(TeamMembership.team_id)
        .subquery()
    )

    own = await team_service.active_membership_for(db, current.user.id)
    own_team_id = own.team_id if own else None

    rows = (
        await db.execute(
            select(Team, func.coalesce(member_count.c.members, 0))
            .outerjoin(member_count, member_count.c.team_id == Team.id)
            .where(
                Team.disbanded_at.is_(None),
                (Team.visibility == TeamVisibility.PUBLIC)
                | (Team.id == own_team_id if own_team_id else False),
            )
            .order_by(Team.name)
        )
    ).all()

    return [
        TeamListItem(
            id=team.id,
            name=team.name,
            visibility=team.visibility,
            member_count=count,
            max_members=team.max_members,
            has_space=count < team.max_members,
            requires_password=team.join_password_hash is not None,
        )
        for team, count in rows
    ]


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_team(
    payload: CreateTeamRequest,
    request: Request,
    db: DbSession,
    redis: RedisClient,
    current: PartyMember,
) -> TeamDetailResponse:
    team = await team_service.create_team(
        db,
        current.user,
        name=payload.name,
        visibility=payload.visibility,
        join_password=payload.join_password,
        request_id=_request_id(request),
    )
    await invalidate(redis, current.user.id)
    return await _detail(db, team)


@router.get("/{team_id}")
async def get_team(team_id: UUID, db: DbSession, current: PartyMember) -> TeamDetailResponse:
    team = await team_service.get_team(db, team_id)
    return await _detail(db, team)


@router.patch("/{team_id}")
async def update_team(
    team_id: UUID,
    payload: UpdateTeamRequest,
    request: Request,
    db: DbSession,
    current: PartyMember,
) -> TeamDetailResponse:
    team = await team_service.get_team(db, team_id)
    await team_service.update_team(
        db,
        team,
        current.user,
        name=payload.name,
        visibility=payload.visibility,
        join_password=payload.join_password,
        clear_password=payload.clear_password,
        request_id=_request_id(request),
    )
    return await _detail(db, team)


@router.post("/{team_id}/join")
async def join_team(
    team_id: UUID,
    payload: JoinTeamRequest,
    request: Request,
    db: DbSession,
    redis: RedisClient,
    current: PartyMember,
) -> TeamDetailResponse:
    await team_service.join_team(
        db,
        current.user,
        team_id,
        password=payload.password,
        request_id=_request_id(request),
    )
    await invalidate(redis, current.user.id)
    # The party board is an aggregate over current members.
    await mark_dirty(redis)
    return await _detail(db, await team_service.get_team(db, team_id))


@router.delete("/{team_id}/members/{user_id}")
async def remove_member(
    team_id: UUID,
    user_id: UUID,
    request: Request,
    db: DbSession,
    redis: RedisClient,
    current: PartyMember,
) -> MessageResponse:
    """Leave a party, or — as leader — remove someone from it."""
    team = await team_service.get_team(db, team_id)

    if user_id == current.user.id:
        await team_service.leave_team(db, current.user, team_id, request_id=_request_id(request))
        message = "You have left the party."
    else:
        await team_service.kick_member(
            db, team, current.user, user_id, request_id=_request_id(request)
        )
        message = "That player has been removed from the party."

    # Invalidate the removed player too: their cached membership is now wrong,
    # and they may well be mid-request.
    await invalidate(redis, current.user.id)
    await invalidate(redis, user_id)
    await mark_dirty(redis)
    return MessageResponse(message=message)


@router.post("/{team_id}/leader")
async def transfer_leadership(
    team_id: UUID,
    payload: TransferLeadershipRequest,
    request: Request,
    db: DbSession,
    redis: RedisClient,
    current: PartyMember,
) -> TeamDetailResponse:
    team = await team_service.get_team(db, team_id)
    await team_service.transfer_leadership(
        db, team, current.user, payload.user_id, request_id=_request_id(request)
    )
    await invalidate(redis, current.user.id)
    await invalidate(redis, payload.user_id)
    return await _detail(db, team)


# --------------------------------------------------------------------------
# Join requests
# --------------------------------------------------------------------------


@router.post("/{team_id}/join-requests", status_code=status.HTTP_201_CREATED)
async def create_join_request(
    team_id: UUID,
    payload: CreateJoinRequest,
    request: Request,
    db: DbSession,
    current: PartyMember,
) -> JoinRequestResponse:
    join_request = await team_service.request_to_join(
        db, current.user, team_id, message=payload.message, request_id=_request_id(request)
    )
    return JoinRequestResponse(
        id=join_request.id,
        team_id=join_request.team_id,
        user_id=join_request.user_id,
        display_name=current.user.display_name,
        status=join_request.status,
        message=join_request.message,
        created_at=join_request.created_at,
    )


@router.get("/{team_id}/join-requests")
async def list_join_requests(
    team_id: UUID, db: DbSession, current: PartyMember
) -> list[JoinRequestResponse]:
    team = await team_service.get_team(db, team_id)
    if team.leader_user_id != current.user.id:
        raise team_service.NotPartyLeader

    rows = (
        (
            await db.execute(
                select(TeamJoinRequest)
                .options(selectinload(TeamJoinRequest.user))
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

    return [
        JoinRequestResponse(
            id=row.id,
            team_id=row.team_id,
            user_id=row.user_id,
            display_name=row.user.display_name,
            status=row.status,
            message=row.message,
            created_at=row.created_at,
        )
        for row in rows
    ]


@router.post("/{team_id}/join-requests/{request_row_id}/accept")
async def accept_join_request(
    team_id: UUID,
    request_row_id: UUID,
    request: Request,
    db: DbSession,
    redis: RedisClient,
    current: PartyMember,
) -> TeamDetailResponse:
    team = await team_service.get_team(db, team_id)
    decided = await team_service.decide_join_request(
        db, team, current.user, request_row_id, accept=True, request_id=_request_id(request)
    )
    await invalidate(redis, decided.user_id)
    await mark_dirty(redis)
    return await _detail(db, team)


@router.post("/{team_id}/join-requests/{request_row_id}/reject")
async def reject_join_request(
    team_id: UUID,
    request_row_id: UUID,
    request: Request,
    db: DbSession,
    current: PartyMember,
) -> MessageResponse:
    team = await team_service.get_team(db, team_id)
    await team_service.decide_join_request(
        db, team, current.user, request_row_id, accept=False, request_id=_request_id(request)
    )
    return MessageResponse(message="Request declined.")


@router.delete("/{team_id}/join-requests/{request_row_id}")
async def cancel_join_request(
    team_id: UUID, request_row_id: UUID, db: DbSession, current: PartyMember
) -> MessageResponse:
    await team_service.cancel_join_request(db, current.user, request_row_id)
    return MessageResponse(message="Request withdrawn.")


# --------------------------------------------------------------------------


async def _detail(db, team: Team) -> TeamDetailResponse:  # noqa: ANN001
    members = await team_service.load_members(db, team.id)
    return TeamDetailResponse(
        id=team.id,
        name=team.name,
        visibility=team.visibility,
        member_count=len(members),
        max_members=team.max_members,
        has_space=len(members) < team.max_members,
        # Whether a password is needed, never the hash itself.
        requires_password=team.join_password_hash is not None,
        leader_user_id=team.leader_user_id,
        members=[
            TeamMemberResponse(
                user_id=member.user_id,
                display_name=member.user.display_name,
                is_leader=member.user_id == team.leader_user_id,
                has_avatar=member.user.avatar_blob is not None,
                joined_at=member.joined_at,
            )
            for member in members
        ],
        created_at=team.created_at,
    )
