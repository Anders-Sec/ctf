"""The dungeon map endpoint (spec 017)."""

from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Request
from sqlalchemy import update

from app.api.deps import Admin, DbSession, Player
from app.errors import NotFoundError
from app.models.challenge import Category
from app.schemas.auth import MessageResponse
from app.schemas.challenges import UnlockRequirementResponse
from app.schemas.dungeon import (
    EdgeResponse,
    MapPositionResponse,
    MapResponse,
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
                slug=zone.slug,
                ability=zone.ability,
                display_order=zone.display_order,
                x=zone.x,
                y=zone.y,
                locked=zone.locked,
                unlock_requirements=[_requirement(r) for r in zone.unlock_requirements],
                cleared=zone.cleared,
                total=zone.total,
            )
            for zone in board.zones
        ],
        edges=[
            EdgeResponse(from_zone_id=e.from_zone_id, to_zone_id=e.to_zone_id) for e in board.edges
        ],
    )


@router.patch("/admin/categories/{category_id}/position")
async def set_zone_position(
    category_id: UUID,
    payload: SetMapPositionRequest,
    request: Request,
    db: DbSession,
    current: Admin,
) -> MapPositionResponse:
    """Place a zone, or clear it (both null) back to the derived layout."""
    category = await db.get(Category, category_id)
    if category is None:
        raise NotFoundError("No such category.")

    category.map_x = payload.x
    category.map_y = payload.y
    await db.flush()

    await record_audit(
        db,
        action="category.map_position",
        target_type="category",
        target_id=category_id,
        actor_user_id=current.user.id,
        meta={"x": payload.x, "y": payload.y},
        request_id=getattr(request.state, "request_id", None),
    )
    return MapPositionResponse(x=category.map_x, y=category.map_y)


@router.post("/admin/map/reset-layout")
async def reset_layout(request: Request, db: DbSession, current: Admin) -> MessageResponse:
    """Drop every authored position, returning the whole map to the derived
    layout — the way out of a layout that has gone wrong."""
    await db.execute(update(Category).values(map_x=None, map_y=None))
    await db.flush()

    await record_audit(
        db,
        action="map.reset_layout",
        target_type="event",
        target_id=None,
        actor_user_id=current.user.id,
        meta={},
        request_id=getattr(request.state, "request_id", None),
    )
    return MessageResponse(message="Layout reset.")
