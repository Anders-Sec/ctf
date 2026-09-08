"""The dungeon map endpoint (spec 017)."""

from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Request

from app.api.deps import Admin, DbSession, Player
from app.errors import NotFoundError
from app.models.challenge import Challenge
from app.schemas.challenges import UnlockRequirementResponse
from app.schemas.dungeon import (
    EdgeResponse,
    MapPositionResponse,
    MapResponse,
    RoomResponse,
    SetMapPositionRequest,
    ZoneResponse,
)
from app.services import dungeon as dungeon_service
from app.services.identity import record_audit

router = APIRouter(tags=["map"])


def _requirement(req) -> UnlockRequirementResponse:
    return UnlockRequirementResponse(
        type=req.type.value,
        met=req.met,
        description=req.description,
        challenge_id=req.challenge_id,
        title=req.title,
        skill_id=req.skill_id,
        skill_name=req.skill_name,
        category_id=req.category_id,
        category_name=req.category_name,
        threshold=req.threshold,
        progress=req.progress,
    )


@router.get("/map")
async def get_map(db: DbSession, current: Player) -> MapResponse:
    board = await dungeon_service.build(db, current.user.id, datetime.now(UTC))
    return MapResponse(
        fog_of_war=board.fog_of_war,
        zones=[
            ZoneResponse(
                id=zone.id,
                name=zone.name,
                display_order=zone.display_order,
                locked=zone.locked,
                unlock_requirements=[_requirement(r) for r in zone.unlock_requirements],
                cleared=zone.cleared,
                total=zone.total,
            )
            for zone in board.zones
        ],
        rooms=[
            RoomResponse(
                challenge_id=room.challenge_id,
                title=room.title,
                zone_id=room.zone_id,
                x=room.x,
                y=room.y,
                state=room.state,
                value=room.value,
                solved=room.solved,
                unlock_requirements=[_requirement(r) for r in room.unlock_requirements],
            )
            for room in board.rooms
        ],
        edges=[
            EdgeResponse(
                from_challenge_id=edge.from_challenge_id,
                to_challenge_id=edge.to_challenge_id,
            )
            for edge in board.edges
        ],
    )


@router.patch("/admin/challenges/{challenge_id}/map-position")
async def set_map_position(
    challenge_id: UUID,
    payload: SetMapPositionRequest,
    request: Request,
    db: DbSession,
    current: Admin,
) -> MapPositionResponse:
    """Pin a room, or clear the pin (both null) to return it to the derived spot."""
    challenge = await db.get(Challenge, challenge_id)
    if challenge is None:
        raise NotFoundError("No such challenge.")

    challenge.map_x = payload.x
    challenge.map_y = payload.y
    await db.flush()

    await record_audit(
        db,
        action="challenge.map_position",
        target_type="challenge",
        target_id=challenge_id,
        actor_user_id=current.user.id,
        meta={"x": payload.x, "y": payload.y},
        request_id=getattr(request.state, "request_id", None),
    )
    return MapPositionResponse(x=challenge.map_x, y=challenge.map_y)
