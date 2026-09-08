"""Admin CRUD for skills and the category→skill map (spec 015).

Reads are open to organizers so staff can see how categories are wired; every
write requires admin. Deleting a skill un-maps its categories (the FK is
``ON DELETE SET NULL``) rather than destroying them or their XP.
"""

from uuid import UUID

from fastapi import APIRouter, Request, status
from sqlalchemy import select

from app.api.deps import Admin, DbSession, Staff
from app.models.challenge import Category
from app.schemas.auth import MessageResponse
from app.schemas.skills import (
    AdminCategoryResponse,
    CreateSkillRequest,
    SetCategoryAbilityRequest,
    SetChallengeSkillsRequest,
    SkillResponse,
    UpdateSkillRequest,
)
from app.services import skills as skill_service
from app.services.identity import record_audit

router = APIRouter(prefix="/admin", tags=["admin-skills"])


def _request_id(request: Request) -> str | None:
    return getattr(request.state, "request_id", None)


@router.get("/skills")
async def list_skills(db: DbSession, current: Staff) -> list[SkillResponse]:
    return [
        SkillResponse.model_validate(skill, from_attributes=True)
        for skill in await skill_service.list_skills(db)
    ]


@router.post("/skills", status_code=status.HTTP_201_CREATED)
async def create_skill(
    payload: CreateSkillRequest, request: Request, db: DbSession, current: Admin
) -> SkillResponse:
    skill = await skill_service.create_skill(
        db,
        name=payload.name,
        display_order=payload.display_order,
        description=payload.description,
        kind=payload.kind,
        category_id=payload.category_id,
    )
    await record_audit(
        db,
        action="skill.create",
        target_type="skill",
        target_id=skill.id,
        actor_user_id=current.user.id,
        meta={"name": skill.name},
        request_id=_request_id(request),
    )
    return SkillResponse.model_validate(skill, from_attributes=True)


@router.patch("/skills/{skill_id}")
async def update_skill(
    skill_id: UUID,
    payload: UpdateSkillRequest,
    request: Request,
    db: DbSession,
    current: Admin,
) -> SkillResponse:
    changes = payload.model_dump(exclude_unset=True)
    skill = await skill_service.update_skill(db, skill_id, changes=changes)
    await record_audit(
        db,
        action="skill.update",
        target_type="skill",
        target_id=skill_id,
        actor_user_id=current.user.id,
        meta={"fields": sorted(changes)},
        request_id=_request_id(request),
    )
    return SkillResponse.model_validate(skill, from_attributes=True)


@router.delete("/skills/{skill_id}")
async def delete_skill(
    skill_id: UUID, request: Request, db: DbSession, current: Admin
) -> MessageResponse:
    await skill_service.delete_skill(db, skill_id)
    await record_audit(
        db,
        action="skill.delete",
        target_type="skill",
        target_id=skill_id,
        actor_user_id=current.user.id,
        meta={},
        request_id=_request_id(request),
    )
    return MessageResponse(message="Skill deleted.")


@router.get("/categories")
async def list_categories_with_ability(
    db: DbSession, current: Staff
) -> list[AdminCategoryResponse]:
    """Every category with the ability it feeds — the admin page's list."""
    categories = (
        (await db.execute(select(Category).order_by(Category.display_order, Category.name)))
        .scalars()
        .all()
    )
    return [
        AdminCategoryResponse.model_validate(category, from_attributes=True)
        for category in categories
    ]


@router.patch("/categories/{category_id}/ability")
async def set_category_ability(
    category_id: UUID,
    payload: SetCategoryAbilityRequest,
    request: Request,
    db: DbSession,
    current: Admin,
) -> AdminCategoryResponse:
    category = await skill_service.set_category_ability(db, category_id, payload.ability)
    await record_audit(
        db,
        action="category.set_ability",
        target_type="category",
        target_id=category_id,
        actor_user_id=current.user.id,
        meta={"ability": payload.ability.value},
        request_id=_request_id(request),
    )
    return AdminCategoryResponse.model_validate(category, from_attributes=True)


@router.get("/challenges/{challenge_id}/skills")
async def list_challenge_skills(challenge_id: UUID, db: DbSession, current: Staff) -> list[UUID]:
    return await skill_service.list_challenge_skills(db, challenge_id)


@router.put("/challenges/{challenge_id}/skills")
async def set_challenge_skills(
    challenge_id: UUID,
    payload: SetChallengeSkillsRequest,
    request: Request,
    db: DbSession,
    current: Admin,
) -> list[UUID]:
    """Replace a challenge's skills. Solving it feeds each of them in full."""
    assigned = await skill_service.set_challenge_skills(db, challenge_id, payload.skill_ids)
    await record_audit(
        db,
        action="challenge.set_skills",
        target_type="challenge",
        target_id=challenge_id,
        actor_user_id=current.user.id,
        meta={"count": len(assigned)},
        request_id=_request_id(request),
    )
    return assigned
