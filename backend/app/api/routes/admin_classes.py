"""Admin CRUD for character classes (spec 016).

Reads are open to organizers; every write requires admin. Twin of the admin
skills router — a class is roster/identity, never a scoring lever.
"""

from uuid import UUID

from fastapi import APIRouter, Request, status

from app.api.deps import Admin, DbSession, Staff
from app.schemas.admin_content import BulkRequest, BulkResultResponse
from app.schemas.auth import MessageResponse
from app.schemas.classes import (
    ClassPreferenceResponse,
    ClassRequirementResponse,
    ClassResponse,
    CreateClassRequest,
    SetPreferencesRequest,
    SetRequirementsRequest,
    UpdateClassRequest,
)
from app.services import admin_content
from app.services import classes as class_service
from app.services.identity import record_audit

router = APIRouter(prefix="/admin", tags=["admin-classes"])


def _request_id(request: Request) -> str | None:
    return getattr(request.state, "request_id", None)


def _response(character_class, tally: dict | None = None) -> ClassResponse:
    """Built field by field, not by `model_validate`.

    `preferences` and `requirements` are relationships, and letting pydantic
    reach for them triggers lazy IO in an async context — which on a
    freshly-created class is a MissingGreenlet rather than an empty list.
    Reading the already-loaded collections explicitly keeps that impossible.
    """
    tally = tally or {}
    loaded = "preferences" in character_class.__dict__
    preferences = character_class.preferences if loaded else []
    requirements = character_class.requirements if loaded else []

    return ClassResponse(
        id=character_class.id,
        name=character_class.name,
        display_order=character_class.display_order,
        description=character_class.description,
        rarity=character_class.rarity,
        preferences=[
            ClassPreferenceResponse(ability=p.ability, skill_id=p.skill_id) for p in preferences
        ],
        requirements=[
            ClassRequirementResponse(skill_id=r.skill_id, min_level=r.min_level)
            for r in requirements
        ],
        preference_count=tally.get("preferences", len(preferences)),
        requirement_count=tally.get("requirements", len(requirements)),
        wearers=tally.get("wearers", 0),
    )


@router.get("/classes")
async def list_classes(db: DbSession, current: Staff) -> list[ClassResponse]:
    counts = await admin_content.class_counts(db)
    return [
        _response(character_class, counts.get(character_class.id, {}))
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
        rarity=payload.rarity,
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
    return _response(character_class)


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
    return _response(character_class)


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


@router.put("/classes/{class_id}/preferences")
async def set_class_preferences(
    class_id: UUID,
    payload: SetPreferencesRequest,
    request: Request,
    db: DbSession,
    current: Admin,
) -> ClassResponse:
    """What the recommender matches a player against (spec 024).

    Editable from nowhere before spec 058, which meant the roster's whole
    recommendation model was seed-only.
    """
    character_class = await class_service.set_preferences(
        db, class_id, [entry.model_dump() for entry in payload.preferences]
    )
    await record_audit(
        db,
        action="class.set_preferences",
        target_type="character_class",
        target_id=class_id,
        actor_user_id=current.user.id,
        meta={"count": len(payload.preferences)},
        request_id=_request_id(request),
    )
    return _response(character_class)


@router.put("/classes/{class_id}/requirements")
async def set_class_requirements(
    class_id: UUID,
    payload: SetRequirementsRequest,
    request: Request,
    db: DbSession,
    current: Admin,
) -> ClassResponse:
    """The skill levels that gate the class."""
    character_class = await class_service.set_requirements(
        db, class_id, [entry.model_dump() for entry in payload.requirements]
    )
    await record_audit(
        db,
        action="class.set_requirements",
        target_type="character_class",
        target_id=class_id,
        actor_user_id=current.user.id,
        meta={"count": len(payload.requirements)},
        request_id=_request_id(request),
    )
    return _response(character_class)


@router.post("/classes/bulk")
async def bulk_classes(
    payload: BulkRequest, request: Request, db: DbSession, current: Admin
) -> BulkResultResponse:
    """One action over a selection, with per-item results (spec 058 §4)."""
    outcome = await admin_content.bulk_classes(db, payload.ids, payload.action, payload.value)
    await record_audit(
        db,
        action="class.bulk",
        target_type="class",
        target_id=None,
        actor_user_id=current.user.id,
        meta={"action": payload.action, "changed": outcome.changed, "asked": len(payload.ids)},
        request_id=_request_id(request),
    )
    return BulkResultResponse(**outcome.as_dict())
