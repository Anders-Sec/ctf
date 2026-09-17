"""Admin control over parties (spec 053).

Every route here is `Admin`, not `Staff`: each one changes state, and each one
is audited. The player-facing endpoints in ``teams.py`` keep their own
leader-scoped rules untouched.
"""

from uuid import UUID

from fastapi import APIRouter, Query, Request

from app.api.deps import Admin, DbSession
from app.schemas.admin_parties import (
    AddMemberRequest,
    EligibleMember,
    MoveMemberRequest,
    PartyDetailResponse,
    PartySummary,
    ReasonRequest,
    TransferLeaderRequest,
    UpdatePartyRequest,
)
from app.schemas.auth import MessageResponse
from app.services import admin_parties

router = APIRouter(prefix="/admin/parties", tags=["admin"])


def _request_id(request: Request) -> str | None:
    return getattr(request.state, "request_id", None)


@router.get("")
async def list_parties(
    db: DbSession,
    current: Admin,
    search: str | None = Query(default=None, max_length=100),
    include_disbanded: bool = False,
) -> list[PartySummary]:
    rows = await admin_parties.list_parties(db, search=search, include_disbanded=include_disbanded)
    return [PartySummary(**row) for row in rows]


@router.get("/eligible-members")
async def eligible_members(db: DbSession, current: Admin) -> list[EligibleMember]:
    """Players in no party, for the add-member picker."""
    return [EligibleMember(**row) for row in await admin_parties.eligible_members(db)]


@router.get("/{team_id}")
async def party_detail(team_id: UUID, db: DbSession, current: Admin) -> PartyDetailResponse:
    return PartyDetailResponse(**await admin_parties.party_detail(db, team_id))


@router.patch("/{team_id}")
async def update_party(
    team_id: UUID,
    payload: UpdatePartyRequest,
    request: Request,
    db: DbSession,
    current: Admin,
) -> PartyDetailResponse:
    await admin_parties.update_party(
        db,
        current.user,
        team_id,
        name=payload.name,
        visibility=payload.visibility,
        max_members=payload.max_members,
        clear_join_password=payload.clear_join_password,
        reason=payload.reason,
        request_id=_request_id(request),
    )
    return PartyDetailResponse(**await admin_parties.party_detail(db, team_id))


@router.post("/{team_id}/leader")
async def transfer_leader(
    team_id: UUID,
    payload: TransferLeaderRequest,
    request: Request,
    db: DbSession,
    current: Admin,
) -> MessageResponse:
    """The fix for a leader who has gone home.

    An admin variant rather than a reuse: the player-facing transfer requires
    the caller to be the leader, which is exactly the person who is not around
    when this is needed.
    """
    await admin_parties.transfer_leadership(
        db,
        current.user,
        team_id,
        payload.user_id,
        request_id=_request_id(request),
    )
    return MessageResponse(message="Leadership transferred.")


@router.post("/{team_id}/members")
async def add_member(
    team_id: UUID,
    payload: AddMemberRequest,
    request: Request,
    db: DbSession,
    current: Admin,
) -> MessageResponse:
    await admin_parties.add_member(
        db,
        current.user,
        team_id,
        payload.user_id,
        reason=payload.reason,
        request_id=_request_id(request),
    )
    return MessageResponse(message="Added to the party.")


@router.delete("/{team_id}/members/{user_id}")
async def remove_member(
    team_id: UUID,
    user_id: UUID,
    request: Request,
    db: DbSession,
    current: Admin,
) -> MessageResponse:
    """Remove a member.

    Hands leadership on if it was theirs, rather than leaving a party with
    nobody able to accept a join request.
    """
    await admin_parties.remove_member(
        db,
        current.user,
        team_id,
        user_id,
        request_id=_request_id(request),
    )
    return MessageResponse(message="Removed from the party.")


@router.post("/members/{user_id}/move")
async def move_member(
    user_id: UUID,
    payload: MoveMemberRequest,
    request: Request,
    db: DbSession,
    current: Admin,
) -> MessageResponse:
    """Routed off the member rather than off a party.

    The source is derivable from the one active membership, and naming both ends
    invites them to disagree.
    """
    await admin_parties.move_member(
        db,
        current.user,
        user_id,
        payload.to_team_id,
        reason=payload.reason,
        request_id=_request_id(request),
    )
    return MessageResponse(message="Moved.")


@router.post("/{team_id}/disband")
async def disband(
    team_id: UUID,
    payload: ReasonRequest,
    request: Request,
    db: DbSession,
    current: Admin,
) -> MessageResponse:
    count = await admin_parties.disband(
        db,
        current.user,
        team_id,
        reason=payload.reason,
        request_id=_request_id(request),
    )
    return MessageResponse(message=f"Disbanded. {count} members are now party-less.")


@router.post("/{team_id}/join-requests/{request_row_id}/accept")
async def accept_join_request(
    team_id: UUID,
    request_row_id: UUID,
    request: Request,
    db: DbSession,
    current: Admin,
) -> MessageResponse:
    """Unstick a request a departed leader left stranded.

    The single most likely reason to open a party's drawer.
    """
    await admin_parties.decide_join_request(
        db,
        current.user,
        team_id,
        request_row_id,
        accept=True,
        request_id=_request_id(request),
    )
    return MessageResponse(message="Accepted.")


@router.post("/{team_id}/join-requests/{request_row_id}/reject")
async def reject_join_request(
    team_id: UUID,
    request_row_id: UUID,
    request: Request,
    db: DbSession,
    current: Admin,
) -> MessageResponse:
    await admin_parties.decide_join_request(
        db,
        current.user,
        team_id,
        request_row_id,
        accept=False,
        request_id=_request_id(request),
    )
    return MessageResponse(message="Rejected.")
