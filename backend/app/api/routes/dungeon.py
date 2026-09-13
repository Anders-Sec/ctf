"""The dungeon map endpoint (spec 017)."""

from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Request
from sqlalchemy import select, update

from app.api.deps import Admin, DbSession, Player, Staff
from app.errors import NotFoundError
from app.models.challenge import Category
from app.schemas.auth import MessageResponse
from app.schemas.challenges import UnlockRequirementResponse
from app.schemas.dungeon import (
    EdgeResponse,
    GateResponse,
    GraphZoneResponse,
    LayoutImportResult,
    LayoutZone,
    MapGraphResponse,
    MapLayoutFile,
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
                boss_tier=zone.boss_tier,
            )
            for zone in board.zones
        ],
        edges=[
            EdgeResponse(from_zone_id=e.from_zone_id, to_zone_id=e.to_zone_id) for e in board.edges
        ],
    )


@router.get("/admin/map/graph")
async def get_map_graph(db: DbSession, current: Staff) -> MapGraphResponse:
    """The whole progression graph, gates resolved to names (spec 022).

    One call rather than one per zone — the editor needs every zone anyway to
    tell the reachable ones from the stranded ones.
    """
    zones = await dungeon_service.admin_graph(db)
    return MapGraphResponse(
        zones=[
            GraphZoneResponse(
                id=zone.id,
                name=zone.name,
                slug=zone.slug,
                reachable=zone.reachable,
                published_challenges=zone.published_challenges,
                gates=[GateResponse(**vars(gate)) for gate in zone.gates],
            )
            for zone in zones
        ]
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


@router.get("/admin/map/layout")
async def export_layout(db: DbSession, current: Staff) -> MapLayoutFile:
    """The authored layout, for carrying to another instance (spec 027).

    Only zones that have actually been placed. Writing derived positions out too
    would silently freeze every automatic one, so a later change to the layout
    algorithm could never reach a map that had once been exported.
    """
    rows = (
        await db.execute(
            select(Category.slug, Category.map_x, Category.map_y).where(
                Category.map_x.is_not(None), Category.map_y.is_not(None)
            )
        )
    ).all()
    return MapLayoutFile(
        version=1,
        zones={slug: LayoutZone(x=x, y=y) for slug, x, y in rows},
    )


@router.post("/admin/map/layout")
async def import_layout(
    payload: MapLayoutFile, request: Request, db: DbSession, current: Admin
) -> LayoutImportResult:
    """Apply a layout exported elsewhere, matching on slug.

    Additive: it sets the positions it names and leaves every other zone alone.
    Clearing already has a verb — reset-layout — and quietly wiping unlisted
    zones would make this a far sharper tool than it looks.
    """
    known = {
        slug: category_id
        for slug, category_id in (await db.execute(select(Category.slug, Category.id))).all()
    }

    applied = 0
    unknown: list[str] = []
    for slug, position in payload.zones.items():
        category_id = known.get(slug)
        if category_id is None:
            unknown.append(slug)
            continue
        await db.execute(
            update(Category)
            .where(Category.id == category_id)
            .values(map_x=position.x, map_y=position.y)
        )
        applied += 1
    await db.flush()

    await record_audit(
        db,
        action="map.import_layout",
        target_type="event",
        target_id=None,
        actor_user_id=current.user.id,
        meta={"applied": applied, "unknown": len(unknown)},
        request_id=getattr(request.state, "request_id", None),
    )
    return LayoutImportResult(applied=applied, unknown=sorted(unknown))


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
