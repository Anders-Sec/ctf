"""Admin CRUD over the achievement roster (spec 030).

Reads are open to organizers; every write requires admin. Twin of the admin
skills and classes routers.
"""

from uuid import UUID

from fastapi import APIRouter, Request, status

from app.api.deps import Admin, DbSession, Staff
from app.schemas.admin_achievements import (
    AdminAchievementResponse,
    CreateAchievementRequest,
    TriggerCodesResponse,
    UpdateAchievementRequest,
)
from app.schemas.admin_content import BulkRequest, BulkResultResponse
from app.schemas.auth import MessageResponse
from app.services import admin_achievements as service
from app.services import admin_content
from app.services.identity import record_audit

router = APIRouter(prefix="/admin/achievements", tags=["admin-achievements"])


def _request_id(request: Request) -> str | None:
    return getattr(request.state, "request_id", None)


@router.get("")
async def list_achievements(db: DbSession, current: Staff) -> list[AdminAchievementResponse]:
    return [AdminAchievementResponse(**vars(row)) for row in await service.list_achievements(db)]


@router.get("/triggers")
async def triggers(db: DbSession, current: Staff) -> TriggerCodesResponse:
    """Registered trigger codes, and which of them no achievement uses yet."""
    return TriggerCodesResponse(**await service.trigger_codes(db))


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_achievement(
    payload: CreateAchievementRequest, request: Request, db: DbSession, current: Admin
) -> AdminAchievementResponse:
    fields = payload.model_dump(exclude_none=True)
    row = await service.create(db, **fields)
    await record_audit(
        db,
        action="achievement.create",
        target_type="achievement",
        target_id=row.id,
        actor_user_id=current.user.id,
        meta={"code": row.code, "has_trigger": row.has_trigger},
        request_id=_request_id(request),
    )
    return AdminAchievementResponse(**vars(row))


@router.patch("/{achievement_id}")
async def update_achievement(
    achievement_id: UUID,
    payload: UpdateAchievementRequest,
    request: Request,
    db: DbSession,
    current: Admin,
) -> AdminAchievementResponse:
    changes = payload.model_dump(exclude_unset=True, exclude_none=True)
    row = await service.update(db, achievement_id, changes=changes)
    await record_audit(
        db,
        action="achievement.update",
        target_type="achievement",
        target_id=achievement_id,
        actor_user_id=current.user.id,
        meta={"fields": sorted(changes)},
        request_id=_request_id(request),
    )
    return AdminAchievementResponse(**vars(row))


@router.delete("/{achievement_id}")
async def delete_achievement(
    achievement_id: UUID, request: Request, db: DbSession, current: Admin
) -> MessageResponse:
    """Refused once anyone holds it — an earned achievement is never taken back."""
    await service.delete(db, achievement_id)
    await record_audit(
        db,
        action="achievement.delete",
        target_type="achievement",
        target_id=achievement_id,
        actor_user_id=current.user.id,
        meta={},
        request_id=_request_id(request),
    )
    return MessageResponse(message="Achievement removed.")


@router.post("/bulk")
async def bulk_achievements(
    payload: BulkRequest, request: Request, db: DbSession, current: Admin
) -> BulkResultResponse:
    """One action over a selection, with per-item results (spec 058 §4).

    A delete refuses any achievement somebody holds, and says which — spec 030's
    rule applied in bulk, where silently skipping rows would be worse than one
    at a time.
    """
    outcome = await admin_content.bulk_achievements(db, payload.ids, payload.action, payload.value)
    await record_audit(
        db,
        action="achievement.bulk",
        target_type="achievement",
        target_id=None,
        actor_user_id=current.user.id,
        meta={"action": payload.action, "changed": outcome.changed, "asked": len(payload.ids)},
        request_id=_request_id(request),
    )
    return BulkResultResponse(**outcome.as_dict())
