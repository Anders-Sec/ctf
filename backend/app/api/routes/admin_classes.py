"""Admin CRUD for character classes (spec 016).

Reads are open to organizers; every write requires admin. Twin of the admin
skills router — a class is roster/identity, never a scoring lever.
"""

from uuid import UUID

from fastapi import APIRouter, Request, status

from app.api.deps import Admin, DbSession, Staff
from app.schemas.auth import MessageResponse
from app.schemas.classes import ClassResponse, CreateClassRequest, UpdateClassRequest
from app.services import classes as class_service
from app.services.identity import record_audit

router = APIRouter(prefix="/admin", tags=["admin-classes"])


def _request_id(request: Request) -> str | None:
    return getattr(request.state, "request_id", None)


@router.get("/classes")
async def list_classes(db: DbSession, current: Staff) -> list[ClassResponse]:
    return [
        ClassResponse.model_validate(character_class, from_attributes=True)
        for character_class in await class_service.list_classes(db)
    ]


@router.post("/classes", status_code=status.HTTP_201_CREATED)
async def create_class(
    payload: CreateClassRequest, request: Request, db: DbSession, current: Admin
) -> ClassResponse:
    character_class = await class_service.create_class(
        db,
        name=payload.name,
        display_order=payload.display_order,
        description=payload.description,
        affinity_skill_id=payload.affinity_skill_id,
    )
    await record_audit(
        db,
        action="class.create",
        target_type="character_class",
        target_id=character_class.id,
        actor_user_id=current.user.id,
        meta={"name": character_class.name},
        request_id=_request_id(request),
    )
    return ClassResponse.model_validate(character_class, from_attributes=True)


@router.patch("/classes/{class_id}")
async def update_class(
    class_id: UUID,
    payload: UpdateClassRequest,
    request: Request,
    db: DbSession,
    current: Admin,
) -> ClassResponse:
    changes = payload.model_dump(exclude_unset=True)
    character_class = await class_service.update_class(db, class_id, changes=changes)
    await record_audit(
        db,
        action="class.update",
        target_type="character_class",
        target_id=class_id,
        actor_user_id=current.user.id,
        meta={"fields": sorted(changes)},
        request_id=_request_id(request),
    )
    return ClassResponse.model_validate(character_class, from_attributes=True)


@router.delete("/classes/{class_id}")
async def delete_class(
    class_id: UUID, request: Request, db: DbSession, current: Admin
) -> MessageResponse:
    await class_service.delete_class(db, class_id)
    await record_audit(
        db,
        action="class.delete",
        target_type="character_class",
        target_id=class_id,
        actor_user_id=current.user.id,
        meta={},
        request_id=_request_id(request),
    )
    return MessageResponse(message="Class deleted.")
