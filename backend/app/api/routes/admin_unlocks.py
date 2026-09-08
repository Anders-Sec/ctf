"""Admin CRUD for unlock requirements (spec 017).

One surface for both targets: a requirement gates a **challenge** or a **zone**
(category), and the four gate types share the same create/list/delete shape.
014's `/challenges/{id}/prerequisites` pair still works — it is the
``challenge_solved`` special case, and this router delegates to it so cycle
detection is not duplicated.
"""

from uuid import UUID

from fastapi import APIRouter, Request, status

from app.api.deps import Admin, DbSession, Staff
from app.errors import NotFoundError
from app.models.challenge import Category, Challenge
from app.schemas.auth import MessageResponse
from app.schemas.unlocks import AdminRequirementResponse, CreateRequirementRequest
from app.services import unlocks as unlock_service
from app.services.identity import record_audit

router = APIRouter(prefix="/admin", tags=["admin-unlocks"])


def _request_id(request: Request) -> str | None:
    return getattr(request.state, "request_id", None)


def _response(requirement) -> AdminRequirementResponse:
    return AdminRequirementResponse.model_validate(requirement, from_attributes=True)


async def _ensure_exists(db: DbSession, model, target_id: UUID, message: str) -> None:
    if await db.get(model, target_id) is None:
        raise NotFoundError(message)


@router.get("/challenges/{challenge_id}/requirements")
async def list_challenge_requirements(
    challenge_id: UUID, db: DbSession, current: Staff
) -> list[AdminRequirementResponse]:
    await _ensure_exists(db, Challenge, challenge_id, "No such challenge.")
    rows = await unlock_service.list_requirements(db, challenge_id=challenge_id)
    return [_response(r) for r in rows]


@router.post("/challenges/{challenge_id}/requirements", status_code=status.HTTP_201_CREATED)
async def add_challenge_requirement(
    challenge_id: UUID,
    payload: CreateRequirementRequest,
    request: Request,
    db: DbSession,
    current: Admin,
) -> AdminRequirementResponse:
    await _ensure_exists(db, Challenge, challenge_id, "No such challenge.")
    requirement = await unlock_service.add_requirement(
        db, challenge_id=challenge_id, **payload.model_dump()
    )
    await record_audit(
        db,
        action="challenge.requirement_add",
        target_type="challenge",
        target_id=challenge_id,
        actor_user_id=current.user.id,
        meta={"type": payload.requirement_type.value},
        request_id=_request_id(request),
    )
    return _response(requirement)


@router.get("/categories/{category_id}/requirements")
async def list_category_requirements(
    category_id: UUID, db: DbSession, current: Staff
) -> list[AdminRequirementResponse]:
    await _ensure_exists(db, Category, category_id, "No such category.")
    rows = await unlock_service.list_requirements(db, category_id=category_id)
    return [_response(r) for r in rows]


@router.post("/categories/{category_id}/requirements", status_code=status.HTTP_201_CREATED)
async def add_category_requirement(
    category_id: UUID,
    payload: CreateRequirementRequest,
    request: Request,
    db: DbSession,
    current: Admin,
) -> AdminRequirementResponse:
    """Gate a whole zone. Its challenges stay locked until this is met."""
    await _ensure_exists(db, Category, category_id, "No such category.")
    requirement = await unlock_service.add_requirement(
        db, category_id=category_id, **payload.model_dump()
    )
    await record_audit(
        db,
        action="category.requirement_add",
        target_type="category",
        target_id=category_id,
        actor_user_id=current.user.id,
        meta={"type": payload.requirement_type.value},
        request_id=_request_id(request),
    )
    return _response(requirement)


@router.delete("/requirements/{requirement_id}")
async def remove_requirement(
    requirement_id: UUID, request: Request, db: DbSession, current: Admin
) -> MessageResponse:
    await unlock_service.remove_requirement(db, requirement_id)
    await record_audit(
        db,
        action="requirement.remove",
        target_type="unlock_requirement",
        target_id=requirement_id,
        actor_user_id=current.user.id,
        meta={},
        request_id=_request_id(request),
    )
    return MessageResponse(message="Requirement removed.")
